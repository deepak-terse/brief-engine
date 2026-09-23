# Architecture

High-level design of how Brief Engine is structured and how data flows through the system.

## System flow

```text
RSS Feeds (Mumbai Live · Google News · The Hindu)
    ↓
Fetcher (feedparser → HTML sanitization → ISO-8601 UTC → 2-day freshness filter)
    ↓
SQLite: articles table (WAL mode · UNIQUE url deduplication)
    ↓
NLP Enricher (spaCy NER → target labels → story signature → all-MiniLM-L6-v2)
    ↓
Clustering Engine (AgglomerativeClustering · cosine metric · threshold 0.55)
    ↓
AI Enricher (Ollama Qwen 3 8B · JSON schema constraint · recency decay · importance score)
    ↓
SQLite: article_clusters table (centroids · entities · scores · summaries)
    ↓
Brief Generator (template rules · section filtering · multi-criteria ranking · format dispatch)
    ↓
SQLite: briefs table (edition_key · content_json · cluster_ids)
    ↓
Static Site Builder (scripts/build_site.py → YAML frontmatter serialization)
    ↓
Astro Static Site (Content Collections · type-safe Zod schema · responsive reader UI)
```

## Component structure

```text
brief-engine/
├── src/
│   ├── main.py                 # Pipeline entry point and stage orchestrator
│   ├── config.py               # Feed registry, taxonomies, scopes, thresholds, and edition templates
│   ├── database.py             # SQLite connection management, schema initialization, indices
│   ├── fetcher.py              # RSS polling, HTML stripping, timestamp normalization, batch insertion
│   ├── enricher.py             # spaCy NER, story signature composition, sentence-transformer embedding
│   ├── clustering.py           # Unsupervised agglomerative clustering, centroid and entity calculation
│   ├── ai_enricher.py          # Ollama JSON summarization, scope classification, recency & importance scoring
│   ├── brief_generator.py      # Declarative template evaluation, multi-factor ranking, section assembly
│   └── model.py                # Ollama client initialization and model pre-warming
├── scripts/
│   └── build_site.py           # Database-to-Astro exporter (generates YAML-frontmatter Markdown)
├── website/
│   ├── astro.config.mjs        # Astro configuration
│   └── src/
│       ├── content.config.js   # Content collection schemas (Zod validation for editions and items)
│       ├── content/editions/   # Generated markdown edition archives by edition key
│       ├── layouts/            # Page layouts and base HTML structures
│       └── pages/              # Index and edition reader routes
└── data/
    └── brief_engine.db         # SQLite database file (WAL mode)
```

## Storage model

The pipeline uses SQLite in WAL mode (`PRAGMA journal_mode=WAL`) for predictable concurrent reads during ingestion and static generation. High-dimensional vectors are stored directly as binary blobs (`np.float32.tobytes()`).

| Table | Primary key | Key columns | Purpose |
|---|---|---|---|
| `articles` | `id` (INTEGER AUTO) | `url` (UNIQUE), `article_source_id`, `rss_feed_id`, `category`, `published_at`, `entities`, `signature`, `embedding` (BLOB), `cluster_id` | Normalized raw ingest records with NLP enrichment metadata |
| `article_clusters` | `id` (INTEGER AUTO) | `category`, `centroid` (BLOB), `entities` (JSON), `summary`, `title`, `article_count`, `scope`, `recency_score`, `importance_score` | Clustered story events with AI-synthesized editorial summaries and scores |
| `briefs` | `id` (INTEGER AUTO) | `edition_key`, `title`, `generated_at`, `template_name`, `content_json`, `cluster_ids_json`, `read_time_minutes` | Compiled daily editions ready for site export (keyed by edition and date) |

**Index strategy:**
- `idx_articles_cluster_id` on `articles(cluster_id)`: Accelerates unclustered article queries and cluster member hydration.
- `idx_articles_embedding_cluster` on `articles(embedding, cluster_id)`: Speeds up unenriched/unclustered pipeline queries.
- `idx_clusters_created_at` on `article_clusters(created_at)`: Filters active clusters for the daily edition window.
- `idx_clusters_category_created` on `article_clusters(category, created_at)`: Accelerates section candidate selection.
- `idx_briefs_generated_at` and `idx_briefs_edition_key`: Optimizes edition lookup and publication export.

## Story representation & signature

