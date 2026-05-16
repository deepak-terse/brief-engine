"""NLP enrichment: entity extraction, story signature, and semantic embedding.

Pipeline per article:
1. Extract named entities (PERSON, ORG, GPE, LOC, EVENT, PRODUCT) via spaCy.
2. Build a story signature: "entity1 | entity2 | ... || article_text"
3. Encode the signature with a sentence-transformer (384-d, L2-normalised).
4. Persist enrichment results into SQLite.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

import numpy as np
import spacy
from sentence_transformers import SentenceTransformer

from .config import SPACY_MODEL, SENTENCE_MODEL, TARGET_LABELS
from .database import get_connection

logger = logging.getLogger(__name__)

@dataclass
class Article:
    id: int | None
    title: str
    description: str | None = None
    entities: str | None = None
    signature: str | None = None
    embedding: bytes | None = None

@lru_cache(maxsize=1)
def load_nlp() -> spacy.language.Language:
    logger.info("Loading spaCy model: %s", SPACY_MODEL)
    try:
        return spacy.load(SPACY_MODEL, disable=["tagger", "parser", "lemmatizer"])
    except OSError:
        logger.exception("spaCy model '%s' not found. Run: python -m spacy download %s", SPACY_MODEL, SPACY_MODEL)
        raise

@lru_cache(maxsize=1)
def load_encoder() -> SentenceTransformer:
    logger.info("Loading sentence-transformer model: %s", SENTENCE_MODEL)
    return SentenceTransformer(SENTENCE_MODEL)

def extract_entities_batch(texts: list[str], batch_size: int = 64) -> list[list[str]]:
    results = []
    for doc in load_nlp().pipe(texts, batch_size=batch_size):
        seen: dict[str, str] = {}
        for ent in doc.ents:
            if ent.label_ in TARGET_LABELS and (original := ent.text.strip()):
                seen.setdefault(original.casefold(), original)
        results.append(sorted(seen.values()))
    return results

def build_signature(entities: list[str], article_text: str) -> str:
    article_text = (article_text or "").strip()
    return f"{' | '.join(entities)} || {article_text}" if entities else article_text

def embed_signatures(signatures: list[str], batch_size: int = 32) -> list[bytes]:
    vectors = np.asarray(
        load_encoder().encode(signatures, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False),
        dtype=np.float32,
    )
    return [v.tobytes() for v in vectors]

def build_article_text(title: str, description: str | None) -> str:
    title = (title or "").strip()
    description = (description or "").strip()
    if not description:
        return title
    separator = " " if title.endswith((".", "!", "?")) else ". "
    return f"{title}{separator}{description}"

def enrich_articles(articles: list[Article]) -> list[Article]:
    if not articles:
        return articles
    texts = [build_article_text(a.title, a.description) for a in articles]
    entities_batch = extract_entities_batch(texts)
    signatures = [build_signature(e, t) for e, t in zip(entities_batch, texts, strict=True)]
    embeddings = embed_signatures(signatures)
    for article, entities, signature, embedding in zip(articles, entities_batch, signatures, embeddings, strict=True):
        article.entities = json.dumps(entities, ensure_ascii=False)
        article.signature = signature
        article.embedding = embedding
    return articles

def fetch_unenriched_articles(conn: sqlite3.Connection, batch_size: int) -> list[Article]:
    rows = conn.execute(
        "SELECT id, title, description FROM articles WHERE embedding IS NULL ORDER BY id LIMIT ?",
        (batch_size,),
    ).fetchall()
    return [Article(id=r["id"], title=r["title"] or "", description=r["description"]) for r in rows]

def update_enriched_articles(conn: sqlite3.Connection, articles: Iterable[Article]) -> int:
    updates = [(a.entities, a.signature, a.embedding, a.id) for a in articles if a.id is not None and a.embedding is not None]
    if not updates:
        return 0
    conn.executemany("UPDATE articles SET entities=?, signature=?, embedding=? WHERE id=?", updates)
    return len(updates)

def enrich_unenriched_articles(batch_size: int = 50) -> dict[str, int]:
    conn = get_connection()
    total_found = total_enriched = 0
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        while True:
            articles = fetch_unenriched_articles(conn, batch_size)
            if not articles:
                break
            total_found += len(articles)
            try:
                enrich_articles(articles)
            except Exception:
                logger.exception("Batch enrichment failed, stopping")
                break
            with conn:
                total_enriched += update_enriched_articles(conn, articles)
    finally:
        conn.close()
    summary = {"total_found": total_found, "total_enriched": total_enriched}
    logger.info("Enrichment pipeline complete: %s", summary)
    return summary

def embedding_from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)