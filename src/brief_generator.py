import json
import logging
import sqlite3
from datetime import datetime, timezone

import ollama

from .config import BRIEF_TEMPLATES
from .database import get_connection
from .model import MODEL

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────────
# LLM prompts — newsletter tone, impact-first framing
# ───────────────────────────────────────────────────────────────────

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


def fetch_clusters(cursor):
    return cursor.execute("""
        SELECT id, title, summary, article_count, entities, category, scope,
               recency_score, importance_score, created_at
        FROM article_clusters
        WHERE title IS NOT NULL AND summary IS NOT NULL AND updated_at >= date('now', '-24 hours')
        ORDER BY created_at DESC
    """).fetchall()


def llm_call(prompt, temperature=0.3):
    """Single LLM call with error handling."""
    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": temperature},
        )
        print('############ ', MODEL, response)
        return response["message"]["content"].strip()
    except Exception:
        logger.exception("LLM call failed")
        return None


def generate_why_it_matters(title, summary):
    result = llm_call(WHY_IT_MATTERS_PROMPT.format(title=title, summary=summary))
    return result or "May affect your daily routine, costs, or commute."


def rewrite_headline_newsletter(title):
    """Rewrite a newspaper headline into newsletter-friendly format."""
    result = llm_call(NEWSLETTER_HEADLINE_PROMPT.format(title=title), temperature=0.4)
    return result or title


def tighten_summary(summary):
    """Tighten a summary to ~25-30 words."""
    result = llm_call(TIGHTEN_SUMMARY_PROMPT.format(summary=summary))
    return result or summary


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


def is_newsletter_tone(template):
    """Check if the template uses newsletter tone."""
    return template.get("tone") == "newsletter"


def maybe_rewrite(title, summary, template):
    """Optionally rewrite headline and tighten summary for newsletter tone."""
    if is_newsletter_tone(template):
        return rewrite_headline_newsletter(title), tighten_summary(summary)
    return title, summary


def format_cluster(cluster, section, template):
    """Format a cluster according to the section's format type."""
    fmt = section.get("format", "short")
    newsletter = is_newsletter_tone(template)

    # Determine title/summary — optionally rewrite for newsletter tone
    title = cluster["title"]
    summary = cluster["summary"]
    if newsletter and fmt not in ("alert_chip", "closing_brief"):
        title, summary = maybe_rewrite(title, summary, template)

    base = {"cluster_id": cluster["id"], "title": title}

    # ── alert_chip: compact colored chip, title only ──────────────
    if fmt == "alert_chip":
        return {"type": "alert_chip", **base, "scope": cluster["scope"]}

    # ── one_line: simple bullet ──────────────────────────────────
    if fmt == "one_line":
        return {"type": "one_line", **base}

    # ── lead: dominant story with full summary + why_it_matters ──
    if fmt == "lead":
        return {
            "type": "lead",
            **base,
            "summary": summary,
            "why_it_matters": generate_why_it_matters(title, summary),
        }

    # ── explainer: title + brief + why_it_matters ────────────────
    if fmt == "explainer":
        return {
            "type": "explainer",
            **base,
            "brief": summary,
            "why_it_matters": generate_why_it_matters(title, summary),
        }

    # ── compact_brief: title + 1-line summary, no extras ────────
    if fmt == "compact_brief":
        return {"type": "compact_brief", **base, "summary": summary}

    # ── closing_brief: ultra-compact for "Before You Go" ────────
    if fmt == "closing_brief":
        return {"type": "closing_brief", **base}

    # ── short (default): title + summary ─────────────────────────
    return {"type": "short", **base, "summary": summary}


def format_mixed_section(clusters, section, template):
    """Format a section with mixed format types (lead_plus_short, explainer_plus_compact)."""
    fmt = section.get("format", "short")
    items = []

    if fmt == "lead_plus_short":
        lead_count = section.get("lead_count", 1)
        for i, c in enumerate(clusters):
            if i < lead_count:
                # Override format for lead item
                override = dict(section, format="lead")
                items.append(format_cluster(c, override, template))
            else:
                override = dict(section, format="short")
                items.append(format_cluster(c, override, template))

    elif fmt == "explainer_plus_compact":
        explainer_count = section.get("explainer_count", 1)
        for i, c in enumerate(clusters):
            if i < explainer_count:
                override = dict(section, format="explainer")
                items.append(format_cluster(c, override, template))
            else:
                override = dict(section, format="compact_brief")
                items.append(format_cluster(c, override, template))

    else:
        # Simple format — all items same type
        for c in clusters:
            items.append(format_cluster(c, section, template))

    return items


def build_section(section, clusters, template, selected_ids):
    filtered = filter_clusters(clusters, section, selected_ids)
    ranked = rank_clusters(filtered, section, template)
    selected = diversify_clusters(ranked, section, template)

    items = format_mixed_section(selected, section, template)
    for c in selected:
        selected_ids.add(c["id"])

    if not items and not section.get("required", False):
        return None

    result = {
        "id": section["id"],
        "title": section["title"],
        "description": section.get("description"),
        "items": items,
    }

    # Include scope_label for visual hierarchy on the website
    if section.get("scope_label"):
        result["scope_label"] = section["scope_label"]

    return result


def build_edition(template, clusters):
    selected_ids = set()
    sections = list(filter(None, [
        build_section(s, clusters, template, selected_ids)
        for s in template["sections"]
    ]))

    edition = {
        "title": template["title"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
    }

    # Include subtitle for newsletter tone
    if template.get("subtitle"):
        edition["subtitle"] = template["subtitle"]

    return edition


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