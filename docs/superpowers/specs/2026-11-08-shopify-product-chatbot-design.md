# Shopify Product Discovery Chatbot: Design

Date: 2026-11-08
Status: Awaiting review

## 1. Goal

A public Shopify app that any store can install. It adds a storefront chatbot that
understands free-form customer requests and answers only with that store's real
products. Requests may not share any words with the product data: "I'm going to
the beach, suggest something" must still lead to suitable products.

The app works for any product type (cosmetics, clothing, jewelry, mixed catalogs).
The owner's cosmetics store is the first test catalog; nothing in the code may be
specific to cosmetics.

### Success criteria

Proposed targets, measured by the evaluation suite in section 11:

| Measure | Target |
|---|---|
| Relevant products in top 5, full catalog data | at least 80% |
| Relevant products in top 5, custom fields removed | at least 60% |
| Recommended products that do not exist in the store | 0 |
| Violations of a stated fact (for example "Not waterproof" sold as waterproof) | 0 |
| Data visible across stores | 0 |
| Time to first reply text, 95th percentile, text message | under 3 seconds |

## 2. Decisions

| Topic | Decision |
|---|---|
| Distribution | Public app, multi-store |
| Billing | Free. Shopify Billing is out of scope |
| LLM provider | OpenAI for chat, vision, embeddings, speech |
| Orchestration | LangGraph pipeline with focused agents |
| Retrieval | RAG in Postgres with pgvector, hybrid with keyword search |
| Language | English only |
| Bot capability | Recommend and answer product questions only; customers click through to the product page. No cart, no order tracking, no store-policy answers |
| Priority | Text first |
| Image upload | Live at launch: similar products, read product or label, style advice, skin analysis |
| Voice | Fully built (speech in, spoken reply with mute), switched off by a setting |
| Hosting | Docker, host-agnostic |
| Cost limits | None. Usage is recorded per store but nothing is blocked |
| Sample data | The owner's CSV is a development and test fixture only |

## 3. Out of scope

Shopify Billing, App Store submission, add to cart, order tracking, store-policy
answers, languages other than English, live real-time voice conversation, stored
chat transcripts.

## 4. Architecture

```
Storefront widget (Theme App Extension, JS)
   |  1. session token through Shopify App Proxy (signed, proves the shop)
   |  2. chat, image and audio calls direct to the API, streamed
   v
FastAPI API ---- LangGraph agent pipeline ---- OpenAI
   |                     |
   |                     v
   |              Postgres + pgvector (products, RAG index, profiles, usage)
   |
   +-- Redis (job queue, chat session state)
   +-- Background worker (bulk import, webhooks, enrichment, embeddings)

Shopify Admin -- embedded merchant page (App Bridge) --> FastAPI
Shopify webhooks --> FastAPI --> queue --> worker
```

Stack: Python 3.12, uv, FastAPI, SQLAlchemy (async), Alembic, LangGraph,
langchain-openai, arq, pytest. Model names are configuration, not code. The
widget and admin page are JavaScript because Shopify requires it, and stay thin.

## 5. Data model

Every table carries `shop_id`. Postgres row-level security is enforced using a
per-transaction `app.shop_id` setting, and the application role cannot bypass it.

- `shops`: domain, encrypted access token, granted scopes, status, feature flags
  (image, skin analysis, voice), install and uninstall times.
- `catalog_profiles`: generated per store. Categories, facets and their values,
  vocabulary, price range, currency, and a short natural-language summary.
- `products`: Shopify ID, handle, title, plain-text description, vendor, type,
  category, tags, status, image URLs, storefront URL, min and max price,
  compare-at price, currency, availability, `facts` (see below), content hash.
- `variants`: Shopify ID, inventory item ID, options, price, availability.
- `product_chunks`: the RAG index. Kind (`summary`, or a detail kind such as
  `usage`, `ingredients`, `materials`, `care`), text, embedding, full-text vector.
- `sync_jobs`: type, status, counts, error.
- `usage_events`: per-store counts of chats, tokens, images, audio seconds.

Chat history lives only in Redis, with a 24-hour expiry, keyed by anonymous
session. No transcripts, photos or audio are stored in Postgres or on disk.

### Facts and provenance

`facts` holds typed values, each marked with its provenance:

- `stated`: parsed from data the merchant supplied, including negation.
  "Not waterproof" becomes `water_resistant: false`, never a match for waterproof.
- `inferred`: added by the LLM from title, description or images to fill a gap.

Firm requirements filter only on `stated` facts, price and availability. Where a
store has no stated value for an attribute, the requirement becomes a soft
preference, and the reply must not claim the attribute as fact. Facet names come
from each store's catalog profile and are never hardcoded.

## 6. Catalog sync

Scopes: `read_products`, `read_inventory`, and `write_app_proxy`, which Shopify requires of
any app with an App Proxy. The app never writes to store data.

1. Install: Shopify OAuth. The access token is encrypted at rest.
2. Initial import: GraphQL bulk operation for products, variants, images and
   metafields, completed by the `bulk_operations/finish` webhook.
3. Normalize: strip HTML and map merchant data into `facts` as `stated`.
4. Enrich: only products with missing information go to the LLM. Output is `inferred`.
5. Profile: generate or refresh the store's catalog profile.
6. Index: build chunks and embeddings. Unchanged content (same hash) is skipped.

Webhooks: `products/create`, `products/update`, `products/delete`,
`inventory_levels/update`, `app/uninstalled`, and the compliance topics
`customers/data_request`, `customers/redact`, `shop/redact`. All are verified by
HMAC and handled idempotently through the queue. `shop/redact` deletes all store data.

