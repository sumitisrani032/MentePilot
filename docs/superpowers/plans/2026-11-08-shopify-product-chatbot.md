# Shopify Product Chatbot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a public, multi-store Shopify app whose storefront chatbot answers free-form requests only with that store's real products.

**Architecture:** FastAPI backend with a LangGraph pipeline of focused agents over hybrid RAG in Postgres with pgvector. Each store's data is isolated by row-level security. A background worker handles catalog sync, and thin JavaScript surfaces (Theme App Extension widget, embedded admin page) talk to the Python API.

**Tech Stack:** Python 3.12, uv, FastAPI, sse-starlette, SQLAlchemy 2 async, asyncpg, pgvector, Alembic, LangGraph, langchain-openai, arq, Redis, httpx, PyJWT, cryptography, pydantic-settings, pytest, pytest-asyncio, respx, ruff, mypy. Vanilla ES modules for JavaScript, with ESLint and Prettier.

**Spec:** `docs/superpowers/specs/2026-11-08-shopify-product-chatbot-design.md`

## Global Constraints

**Rules set by the project owner. These override every other instruction here.**

- **Do not run any test.** Write every test, but do not execute pytest, evals or JS tests until the owner starts the joint test session (Task 27).
- **Never call the LLM API without asking the owner first, every time.** `LLM_CALLS_ENABLED` defaults to `false`.
- **Call no external API except Shopify.** Installing packages or pulling images needs the owner's confirmation first.
- **Ask the owner whenever a key is needed.** Keys go in a local `.env`, never in chat or git.
- **Ask questions one at a time.**
- **Small, relevant commits**, using Conventional Commits. A task may be several commits. End each message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Follow each language's standards:** PEP 8 with ruff, full type hints with `mypy --strict`, ESLint and Prettier for JavaScript, Shopify conventions for Liquid and TOML.

**Because tests cannot run yet:** keep test-first order, and write each test before its code. Each task's check step is the static check only: `uv run ruff check . && uv run ruff format --check . && uv run mypy src` (once dependencies are installed). Never report a task's behaviour as verified; report "written, not run".

**Values from the spec:**

- English only. Non-English messages get a polite English reply.
- Up to 5 products per reply. At most 1 retrieval retry per message.
- Chat history in Redis only, 24-hour expiry (`86400` seconds). No stored transcripts, photos or audio.
- Scopes: `read_products`, `read_inventory`. The app never writes to the store.
- Firm requirements filter only on `stated` facts, price and availability.
- No code may be specific to cosmetics. Cosmetic wording may appear only in test data.
- No cost limits: record usage, block nothing.

**Plan-level values:** package `shopchat` in `src/shopchat`. Embeddings 1536 dimensions. RRF `k=60`; 50 results from each search, 30 merged candidates, 20 passed to selection. Message limit 1000 characters. Images JPEG, PNG or WebP up to 5 MB. Audio webm, mp4, mpeg or wav up to 10 MB. Widget token lifetime 3600 seconds. Session history 10 turns. Shopify API version from `SHOPIFY_API_VERSION`, default `2026-10`.

## Review Focus

Each has a named test in the owning task.

1. Empty, whitespace-only or over-long message: rejected with 422 before any LLM call (Task 18).
2. Store with no products yet, or import running: friendly "catalog is still being prepared" reply, no crash, no invented products (Task 17).
3. Product with no image or description, or all variants sold out: cards render without an image, sold-out products are not recommended (Tasks 10, 15).
4. Duplicate or out-of-order webhooks, or a webhook arriving during the first import: idempotent, and an older `updated_at` never overwrites newer data (Task 25).
5. Blurry or irrelevant photo, or a face uploaded through the normal product path: asks for a better photo, or points to the consent flow, without analysing the face (Task 20).

---

## Milestone 1: Foundation and catalog

### Task 1: Project scaffold and settings

**Files:**
- Create: `pyproject.toml`, `.env.example`, `Dockerfile`, `docker-compose.yml`, `README.md`, `src/shopchat/__init__.py`, `src/shopchat/config.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `Settings` (pydantic-settings) and `get_settings() -> Settings`. Fields: `database_url`, `database_owner_url`, `redis_url`, `app_url`, `llm_calls_enabled: bool = False`, `voice_enabled: bool = False`, `openai_api_key: SecretStr | None = None`, `openai_model_fast`, `openai_model_smart`, `openai_model_embedding`, `openai_model_stt`, `openai_model_tts` (all `str | None = None`), `shopify_api_key`, `shopify_api_secret: SecretStr | None = None`, `shopify_api_version = "2026-10"`, `token_encryption_key: SecretStr | None = None`, `widget_token_secret: SecretStr | None = None`.

- [ ] **Step 1: Write the test**

```python
def test_llm_and_voice_are_off_by_default(monkeypatch):
    monkeypatch.delenv("LLM_CALLS_ENABLED", raising=False)
    monkeypatch.delenv("VOICE_ENABLED", raising=False)
    s = Settings(_env_file=None, database_url="x", database_owner_url="x", redis_url="x", app_url="x")
    assert s.llm_calls_enabled is False and s.voice_enabled is False
