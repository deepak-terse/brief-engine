"""Main entry point for the brief engine."""

import logging

from .clustering import cluster_articles	
from .database import init_database
from .model import init_model
from .enricher import enrich_unenriched_articles
from .fetcher import fetch_and_store
from .ai_enricher import enrich_clusters
from .brief_generator import generate_brief

logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

def main():
	"""Main pipeline orchestrator."""
	logger.info("Starting brief-engine pipeline...")
	init_database()
	init_model()
	fetch_and_store()
	enrich_unenriched_articles()
	cluster_articles()
	enrich_clusters()
	generate_brief()
	logger.info("Pipeline completed successfully")

if __name__ == "__main__":
	main()
