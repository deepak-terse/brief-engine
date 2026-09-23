# Implementation

Feature-level flows explaining how each part of Brief Engine works, the approach taken, and notable tradeoffs.

---

## Feed ingestion & deduplication

1. **Poll feeds:** Reads the `RSS_FEEDS` registry in `src/config.py`. Each entry defines `url`, `articleSourceId`, `category`, and geographic `scope`.
2. **Parse XML:** `feedparser.parse(url)` retrieves channel entries and detects malformed XML via `bozo_exception`.
3. **Freshness filtering:** Articles older than `FRESHNESS_DAYS = 2` are pruned before entering the pipeline:
   ```python
   pub_date >= datetime.now(timezone.utc) - timedelta(days=FRESHNESS_DAYS)
   ```
4. **Sanitization:**
   - HTML markup in summaries/descriptions is stripped using regex (`re.sub(r"<[^>]+>", "", html)`).
   - Publication timestamps are normalized into standard ISO-8601 UTC strings.
5. **Deduplication on insert:** Articles are inserted into SQLite with an `INSERT INTO articles ...` statement governed by a `url TEXT UNIQUE` constraint. Duplicate URLs trigger an `IntegrityError` and are safely skipped.

**Tradeoff:** Using RSS feeds rather than arbitrary headless browser scraping avoids complex DOM extraction pipelines, anti-scraping countermeasures, and rate limits. The tradeoff is that RSS feeds typically provide article excerpts rather than full bodies. For clustering, entity extraction, and editorial summaries, feed descriptions provide sufficient semantic signal while keeping database footprint and latency low.

---

## NLP enrichment & story signatures

1. **Target entity extraction:** The pipeline loads spaCy's `en_core_web_sm` model with unused components (`tagger`, `parser`, `lemmatizer`) disabled for high throughput.
2. **Entity filtering:** Entities are extracted and filtered against high-signal categories:
   ```python
   TARGET_LABELS = {"PERSON", "ORG", "GPE", "LOC", "EVENT", "PRODUCT"}
   ```
   Duplicates are eliminated using case-folded normalization (`seen.setdefault(ent.text.casefold(), ent.text)`).
3. **Story signature construction:** Entities and article text (title + description) are concatenated:
   ```python
   f"{' | '.join(entities)} || {article_text}"
   ```
4. **Vector encoding:** Signatures are encoded in batches using `all-MiniLM-L6-v2` (`SentenceTransformer`) with `normalize_embeddings=True`, producing 384-dimensional float32 vectors.
5. **Persistence:** The vector array is serialized via `.tobytes()` and written to the `embedding` column (BLOB) inside a SQLite transaction with WAL journaling enabled.

**Tradeoff:** Using dedicated local NLP models (`spaCy` + `SentenceTransformer`) instead of delegating entity extraction and embeddings to a large language model runs orders of magnitude faster (sub-millisecond per article on CPU) with deterministic reproducibility and zero token cost. The tradeoff is that `en_core_web_sm` is a small statistical model and occasionally mislabels domain-specific Indian proper nouns or acronyms; prepending all extracted entities into the signature helps mitigate individual label errors.

---

## Semantic clustering & centroid calculation

1. **Unclustered query:** Fetches all articles where `embedding IS NOT NULL AND cluster_id IS NULL`.
2. **Agglomerative clustering:** Embeddings are stacked into a 2D NumPy matrix and clustered using `scikit-learn`:
   ```python
   AgglomerativeClustering(
       n_clusters=None,
       metric="cosine",
       linkage="average",
       distance_threshold=CLUSTER_DISTANCE_THRESHOLD,  # 0.55
   ).fit_predict(embeddings)
   ```
3. **Centroid derivation:** For each cluster, the centroid vector is computed by taking the mean of all member vectors and normalizing to unit length:
   ```python
   mean = np.mean(np.stack(embeddings), axis=0)
   norm = np.linalg.norm(mean)
   centroid = mean / norm if norm > 0 else mean
   ```
4. **Entity aggregation & category voting:**
   - Entities across member articles are aggregated using a `Counter` to track topical prominence.
   - The cluster category is resolved by modal voting across member articles (`Counter(cats).most_common(1)[0][0]`).
5. **Atomic assignment:** The cluster record is created in `article_clusters`, and the assigned cluster ID is written back to member rows in `articles` within an atomic SQLite transaction.

**Tradeoff:** Agglomerative clustering with a distance threshold guarantees that any two articles within a cluster satisfy the average cosine similarity threshold ($\ge 0.45$). This avoids the arbitrary cluster counts required by $k$-means and the density sensitivity of DBSCAN across variable news volume. The tradeoff is quadratic memory complexity $O(N^2)$ for the pairwise distance matrix during clustering; because clustering runs daily over a rolling 2-day window ($N \approx 200\text{--}1,000$ articles), this computation takes under 2 seconds.

---