```

- [ ] **Step 2: Implement settings and scaffold.** Compose runs `pgvector/pgvector:pg16` (pgvector 0.8 or later) and `redis:7`, plus `api` and `worker` services. Compose must not start anything automatically in this plan.
- [ ] **Step 3: Static check** (ask to install dependencies the first time).
- [ ] **Step 4: Commit** — one commit for tooling, one for settings: `chore: scaffold python project`, `feat: add typed settings with LLM calls off by default`.

### Task 2: LLM ports with a hard off switch

**Files:**
- Create: `src/shopchat/llm/ports.py`, `src/shopchat/llm/openai_adapters.py`, `tests/fakes.py`
- Test: `tests/unit/test_llm_gate.py`

**Interfaces:**
- Produces in `ports.py`: `ModelTier(StrEnum)` with `FAST`, `SMART`; `ImagePart(data: bytes, media_type: str)`; protocols:
  - `StructuredLLM.generate(system: str, user: str, schema: type[T], tier: ModelTier, images: Sequence[ImagePart] = ()) -> T` (async)
  - `TextStreamer.stream(system: str, user: str, tier: ModelTier) -> AsyncIterator[str]`
  - `Embedder.embed(texts: Sequence[str]) -> list[list[float]]` (async)
  - `SpeechToText.transcribe(audio: bytes, media_type: str) -> str` (async)
  - `TextToSpeech.speak(text: str) -> bytes` (async)
  - `LLMBundle` dataclass with fields `structured`, `streamer`, `embedder`, `stt`, `tts`
- Produces in `openai_adapters.py`: `LLMCallsDisabledError(RuntimeError)`, `build_openai_bundle(settings: Settings) -> LLMBundle`
- Produces in `tests/fakes.py`: `FakeStructuredLLM(responses: list[BaseModel])` (records calls), `FakeStreamer(tokens)`, `FakeEmbedder` (deterministic 1536-dimension hash vectors), `fake_bundle(...) -> LLMBundle`

- [ ] **Step 1: Write the test**

```python
async def test_every_adapter_refuses_when_llm_calls_disabled():
    bundle = build_openai_bundle(settings_with(llm_calls_enabled=False))
    with pytest.raises(LLMCallsDisabledError):
        await bundle.embedder.embed(["x"])
    with pytest.raises(LLMCallsDisabledError):
        await bundle.structured.generate(system="s", user="u", schema=Dummy, tier=ModelTier.FAST)
```

- [ ] **Step 2: Implement.** Every adapter method checks the switch before any client is created. Structured output uses `ChatOpenAI.with_structured_output`.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: add LLM ports and gated OpenAI adapters`.

### Task 3: Database schema and store isolation

**Files:**
- Create: `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_initial.py`, `src/shopchat/db/models.py`, `src/shopchat/db/session.py`, `tests/conftest.py`
- Test: `tests/integration/test_rls.py`

**Interfaces:**
- Produces: ORM models `Shop`, `CatalogProfileRow`, `Product`, `Variant`, `ProductChunk`, `SyncJob`, `UsageEvent` with the columns in spec section 5, `Product.source_updated_at`, and `shops.features` JSONB.
- Produces: `session_for_shop(shop_id: UUID) -> AsyncContextManager[AsyncSession]`, which runs `SET LOCAL app.shop_id`; `system_session()` for the `shops` table only.

- [ ] **Step 1: Write the tests**

```python
async def test_shop_cannot_read_another_shops_products(two_shops): ...
    # insert a product for shop A; inside session_for_shop(B), select returns []
async def test_app_role_cannot_bypass_rls(db_app_conn): ...
    # with no app.shop_id set, select from products returns 0 rows
async def test_insert_for_other_shop_is_rejected(two_shops): ...
    # inside session_for_shop(A), inserting shop_id=B raises a policy error
```

- [ ] **Step 2: Implement the migration.** Use roles `shopchat_owner` and `shopchat_app` (`NOBYPASSRLS`). `ENABLE` and `FORCE ROW LEVEL SECURITY` on every table except `shops`, with policy `shop_id = current_setting('app.shop_id', true)::uuid`. Add an HNSW index on `product_chunks.embedding` with `vector_cosine_ops`, GIN on the full-text column (`english`), and GIN on `products.facts`.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: add database models`, `feat: add initial migration with row-level security`.

### Task 4: Catalog types and CSV reader

**Files:**
- Create: `src/shopchat/catalog/types.py`, `src/shopchat/catalog/csv_source.py`, `tests/fixtures/mini_catalog.csv` (hand-written, 6 products, no cost column)
- Test: `tests/unit/test_csv_source.py`

**Interfaces:**
- Produces in `types.py`: `Provenance(StrEnum)` with `STATED`, `INFERRED`; `Fact(value: bool | float | str | list[str], provenance: Provenance, caveat: str | None = None)`; `NormalizedVariant(source_id, inventory_item_id: str | None, title, options: dict[str, str], price: Decimal, compare_at_price: Decimal | None, available: bool)`; `NormalizedProduct(source_id, handle, title, description, vendor, product_type, category, tags: list[str], status, image_urls: list[str], currency, source_updated_at: datetime | None, variants, raw_attributes: dict[str, str], facts: dict[str, Fact] = {})`.
- Produces in `csv_source.py`: `read_csv(path: Path, currency: str) -> list[NormalizedProduct]`

- [ ] **Step 1: Write the tests**

```python
def test_groups_rows_by_url_handle(): assert len(read_csv(MINI, "USD")) == 6
def test_description_html_is_stripped(): assert "<p>" not in first().description
def test_metafield_columns_become_raw_attributes():
    assert first().raw_attributes["Water and sweat resistance"] == "Not waterproof"
