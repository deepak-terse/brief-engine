#!/usr/bin/env python3
"""Build cluster baseline from Google News India RSS feed.

Each RSS <item> represents a story-group curated by Google News.
The <description> contains related article titles as <li><a> links —
these become the ground-truth cluster members.

Only story groups with ≥2 related titles are kept (genuine multi-article clusters).

Output layout (under --output-dir, default benchmarks/fixtures/cluster_baseline/):
    manifest.json          – run metadata & cluster summary
    raw/
        in.xml             – raw RSS snapshot (skipped when --skip-fetch)
    clusters/
        <id>.json          – one file per cluster: item_title, members (list of {title})
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

FEED_URL = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
MIN_CLUSTER_SIZE = 2  # Only keep story groups with this many related titles or more


# ── HTML parser ───────────────────────────────────────────────────────────────

class RelatedTitleParser(HTMLParser):
    """Extract anchor text inside <li> blocks from description HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._inside_li = False
        self._inside_a = False
        self._buffer: list[str] = []
        self.titles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower == "li":
            self._inside_li = True
        elif lower == "a" and self._inside_li:
            self._inside_a = True
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower == "a" and self._inside_a:
            self._inside_a = False
            text = "".join(self._buffer).strip()
            if text:
                self.titles.append(text)
            self._buffer = []
        elif lower == "li":
            self._inside_li = False

    def handle_data(self, data: str) -> None:
        if self._inside_a:
            self._buffer.append(data)


# ── title helpers ─────────────────────────────────────────────────────────────

def normalize_title(title: str) -> str:
    if not title:
        return ""
    value = unescape(title).strip()
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def canonical_title_key(title: str) -> str:
    value = normalize_title(title)
    value = unicodedata.normalize("NFKC", value).casefold()
    value = (
        value.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    value = re.sub(r"[^\w\s]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        candidate = normalize_title(value)
        if not candidate:
            continue
        key = canonical_title_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


# ── network ───────────────────────────────────────────────────────────────────

def fetch_feed_xml(url: str, timeout: int = 30) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    )
    with urlopen(req, timeout=timeout) as response:
        payload = response.read()
    return payload.decode("utf-8", errors="replace")


# ── parsing ───────────────────────────────────────────────────────────────────

def extract_related_titles(description_html: str) -> list[str]:
    parser = RelatedTitleParser()
    parser.feed(description_html or "")
    parser.close()
    return dedupe_preserve_order(parser.titles)


def parse_clusters(xml_text: str) -> list[dict]:
    """Parse RSS XML and return a list of story-group dicts (multi-article only)."""
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        return []

    clusters: list[dict] = []
    idx = 0
    for item in channel.findall("item"):
        raw_title = (item.findtext("title") or "").strip()
        description_html = item.findtext("description") or ""

        item_title = normalize_title(raw_title)
        related_titles = extract_related_titles(description_html)

        if len(related_titles) < MIN_CLUSTER_SIZE:
            continue  # skip singletons / empty groups

        idx += 1
        clusters.append(
            {
                "id": idx,
                "item_title": item_title,
                "members": [{"title": t} for t in related_titles],
            }
        )

    return clusters


# ── I/O helpers ───────────────────────────────────────────────────────────────

def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ── core ──────────────────────────────────────────────────────────────────────

def run(skip_fetch: bool, output_dir: Path) -> None:
    raw_dir = output_dir / "raw"
    clusters_dir = output_dir / "clusters"

    raw_dir.mkdir(parents=True, exist_ok=True)
    clusters_dir.mkdir(parents=True, exist_ok=True)

    raw_file = raw_dir / "in.xml"

    if skip_fetch:
        if not raw_file.exists():
            raise FileNotFoundError(
                f"Missing raw snapshot for --skip-fetch mode: {raw_file}"
            )
        xml_text = raw_file.read_text(encoding="utf-8")
        fetched_at_str = datetime.fromtimestamp(
            raw_file.stat().st_mtime, tz=timezone.utc
        ).isoformat()
    else:
        print(f"Fetching {FEED_URL} ...")
        xml_text = fetch_feed_xml(FEED_URL)
        raw_file.write_text(xml_text, encoding="utf-8")
        fetched_at_str = datetime.now(timezone.utc).isoformat()

    print("Parsing RSS clusters ...")
    clusters = parse_clusters(xml_text)

    # Remove stale cluster files from a previous run
    for old in clusters_dir.glob("*.json"):
        old.unlink()

    # Per-cluster files
    for c in clusters:
        write_json(clusters_dir / f"{c['id']}.json", c)

    # Manifest
    manifest = {
        "generated_at": fetched_at_str,
        "feed_url": FEED_URL,
        "cluster_summary": {
            "total": len(clusters),
            "min_cluster_size": MIN_CLUSTER_SIZE,
        },
        "cluster_index": [
            {
                "id": c["id"],
                "item_title": c["item_title"],
                "article_count": len(c["members"]),
            }
            for c in clusters
        ],
    }
    write_json(output_dir / "manifest.json", manifest)

    total_titles = sum(len(c["members"]) for c in clusters)
    print(f"Baseline written to: {output_dir}")
    print(f"  Story clusters    : {len(clusters)}  (≥{MIN_CLUSTER_SIZE} articles each)")
    print(f"  Total titles      : {total_titles}")


# ── CLI ───────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _parse_args() -> argparse.Namespace:
    default_output = PROJECT_ROOT / "benchmarks" / "fixtures" / "cluster_baseline"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Skip network fetch; reparse from existing raw/in.xml snapshot.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(default_output),
        help="Directory for baseline artifacts (default: benchmarks/fixtures/cluster_baseline/).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    run(skip_fetch=bool(args.skip_fetch), output_dir=Path(args.output_dir).expanduser().resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
