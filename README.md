# Brief Engine

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-D22128?logo=apache&logoColor=white)](https://www.apache.org/licenses/LICENSE-2.0)
[![AI: Ollama](https://img.shields.io/badge/AI-Ollama-10B981?logoColor=white&logo=ollama&logoColor=white)](https://ollama.com)

> An open-source intelligence engine that turns noisy information into a focused daily brief.

Brief Engine ingests RSS content from multiple sources, groups related stories, ranks what matters, and generates concise summaries using local LLMs.

```text
Sources → Extract → Cluster → Rank → Summarise → Publish
```

## Why this project exists

The internet produces more information than any person can reasonably absorb.

Brief Engine is a practical response to that problem: filter the signal, reduce duplication, surface the stories that matter, and present them in a format that is fast to read and easy to trust.

What started as a local, personal daily brief for Powai, Mumbai evolved into a broader idea: build a reusable pipeline for turning fragmented news into a clean, narrative summary.

## What it does

- 📰 Ingests news from multiple RSS sources
- 🧠 Extracts entities and generates embeddings
- 🔗 Clusters related stories across sources
- 📊 Ranks stories by relevance, recency, and source diversity
- ✍️ Generates newsletters-style headlines and summaries
- 🤖 Uses local LLMs through Ollama instead of paid APIs
- 📝 Publishes clean Markdown editions for a static site

## Built for

- Local and community news
- AI and technology news
- Developer and open-source intelligence
- Research and industry monitoring
- Personalized information feeds

## Why it stands out

This project combines multiple real-world engineering patterns in one system:

- Multi-source ingestion with normalization and deduplication
- NLP enrichment using entity extraction and semantic embeddings
- Unsupervised clustering to group related coverage across providers
- Ranking logic based on relevance, recency, and source diversity
- Local-first AI summarization with Ollama, avoiding paid API dependency
- Static publishing with Astro for lightweight content delivery

It is not just a prompt demo; it is a pipeline system that turns raw information into something useful.

## Architecture

### Pipeline overview

| Stage | Technology | Purpose |
|---|---|---|
| Fetch | `feedparser` | Pull articles from RSS feeds |
| Extract | `spaCy` + `sentence-transformers` | Extract entities and encode article meaning |
| Cluster | `scikit-learn` | Group related stories across sources |
| Rank | Custom scoring logic | Prioritize high-signal stories |
| Summarise | Ollama + local LLM | Generate concise, impact-focused summaries |
| Publish | Astro + Markdown | Render the final brief as structured content |

### Runtime and storage

- SQLite for local persistence and easy inspection
- Python orchestration for the full pipeline
- Astro static site for fast, low-maintenance content delivery

## Local-first by design

The system is intentionally designed to run without paid APIs:

- Ollama
- Qwen
- spaCy
- SQLite
- Sentence Transformers

No paid API required.

## Example workflow

```text
500+ articles
      ↓
Related stories clustered
      ↓
Important stories ranked
      ↓
Daily brief generated
```

## Screenshots

### Landing page

![Powai Daily landing page](assets/screenshot0.png)

### Sample edition

![Sample daily brief edition](assets/screenshot1.png)

## Getting started

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management
- Node.js 18+
- [Ollama](https://ollama.com) running locally

### Installation

```bash
git clone https://github.com/deepak-terse/brief-engine
cd brief-engine
uv sync
```

Pull the model used by the pipeline:

```bash
ollama pull qwen3:8b-q4_K_M
```

Install the website dependencies:

```bash
cd website && npm install
```

### Configure the pipeline

Edit `src/config.py` to customize:

- `RSS_FEEDS` for source and scope setup
- `BRIEF_TEMPLATES` for section logic and scoring
- `CLUSTER_DISTANCE_THRESHOLD` for story grouping granularity

You can also swap the model in `src/model.py`.

### Run the pipeline

```bash
# Fetch, enrich, cluster, rank, and generate the brief
uv run start

# Export generated briefs to Markdown for the website
uv run publish

# Start the Astro site locally
cd website && npm run dev
```

The site is typically available at:

```text
http://localhost:4321
```

## Why it matters

The goal is not just to collect headlines. It is to reduce noise and surface what deserves attention.

Brief Engine is an attempt to turn information overload into a focused, trustworthy daily brief that helps a reader decide what is worth knowing.

## Contributing

Contributions are welcome.

This project is a practical end-to-end AI pipeline for local news intelligence, with opportunities in:

- ranking and deduplication
- cluster quality and topic grouping
- LLM prompt tuning and summary quality
- source expansion and filtering
- frontend and newsletter UX

If you are interested in improving the pipeline, adding sources, or tuning the publication flow, open an issue or submit a pull request.

## Roadmap

- Scheduled daily runs
- Email and WhatsApp delivery
- Feedback-driven ranking improvements
- Multi-city and multi-audience support
- Better observability and quality metrics
- More source adapters and content filters

## Contributing

Contributions are welcome.

If you are interested in improving the pipeline, adding sources, tuning ranking, or enhancing the publishing experience, open an issue or start a pull request.

## License

This project is open source and intended for learning, experimentation, and community improvement.

---

Built to make information more useful, not just more available.
