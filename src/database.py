"""SQLite database initialization and management."""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "brief_engine.db"

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database(db_path: Path | None = None) -> None:
	if db_path is None:
		db_path = DB_PATH
	
	db_path.parent.mkdir(parents=True, exist_ok=True)
	conn = sqlite3.connect(db_path)
	cursor = conn.cursor()
	
	try:
		cursor.execute("""
			CREATE TABLE IF NOT EXISTS articles (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				article_source_id INTEGER NOT NULL,
				rss_feed_id INTEGER NOT NULL,
				category TEXT,
				published_at TIMESTAMP,
				title TEXT NOT NULL,
				description TEXT,
				url TEXT UNIQUE,
				entities TEXT,
				signature TEXT,
				embedding BLOB,
				cluster_id INTEGER REFERENCES article_clusters(id) ON DELETE SET NULL,
				created_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
				updated_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
			)
		""")
		
		cursor.execute("""
			CREATE TABLE IF NOT EXISTS article_clusters (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				category TEXT,
				centroid BLOB NOT NULL,
				entities TEXT NOT NULL DEFAULT '{}',
				summary TEXT NOT NULL,
				title TEXT NOT NULL,
				article_count INTEGER NOT NULL DEFAULT 1,
				scope TEXT,
				recency_score REAL,
				importance_score REAL,
				created_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
				updated_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
			)
		""")

		cursor.execute("""
			CREATE TABLE IF NOT EXISTS briefs (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				edition_key TEXT NOT NULL,
				title TEXT NOT NULL,
				generated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
				template_name TEXT NOT NULL,
				template_version TEXT DEFAULT 'v1',
				content_json TEXT NOT NULL,
				rendered_text TEXT,
				cluster_ids_json TEXT,
				read_time_minutes INTEGER DEFAULT 5,
				metadata_json TEXT,
				UNIQUE(edition_key, generated_at)
			);
		""")
		
		cursor.execute("CREATE INDEX IF NOT EXISTS idx_clusters_created_at ON article_clusters(created_at)")
		cursor.execute("CREATE INDEX IF NOT EXISTS idx_clusters_category_created ON article_clusters(category, created_at)")
		cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_cluster_id ON articles(cluster_id)")
		cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_embedding_cluster ON articles(embedding, cluster_id)")
		cursor.execute("CREATE INDEX IF NOT EXISTS idx_briefs_generated_at ON briefs(generated_at DESC)")
		cursor.execute("CREATE INDEX IF NOT EXISTS idx_briefs_edition_key ON briefs(template_name)")
		
		conn.commit()
		logger.info(f"Database initialized at {db_path}")

	except sqlite3.Error as e:
			logger.error(f"Database initialization error: {e}")
			conn.rollback()
			raise

	finally:
			conn.close()

if __name__ == "__main__":
	init_database()