## AI cluster enrichment & scoring

1. **Candidate selection:** Selects clusters where `title = '' OR title IS NULL`.
2. **Context window preparation:** Retrieves up to `MAX_ARTICLES_PER_CLUSTER = 8` articles sorted by `published_at DESC`, assembling titles and descriptions into an indexed text block.
3. **Constrained LLM inference:** Prompts local Qwen 3 8B via Ollama (`temperature=0.1`) with a strict JSON response schema:
   ```json
   {"title": "string", "summary": "string", "category": "string", "scope": "string"}
   ```
   - **Headline constraint:** Conversational, newsletter-style headline focused on reader impact (max 12 words).
   - **Summary constraint:** 2 sentences, max 30 words, leading with daily life / commute / cost impact.
   - **Taxonomy validation:** Category and scope outputs are checked against `VALID_CATEGORIES` and `VALID_SCOPES`. Invalid outputs fall back safely to defaults (`"Community"` and `"World"`).
4. **Scoring calculations:**
   - **Recency score ($R$):** $R = \exp(-\Delta t_{\text{hours}} / 24)$ where $\Delta t_{\text{hours}}$ is the age of the latest article in hours.
   - **Importance score ($I$):**
     $$I = \min(N_{\text{articles}} / 10, 1) \times 0.45 + R \times 0.35 + \min(N_{\text{sources}} / 5, 1) \times 0.20$$
5. **Persistence:** The cluster row is updated with generated editorial copy, calculated scores, and timestamp.

**Tradeoff:** Single-turn JSON generation with strict validation minimizes latency and eliminates conversational overhead on local hardware. The tradeoff is that smaller quantized models (such as 8B Q4) occasionally output invalid JSON or unapproved categories. Defensive JSON parsing and schema fallbacks ensure that malformed responses never crash the pipeline.

---

## Brief compilation & template orchestration

1. **Cluster retrieval:** Fetches all clusters updated in the past 24 hours (`updated_at >= date('now', '-24 hours')`).
2. **Template iteration:** Iterates through declarative templates configured in `src/config.py` (e.g., `powai_pulse`, `powai_morning_edition`).
3. **Section filtering & ranking:** For each section:
   - Filters candidate clusters by allowed `scope`, `category`, and minimum importance score.
   - Excludes clusters already selected by previous sections in the same edition (`selected_ids`).
   - Ranks candidates using section-specific weights:
     ```python
     score = (
         c["importance_score"] * sort.get("importance", 0)
         + c["recency_score"] * sort.get("recency", 0)
         + template["scope_priority"].get(c["scope"], 0) * sort.get("scope", 0)
     )
     ```
   - Applies `dedupe_categories_per_section` to prevent single-category saturation.
4. **Format transformation:** Dispatches selected items to their designated format:
   - For `lead` and `explainer` formats, invokes a targeted LLM prompt to generate a concrete "Why it matters" statement.
   - If the template specifies `tone = "newsletter"`, runs secondary rewriting passes to tighten summaries and reframe headlines.
5. **Database storage:** Persists the compiled edition JSON into the `briefs` table with an idempotent `DELETE` on existing editions for the same date and template key.

**Tradeoff:** Using a deterministic rule engine for section filtering and ranking combined with targeted LLM formatting prevents hallucinations and missing sections. Letting an LLM decide the entire brief structure end-to-end often leads to dropped categories or inconsistent story counts; deterministic template orchestration ensures guaranteed editorial layout every day.

---

## Static site publishing

1. **Brief extraction:** `scripts/build_site.py` connects to SQLite and reads today's generated records from `briefs`.
2. **YAML frontmatter generation:** Serializes the edition hierarchy (metadata, sections, items, why-it-matters blurbs, tags) into structured Markdown frontmatter.
3. **Idempotent disk writes:** Writes files to `website/src/content/editions/{edition_key}/{YYYY-MM-DD}.md`. Skips files that already exist to prevent unintentional overwrite of manual edits.
4. **Astro content validation:** Astro's Content Collections (`website/src/content.config.js`) parse the exported Markdown using Zod schemas:
   ```javascript
   const newsItemSchema = z.object({
     type: z.enum(['one_line', 'short', 'explainer', 'alert_chip', 'lead', 'compact_brief', 'closing_brief']),
     title: z.string(),
     summary: z.string().optional(),
     why_it_matters: z.string().optional(),
     scope: z.string().optional(),
   });
   ```
5. **Zero-runtime rendering:** The Astro static site generator renders responsive, high-performance static HTML pages at build time.

**Tradeoff:** Decoupling the data pipeline from the presentation layer via static Markdown files means the website can be deployed to static edge hosting (Cloudflare Pages, Vercel, S3) with zero database exposure, zero server maintenance, and near-instant page load speeds. The tradeoff is that changes in the database require a static rebuild (`npm run build` or `npm run dev`) to become visible on the site.