def test_available_uses_inventory_and_continue_selling(): ...
def test_blank_metafields_are_omitted(): ...
def test_cost_is_never_read(): assert "Cost per item" not in first().raw_attributes
```

- [ ] **Step 2: Implement.** Column names are as exported by Shopify: `URL handle`, `Title`, `Description`, `Product category`, `Type`, `Tags`, `Status`, `SKU`, `Option1 name`, `Option1 value`, `Option2 name`, `Option2 value`, `Price`, `Compare-at price`, `Inventory quantity`, `Continue selling when out of stock`, `Product image URL`, `Image position`. Metafield columns match `^(?P<label>.+) \(product\.metafields\.[^.]+\.[^)]+\)$`, and the label is the attribute key. Only the first row of a handle carries product-level fields.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: add normalized catalog types`, `feat: read Shopify product CSV exports`.

### Task 5: Stated facts, including negation

**Files:**
- Create: `src/shopchat/catalog/facts.py`
- Test: `tests/unit/test_facts.py`

**Interfaces:**
- Consumes: `StructuredLLM`, `NormalizedProduct`, `Fact`
- Produces: `negation_contradicts(value_text: str, fact_key: str) -> bool`; `parse_stated_facts(products: Sequence[NormalizedProduct], llm: StructuredLLM) -> list[NormalizedProduct]`. Output schema `ValueInterpretations(items: list[ValueInterpretation])` with fields `attribute`, `value_text`, `fact_key`, `fact_value`, `caveat`.

- [ ] **Step 1: Write the tests**

```python
def test_negation_contradicts():
    assert negation_contradicts("Not waterproof", "waterproof")
    assert negation_contradicts("No parabens", "parabens")
    assert not negation_contradicts("Waterproof", "waterproof")
    assert not negation_contradicts("No parabens", "paraben_free")          # a true "free from" claim
    assert not negation_contradicts("Non-comedogenic", "non_comedogenic")   # a true positive claim

async def test_negation_guard_overrides_llm_true():
    llm = FakeStructuredLLM([interp("Water resistance", "Not waterproof", "waterproof", True)])
    [p] = await parse_stated_facts([product(raw={"Water resistance": "Not waterproof"})], llm)
    assert p.facts["waterproof"].value is False and p.facts["waterproof"].provenance is Provenance.STATED

async def test_caveat_is_kept(): ...      # "SPF 20 (still wear a dedicated sunscreen)" keeps the caveat
async def test_identical_values_are_sent_once(): ...   # 2 products, same value, 1 item in the prompt
async def test_long_free_text_is_not_a_fact(): ...     # value over 60 characters is skipped
```

- [ ] **Step 2: Implement.** Send unique `(attribute, value)` pairs in batches of 50, `ModelTier.FAST`. Only values of 60 characters or fewer are interpreted. A boolean `True` is forced to `False` only when `negation_contradicts` holds: the value starts with "not", "no" or "never" and the rest of it contains the fact key's words.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: parse stated facts with a negation guard`.

### Task 6: Enrichment for sparse products

**Files:**
- Create: `src/shopchat/catalog/enrich.py`
- Test: `tests/unit/test_enrich.py`

**Interfaces:**
- Produces: `needs_enrichment(p: NormalizedProduct) -> bool` (fewer than 3 facts, or description under 80 characters); `enrich_missing(products, llm) -> list[NormalizedProduct]`.

- [ ] **Step 1: Write the tests**

```python
async def test_inferred_never_overwrites_stated(): ...   # fact stays STATED with its original value
async def test_new_facts_are_marked_inferred(): ...      # provenance is INFERRED
async def test_rich_products_make_no_llm_call(): assert llm.calls == []
```

- [ ] **Step 2: Implement** with `ModelTier.SMART`.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: infer missing product attributes`.

### Task 7: Catalog profile

**Files:**
- Create: `src/shopchat/catalog/profile.py`
- Test: `tests/unit/test_profile.py`

**Interfaces:**
- Produces: `FacetSummary(stated_count: int, value_type: str, top_values: list[str])`; `CatalogProfile(categories: list[str], facets: dict[str, FacetSummary], price_min: Decimal, price_max: Decimal, currency: str, summary: str, vocabulary: list[str], has_skincare: bool)`; `build_profile(products, llm) -> CatalogProfile`.

- [ ] **Step 1: Write the tests**

```python
async def test_inferred_facts_do_not_count_as_stated(): assert profile.facets["x"].stated_count == 1
async def test_price_range_comes_from_variants(): ...
async def test_clothing_catalog_produces_clothing_facets(): ...   # no cosmetic assumptions
```

- [ ] **Step 2: Implement.** Facets, counts, top 30 values and price range are computed in Python. The LLM (`FAST`) supplies only `summary`, `vocabulary` and `has_skincare`.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: generate a catalog profile per store`.

