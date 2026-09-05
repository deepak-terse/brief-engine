"""RSS article fetching and database storage module."""

from src.utils import log_time
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import feedparser

from .config import RSS_FEEDS, FRESHNESS_DAYS
from .database import get_connection

logger = logging.getLogger(__name__)

def strip_html(html: str | None) -> str:
	if not html:
		return ""
	return re.sub(r"<[^>]+>", "", html).strip()

def normalize_timestamp(date_tuple: tuple | None) -> str | None:
	if not date_tuple:
		return None
	try:
		return datetime(*date_tuple[:6], tzinfo=timezone.utc).isoformat()
	except (ValueError, TypeError) as e:
		logger.warning(f"Failed to normalize timestamp {date_tuple}: {e}")
		return None

def is_fresh(date_tuple: tuple | None) -> bool:
	"""Return True if the entry's date is within the freshness window."""
	if not date_tuple:
		return False
	try:
		pub_date = datetime(*date_tuple[:6], tzinfo=timezone.utc)
		return pub_date >= datetime.now(timezone.utc) - timedelta(days=FRESHNESS_DAYS)
	except (ValueError, TypeError):
		return False

def clean_article(entry: dict, rss_feed_id: int, article_source_id: int, category: str) -> dict:
	return {
		"article_source_id": article_source_id,
		"rss_feed_id": rss_feed_id,
		"category": category,
		"published_at": normalize_timestamp(entry.get("published_parsed")),
		"title": entry.get("title", "").strip(),
		"description": strip_html(entry.get("summary", entry.get("description", ""))),
		"url": entry.get("link", "").strip(), # ToDo: Strip tracking params
		"entities": None,
		"signature": None,
		"embedding": None,
	}

def fetch_rss_feeds() -> list[dict]:
	articles = []

	for feed in RSS_FEEDS:
		feed_url = feed.get("url")
		feed_id = feed.get("id")

		if not feed_url:
			logger.warning(f"Feed {feed_id} has no URL, skipping")
			continue

		try:
			logger.info(f"Fetching feed {feed_id}: {feed_url}")
			result = feedparser.parse(feed_url)

			if result.get("bozo_exception"):
				logger.warning(f"Feed {feed_id} has parsing issues: {result.bozo_exception}")

			entries = result.get("entries", [])
			if not entries:
				logger.warning(f"Feed {feed_id} returned no entries")
				continue

			fresh = [e for e in entries if is_fresh(e.get("published_parsed"))]
			logger.info(f"Feed {feed_id}: {len(entries)} entries, {len(fresh)} within {FRESHNESS_DAYS}-day window")

			for entry in fresh:
				try:
					articles.append(clean_article(entry, feed_id, feed.get("articleSourceId"), feed.get("category", "Uncategorized")))
				except Exception as e:
					logger.warning(f"Failed to clean entry from feed {feed_id}: {e}")

		except Exception as e:
			logger.error(f"Failed to fetch feed {feed_id} from {feed_url}: {e}")

	return articles

def insert_articles_batch(articles: list[dict]) -> int:
	if not articles:
		return 0

	conn = get_connection()
	cursor = conn.cursor()
	inserted_count = 0

	try:
		for article in articles:
			try:
				cursor.execute("""
					INSERT INTO articles (
							article_source_id, rss_feed_id, category, published_at,
							title, description, url, entities, signature, embedding
					) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
				""", (
					article["article_source_id"], article["rss_feed_id"], article["category"],
					article["published_at"], article["title"], article["description"],
					article["url"], article["entities"], article["signature"], article["embedding"],
				))
				inserted_count += 1
			except sqlite3.IntegrityError as e:
				logger.warning(f"Integrity error inserting article '{article['title'][:50]}': {e}")

		conn.commit()
		logger.info(f"Inserted {inserted_count} articles into database")

	except Exception as e:
		logger.error(f"Batch insert failed: {e}")
		conn.rollback()
		raise

	finally:
		conn.close()

	return inserted_count

@log_time
def fetch_and_store() -> dict:
	logger.info("Starting RSS fetch and store pipeline...")
	articles = fetch_rss_feeds()
	inserted = insert_articles_batch(articles)
	summary = {"total_fetched": len(articles), "total_inserted": inserted}
	logger.info(f"Pipeline complete: {summary}")
	return summary