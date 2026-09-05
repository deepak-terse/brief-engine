#!/usr/bin/env python3
"""Run cluster quality benchmark against the captured baseline.

The benchmark is fully self-contained: it reads article titles from the
baseline fixture, encodes them with the same NLP pipeline used in production,
runs clustering, then compares the predicted groupings against the baseline.

This means results are deterministic and independent of current DB state —
matching the approach from the reference project.

Output:
  benchmarks/fixtures/cluster_baseline/benchmark_report.json
  benchmarks/fixtures/cluster_baseline/benchmark_report.html
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from time import perf_counter
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import CLUSTER_DISTANCE_THRESHOLD
from src.enricher import load_encoder, build_article_text
from src.clustering import _cluster_groups, UnclusteredArticle

import numpy as np

DEFAULT_BASELINE_DIR = PROJECT_ROOT / "benchmarks" / "fixtures" / "cluster_baseline"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "benchmarks" / "benchmark_report.json"
DEFAULT_HTML_REPORT_PATH = PROJECT_ROOT / "benchmarks" / "benchmark_report.html"
DEFAULT_HTML_TEMPLATE_PATH = PROJECT_ROOT / "benchmarks" / "templates" / "cluster_benchmark_report.html"


# ── title normalisation ───────────────────────────────────────────────────────

def _title_key(title: str) -> str:
    return (title or "").casefold().strip()


# ── baseline loading ──────────────────────────────────────────────────────────

def _load_baseline(baseline_dir: Path) -> dict[str, Any]:
    manifest = json.loads((baseline_dir / "manifest.json").read_text(encoding="utf-8"))
    clusters: list[dict] = []
    for entry in manifest["cluster_index"]:
        path = baseline_dir / "clusters" / f"{entry['id']}.json"
        clusters.append(json.loads(path.read_text(encoding="utf-8")))
    manifest["clusters"] = clusters
    # Normalise: ensure every cluster has a generated_at timestamp for display
    manifest.setdefault("generated_at", "unknown")
    return manifest


# ── embed baseline titles via the real NLP stack ──────────────────────────────

@dataclass
class _TitledArticle:
    """Thin wrapper that satisfies UnclusteredArticle's interface + carries title."""
    id: int
    category: str | None
    entities: list[str]
    embedding: np.ndarray
    title: str


def _embed_titles(titles: list[str]) -> list[np.ndarray]:
    """Encode a list of titles with the production sentence-transformer."""
    encoder = load_encoder()
    vectors = np.asarray(
        encoder.encode(titles, batch_size=32, normalize_embeddings=True, show_progress_bar=False),
        dtype=np.float32,
    )
    return [v for v in vectors]


def _build_titled_articles(baseline_clusters: list[dict]) -> list[_TitledArticle]:
    """Collect all unique article titles from baseline, embed them, return as articles.

    Works with both the old DB-style schema (members have id/category) and the new
    RSS schema (members have only title).
    """
    seen_keys: set[str] = set()
    # (synthetic_id, title, category, entities)
    rows: list[tuple[int, str, str | None, list[str]]] = []
    synthetic_id = 0

    for bc in baseline_clusters:
        # RSS clusters have no category/entities; DB clusters do — handle both
        cat: str | None = bc.get("category") or None
        entities: list[str] = bc.get("top_entities") or []
        for m in bc.get("members", []):
            title = (m.get("title") or "").strip()
            if not title:
                continue
            key = _title_key(title)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            synthetic_id += 1
            rows.append((synthetic_id, title, cat, entities))

    if not rows:
        return []

    titles = [r[1] for r in rows]
    print(f"  Embedding {len(titles)} unique baseline titles ...")
    embeddings = _embed_titles(titles)

    return [
        _TitledArticle(
            id=orig_id,
            category=cat,
            entities=ents,
            embedding=emb,
            title=title,
        )
        for (orig_id, title, cat, ents), emb in zip(rows, embeddings)
    ]


# ── pairwise helpers ──────────────────────────────────────────────────────────

