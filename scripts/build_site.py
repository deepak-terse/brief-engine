"""
Build Site — Generate Astro markdown editions from the briefs database.

Reads the `briefs` table from brief_engine.db and writes structured
markdown files into website/src/content/editions/{edition_key}/.

Each edition_key gets its own folder so Astro can host them at separate
paths, e.g. /powai_morning_edition/2026-05-16.

Usage:
    python -m scripts.build_site
    python -m scripts.build_site --clean    # wipe editions before writing
    python -m scripts.build_site --latest   # only export the latest per edition_key
"""

import argparse
import json
import logging
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "brief_engine.db"
EDITIONS_DIR = ROOT_DIR / "website" / "src" / "content" / "editions"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def get_briefs(db_path: Path, latest_only: bool = False) -> list[dict]:
    """Fetch briefs from the database, returned as a list of dicts."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        if latest_only:
            # Get only the most recent brief per edition_key
            query = """
                SELECT b.*
                FROM briefs b
                INNER JOIN (
                    SELECT edition_key, MAX(generated_at) AS max_generated_at
                    FROM briefs
                    GROUP BY edition_key
                ) latest
                ON b.edition_key = latest.edition_key
                AND b.generated_at = latest.max_generated_at
                ORDER BY b.generated_at DESC
            """
        else:
            query = """
                SELECT *
                FROM briefs
                ORDER BY generated_at DESC
            """

        rows = cursor.execute(query).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# YAML serialization (minimal, no external dependency)
# ---------------------------------------------------------------------------
def yaml_escape(value: str) -> str:
    """Escape a string for safe YAML scalar output."""
    # If the string contains characters that need quoting, double-quote it
    if any(ch in value for ch in (':', '#', '"', "'", '\n', '{', '}', '[', ']', '&', '*', '!', '|', '>', '%', '@', '`')):
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    # Also quote if it starts/ends with whitespace or looks like a number/bool
    stripped = value.strip()
    if stripped != value or stripped.lower() in ('true', 'false', 'null', 'yes', 'no'):
        return f'"{value}"'
    return f'"{value}"'


def format_section_yaml(section: dict, indent: int = 2) -> str:
    """Format a single section as YAML."""
    prefix = " " * indent
    item_prefix = " " * (indent + 4)
    lines = []

    lines.append(f"{prefix}- id: {yaml_escape(section['id'])}")
    lines.append(f"{prefix}  title: {yaml_escape(section['title'])}")
    lines.append(f"{prefix}  items:")

    for item in section.get("items", []):
        lines.append(f"{item_prefix}- type: {yaml_escape(item['type'])}")
        lines.append(f"{item_prefix}  title: {yaml_escape(item['title'])}")

        if item.get("summary"):
            lines.append(f"{item_prefix}  summary: {yaml_escape(item['summary'])}")

        if item.get("brief"):
            lines.append(f"{item_prefix}  brief: {yaml_escape(item['brief'])}")

        if item.get("why_it_matters"):
            lines.append(f"{item_prefix}  why_it_matters: {yaml_escape(item['why_it_matters'])}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------
def brief_to_markdown(brief: dict) -> str:
    """Convert a brief DB row (dict) into Astro-compatible markdown content."""
    content = json.loads(brief["content_json"])
    generated_at = brief["generated_at"]

    # Parse the date from generated_at (handles both ISO and sqlite formats)
    if "T" in generated_at:
        date_str = generated_at.split("T")[0]
    else:
        date_str = generated_at.split(" ")[0]

    edition_key = brief["edition_key"]
    title = content.get("title", brief["title"])
    read_time = brief.get("read_time_minutes", 5)

    # Filter out sections with no items
    sections = [s for s in content.get("sections", []) if s.get("items")]

    # Build frontmatter
    lines = [
        "---",
        f"title: {yaml_escape(title)}",
        f"date: {yaml_escape(date_str)}",
        f"readTime: {read_time}",
        f"editionKey: {yaml_escape(edition_key)}",
        "sections:",
    ]

    for section in sections:
        lines.append(format_section_yaml(section))

    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def write_edition(brief: dict, output_dir: Path) -> Path:
    """Write a single edition markdown file.

    Files are organized as: {output_dir}/{edition_key}/{date}.md
    """
    content = json.loads(brief["content_json"])
    generated_at = brief["generated_at"]
    edition_key = brief["edition_key"]

    if "T" in generated_at:
        date_str = generated_at.split("T")[0]
    else:
        date_str = generated_at.split(" ")[0]

    # Create edition_key folder
    edition_dir = output_dir / edition_key
    edition_dir.mkdir(parents=True, exist_ok=True)

    # Write markdown
    file_path = edition_dir / f"{date_str}.md"
    markdown = brief_to_markdown(brief)
    file_path.write_text(markdown, encoding="utf-8")

    return file_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def build_site(
    db_path: Path = DB_PATH,
    output_dir: Path = EDITIONS_DIR,
    clean: bool = False,
    latest_only: bool = False,
) -> list[Path]:
    """Main entry point: read briefs from DB, write markdown editions.

    Args:
        db_path: Path to the SQLite database.
        output_dir: Directory to write edition markdown files.
        clean: If True, remove all existing editions before writing.
        latest_only: If True, only export the most recent brief per edition_key.

    Returns:
        List of paths to the written markdown files.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        return []

    # Clean existing editions if requested
    if clean and output_dir.exists():
        logger.info("Cleaning editions directory: %s", output_dir)
        # Only remove edition_key subdirectories, keep any other files
        for child in output_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
                logger.info("  Removed: %s/", child.name)

    # Fetch briefs
    briefs = get_briefs(db_path, latest_only=latest_only)
    logger.info("Found %d brief(s) in database", len(briefs))

    if not briefs:
        logger.warning("No briefs found. Nothing to generate.")
        return []

    # Write editions
    written_files = []
    edition_keys_seen = set()

    for brief in briefs:
        try:
            file_path = write_edition(brief, output_dir)
            written_files.append(file_path)
            edition_keys_seen.add(brief["edition_key"])
            logger.info(
                "  ✓ %s/%s.md",
                brief["edition_key"],
                brief["generated_at"].split("T")[0] if "T" in brief["generated_at"] else brief["generated_at"].split(" ")[0],
            )
        except Exception:
            logger.exception(
                "  ✗ Failed to write edition for brief id=%s",
                brief.get("id", "?"),
            )

    # Summary
    logger.info(
        "Done: %d file(s) written across %d edition type(s)",
        len(written_files),
        len(edition_keys_seen),
    )
    for key in sorted(edition_keys_seen):
        count = sum(1 for f in written_files if key in str(f))
        logger.info("  %s: %d edition(s)", key, count)

    return written_files


def main():
    """CLI entry point for `uv run publish`."""
    parser = argparse.ArgumentParser(
        description="Generate Astro markdown editions from the briefs database."
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove existing edition folders before generating.",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Only export the latest brief per edition_key.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help=f"Path to the SQLite database (default: {DB_PATH}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=EDITIONS_DIR,
        help=f"Output directory for editions (default: {EDITIONS_DIR}).",
    )

    args = parser.parse_args()
    build_site(
        db_path=args.db,
        output_dir=args.output,
        clean=args.clean,
        latest_only=args.latest,
    )


if __name__ == "__main__":
    main()
