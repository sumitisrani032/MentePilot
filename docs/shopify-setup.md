# Connecting to Shopify

You need a Shopify Partner account, a development store, an app in the Partner Dashboard, and a
public HTTPS URL for the backend.

## 1. Create the app configuration

```bash
cd frontend
cp shopify.app.toml.example shopify.app.toml
```

Replace `client_id` and every `https://your-public-app-url.example` with your values.

## 2. Expose the backend

```bash
ngrok http 8000
```

Put the HTTPS URL in `APP_URL` in `backend/.env` and in `shopify.app.toml`.

## 3. Add credentials

In `backend/.env`, set `SHOPIFY_API_KEY`, `SHOPIFY_API_SECRET`, `TOKEN_ENCRYPTION_KEY` and
`WIDGET_TOKEN_SECRET`. `backend/.env.example` shows how to generate the last two.

## 4. Deploy the app configuration and widget

```bash
cd frontend
npx shopify app deploy
```

## 5. Install and turn on the widget

1. Install the app on your development store from the Partner Dashboard.
2. Open the store's theme editor, then **App embeds**.
3. Turn on **Shop assistant** and save.

The first import starts on install. Its progress shows on the app's page in Shopify admin.

## Scopes

| Scope | Reason |
| --- | --- |
| `read_products` | Read the catalog |
| `read_inventory` | Keep availability correct |
| `write_app_proxy` | Required by Shopify for an app with an App Proxy |

## Custom fields

Shopify only returns product metafields that the API can see. Fields in the `custom` namespace
need definitions, and any other namespace to read must be listed in `shopify_source.py`.

## Before an App Store listing

- Replace redirect-based install with session token exchange.
- Publish a privacy policy and have the skin-analysis wording reviewed legally.
- Request bulk operation access, or keep the page-by-page import.
- Add per-store usage limits.
