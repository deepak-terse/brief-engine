"""Minimal Ollama model initialization."""

from src.utils import log_time
import logging
import ollama

logger = logging.getLogger(__name__)

MODEL = "qwen3:8b-q4_K_M"
# MODEL = "qwen2.5:3b-instruct"

@log_time
def init_model() -> bool:
    """Pull model if needed and warm it up."""
    try:
        logger.info(f"Ensuring model '{MODEL}' is available...")
        ollama.pull(MODEL)

        logger.info(f"Warming up '{MODEL}'...")
        ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": "Ready?"}],
        )

        logger.info("Model ready.")
        return True

    except Exception as e:
        logger.exception(f"Failed to initialize model: {e}")
        return False