The CSV importer feeds the same normalize, enrich, profile and index steps, so
search can be built and tested before Shopify credentials are used.

## 7. Agent pipeline

1. **Input.** Text passes through. Audio is transcribed when voice is on. Images
   are read by a vision step into a structured description, which joins the text.
2. **Router agent.** Classifies: product search, follow-up, product detail
   question, skin analysis, small talk or out of scope. Small talk and out-of-scope
   messages skip retrieval. A message not in English gets a polite English reply
   asking the customer to use English.
3. **Need-understanding agent.** Uses the catalog profile and session context to
   produce firm requirements (price, availability, stated facts), soft preferences
   and search phrases.
4. **Retrieval, no LLM.** Vector and full-text search merged with reciprocal rank
   fusion, always filtered by store, active status and firm requirements.
5. **Selection agent.** Picks up to 5 products from the retrieved set with a short
   reason each, and includes relevant merchant-supplied cautions. If too few fit,
   it loosens soft preferences and retrieves once more, or asks one clarifying
   question. At most one retry per message.
6. **Reply and validation.** Streams the reply. Every product ID is checked against
   the retrieved set. Price, availability, image and link are taken from the
   database and rendered as cards, never written by the LLM.

Product detail questions ("how do I use this?") retrieve from `product_chunks`
for the product under discussion and answer only from that text.

Prices are in the store's currency. Currency conversion is not performed.

### Image behaviour

| Use | Behaviour |
|---|---|
| Similar products | Vision description drives retrieval |
| Read product or label | Extracts name, brand and ingredients, then finds the same product or an equivalent |
| Style advice | Describes the outfit or room and searches for complementary products |
| Skin analysis | See below |

Similar-image search begins with text descriptions. It is evaluated early on
look-driven catalogs, and a dedicated image-embedding model is added only if
results fall short.

### Skin analysis

- The server rejects the request unless the customer has given explicit consent
  for that image.
- Advice is cosmetic only: no diagnosis or medical claims, and it must not identify
  the person or infer age, ethnicity or other sensitive traits.
- Enabled by default only where the catalog profile shows skincare products.
  Each merchant can switch it off.
- The consent text states that the photo is sent to OpenAI for processing and is
  not stored by the app.

## 8. Storefront and admin

**Widget.** Theme App Extension app embed: a floating chat box with typed text,
photo upload, streamed replies and product cards linking to product pages. The
microphone control appears only when voice is enabled.

**Session flow.** The widget requests a short-lived token through the App Proxy.
The backend verifies Shopify's signature and issues a token bound to that shop.
Later calls go direct to the API so streaming and uploads work, with CORS limited
to that shop's storefront origins.

**Merchant page.** Embedded through App Bridge: sync status with a re-sync action,
usage figures, and switches for image, skin analysis and voice.

**Voice.** Speech-to-text and text-to-speech endpoints and widget controls are
complete. A global `VOICE_ENABLED` setting, off by default, plus the per-store
flag controls them; when off, endpoints return a feature-disabled response.

## 9. Error handling

| Failure | Behaviour |
|---|---|
| OpenAI error or timeout during selection | Retry once, then show top retrieved products without reasons |
| OpenAI unavailable before retrieval | Friendly "try again" message; no products invented |
| No suitable products | Says so plainly and asks one narrowing question |
| Validation removes a product | Dropped from the reply; never shown |
| Bad or oversized upload | Rejected with a clear message (type and size limits) |
| Webhook or sync failure | Queue retries with backoff; failure shown on the merchant page |
| Store uninstalled or token invalid | Widget hides; store marked inactive |

## 10. Security and privacy

- Every webhook and App Proxy request is verified by HMAC. Row-level security
  isolates stores at the database.
- Uploaded photos and audio are held in memory only for the request.
- Customer messages, images and product text are treated as untrusted input. The
  LLM has no tools that change data, and its product output is validated.
- Secrets live in a local `.env` file that is never committed. Store tokens are
  encrypted at rest.

## 11. Testing

- **Evaluation suite**: at least 50 realistic questions with expected products,
  scored against the 1,000-product catalog, covering occasion, climate, skin or
  hair need, price and vague requests.
- **Sparse-store run**: the same questions with custom fields removed.
- **Trap tests**: negation and misleading values, including "Not waterproof" and
  low-SPF products with "still wear a dedicated sunscreen" wording.
- **Isolation tests**: two stores with overlapping products; neither can read the
  other, at both API and database level.
- **Grounding tests**: no product or price outside the retrieved set can reach a reply.
- **Unit and integration tests** for normalization, webhook verification and
  idempotency, the OAuth flow, and each graph node using a fake LLM.

## 12. Build order

1. Project setup, database schema, CSV import
2. RAG search, tested on the catalog
3. Agent pipeline with text chat
4. Chat API and storefront widget
5. Image upload, including skin analysis
6. Voice, built and switched off
7. Shopify install, sync and webhooks on the development store
8. Merchant admin page

## 13. Known risks

- **No cost limits.** The app is free and runs on the owner's OpenAI key, and the
  chat endpoint is public, so a busy store or a scripted abuser could produce a
  large bill. Usage is recorded so limits can be added later. Decision made by the owner.
- **Skin analysis** processes customer face photos. Legal review, including
  biometric privacy rules and Shopify's protected customer data requirements, is
  needed before App Store submission.
- **Test catalog is unusually rich.** Results on it can overstate quality for
  sparse stores; the sparse-store run measures this.
- **Filtered vector search across many stores** can lose recall. Requires pgvector
  0.8 or later with iterative index scans.
