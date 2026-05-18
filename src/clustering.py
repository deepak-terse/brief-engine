from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from .config import CLUSTER_DISTANCE_THRESHOLD
from .database import get_connection
from .enricher import embedding_from_blob

logger = logging.getLogger(__name__)

@dataclass
class UnclusteredArticle:
    id: int
    category: str | None
    entities: list[str]
    embedding: np.ndarray

def fetch_unclustered_articles(conn: sqlite3.Connection) -> list[UnclusteredArticle]:
    rows = conn.execute(
        """
        SELECT id, category, entities, embedding
        FROM   articles
        WHERE  embedding  IS NOT NULL
          AND  cluster_id IS NULL
        ORDER  BY id
        """,
    ).fetchall()

    articles = []
    for row in rows:
        try:
            entities: list[str] = json.loads(row["entities"] or "[]")
        except (json.JSONDecodeError, TypeError):
            entities = []
        articles.append(
            UnclusteredArticle(
                id=row["id"],
                category=row["category"],
                entities=entities,
                embedding=embedding_from_blob(row["embedding"]),
            )
        )
    return articles


def insert_cluster(
    conn: sqlite3.Connection,
    category: str | None,
    centroid: np.ndarray,
    entities: dict[str, int],
    article_count: int,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO article_clusters (category, centroid, entities, summary, title, article_count)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            category,
            centroid.astype(np.float32).tobytes(),
            json.dumps(entities, ensure_ascii=False),
            "",
            "",
            article_count,
        ),
    )
    return cursor.lastrowid


def assign_cluster_to_articles(
    conn: sqlite3.Connection,
    article_ids: list[int],
    cluster_id: int,
) -> None:
    if not article_ids:
        return
    placeholders = ",".join("?" * len(article_ids))
    conn.execute(
        f"UPDATE articles SET cluster_id = ? WHERE id IN ({placeholders})",
        [cluster_id, *article_ids],
    )

def _merge_entities(articles: list[UnclusteredArticle]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for a in articles:
        counter.update(a.entities)
    return dict(counter)


def _centroid(embeddings: list[np.ndarray]) -> np.ndarray:
    mean = np.mean(np.stack(embeddings), axis=0)
    norm = np.linalg.norm(mean)
    return mean / norm if norm > 0 else mean


def _dominant_category(articles: list[UnclusteredArticle]) -> str | None:
    cats = [a.category for a in articles if a.category]
    return Counter(cats).most_common(1)[0][0] if cats else None


def _cluster_groups(articles: list[UnclusteredArticle]) -> dict[int, list[UnclusteredArticle]]:
    embeddings = np.stack([a.embedding for a in articles])
    labels = AgglomerativeClustering(
        n_clusters=None,
        metric="cosine",
        linkage="average",
        distance_threshold=CLUSTER_DISTANCE_THRESHOLD,
    ).fit_predict(embeddings)

    groups: dict[int, list[UnclusteredArticle]] = {}
    for label, article in zip(labels, articles):
        groups.setdefault(int(label), []).append(article)
    return groups

def cluster_articles() -> dict[str, int]:
    conn = get_connection()
    clusters_created = articles_assigned = 0

    try:
        conn.execute("PRAGMA journal_mode=WAL")
        articles = fetch_unclustered_articles(conn)

        if not articles:
            logger.info("Clustering: no unclustered articles found, skipping.")
            return {"total_articles": 0, "clusters_created": 0, "articles_assigned": 0}

        logger.info("Clustering %d articles...", len(articles))
        groups = _cluster_groups(articles)
        logger.info("Produced %d cluster(s).", len(groups))

        with conn:
            for members in groups.values():
                cluster_id = insert_cluster(
                    conn,
                    category=_dominant_category(members),
                    centroid=_centroid([m.embedding for m in members]),
                    entities=_merge_entities(members),
                    article_count=len(members),
                )
                assign_cluster_to_articles(conn, [m.id for m in members], cluster_id)
                clusters_created += 1
                articles_assigned += len(members)

    except Exception:
        logger.exception("Clustering pipeline failed.")
        raise
    finally:
        conn.close()

    summary = {"total_articles": len(articles), "clusters_created": clusters_created, "articles_assigned": articles_assigned}
    logger.info("Clustering complete: %s", summary)
    return summary