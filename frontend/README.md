# Frontend

The storefront chat widget and the merchant page. Both are plain JavaScript with no build step.

| Path | What it is |
| --- | --- |
| `extensions/chat-widget` | Shopify Theme App Extension for the storefront |
| `admin` | Page shown inside Shopify admin, served by the backend |
| `tests/widget` | Widget tests using `node:test` and jsdom |

```bash
npm ci
npm test
npm run lint
cp shopify.app.toml.example shopify.app.toml   # Then set your client ID and URLs
npx shopify app deploy
```

See [docs/shopify-setup.md](../docs/shopify-setup.md).
