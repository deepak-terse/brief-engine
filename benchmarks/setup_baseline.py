#!/usr/bin/env python3
"""Snapshot the current cluster state from brief_engine.db into a baseline fixture.

Captures every cluster together with its member article titles so that the
benchmark can later re-run clustering from scratch on the same corpus and
compare the result against this ground-truth snapshot.

Output layout (under --output-dir, default benchmarks/fixtures/cluster_baseline/):
    manifest.json          – run metadata & per-cluster summary
    clusters/
        <id>.json          – one file per cluster: category, scope, member titles,
                             importance_score, recency_score, article_count
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running as a top-level script without installing the package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.database import get_connection


# ── helpers ──────────────────────────────────────────────────────────────────

def _fetch_clusters(conn) -> list[dict]:
    """Return every cluster row enriched with member titles."""
    rows = conn.execute(
        """
        SELECT
            ac.id,
            ac.category,
            ac.scope,
            ac.title          AS cluster_title,
            ac.summary,
            ac.article_count,
            ac.importance_score,
            ac.recency_score,
            ac.entities,
            ac.created_at
        FROM article_clusters ac
        ORDER BY ac.id
        """
    ).fetchall()

    clusters: list[dict] = []
    for row in rows:
        member_rows = conn.execute(
            """
            SELECT a.id, a.title, a.category, a.published_at
            FROM   articles a
            WHERE  a.cluster_id = ?
            ORDER  BY a.id
            """,
            (row["id"],),
        ).fetchall()

        try:
            entities = json.loads(row["entities"] or "{}")
        except (json.JSONDecodeError, TypeError):
            entities = {}

        clusters.append(
            {
                "id": row["id"],
                "category": row["category"],
                "scope": row["scope"],
                "cluster_title": row["cluster_title"],
                "summary": row["summary"],
                "article_count": row["article_count"],
                "importance_score": row["importance_score"],
                "recency_score": row["recency_score"],
                "top_entities": sorted(entities, key=lambda k: -entities[k])[:5],
                "created_at": row["created_at"],
                "members": [
                    {
                        "id": m["id"],
                        "title": m["title"],
                        "category": m["category"],
                        "published_at": m["published_at"],
                    }
                    for m in member_rows
                ],
            }
        )

    return clusters


def _db_stats(conn) -> dict:
    row = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM articles)                               AS total_articles,
            (SELECT COUNT(*) FROM articles WHERE cluster_id IS NOT NULL)  AS clustered_articles,
            (SELECT COUNT(*) FROM articles WHERE cluster_id IS NULL)      AS unclustered_articles,
            (SELECT COUNT(*) FROM article_clusters)                       AS total_clusters
        """
    ).fetchone()
    return dict(row)


# ── core ─────────────────────────────────────────────────────────────────────

def run(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    clusters_dir = output_dir / "clusters"
    clusters_dir.mkdir(exist_ok=True)

    conn = get_connection()
    try:
        clusters = _fetch_clusters(conn)
        stats = _db_stats(conn)
    finally:
        conn.close()

    # Per-cluster files
    for c in clusters:
        path = clusters_dir / f"{c['id']}.json"
        path.write_text(json.dumps(c, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Distribution helpers for manifest
    size_hist: dict[str, int] = {"1": 0, "2-3": 0, "4-7": 0, "8+": 0}
    for c in clusters:
        n = len(c["members"])
        if n == 1:
            size_hist["1"] += 1
        elif n <= 3:
            size_hist["2-3"] += 1
        elif n <= 7:
            size_hist["4-7"] += 1
        else:
            size_hist["8+"] += 1

    category_dist: dict[str, int] = {}
    scope_dist: dict[str, int] = {}
    for c in clusters:
        cat = c["category"] or "unknown"
        scp = c["scope"] or "unknown"
        category_dist[cat] = category_dist.get(cat, 0) + 1
        scope_dist[scp] = scope_dist.get(scp, 0) + 1

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_stats": stats,
        "cluster_summary": {
            "total": len(clusters),
            "singleton_count": size_hist["1"],
            "multi_article_count": len(clusters) - size_hist["1"],
            "size_distribution": size_hist,
            "by_category": category_dist,
            "by_scope": scope_dist,
            "avg_importance_score": round(
                sum(c["importance_score"] or 0 for c in clusters) / len(clusters), 4
            ) if clusters else None,
            "avg_recency_score": round(
                sum(c["recency_score"] or 0 for c in clusters) / len(clusters), 4
            ) if clusters else None,
        },
        "cluster_index": [
            {
                "id": c["id"],
                "category": c["category"],
                "scope": c["scope"],
                "article_count": len(c["members"]),
                "cluster_title": c["cluster_title"],
            }
            for c in clusters
        ],
    }

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"Baseline written to: {output_dir}")
    print(f"  Clusters captured : {len(clusters)}")
    print(f"  Clustered articles: {stats['clustered_articles']} / {stats['total_articles']}")
    print(f"  Multi-article     : {manifest['cluster_summary']['multi_article_count']}")
    print(f"  Size distribution : {size_hist}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    default_output = PROJECT_ROOT / "benchmarks" / "fixtures" / "cluster_baseline"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(default_output),
        help="Directory for baseline artifacts (default: benchmarks/fixtures/cluster_baseline/).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    run(Path(args.output_dir).expanduser().resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
