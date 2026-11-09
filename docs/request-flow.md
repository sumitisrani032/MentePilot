# Request flow

What happens from the moment a customer presses send. The README has the end-to-end sequence
diagram. This page covers each stage in more detail.

## The agent graph

Defined in `backend/src/shopchat/agents/graph.py`.

```mermaid
flowchart TD
    START((Start)) --> router{{router<br/>gpt-4o-mini}}

    router -- product_search, follow_up,<br/>skin_analysis --> understand{{understand<br/>gpt-4o-mini}}
    router -- product_detail --> detail[product_detail<br/>chunks for one product]
    router -- small_talk --> small{{small_talk<br/>gpt-4o-mini, streamed}}
    router -- out_of_scope --> oos[Fixed reply]
    router -- unclear --> unclear[Fixed reply]
    router -- non_english --> eng[Fixed reply]

    understand -- enough to search --> retrieve[(retrieve<br/>hybrid RAG)]
    understand -- only a question --> ask[ask_question]

    retrieve -- candidates --> select{{select<br/>gpt-4o-mini}}
    retrieve -- none, first try --> loosen[loosen]
    retrieve -- none, retried --> nomatch[Fixed reply]

    select --> validate[validate<br/>code only]
    validate -- fewer than 2 picks,<br/>first try --> loosen
    validate -- good --> END((End))
    loosen --> retrieve

    detail --> answer{{detail_answer<br/>gpt-4o-mini}} --> END
    small --> END
    oos --> END
    unclear --> END
    eng --> END
    ask --> END
    nomatch --> END
```

Hexagons call a model. Rectangles run code only.

## What each agent does

| Node | Input | Output | Model |
| --- | --- | --- | --- |
| `router` | Message and recent history | One of 8 intents, plus a focus product | Yes |
| `understand` | Message, history, store profile | `SearchPlan`: firm limits, soft preferences, 2 to 4 search phrases | Yes |
| `retrieve` | `SearchPlan` | Up to 30 candidate products | Embeddings only |
| `select` | Candidates, message, history | Up to 4 sections of up to 5 products with reasons, how-to-use and tips | Yes |
| `validate` | Selection and candidates | Cleaned selection | No |
| `loosen` | Current plan | Broader plan; price limits stay, facts go only if nothing matched | No |
| `product_detail` | Focus product and question | Most relevant chunks of that product | Embeddings only |
| `detail_answer` | Those chunks | An answer grounded in them | Yes |
| `small_talk` | Message | A short reply | Yes |

## Retrieval

```mermaid
flowchart LR
    P[SearchPlan] --> E[Embed each phrase<br/>text-embedding-3-small]
    P --> K[Keyword query<br/>per phrase]
    P --> FL[Hard filters:<br/>store, active, in stock,<br/>price, stated facts]
    E --> V[pgvector cosine search<br/>top 50 chunks]
    K --> T[Postgres full-text search<br/>top 50 chunks]
    FL --> V
    FL --> T
    V --> RRF[Reciprocal rank fusion<br/>k = 60]
    T --> RRF
    RRF --> C[30 candidates<br/>facts, cautions, usage]
```

HNSW iterative scan is switched on, so filtered vector searches still return enough rows.

## Text chat

```mermaid
sequenceDiagram
    autonumber
    participant B as Widget
    participant F as FastAPI
    participant C as ChatService
    participant R as Redis
    participant G as LangGraph
    B->>F: POST /v1/chat (form data, Bearer token, Origin)
    F->>F: Check token, origin, store and features
    F->>C: ChatRequest
    C->>C: Load store profile
    alt Catalog not ready
        C-->>B: token events and done
    else Ready
        C->>R: Load last 10 turns
        C->>G: ainvoke(state)
        G-->>C: answer, or validated selection
        C->>C: Load cards with live prices
        C-->>B: event: token (one per word)
        C-->>B: event: sections
        C-->>B: event: done
        C->>R: Save turn, 24-hour expiry
        C->>C: Record usage
    end
```

## Image upload

```mermaid
sequenceDiagram
    autonumber
    participant B as Widget
    participant F as FastAPI
    participant V as Vision agent
    participant G as LangGraph
    B->>F: POST /v1/chat with image and purpose
    F->>F: Authorize feature and consent, before any model sees the image
    F->>F: Check size and real file type, held in memory only
    alt purpose = product
        F->>V: read_image
        alt A face
            V-->>B: Polite reply, turn ends
        else Product, ingredients or scene
            V->>G: image_context
            G-->>B: Normal recommendation
        end
    else purpose = skin, with consent
        F->>V: analyze_skin
        V->>G: skin observations as context
        G-->>B: Normal recommendation
    end
```

Photos are never written to disk or stored.

## Replies that never call a model

| Situation | Reply comes from |
| --- | --- |
| Catalog still being prepared | `PREPARING_REPLY` in `chat/service.py` |
| Out of scope, unclear, or not English | `agents/answers.py` |
| Nothing matched after loosening | `NO_MATCH_REPLY` in `agents/answers.py` |
| Any exception | `TRY_AGAIN_REPLY`; only the error type is logged |