### Task 8: Chunks, indexer and catalog pipeline

**Files:**
- Create: `src/shopchat/catalog/chunks.py`, `src/shopchat/catalog/indexer.py`, `src/shopchat/catalog/pipeline.py`, `src/shopchat/catalog/import_csv.py`
- Test: `tests/unit/test_chunks.py`, `tests/integration/test_indexer.py`

**Interfaces:**
- Produces: `build_chunks(p: NormalizedProduct) -> list[ChunkDraft(kind: str, text: str)]`; `index_products(shop_id: UUID, products, embedder) -> IndexResult(indexed: int, skipped: int)`; `run_catalog_pipeline(shop_id: UUID, products, bundle: LLMBundle) -> IndexResult`; CLI `python -m shopchat.catalog.import_csv --shop-domain D --csv PATH --currency C`.

- [ ] **Step 1: Write the tests**

```python
def test_summary_chunk_has_title_and_stated_facts(): ...
def test_long_attributes_become_detail_chunks(): assert "how-to-use" in kinds
async def test_unchanged_product_is_skipped(two_shops): assert second.skipped == 1
async def test_changed_product_is_reindexed(two_shops): assert second.indexed == 1
async def test_cli_refuses_when_llm_calls_disabled(): ...
```

- [ ] **Step 2: Implement.** The pipeline order is facts, enrich, profile, index. The content hash covers all fields that affect chunks. The summary chunk must carry negated facts in plain words ("not waterproof").
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: build RAG chunks from products`, `feat: index products with change detection`, `feat: add catalog pipeline and CSV import command`.

## Milestone 2: RAG search

### Task 9: Requirements and filters

**Files:**
- Create: `src/shopchat/search/types.py`, `src/shopchat/search/filters.py`
- Test: `tests/unit/test_filters.py`

**Interfaces:**
- Produces in `types.py`: `Requirements(min_price: Decimal | None, max_price: Decimal | None, facts: dict[str, bool | float | str], in_stock: bool = True)`; `SearchPlan(firm: Requirements, soft_preferences: list[str], search_phrases: list[str], clarifying_question: str | None)`; `Candidate(product_id: UUID, title, vendor, product_type, facts: dict[str, Fact], best_chunk: str, score: float)`.
- Produces in `filters.py`: `effective_requirements(req: Requirements, profile: CatalogProfile) -> tuple[Requirements, list[str]]`, returning usable firm requirements plus those downgraded to soft preferences.

- [ ] **Step 1: Write the tests**

```python
def test_attribute_with_no_stated_values_becomes_soft():
    firm, soft = effective_requirements(req(facts={"waterproof": True}), profile(stated_count=0))
    assert firm.facts == {} and "waterproof" in soft[0]
def test_stated_attribute_stays_firm(): ...
def test_price_is_always_firm(): ...
```

- [ ] **Step 2: Implement.**
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: add search requirements and soft downgrade`.

### Task 10: Hybrid retrieval

**Files:**
- Create: `src/shopchat/search/hybrid.py`
- Test: `tests/unit/test_rrf.py`, `tests/integration/test_retrieval.py`

**Interfaces:**
- Produces: `rrf(rankings: Sequence[Sequence[UUID]], k: int = 60) -> list[tuple[UUID, float]]`; `retrieve(shop_id: UUID, plan: SearchPlan, profile: CatalogProfile, embedder: Embedder, limit: int = 30) -> list[Candidate]`; `product_detail_chunks(shop_id: UUID, product_id: UUID, query: str, embedder: Embedder, limit: int = 4) -> list[str]`.

- [ ] **Step 1: Write the tests**

```python
def test_rrf_rewards_appearing_in_both_lists(): ...
async def test_retrieval_never_returns_another_shop(two_shops): ...
async def test_negated_fact_fails_firm_requirement(seeded):
    assert "not-waterproof-product" not in titles(await retrieve(..., firm_facts={"waterproof": True}))
async def test_inferred_fact_cannot_satisfy_firm_requirement(seeded): ...
async def test_all_sold_out_product_is_excluded(seeded): ...   # Review Focus 3
async def test_draft_product_is_excluded(seeded): ...
async def test_price_range_filters(seeded): ...
```

