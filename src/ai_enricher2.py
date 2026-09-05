from src.utils import log_time
import json
import logging
import math
import sqlite3
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import ollama

from .database import get_connection
from .model import MODEL

logger = logging.getLogger(__name__)

MAX_ARTICLES_PER_CLUSTER = 8

# Batching config (TUNE THIS)
CLUSTER_BATCH_SIZE = 20
MAX_WORKERS = 4  # safe for M3 + Ollama

VALID_CATEGORIES = [
    "Politics", "Crime", "Safety", "Transport", "Weather", "Infra",
    "Healthcare", "Environment", "Business", "Education", "Community",
    "Lifestyle", "Sports",
]
VALID_SCOPES = ["Powai", "Mumbai", "India", "World"]

PROMPT_TEMPLATE = """\
You are a local news intelligence engine. Given articles about the SAME event:

1. Write a newsletter-style headline (max 12 words).
2. Write a tight summary (2 sentences, max 30 words).
3. Pick EXACTLY ONE category from: {categories}
4. Pick EXACTLY ONE scope: Powai, Mumbai, India, World

Return valid JSON only:
{{"title": "string", "summary": "string", "category": "string", "scope": "string"}}

Articles:
{articles}
"""


# ---------------- DB ----------------

def fetch_unenriched_clusters(cursor, limit=None, offset=0):
    query = """
        SELECT id, entities FROM article_clusters
        WHERE title = '' OR title IS NULL
        ORDER BY id
        LIMIT ? OFFSET ?
    """
    return cursor.execute(query, (limit or 1000000, offset)).fetchall()


def fetch_cluster_articles(cursor, cluster_id):
    return cursor.execute("""
        SELECT title, description, article_source_id, published_at
        FROM articles
        WHERE cluster_id = ?
        ORDER BY published_at DESC
        LIMIT ?
    """, (cluster_id, MAX_ARTICLES_PER_CLUSTER)).fetchall()


# ---------------- Prompt ----------------

def build_articles_text(articles):
    return "\n\n".join(
        f"{i}. Title: {a['title'] or ''}\nDescription: {a['description'] or ''}"
        for i, a in enumerate(articles, 1)
    )


# ---------------- LLM ----------------

def generate_cluster_metadata(articles_text):
    response = ollama.chat(
        model=MODEL,
        messages=[{
            "role": "user",
            "content": PROMPT_TEMPLATE.format(
                categories=", ".join(VALID_CATEGORIES),
                articles=articles_text,
            )
        }],
        options={
            "temperature": 0.1,
            "num_thread": 4
        },
    )

    try:
        result = json.loads(response["message"]["content"].strip())
        return {
            "title": result.get("title", "").strip(),
            "summary": result.get("summary", "").strip(),
            "category": result.get("category") if result.get("category") in VALID_CATEGORIES else "Community",
            "scope": result.get("scope") if result.get("scope") in VALID_SCOPES else "World",
        }
    except Exception:
        logger.exception("Failed parsing LLM response")
        return None


# ---------------- Scoring ----------------

def compute_recency_score(articles):
    datetimes = [
        datetime.fromisoformat(a["published_at"].replace("Z", "+00:00"))
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


# ---------------- Worker ----------------

def process_cluster(cluster_id):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        t0 = time.time()

        articles = fetch_cluster_articles(cursor, cluster_id)
        if not articles:
            return None

        result = generate_cluster_metadata(build_articles_text(articles))
        if not result:
            return None

        recency_score = compute_recency_score(articles)

        importance_score = compute_importance_score(
            len(articles),
            recency_score,
            len({a["article_source_id"] for a in articles}),
        )

        return {
            "cluster_id": cluster_id,
            "result": result,
            "recency_score": recency_score,
            "importance_score": importance_score,
            "article_count": len(articles),
            "duration": time.time() - t0,
        }

    finally:
        conn.close()

# ---------------- Main ----------------

@log_time
def enrich_clusters():
    logger.info("Starting AI cluster enrichment (BATCH MODE)")

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        clusters = fetch_unenriched_clusters(cursor)
        total = len(clusters)

        if not total:
            logger.info("No clusters found.")
            return

        logger.info("Total clusters: %d", total)

        # Convert to list of IDs
        cluster_ids = [c["id"] for c in clusters]

        # Process in batches
        for batch_start in range(0, total, CLUSTER_BATCH_SIZE):
            batch = cluster_ids[batch_start:batch_start + CLUSTER_BATCH_SIZE]

            logger.info(
                "Processing batch %d-%d",
                batch_start, batch_start + len(batch)
            )

            results = []

            # Parallel execution inside batch
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(process_cluster, cid): cid
                    for cid in batch
                }

                for f in as_completed(futures):
                    try:
                        res = f.result()
                        if res:
                            results.append(res)
                    except Exception:
                        logger.exception("Cluster failed")

            # DB write phase (sequential & safe)
            for r in results:
                try:
                    cursor.execute("""
                        UPDATE article_clusters
                        SET title = ?, summary = ?, category = ?, scope = ?,
                            article_count = ?, recency_score = ?, importance_score = ?,
                            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                        WHERE id = ?
                    """, (
                        r["result"]["title"],
                        r["result"]["summary"],
                        r["result"]["category"],
                        r["result"]["scope"],
                        r["article_count"],
                        r["recency_score"],
                        r["importance_score"],
                        r["cluster_id"],
                    ))
                except Exception:
                    logger.exception("DB update failed for %s", r["cluster_id"])

            conn.commit()

            logger.info(
                "Batch complete: %d clusters processed",
                len(results)
            )

    finally:
        conn.close()