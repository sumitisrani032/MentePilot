# Security and privacy

To run the project on your own computer, follow [Local setup](local-setup.md).

| Area | Protection |
| --- | --- |
| Store isolation | Postgres row-level security on every store table |
| Store tokens | Encrypted with Fernet; refreshed automatically before they expire |
| Widget calls | One-hour JWT bound to the store and browser origin |
| Webhooks and App Proxy | Shopify HMAC verified before any work happens |
| Upload limits | 11 MB body limit, 5 MB images, 10 MB audio, and file type checked by content |
| Photos and audio | Kept in memory for one request, never written to disk |
| Conversations | Kept in Redis for 24 hours, 10 turns at most |
| Logs | Customer messages stay out; failures log only the error type |
| Prompt injection | Customer text is wrapped in tags and marked as data |
| Model output | Product IDs are checked against candidates; money is removed from text |
| Skin analysis | Off without explicit consent; consent is checked before the image reaches a model |
| Compliance webhooks | `shop/redact` deletes store data; no customer data is stored |

The seed dump in `db/seed` has store tokens, sync history and usage removed. It still contains the
demo store's product catalog, so keep the repository private if that catalog is confidential.

To report a problem, contact the maintainer privately and do not open a public issue.