- [ ] **Step 2: Implement.** Use `SET LOCAL hnsw.iterative_scan = strict_order`, 50 vector and 50 `websearch_to_tsquery('english', ...)` results per search phrase, merged by RRF and grouped by product with the best chunk. A firm fact matches only when `facts -> key ->> 'provenance' = 'stated'` and the value matches.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: add reciprocal rank fusion`, `feat: add hybrid store-scoped retrieval`.

### Task 11: Evaluation harness

**Files:**
- Create: `evals/dataset.yaml` (at least 50 cases), `evals/run_eval.py`, `evals/scoring.py`
- Test: `tests/unit/test_scoring.py`

**Interfaces:**
- Produces: `EvalCase(query: str, relevant_if: dict[str, object], trap: bool)`, `CaseScore(relevant_in_top5: float, fact_violations: int, money_in_reply: bool)`, `score_case(case: EvalCase, products: Sequence[Candidate], reply: str) -> CaseScore`; CLI `python -m evals.run_eval --csv PATH [--sparse]`. A case has `query` and `relevant_if` (attribute conditions rather than product IDs). `--sparse` clears `raw_attributes` before the pipeline.

- [ ] **Step 1: Write the tests**

```python
def test_top5_relevance(): assert score_case(case, picks).relevant_in_top5 == 0.8
def test_trap_violation_is_counted(): assert score_case(trap_case, picks).fact_violations == 1
def test_price_in_reply_is_flagged(): ...
```

- [ ] **Step 2: Write the dataset** by reading the CSV locally. Cover occasion, climate, skin and hair need, price, vague requests and traps.
- [ ] **Step 3: Implement.** The CLI exits with a message unless `LLM_CALLS_ENABLED=true`. Report against the spec's targets.
- [ ] **Step 4: Static check.**
- [ ] **Step 5: Commit** — `test: add evaluation scoring`, `test: add evaluation dataset`.

## Milestone 3: Agent pipeline

### Task 12: Graph state and router agent

**Files:**
- Create: `src/shopchat/agents/state.py`, `src/shopchat/agents/router.py`
- Test: `tests/unit/test_router.py`

**Interfaces:**
- Produces: `Intent(StrEnum)` with `PRODUCT_SEARCH`, `FOLLOW_UP`, `PRODUCT_DETAIL`, `SKIN_ANALYSIS`, `SMALL_TALK`, `OUT_OF_SCOPE`, `NON_ENGLISH`; `Turn(role: str, text: str, product_ids: list[UUID])`; `Node = Callable[[ChatState], Awaitable[dict[str, object]]]`; `ChatState` TypedDict with `shop_id`, `message`, `image_context: str | None`, `history: list[Turn]`, `profile: CatalogProfile`, `intent`, `focus_product_id: UUID | None`, `plan`, `candidates`, `selection`, `validated`, `retries: int`, `answer: str | None`; `make_router(llm) -> Node`.

- [ ] **Step 1: Write the tests**

```python
async def test_router_sets_intent(): assert (await node(state()))["intent"] is Intent.PRODUCT_SEARCH
async def test_customer_text_is_delimited_as_untrusted(): assert "<customer_message>" in llm.calls[0].user
```

- [ ] **Step 2: Implement** with `ModelTier.FAST`. Prompts live next to the node as constants.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: add chat state and router agent`.

### Task 13: Need-understanding agent

**Files:**
- Create: `src/shopchat/agents/understand.py`
- Test: `tests/unit/test_understand.py`

**Interfaces:**
- Produces: `make_understand(llm) -> Node`, which sets `plan: SearchPlan`.

- [ ] **Step 1: Write the tests**

```python
async def test_prompt_contains_store_profile_summary(): ...
async def test_prompt_contains_history_for_follow_ups(): ...
async def test_only_known_facets_are_kept_as_firm(): ...   # an invented facet moves to soft preferences
```

- [ ] **Step 2: Implement** with `ModelTier.FAST`.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: add need-understanding agent`.

### Task 14: Selection agent

**Files:**
- Create: `src/shopchat/agents/select.py`
- Test: `tests/unit/test_select.py`

**Interfaces:**
- Produces: `Pick(product_id: UUID, reason: str)`; `Selection(intro: str, picks: list[Pick], clarifying_question: str | None, too_few: bool)`; `make_select(llm) -> Node`.

- [ ] **Step 1: Write the tests**

```python
async def test_only_top_20_candidates_are_sent(): ...
async def test_prompt_includes_caveats_and_cautions(): ...
async def test_inferred_facts_are_labelled_in_prompt(): ...
async def test_prompt_does_not_contain_prices(): ...
```

- [ ] **Step 2: Implement** with `ModelTier.SMART`. `intro` and `reason` are structured, so the full text is validated before it reaches the customer. The API then emits it word by word.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: add product selection agent`.

### Task 15: Grounding validation and product cards

**Files:**
- Create: `src/shopchat/agents/validate.py`, `src/shopchat/search/cards.py`
- Test: `tests/unit/test_validate.py`, `tests/integration/test_cards.py`

**Interfaces:**
- Produces: `ValidatedSelection(intro: str, picks: list[Pick], clarifying_question: str | None)`; `validate_selection(selection: Selection, candidates: Sequence[Candidate], max_picks: int = 5) -> ValidatedSelection`; `scrub_money(text: str) -> str`; `ProductCard(id, title, price: Decimal, compare_at_price: Decimal | None, currency, image_url: str | None, url)`; `load_cards(shop_id: UUID, ids: Sequence[UUID], shop_domain: str) -> list[ProductCard]`.

- [ ] **Step 1: Write the tests**

```python
def test_unknown_product_id_is_dropped(): ...
def test_duplicates_removed_and_capped_at_5(): ...
def test_money_is_removed_from_text(): assert "$" not in scrub_money("only $12.99 today")
async def test_card_price_comes_from_database(seeded): ...
async def test_card_without_image_is_valid(seeded): assert card.image_url is None   # Review Focus 3
async def test_sold_out_at_card_time_is_dropped(seeded): ...
```

