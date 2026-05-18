"""
Build Site — Generate Astro markdown editions from the briefs database.

Reads the `briefs` table from brief_engine.db and writes structured
markdown files into website/src/content/editions/{edition_key}/.

Set TODAY_ONLY = False to process all entries in the database.
"""

import json
import logging
import sqlite3
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

TODAY_ONLY = True  # Set to False to process all briefs in the database
ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "brief_engine.db"
EDITIONS_DIR = ROOT_DIR / "website" / "src" / "content" / "editions"

def get_briefs(db_path: Path) -> list[dict]:
    """Fetch briefs from the database, filtered to today if TODAY_ONLY is set."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        query = "SELECT * FROM briefs WHERE date(generated_at) = date('now')" if TODAY_ONLY else "SELECT * FROM briefs"
        return [dict(row) for row in conn.execute(query).fetchall()]
    finally:
        conn.close()


def yaml_escape(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'

def format_section_yaml(section: dict, indent: int = 2) -> str:
    p, ip = " " * indent, " " * (indent + 4)
    lines = [
        f"{p}- id: {yaml_escape(section['id'])}",
        f"{p}  title: {yaml_escape(section['title'])}",
    ]
    if section.get("description"):
        lines.append(f"{p}  description: {yaml_escape(section['description'])}")
    if section.get("scope_label"):
        lines.append(f"{p}  scope_label: {yaml_escape(section['scope_label'])}")
    lines.append(f"{p}  items:")
    for item in section.get("items", []):
        lines.append(f"{ip}- type: {yaml_escape(item['type'])}")
        lines.append(f"{ip}  title: {yaml_escape(item['title'])}")
        for key in ("summary", "brief", "why_it_matters", "scope"):
            if item.get(key):
                lines.append(f"{ip}  {key}: {yaml_escape(item[key])}")
    return "\n".join(lines)


def brief_to_markdown(brief: dict, content: dict) -> str:
    date_str = brief["generated_at"].split("T")[0].split(" ")[0]
    sections = [s for s in content.get("sections", []) if s.get("items")]
    lines = [
        "---",
        f"title: {yaml_escape(content.get('title', brief['title']))}",
    ]
    if subtitle := content.get("subtitle", ""):
        lines.append(f"subtitle: {yaml_escape(subtitle)}")
    lines.extend([
        f"date: {yaml_escape(date_str)}",
        f"readTime: {brief.get('read_time_minutes', 5)}",
        f"editionKey: {yaml_escape(brief['edition_key'])}",
        "sections:",
        *[format_section_yaml(s) for s in sections],
        "---",
        "",
    ])
    return "\n".join(lines)


def main():
    if not DB_PATH.exists():
        logger.error("Database not found: %s", DB_PATH)
        return

    briefs = get_briefs(DB_PATH)
    logger.info("Found %d brief(s) to process", len(briefs))
    if not briefs:
        return

    written = 0
    for brief in briefs:
        content = json.loads(brief["content_json"])
        date_str = brief["generated_at"].split("T")[0].split(" ")[0]
        edition_dir = EDITIONS_DIR / brief["edition_key"]
        edition_dir.mkdir(parents=True, exist_ok=True)
        file_path = edition_dir / f"{date_str}.md"

        if file_path.exists():
            logger.info("  – skipped (already exists): %s/%s.md", brief["edition_key"], date_str)
            continue

        file_path.write_text(brief_to_markdown(brief, content), encoding="utf-8")
        logger.info("  ✓ %s/%s.md", brief["edition_key"], date_str)
        written += 1

    logger.info("Done: %d file(s) written", written)

if __name__ == "__main__":
    main()