Embedding raw news articles directly leads to semantic drift when multiple outlets cover the same event using different rhetorical framing or boilerplate filler. Brief Engine solves this by prepending extracted named entities to the text to form a **story signature**:

```text
Raw Article:
  Title:       "Tunnel road project faces civic opposition in Powai"
  Entities:    ["Powai", "Adani", "BMC", "Tunnel Road"]

Story Signature:
  "Adani | BMC | Powai | Tunnel Road || Tunnel road project faces civic opposition in Powai. Residents cite traffic delays..."
```

The signature is encoded using `all-MiniLM-L6-v2` into a 384-dimensional vector, L2-normalized:

$$\vec{v} = \frac{\text{encode}(\text{signature})}{\|\text{encode}(\text{signature})\|_2}$$

Because vectors are unit-normalized, the cosine distance between two signatures corresponds directly to Euclidean distance:

$$D_{\text{cosine}}(\vec{u}, \vec{v}) = 1 - (\vec{u} \cdot \vec{v})$$

## Unsupervised clustering model

Clustering groups cross-source reporting into discrete event clusters without requiring a predefined cluster count $k$:

1. **Algorithm:** `AgglomerativeClustering` with average linkage and metric `cosine`.
2. **Distance Threshold:** `0.55`. Articles with cosine distance $\le 0.55$ merge into the same event.
3. **Centroid Computation:** The cluster centroid is the unit-normalized mean of all constituent article vectors:

$$\vec{c} = \frac{\sum_{i=1}^N \vec{v}_i}{\|\sum_{i=1}^N \vec{v}_i\|_2}$$

4. **Entity Aggregation:** Entity frequencies across all articles in the cluster are merged into a frequency map (`{"Powai": 4, "BMC": 3}`) to preserve topical context.
5. **Dominant Category:** The modal category among member articles is assigned as the cluster's default category.

## Scoring & ranking framework

Clusters are prioritized through two complementary metrics:

### 1. Recency score ($R$)
Models information decay using an exponential half-life curve over the newest article in the cluster:

$$R = \text{round}\left(\exp\left(-\frac{\Delta t_{\text{hours}}}{24}\right), 3\right)$$

A story published 6 hours ago scores $\approx 0.779$; a story published 24 hours ago scores $\approx 0.368$.

### 2. Importance score ($I$)
Synthesizes coverage depth, freshness, and cross-source verification:

$$I = \text{round}\left(\min\left(\frac{N_{\text{articles}}}{10}, 1\right) \times 0.45 + R \times 0.35 + \min\left(\frac{N_{\text{sources}}}{5}, 1\right) \times 0.20, 3\right)$$

- **Coverage volume ($45\%$):** Multi-outlet coverage indicates higher editorial priority.
- **Recency ($35\%$):** Fresh developments outrank stale events.
- **Source diversity ($20\%$):** Stories syndicated across distinct publishers receive a verification boost.

### 3. Section candidate ranking
Sections in each edition template evaluate candidates by combining importance, recency, and scope priority weights:

$$\text{Score}_{\text{candidate}} = I \cdot w_{\text{importance}} + R \cdot w_{\text{recency}} + P_{\text{scope}} \cdot w_{\text{scope}}$$

## Templating & edition engine

Editions are compiled through declarative configurations in `src/config.py`:

- **Scope Priority:** Biases story selection toward hyperlocal coverage (e.g., `Powai: 1.0`, `Mumbai: 0.82`, `India: 0.42`, `World: 0.22`).
- **Diversity Enforcement:** `dedupe_categories_per_section` caps how many stories of the same category can appear in a single section (default: 2), preventing civic or sports news from crowding out other updates.
- **Format Polymorphism:** Sections dispatch items to specific visual presentations:
  - `one_line`: Minimal single-sentence status line.
  - `short`: Headline and tightened 2-sentence summary.
  - `lead`: Prominent card requiring an LLM-generated "Why it matters" impact sentence.
  - `explainer`: Context-heavy card detailing policy, price, or civic ramifications.
  - `compact_brief`: Condensed side-card for secondary coverage.

## Static site publishing

The publishing bridge (`scripts/build_site.py`) decodes compiled briefs from SQLite and serializes them into YAML-frontmatter Markdown files:

```text
website/src/content/editions/{edition_key}/{YYYY-MM-DD}.md
```

Astro ingests these files through type-safe Content Collections validated by Zod schemas (`website/src/content.config.js`). This architecture completely decouples compute-heavy ingestion, NLP, and LLM synthesis from static web serving.