- [ ] **Step 2: Implement.**
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: validate selections against retrieved products`, `feat: build product cards from the database`.

### Task 16: Graph assembly

**Files:**
- Create: `src/shopchat/agents/graph.py`, `src/shopchat/agents/answers.py`
- Test: `tests/unit/test_graph.py`

**Interfaces:**
- Produces: `RetrieveFn` and `DetailFn`, callable aliases matching `retrieve` and `product_detail_chunks` from Task 10; `build_graph(bundle: LLMBundle, retrieve: RetrieveFn, detail: DetailFn) -> CompiledGraph`; in `answers.py`, `SMALL_TALK_SYSTEM`, `make_detail_answer(llm) -> Node`, and constant replies `ENGLISH_ONLY_REPLY`, `OUT_OF_SCOPE_REPLY`.

- [ ] **Step 1: Write the tests**

```python
async def test_small_talk_skips_retrieval(): assert retrieve.calls == 0
async def test_non_english_gets_english_only_reply(): assert result["answer"] == ENGLISH_ONLY_REPLY
async def test_retry_happens_at_most_once(): assert retrieve.calls == 2
async def test_retry_drops_soft_preferences(): ...
async def test_detail_answer_uses_only_retrieved_chunks(): ...
async def test_no_rows_ends_with_clarifying_question(): ...
```

- [ ] **Step 2: Implement** the flow in spec section 7.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: add product detail and fixed answers`, `feat: assemble the agent graph`.

### Task 17: Chat service, sessions and failure handling

**Files:**
- Create: `src/shopchat/chat/session_store.py`, `src/shopchat/chat/usage.py`, `src/shopchat/chat/service.py`
- Test: `tests/unit/test_session_store.py`, `tests/unit/test_chat_service.py`

**Interfaces:**
- Produces: `SessionStore.load(shop_id, session_id) -> list[Turn]`, `.append(shop_id, session_id, turn)`; `record_usage(shop_id, kind: str, quantity: int) -> None`; `ChatRequest(shop_id, shop_domain, session_id, message, image_context: str | None)`; events `TokenEvent(text)`, `ProductsEvent(cards)`, `DoneEvent()`, `ErrorEvent(message)`; `ChatService.handle(req: ChatRequest) -> AsyncIterator[ChatEvent]`.

- [ ] **Step 1: Write the tests**

```python
async def test_history_expires_after_24h(): assert ttl == 86400
async def test_history_keeps_10_turns(): ...
async def test_session_keys_are_per_shop(): ...
async def test_events_order_tokens_then_products_then_done(): ...
async def test_empty_catalog_gets_preparing_message(): ...   # Review Focus 2; no LLM call
async def test_selection_failure_retries_then_shows_top_candidates(): ...
async def test_failure_before_retrieval_shows_try_again(): ...
async def test_usage_is_recorded_and_nothing_is_blocked(): ...
```

- [ ] **Step 2: Implement.** Selection text is emitted word by word. Errors are logged without customer message content.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: add expiring chat sessions`, `feat: record usage per store`, `feat: add chat service with failure handling`.

## Milestone 4: API and widget

### Task 18: API, App Proxy session and chat endpoint

**Files:**
- Create: `src/shopchat/shopify/signatures.py`, `src/shopchat/api/app.py`, `src/shopchat/api/deps.py`, `src/shopchat/api/proxy.py`, `src/shopchat/api/chat.py`
- Test: `tests/unit/test_signatures.py`, `tests/integration/test_chat_api.py`

**Interfaces:**
- Produces: `verify_proxy_signature(query: Mapping[str, str], secret: str) -> bool`; `verify_webhook_hmac(body: bytes, header: str, secret: str) -> bool`; `verify_oauth_hmac(query, secret) -> bool`; `issue_widget_token(shop_id, shop_domain) -> str`; `WidgetContext(shop_id: UUID, shop_domain: str, features: dict[str, bool])`; dependency `widget_shop(authorization: str) -> WidgetContext`.
- Routes: `GET /healthz`; `GET /proxy/session` returns `{token, api_base, features}`; `POST /v1/chat` (multipart: `session_id`, `message`, optional `image`, `image_purpose` of `product` or `skin`, `skin_consent`) returns SSE.

- [ ] **Step 1: Write the tests**

```python
def test_tampered_proxy_signature_is_rejected(): ...
async def test_token_for_shop_a_cannot_use_shop_b(client): ...
@pytest.mark.parametrize("msg", ["", "   ", "x" * 1001])
async def test_invalid_message_is_422_with_no_llm_call(client, msg): ...   # Review Focus 1
async def test_cors_allows_only_the_shop_origin(client): ...
async def test_inactive_shop_session_is_403(client): ...
```

- [ ] **Step 2: Implement.** Tokens are HS256 with `exp` of 3600 seconds, signed with `widget_token_secret`.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: verify Shopify signatures`, `feat: issue widget sessions through App Proxy`, `feat: add streaming chat endpoint`.

### Task 19: Storefront chat widget

