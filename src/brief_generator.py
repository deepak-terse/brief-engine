import json
import logging
import sqlite3
from datetime import datetime, timezone

import ollama

from .config import BRIEF_TEMPLATES
from .database import get_connection

logger = logging.getLogger(__name__)

MODEL = "qwen3:8b"

WHY_IT_MATTERS_PROMPT = """\
You are a local news assistant. Given a news title and summary, write 1-2 sentences \
explaining how this event specifically affects a reader's daily life — covering costs, \
commute, safety, health, work, or decisions as relevant. Be concrete and direct. \
No preamble, no generic filler.

Title: {title}
Summary: {summary}

Return only the explanation."""


def fetch_clusters(cursor):
    return cursor.execute("""
        SELECT id, title, summary, article_count, entities, category, scope,
               recency_score, importance_score, created_at
        FROM article_clusters
        WHERE title IS NOT NULL AND summary IS NOT NULL
        ORDER BY created_at DESC
    """).fetchall()


def generate_why_it_matters(title, summary):
    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": WHY_IT_MATTERS_PROMPT.format(
                title=title, summary=summary
            )}],
            options={"temperature": 0.3},
        )
        return response["message"]["content"].strip()
    except Exception:
        logger.exception("Failed to generate why_it_matters for: %s", title)
        return "May affect daily life, costs, travel or decisions."


def compute_cluster_score(cluster, section, template):
    sort = section.get("sort", {})
    scope_priority = template["scope_priority"].get(cluster["scope"], 0)
    return round(
        cluster["importance_score"] * sort.get("importance", 0)
        + cluster["recency_score"] * sort.get("recency", 0)
        + scope_priority * sort.get("scope", 0),
        4,
    )


def filter_clusters(clusters, section, selected_ids):
    f = section.get("filters", {})
    allowed_scopes = set(f.get("scope", []))
    allowed_cats = set(f.get("category", []))
    min_importance = f.get("min_importance_score", 0)

    return [
        c for c in clusters
        if c["id"] not in selected_ids
        and (not allowed_scopes or c["scope"] in allowed_scopes)
        and (not allowed_cats or c["category"] in allowed_cats)
        and c["importance_score"] >= min_importance
    ]


def rank_clusters(clusters, section, template):
    return sorted(
        clusters,
        key=lambda c: compute_cluster_score(c, section, template),
        reverse=True,
    )


def diversify_clusters(clusters, section, template):
    limit = section.get("limit", 5)
    max_per_cat = template["selection"].get("dedupe_categories_per_section", 2)
    selected, cat_counts = [], {}

    for c in clusters:
        cat = c["category"]
        if cat_counts.get(cat, 0) >= max_per_cat:
            continue
        selected.append(c)
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        if len(selected) >= limit:
            break

    return selected


def format_cluster(cluster, section):
    fmt = section.get("format", "short")
    base = {"cluster_id": cluster["id"], "title": cluster["title"]}

    if fmt == "one_line":
        return {"type": "one_line", **base}

    if fmt == "explainer":
        return {
            "type": "explainer",
            **base,
            "brief": cluster["summary"],
            "why_it_matters": generate_why_it_matters(cluster["title"], cluster["summary"]),
        }

    return {"type": "short", **base, "summary": cluster["summary"]}


def build_section(section, clusters, template, selected_ids):
    filtered = filter_clusters(clusters, section, selected_ids)
    ranked = rank_clusters(filtered, section, template)
    selected = diversify_clusters(ranked, section, template)

    items = []
    for c in selected:
        selected_ids.add(c["id"])
        items.append(format_cluster(c, section))

    if not items and not section.get("required", False):
        return None

    return {
        "id": section["id"],
        "title": section["title"],
        "description": section.get("description"),
        "items": items,
    }


def build_edition(template, clusters):
    selected_ids = set()
    sections = list(filter(None, [
        build_section(s, clusters, template, selected_ids)
        for s in template["sections"]
    ]))

    return {
        "title": template["title"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
    }


def save_news_edition(cursor, template, edition, cluster_ids):
    cursor.execute("""
        INSERT INTO briefs
            (edition_key, title, template_name, content_json, cluster_ids_json, read_time_minutes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        template["name"], template["title"], template["name"],
        json.dumps(edition), json.dumps(list(cluster_ids)),
        template.get("max_read_time_minutes", 5),
    ))


def generate_brief():
    logger.info("Starting news edition generation")
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        clusters = fetch_clusters(cursor)

        for template in BRIEF_TEMPLATES:
            edition = build_edition(template, clusters)
            cluster_ids = [
                item["cluster_id"]
                for section in edition["sections"]
                for item in section["items"]
            ]
            save_news_edition(cursor, template, edition, cluster_ids)
            conn.commit()
            logger.info("Generated edition: %s", template["name"])
    finally:
        conn.close()