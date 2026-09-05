from src.utils import log_time
import json
import logging
import math
import sqlite3
import time
from datetime import datetime, timezone
import re
import ollama

from .database import get_connection
from .model import MODEL

logger = logging.getLogger(__name__)

MAX_ARTICLES_PER_CLUSTER = 8

VALID_CATEGORIES = [
    "Politics", "Crime", "Safety", "Transport", "Weather", "Infra",
    "Healthcare", "Environment", "Business", "Education", "Community",
    "Lifestyle", "Sports",
]
VALID_SCOPES = ["Powai", "Mumbai", "India", "World"]

PROMPT_TEMPLATE = """\
You are a local news intelligence engine. Given articles about the SAME event:

1. Write a newsletter-style headline (max 12 words).
   - Focus on READER IMPACT, not the event itself.
   - Use conversational, direct language.
2. Write a tight summary (2 sentences, max 30 words).
   - Lead with how it affects a resident's commute, cost, safety, or daily routine.
   - Be concrete and specific.
3. Pick EXACTLY ONE category from: {categories}
4. Pick EXACTLY ONE scope:
   - Powai → hyperlocal Powai issue/event
   - Mumbai → city-level relevance
   - India → national relevance
   - World → international relevance

Rules: merge overlaps, no clickbait, confirmed facts only, mention key \
people/places/companies, no sources. Prefer Powai scope when plausible.

No markdown, no code fences. Return valid JSON only:
{{"title": "string", "summary": "string", "category": "string", "scope": "string"}}

Articles:
{articles}"""


def fetch_unenriched_clusters(cursor):
    return cursor.execute("""
        SELECT id, entities FROM article_clusters
        WHERE title = '' OR title IS NULL
    """).fetchall()


def fetch_cluster_articles(cursor, cluster_id):
    return cursor.execute("""
        SELECT title, description, article_source_id, published_at
        FROM articles
        WHERE cluster_id = ?
        ORDER BY published_at DESC
        LIMIT ?
    """, (cluster_id, MAX_ARTICLES_PER_CLUSTER)).fetchall()


def build_articles_text(articles):
    return "\n\n".join(
        f"{i}. Title: {a['title'] or ''}\nDescription: {a['description'] or ''}"
        for i, a in enumerate(articles, 1)
    )


def generate_cluster_metadata(articles_text):
    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": PROMPT_TEMPLATE.format(
            categories=", ".join(VALID_CATEGORIES),
            articles=articles_text,
        )}],
        options={"temperature": 0.1},
    )


    content = response["message"]["content"].strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.DOTALL)
    result = json.loads(content)

    print('################ response : ' , response['message']['content'])
    try:
        # result = json.loads(response["message"]["content"].strip())
        content = response["message"]["content"].strip()
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.DOTALL)
        result = json.loads(content)
        return {
            "title": result.get("title", "").strip(),
            "summary": result.get("summary", "").strip(),
            "category": result.get("category") if result.get("category") in VALID_CATEGORIES else "Community",
            "scope": result.get("scope") if result.get("scope") in VALID_SCOPES else "World",
        }
    except Exception:
        logger.exception("Failed parsing LLM response")
        return None


def compute_recency_score(articles):
    datetimes = [
        datetime.fromisoformat(a["published_at"].replace("Z", "+00:00")).replace(
            tzinfo=timezone.utc
        ) if datetime.fromisoformat(a["published_at"].replace("Z", "+00:00")).tzinfo is None
        else datetime.fromisoformat(a["published_at"].replace("Z", "+00:00"))
        for a in articles
    ]
    age_hours = (datetime.now(timezone.utc) - max(datetimes)).total_seconds() / 3600
    return round(math.exp(-age_hours / 24), 3)


def compute_importance_score(article_count, recency_score, unique_source_count):
    return round(
        min(article_count / 10, 1) * 0.45
        + recency_score * 0.35
        + min(unique_source_count / 5, 1) * 0.20,
        3,
    )

@log_time
def enrich_clusters():
    logger.info("Starting AI cluster enrichment")
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        clusters = fetch_unenriched_clusters(cursor)
        total = len(clusters)

        if not total:
            logger.info("No unenriched clusters found. Skipping.")
            return

        logger.info("Found %d clusters to enrich.", total)

        for i, cluster in enumerate(clusters, 1):
            if i == 11:
                break
            cluster_id = cluster["id"]
            t0 = time.time()
            try:
                logger.info("[%d/%d] Enriching cluster %s...", i, total, cluster_id)

                articles = fetch_cluster_articles(cursor, cluster_id)
                if not articles:
                    logger.warning("Cluster %s has no articles. Skipping.", cluster_id)
                    continue

                result = generate_cluster_metadata(build_articles_text(articles))
                if not result:
                    logger.error("Failed to generate metadata for cluster %s", cluster_id)
                    continue

                recency_score = compute_recency_score(articles)
                importance_score = compute_importance_score(
                    len(articles),
                    recency_score,
                    len({a["article_source_id"] for a in articles}),
                )

                # cursor.execute("""
                #     UPDATE article_clusters
                #     SET title = ?, summary = ?, category = ?, scope = ?,
                #         article_count = ?, recency_score = ?, importance_score = ?,
                #         updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                #     WHERE id = ?
                # """, (
                #     result["title"], result["summary"], result["category"], result["scope"],
                #     len(articles), recency_score, importance_score, cluster_id,
                # ))

                conn.commit()
                logger.info(
                    "Cluster %s enriched in %.2fs [%s | %s]",
                    cluster_id, time.time() - t0, result["category"], result["scope"],
                )

            except Exception:
                logger.exception("Cluster enrichment failed: %s", cluster_id)

    finally:
        conn.close()