**Files:**
- Create: `shopify.app.toml`, `extensions/chat-widget/shopify.extension.toml`, `extensions/chat-widget/blocks/chat-embed.liquid`, `extensions/chat-widget/assets/chat.js`, `extensions/chat-widget/assets/chat.css`, `eslint.config.js`, `package.json`
- Test: `extensions/chat-widget/tests/chat.test.js`

**Interfaces:**
- Consumes: `GET {proxy}/session`, `POST /v1/chat` SSE events `token`, `products`, `done`, `error`.

- [ ] **Step 1: Write the tests** (node:test): `renders tokens incrementally`, `renders a card without an image`, `escapes HTML in bot text`, `hides the mic button unless features.voice`, `hides the widget on 403`.
- [ ] **Step 2: Implement.** Vanilla ES module, no build step. Use `textContent` only for bot text, keyboard operable with ARIA labels, and a mobile layout. `shopify.app.toml` sets `scopes = "read_products,read_inventory"` and the App Proxy; `client_id` stays empty until the owner supplies it.
- [ ] **Step 3: Static check:** `npx eslint extensions && npx prettier --check extensions`.
- [ ] **Step 4: Commit** — `feat: add theme extension and chat embed`, `feat: render streamed replies and product cards`.

## Milestone 5: Image

### Task 20: Image reading

**Files:**
- Create: `src/shopchat/agents/vision.py`, `src/shopchat/api/uploads.py`
- Modify: `src/shopchat/api/chat.py`, `extensions/chat-widget/assets/chat.js`
- Test: `tests/unit/test_vision.py`, `tests/integration/test_image_upload.py`

**Interfaces:**
- Produces: `ImageReading(kind: Literal["product", "label", "outfit_or_room", "face", "unusable"], description: str, extracted_text: str | None, product_name: str | None, brand: str | None)`; `read_image(image: ImagePart, llm) -> ImageReading`; `image_context_for(reading: ImageReading) -> str | None`; `validate_upload(data: bytes, content_type: str, allowed: frozenset[str], max_bytes: int) -> None`.

- [ ] **Step 1: Write the tests**

```python
async def test_label_text_is_passed_into_context(): ...
async def test_image_text_is_marked_untrusted(): ...
async def test_unusable_photo_asks_for_a_better_one(client): ...      # Review Focus 5
async def test_face_on_product_path_points_to_consent_flow(client): ...   # Review Focus 5
async def test_wrong_type_or_oversized_upload_is_rejected(client): ...
async def test_image_is_not_written_to_disk_or_redis(client): ...
async def test_image_disabled_for_shop_is_rejected(client): ...
```

- [ ] **Step 2: Implement** with `ModelTier.SMART`. Check magic bytes as well as the declared type.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: validate image uploads`, `feat: read customer images with vision`, `feat: add photo upload to the widget`.

### Task 21: Skin analysis with consent

**Files:**
- Create: `src/shopchat/agents/skin.py`
- Modify: `src/shopchat/api/chat.py`, `extensions/chat-widget/assets/chat.js`
- Test: `tests/integration/test_skin_analysis.py`

**Interfaces:**
- Produces: `SkinObservations(observations: list[str], needs: list[str])`; `analyze_skin(image: ImagePart, llm) -> SkinObservations`; constant `SKIN_CONSENT_TEXT`.

- [ ] **Step 1: Write the tests**

```python
async def test_no_consent_rejected_before_any_llm_call(client): ...
async def test_disabled_store_rejected_before_any_llm_call(client): ...
async def test_prompt_forbids_diagnosis_identity_age_and_ethnicity(): ...
async def test_consent_applies_to_one_image_only(client): ...
async def test_consent_text_mentions_openai_and_no_storage(): ...
```

- [ ] **Step 2: Implement.** Default is on only when `profile.has_skincare`; the merchant can switch it off. `needs` feeds the normal search path.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: add consent-gated skin analysis`, `feat: add skin consent flow to the widget`.

## Milestone 6: Voice

### Task 22: Voice, built and switched off

**Files:**
- Create: `src/shopchat/api/voice.py`
- Modify: `src/shopchat/api/app.py`, `extensions/chat-widget/assets/chat.js`
- Test: `tests/integration/test_voice_api.py`

**Interfaces:**
- Routes: `POST /v1/voice/transcribe` returns `{text}`; `POST /v1/voice/speak` returns audio.
- Produces: `voice_active(settings: Settings, shop_features: Mapping[str, bool]) -> bool`.

- [ ] **Step 1: Write the tests**

```python
async def test_endpoints_refuse_when_voice_is_off(client): assert r.status_code == 403
async def test_oversized_audio_is_rejected(client): ...
async def test_audio_is_not_stored(client): ...
```

- [ ] **Step 2: Implement** endpoints and the widget's mic and mute controls. `features.voice` is `false` by default.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: add voice endpoints behind a switch`, `feat: add mic and mute controls to the widget`.

## Milestone 7: Shopify install and sync

**Before Task 23, ask the owner for the Shopify client ID and secret, going in `.env`. Real Shopify calls are allowed. LLM calls are not.**

### Task 23: OAuth install

**Files:**
- Create: `src/shopchat/shopify/crypto.py`, `src/shopchat/shopify/oauth.py`, `src/shopchat/api/auth.py`
- Test: `tests/unit/test_crypto.py`, `tests/integration/test_oauth.py`