def _pair_set(groups: list[list[str]]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for group in groups:
        deduped = sorted({k for k in group if k})
        for left, right in combinations(deduped, 2):
            pairs.add((left, right))
    return pairs


def _pairwise_prf(
    baseline_groups: list[list[str]],
    predicted_groups: list[list[str]],
) -> tuple[float, float, float, int, int]:
    expected_pairs = _pair_set(baseline_groups)
    predicted_pairs = _pair_set(predicted_groups)
    tp = len(expected_pairs & predicted_pairs)
    precision = tp / len(predicted_pairs) if predicted_pairs else 0.0
    recall = tp / len(expected_pairs) if expected_pairs else 0.0
    f1 = 0.0 if (precision + recall) == 0 else (2 * precision * recall) / (precision + recall)
    return precision, recall, f1, len(expected_pairs), len(predicted_pairs)


# ── cluster mapping (Jaccard best-match) ─────────────────────────────────────

def _best_jaccard_matches(
    baseline_clusters: list[dict[str, Any]],
    generated_clusters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for base in baseline_clusters:
        base_set = set(base["title_keys"])
        best: dict | None = None
        best_j = -1.0
        best_inter: set[str] = set()
        for gen in generated_clusters:
            gen_set = set(gen["title_keys"])
            inter = base_set & gen_set
            union = base_set | gen_set
            j = len(inter) / len(union) if union else 0.0
            if j > best_j:
                best_j = j
                best = gen
                best_inter = inter
        if best is None or not best_inter:
            out.append({
                "baseline_cluster_id": base["id"],
                "generated_cluster_id": None,
                "overlap_count": 0,
                "jaccard_score": 0.0,
                "baseline_size": len(base_set),
                "generated_size": 0,
                "common_titles": [],
            })
        else:
            out.append({
                "baseline_cluster_id": base["id"],
                "generated_cluster_id": best["id"],
                "overlap_count": len(best_inter),
                "jaccard_score": round(best_j, 4),
                "baseline_size": len(base_set),
                "generated_size": len(best["title_keys"]),
                "common_titles": list(best_inter)[:10],
            })
    return out


# ── per-category metrics ──────────────────────────────────────────────────────

def _run_category(
    category: str,
    baseline_clusters: list[dict],
    pred_label_to_members: dict[int, list[_TitledArticle]],
) -> dict[str, Any]:
    """Compute all metrics for one category."""

    # Baseline groups as title-key lists
    base_groups: list[list[str]] = []
    base_shapes: list[dict[str, Any]] = []
    baseline_all_keys: set[str] = set()
    for bc in baseline_clusters:
        keys = [_title_key(m["title"]) for m in bc.get("members", []) if m.get("title")]
        titles = [m["title"] for m in bc.get("members", []) if m.get("title")]
        if keys:
            base_groups.append(keys)
            base_shapes.append({"id": f"B{bc['id']}", "title_keys": keys, "titles": titles})
            baseline_all_keys.update(keys)

    # Predicted groups that overlap with this category's baseline keys
    pred_groups: list[list[str]] = []
    pred_shapes: list[dict[str, Any]] = []
    idx = 0
    for label, members in sorted(pred_label_to_members.items()):
        titles = [m.title for m in members if m.title]
        keys = [_title_key(t) for t in titles]
        if baseline_all_keys & set(keys):
            idx += 1
            pred_groups.append(keys)
            pred_shapes.append({"id": f"G{idx}", "title_keys": keys, "titles": titles})

    pw_prec, pw_rec, pw_f1, exp_pairs, pred_pairs = _pairwise_prf(base_groups, pred_groups)

    # Missing / extra titles (set difference at title-key level)
    predicted_keys = {k for g in pred_groups for k in g}
    key_to_base: dict[str, str] = {
        _title_key(m["title"]): m["title"]
        for bc in baseline_clusters
        for m in bc.get("members", []) if m.get("title")
    }
    key_to_pred: dict[str, str] = {k: t for shape in pred_shapes for k, t in zip(shape["title_keys"], shape["titles"])}

    missing = [key_to_base[k] for k in sorted(baseline_all_keys - predicted_keys)]
    extra = [key_to_pred[k] for k in sorted(predicted_keys - baseline_all_keys)]

    # Singleton rate for predicted clusters in this category
    singleton_rate = sum(1 for g in pred_groups if len(g) == 1) / len(pred_groups) if pred_groups else 0.0

    # Article counts: baseline (unique titles in this category) + predicted (articles in overlapping clusters)
    baseline_article_count = len(baseline_all_keys)
    predicted_article_count = len({k for g in pred_groups for k in g})

    return {
        "pairwise_precision": round(pw_prec, 6),
        "pairwise_recall": round(pw_rec, 6),
        "pairwise_f1": round(pw_f1, 6),
        "expected_pair_count": exp_pairs,
        "predicted_pair_count": pred_pairs,
        "baseline_cluster_count": len(base_shapes),
        "generated_cluster_count": len(pred_shapes),
        "baseline_article_count": baseline_article_count,
        "predicted_article_count": predicted_article_count,
        "singleton_rate": round(singleton_rate, 4),
        "baseline_clusters": base_shapes,
        "generated_clusters": pred_shapes,
        "cluster_overlap_matches": _best_jaccard_matches(base_shapes, pred_shapes),
        "missing_titles": missing[:40],
        "extra_titles": extra[:40],
    }


# ── orchestration ─────────────────────────────────────────────────────────────

def run_benchmark(baseline_dir: Path) -> dict[str, Any]:
    run_started_at = datetime.now(timezone.utc).isoformat()
    t0 = perf_counter()

    print(f"Loading baseline from {baseline_dir} ...")
    baseline = _load_baseline(baseline_dir)
    all_baseline_clusters: list[dict] = baseline["clusters"]
    print(f"  Baseline clusters : {len(all_baseline_clusters)}")

    # Embed baseline titles using the production NLP stack
    titled_articles = _build_titled_articles(all_baseline_clusters)
    print(f"  Unique titles     : {len(titled_articles)}")

    if not titled_articles:
        raise RuntimeError("No article titles found in baseline fixture.")

    # Run the real clustering algorithm on those embeddings
    print("Running clustering algorithm ...")
    # _cluster_groups expects objects with .embedding; _TitledArticle satisfies this
    pred_label_to_members: dict[int, list[_TitledArticle]] = _cluster_groups(titled_articles)  # type: ignore[arg-type]
    print(f"  Predicted clusters: {len(pred_label_to_members)}")

    # Group baseline clusters by category.
    # RSS-based clusters have no category, so they all land in "unknown".
    by_category: dict[str, list[dict]] = defaultdict(list)
    for bc in all_baseline_clusters:
        cat = bc.get("category") or "unknown"
        by_category[cat].append(bc)

    print("Computing per-category metrics ...")
    categories: dict[str, Any] = {}
    for cat in sorted(by_category):
        categories[cat] = _run_category(cat, by_category[cat], pred_label_to_members)

    # ── Aggregate KPIs ────────────────────────────────────────────────────────
    f1_values = [v["pairwise_f1"] for v in categories.values()]
    prec_values = [v["pairwise_precision"] for v in categories.values()]
    rec_values = [v["pairwise_recall"] for v in categories.values()]

    # Title-key → predicted label map (for purity + coverage)
    titlekey_to_pred: dict[str, int] = {}
    for label, members in pred_label_to_members.items():
        for m in members:
            k = _title_key(m.title)
            if k:
                titlekey_to_pred[k] = label

    baseline_all_keys = {
        _title_key(m["title"])
        for bc in all_baseline_clusters
        for m in bc.get("members", []) if m.get("title")
    }
    covered = sum(1 for k in baseline_all_keys if k in titlekey_to_pred)
    coverage_rate = covered / len(baseline_all_keys) if baseline_all_keys else 0.0

    singleton_rate_global = (
        sum(1 for members in pred_label_to_members.values() if len(members) == 1)
        / len(pred_label_to_members)
        if pred_label_to_members else 0.0
    )

    cluster_count_ratio = (
        len(pred_label_to_members) / len(all_baseline_clusters)
        if all_baseline_clusters else None
    )

    # Mean purity
    purity_scores: list[float] = []
    for bc in all_baseline_clusters:
        member_keys = [_title_key(m["title"]) for m in bc.get("members", []) if m.get("title")]
        if not member_keys:
            continue
        pred_labels = [titlekey_to_pred[k] for k in member_keys if k in titlekey_to_pred]
        if not pred_labels:
            purity_scores.append(0.0)
            continue
        best_count = Counter(pred_labels).most_common(1)[0][1]
        purity_scores.append(best_count / len(member_keys))
    mean_purity = sum(purity_scores) / len(purity_scores) if purity_scores else 0.0

    aggregate = {
        "category_count": len(categories),
        "total_article_count": len(titled_articles),
        "baseline_cluster_count": len(all_baseline_clusters),
        "predicted_cluster_count": len(pred_label_to_members),
        "cluster_count_ratio": round(cluster_count_ratio, 4) if cluster_count_ratio else None,
        "avg_pairwise_f1": round(sum(f1_values) / len(f1_values), 6) if f1_values else 0.0,
        "avg_pairwise_precision": round(sum(prec_values) / len(prec_values), 6) if prec_values else 0.0,
        "avg_pairwise_recall": round(sum(rec_values) / len(rec_values), 6) if rec_values else 0.0,
        "min_pairwise_f1": round(min(f1_values), 6) if f1_values else 0.0,
        "max_pairwise_f1": round(max(f1_values), 6) if f1_values else 0.0,
        "mean_purity": round(mean_purity, 4),
        "coverage_rate": round(coverage_rate, 4),
        "singleton_rate": round(singleton_rate_global, 4),
    }

    return {
        "generated_at": run_started_at,
        "baseline_generated_at": baseline["generated_at"],
        "baseline_dir": str(baseline_dir),
        "cluster_distance_threshold": CLUSTER_DISTANCE_THRESHOLD,
        "runtime_seconds": round(perf_counter() - t0, 3),
        "aggregate": aggregate,
        "categories": categories,
    }


# ── report persistence ────────────────────────────────────────────────────────

def save_report(report: dict[str, Any], report_path: Path) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report_path


def save_html_report(report: dict[str, Any], report_path: Path) -> Path:
    payload = json.dumps(report, ensure_ascii=False).replace("</", "<\\/")
    template = DEFAULT_HTML_TEMPLATE_PATH.read_text(encoding="utf-8")
    html = template.replace("__REPORT_JSON_PAYLOAD__", payload)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(html, encoding="utf-8")
    return report_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-dir",
        default=str(DEFAULT_BASELINE_DIR),
        help="Directory with baseline fixture.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_REPORT_PATH),
        help="JSON report output path.",
    )
    parser.add_argument(
        "--html-output",
        default=str(DEFAULT_HTML_REPORT_PATH),
        help="HTML report output path.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    baseline_dir = Path(args.baseline_dir).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    html_output_path = Path(args.html_output).expanduser().resolve()

    report = run_benchmark(baseline_dir)
    saved = save_report(report, output_path)
    saved_html = save_html_report(report, html_output_path)

    agg = report["aggregate"]
    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)
    print(f"  Avg Pairwise F1     : {agg['avg_pairwise_f1']:.1%}")
    print(f"  Avg Pairwise Prec   : {agg['avg_pairwise_precision']:.1%}")
    print(f"  Avg Pairwise Recall : {agg['avg_pairwise_recall']:.1%}")
    print(f"  Mean Purity         : {agg['mean_purity']:.1%}")
    print(f"  Coverage Rate       : {agg['coverage_rate']:.1%}")
    print(f"  Singleton Rate      : {agg['singleton_rate']:.1%}")
    print(f"  Cluster Count Ratio : {agg['cluster_count_ratio']:.2f}x")
    print(f"\n  JSON  → {saved}")
    print(f"  HTML  → {saved_html}")

    print(
        "\n" + json.dumps(
            {"report_path": str(saved), "html_report_path": str(saved_html), "aggregate": agg},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
