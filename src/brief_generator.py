import json
import logging
import sqlite3
from datetime import datetime, timezone

import ollama

from .config import BRIEF_TEMPLATES
from .database import get_connection
from .model import MODEL

logger = logging.getLogger(__name__)

WHY_IT_MATTERS_PROMPT = """\
You are writing for a hyperlocal neighborhood newsletter (Powai, Mumbai).
Given a news title and summary, write 1 sentence explaining how this \
specifically affects a resident's daily life — focus on commute impact, \
cost impact, safety impact, or time-saving impact. Be concrete, direct, \
conversational. No preamble, no filler.

Title: {title}
Summary: {summary}

Return only the explanation."""

NEWSLETTER_HEADLINE_PROMPT = """\
Rewrite this newspaper-style headline into a newsletter-friendly headline.
Make it conversational, impact-focused, and reader-centric.
Instead of "Civic Groups Oppose Adani's Tunnel Road Project", prefer
"Mumbai tunnel project may worsen Powai traffic during construction".
Max 12 words. No clickbait. No quotes.

Original: {title}

Return only the rewritten headline."""

TIGHTEN_SUMMARY_PROMPT = """\
Tighten this news summary for a newsletter. Remove filler, keep only \
facts that matter to a local reader. Max 2 sentences, ~25-30 words. \
Start with the most impactful fact.

Summary: {summary}

Return only the tightened summary."""

def llm(prompt, fallback="", temperature=0.3):
    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": temperature},
        )
        return response["message"]["content"].strip()
    except Exception:
        logger.exception("LLM call failed")
        return fallback

def fetch_clusters(cursor):
    return cursor.execute("""
        SELECT id, title, summary, article_count, entities, category, scope,
               recency_score, importance_score, created_at
        FROM article_clusters
        WHERE title IS NOT NULL AND summary IS NOT NULL AND updated_at >= date('now', '-24 hours')
        ORDER BY created_at DESC
    """).fetchall()

def select_clusters(clusters, section, template, selected_ids):
    """Filter, rank, and dedupe clusters for a section."""
    f = section.get("filters", {})
    allowed_scopes = set(f.get("scope", []))
    allowed_cats = set(f.get("category", []))
    sort = section.get("sort", {})

    candidates = sorted(
        (c for c in clusters
         if c["id"] not in selected_ids
         and (not allowed_scopes or c["scope"] in allowed_scopes)
         and (not allowed_cats or c["category"] in allowed_cats)
         and c["importance_score"] >= f.get("min_importance_score", 0)),
        key=lambda c: (
            c["importance_score"] * sort.get("importance", 0)
            + c["recency_score"] * sort.get("recency", 0)
            + template["scope_priority"].get(c["scope"], 0) * sort.get("scope", 0)
        ),
        reverse=True,
    )

    limit = section.get("limit", 5)
    max_per_cat = template["selection"].get("dedupe_categories_per_section", 2)
    selected, cat_counts = [], {}
    for c in candidates:
        if cat_counts.get(c["category"], 0) < max_per_cat:
            selected.append(c)
            cat_counts[c["category"]] = cat_counts.get(c["category"], 0) + 1
            if len(selected) >= limit:
                break
    return selected

def format_cluster(cluster, section, template):
    fmt = section.get("format", "short")
    newsletter = template.get("tone") == "newsletter"

    title, summary = cluster["title"], cluster["summary"]
    if newsletter and fmt not in ("alert_chip", "closing_brief"):
        title = llm(NEWSLETTER_HEADLINE_PROMPT.format(title=title), fallback=title, temperature=0.4)
        summary = llm(TIGHTEN_SUMMARY_PROMPT.format(summary=summary), fallback=summary)

    base = {"cluster_id": cluster["id"], "title": title}

    if fmt == "alert_chip":    return {"type": "alert_chip", **base, "scope": cluster["scope"]}
    if fmt == "one_line":      return {"type": "one_line", **base}
    if fmt == "closing_brief": return {"type": "closing_brief", **base}
    if fmt == "compact_brief": return {"type": "compact_brief", **base, "summary": summary}
    if fmt in ("lead", "explainer"):
        why = llm(WHY_IT_MATTERS_PROMPT.format(title=title, summary=summary),
                  fallback="May affect your daily routine, costs, or commute.")
        key = "summary" if fmt == "lead" else "brief"
        return {"type": fmt, **base, key: summary, "why_it_matters": why}
    return {"type": "short", **base, "summary": summary}

def format_section_items(clusters, section, template):
    fmt = section.get("format", "short")
    if fmt == "lead_plus_short":
        n = section.get("lead_count", 1)
        return [format_cluster(c, dict(section, format="lead" if i < n else "short"), template) for i, c in enumerate(clusters)]
    if fmt == "explainer_plus_compact":
        n = section.get("explainer_count", 1)
        return [format_cluster(c, dict(section, format="explainer" if i < n else "compact_brief"), template) for i, c in enumerate(clusters)]
    return [format_cluster(c, section, template) for c in clusters]

def build_section(section, clusters, template, selected_ids):
    selected = select_clusters(clusters, section, template, selected_ids)
    items = format_section_items(selected, section, template)
    selected_ids.update(c["id"] for c in selected)

    if not items and not section.get("required", False):
        return None

    result = {"id": section["id"], "title": section["title"], "description": section.get("description"), "items": items}
    if section.get("scope_label"):
        result["scope_label"] = section["scope_label"]
    return result

def build_edition(template, clusters):
    selected_ids = set()
    sections = [s for s in (build_section(s, clusters, template, selected_ids) for s in template["sections"]) if s]
    edition = {"title": template["title"], "generated_at": datetime.now(timezone.utc).isoformat(), "sections": sections}
    if template.get("subtitle"):
        edition["subtitle"] = template["subtitle"]
    return edition

def save_edition(cursor, template, edition, cluster_ids):
    cursor.execute("DELETE FROM briefs WHERE edition_key = ? AND date(generated_at) = date('now')", (template["name"],))
    cursor.execute("""
        INSERT INTO briefs (edition_key, title, template_name, content_json, cluster_ids_json, read_time_minutes)
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
            cluster_ids = [item["cluster_id"] for section in edition["sections"] for item in section["items"]]
            save_edition(cursor, template, edition, cluster_ids)
            conn.commit()
            logger.info("Generated edition: %s", template["name"])
    finally:
        conn.close()