**Interfaces:**
- Produces: `encrypt_token(token: str) -> bytes`, `decrypt_token(data: bytes) -> str` (Fernet); routes `GET /auth/install?shop=`, `GET /auth/callback`.

- [ ] **Step 1: Write the tests**

```python
async def test_rejects_non_myshopify_domain(client): ...
async def test_rejects_bad_state_or_hmac(client): ...
async def test_stored_token_is_encrypted(client): ...
async def test_reinstall_reactivates_shop(client): ...
```

- [ ] **Step 2: Implement.** Shop domains must match `^[a-z0-9][a-z0-9-]*\.myshopify\.com$`.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: encrypt store tokens`, `feat: add Shopify OAuth install`.

### Task 24: Bulk product import

**Files:**
- Create: `src/shopchat/shopify/graphql.py`, `src/shopchat/catalog/shopify_source.py`
- Test: `tests/unit/test_shopify_source.py`

**Interfaces:**
- Produces: `AdminClient(shop_domain, token).query(query, variables) -> dict`; `start_bulk_import(client) -> str`; `parse_bulk_jsonl(lines: Iterable[str], currency: str) -> list[NormalizedProduct]`; `product_from_node(node: dict, currency: str) -> NormalizedProduct`.

- [ ] **Step 1: Write the tests**

```python
def test_children_attach_through_parent_id(): ...
def test_metafield_label_uses_key_when_no_definition(): ...
def test_html_description_is_stripped(): ...
```

- [ ] **Step 2: Implement** with `bulkOperationRunQuery`, `metafields(first: 250)` and `currencyCode` from the `shop` query.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: add Shopify Admin client`, `feat: import products by bulk operation`.

### Task 25: Webhooks and worker

**Files:**
- Create: `src/shopchat/api/webhooks.py`, `src/shopchat/worker/main.py`, `src/shopchat/worker/tasks.py`
- Test: `tests/integration/test_webhooks.py`, `tests/integration/test_worker_tasks.py`

**Interfaces:**
- Route: `POST /webhooks/shopify`. Uses the topic header, always HMAC-verified, enqueues and returns 200.
- Produces arq tasks: `sync_shop(shop_id)`, `finish_bulk(shop_id, url)`, `upsert_product(shop_id, payload)`, `delete_product(shop_id, source_id)`, `update_inventory(shop_id, payload)`, `deactivate_shop(shop_id)`, `redact_shop(shop_id)`.

- [ ] **Step 1: Write the tests**

```python
async def test_bad_hmac_is_401_and_not_enqueued(client): ...
async def test_duplicate_webhook_has_one_effect(worker): ...           # Review Focus 4
async def test_older_updated_at_never_overwrites(worker): ...          # Review Focus 4
async def test_webhook_during_first_import_is_kept(worker): ...        # Review Focus 4
async def test_inventory_update_changes_availability(worker): ...
async def test_uninstall_marks_inactive(worker): ...
async def test_shop_redact_deletes_all_store_data(worker): ...
async def test_customers_redact_and_data_request_return_200(client): ...
```

- [ ] **Step 2: Implement.** Retries use arq backoff, and failures are written to `sync_jobs`. No customer data is stored, so customer compliance topics acknowledge only.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: receive and verify Shopify webhooks`, `feat: add background worker tasks`, `feat: handle compliance webhooks`.

## Milestone 8: Merchant page and joint test run

### Task 26: Merchant admin page

**Files:**
- Create: `src/shopchat/api/admin.py`, `admin/index.html`, `admin/admin.js`
- Test: `tests/integration/test_admin_api.py`

**Interfaces:**
- Routes: `GET /admin`; `GET /admin/api/status`; `PATCH /admin/api/settings`; `POST /admin/api/resync`. Authenticated by App Bridge session token (HS256, signed with the app secret, checking `aud` and `dest`).

- [ ] **Step 1: Write the tests**

```python
async def test_missing_or_bad_session_token_is_401(client): ...
async def test_status_shows_only_own_shop(client): ...
async def test_toggle_skin_analysis_takes_effect(client): ...
async def test_voice_cannot_activate_when_global_switch_is_off(client): ...
```

- [ ] **Step 2: Implement.** Static page using App Bridge and Polaris web components, no build step.
- [ ] **Step 3: Static check.**
- [ ] **Step 4: Commit** — `feat: add merchant admin API`, `feat: add embedded merchant page`.

### Task 27: Documentation and joint test session

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document** setup, `.env` keys, migrations, running the API and worker, and installing on a development store.
- [ ] **Step 2: Commit** — `docs: add setup and operations guide`.
- [ ] **Step 3: Stop and ask the owner to start the joint session.** Run in this order, with the owner, fixing failures in small commits:
  1. `uv run pytest tests/unit` (no network)
  2. `uv run pytest tests/integration` (local Postgres and Redis)
  3. `node --test extensions/chat-widget/tests`
- [ ] **Step 4: Ask for the OpenAI key and separate permission** for each LLM step: catalog import on the CSV, `evals.run_eval`, `evals.run_eval --sparse`, and manual chats on the development store. Give a cost estimate before each.
- [ ] **Step 5: Report results** against the spec's success criteria.
