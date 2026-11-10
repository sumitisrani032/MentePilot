# API reference

FastAPI also serves interactive documentation at `/docs` and the schema at `/openapi.json`.

## Authentication

| Caller | Proof |
| --- | --- |
| Widget, first call | Shopify App Proxy signature on the query string |
| Widget, later calls | `Authorization: Bearer <token>`, a one-hour JWT bound to the store and browser origin |
| Merchant page | Shopify session token in `Authorization` |
| Webhooks | `X-Shopify-Hmac-Sha256` over the raw body |

## Storefront

### `GET` or `POST /proxy/session`

Called through Shopify as `/apps/shopchat/session?origin=<origin>`.

```json
{
  "token": "<jwt>",
  "api_base": "https://your-app.example",
  "skin_consent_text": "...",
  "features": { "image": true, "skin_analysis": true, "voice": false },
  "suggestions": ["Show me sunscreen", "Help me find a gift"]
}
```

| Status | Meaning |
| --- | --- |
| 401 | Invalid signature |
| 403 | Store not active |
| 422 | Invalid origin |
| 503 | A required secret is not configured |

### `POST /v1/chat`

`multipart/form-data`, responds with Server-Sent Events.

| Field | Type | Notes |
| --- | --- | --- |
| `session_id` | string, required | 1 to 128 characters |
| `message` | string | 1 to 1000 characters; optional only with an image |
| `image` | file | JPEG, PNG or WebP, up to 5 MB |
| `image_purpose` | `product` or `skin` | Defaults to `product` |
| `skin_consent` | boolean | Required for `skin` |

| Event | Data |
| --- | --- |
| `token` | `{"text": "word "}` |
| `sections` | Sections, `follow_up_question`, `quick_replies` |
| `done` | `{}` |
| `error` | `{"message": "..."}` |

Example `sections` data:

```json
{
  "sections": [
    {
      "heading": "Sunscreen",
      "detail": "Protection for a day outdoors.",
      "cards": [
        {
          "id": "uuid",
          "title": "Example SPF 50",
          "vendor": "Example",
          "description": "...",
          "reason": "Water-resistant cover for the beach."
        }
      ],
      "how_to_use": ["Apply 15 minutes before sun."],
      "tips": ["Reapply after swimming."]
    }
  ],
  "follow_up_question": "Would you like an after-sun product too?",
  "quick_replies": ["Find an after-sun lotion", "Show more options", "Show cheaper options"]
}
```

| Status | Meaning |
| --- | --- |
| 401 | Invalid or expired session |
| 403 | Wrong origin, inactive store, feature off, or consent missing |
| 411 | `Content-Length` missing |
| 413 | Body over 11 MB |
| 422 | Invalid message or file |

### `POST /v1/voice/transcribe`

Form field `audio` (webm, mp4, mpeg or wav, up to 10 MB). Returns the text. Off unless voice is
enabled globally and by the merchant.

### `POST /v1/voice/speak`

Form field `text` (1 to 1000 characters). Returns audio.

## Merchant

| Method and path | Purpose | Result |
| --- | --- | --- |
| `GET /admin` | The embedded page, or starts install if needed | HTML |
| `GET /admin/admin.js` | Page script | JavaScript |
| `GET /admin/api/status` | Index progress, usage and features | JSON, below |
| `PATCH /admin/api/settings` | `image`, `skin_analysis`, `voice` booleans | Stored choices |
| `POST /admin/api/resync` | Queue a full import | `202 {"status": "queued"}` |

```json
{
  "shop": "example.myshopify.com",
  "products": 1000,
  "indexed": 1000,
  "sync": { "status": "complete", "error": null },
  "usage": { "chat": 42, "image": 3 },
  "features": { "image": true, "skin_analysis": true, "voice": false },
  "voice_available": false
}
```

## Shopify integration

| Method and path | Purpose |
| --- | --- |
| `GET /auth/install?shop=` | Start OAuth |
| `GET /auth/callback` | Finish OAuth, save tokens, queue the first import |
| `POST /webhooks/shopify` | All webhooks, including mandatory compliance topics |

## Operations

| Method and path | Purpose |
| --- | --- |
| `GET /healthz` | Liveness: `{"status": "ok"}` |

## Development only

These routes exist only with `DEV_MODE=true`, and only for a browser on this machine or a private
network. Otherwise, and for any request carrying `X-Forwarded-For` (for example through ngrok), they
answer 404.

| Route | Purpose |
| --- | --- |
| `GET /dev` | Placeholder shop page with the widget, which has a maximize button |
| `GET /dev/widget/chat.js`, `GET /dev/widget/chat.css` | Widget files, uncached |
| `POST /dev/session?origin=<origin>` | Same reply as `/proxy/session`, for `DEV_SHOP_DOMAIN`, with no Shopify signature; `http` origins are allowed and `api_base` is this server |

| Status | Meaning |
| --- | --- |
| 403 | `DEV_SHOP_DOMAIN` is not an active store in the database |
| 404 | `DEV_MODE` is off, or the request is not local |
| 422 | Invalid origin |
