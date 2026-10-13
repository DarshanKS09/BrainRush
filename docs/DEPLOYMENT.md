# BrainRush Production Deployment Guide

Goal: bot polling + FastAPI run 24/7 on hosted infrastructure, React Mini App
on static HTTPS hosting, Supabase stays the database. No laptop, no terminal,
no Cloudflare Tunnel required after setup.

> Status: infrastructure-as-code in this repo (`Dockerfile`, `fly.toml`,
> `render.yaml`, CI). **No real deployment has been performed yet** — Block 8
> below lists the manual steps that remain.

## 1. Architecture

- **Backend (one persistent service):** the existing combined process
  (`python -m brainrush --serve-api`) runs Telegram long polling and FastAPI
  in a single event loop. It already shuts down cleanly (cancels tasks,
  closes the bot session, disposes the engine) and exposes `GET /health`
  for provider health checks.
- **Single poller rule:** run exactly **one** backend replica/container.
  Two competing long-pollers double-answer users. `fly.toml` pins one
  machine; `render.yaml` pins `numInstances: 1`.
- **Frontend (static hosting):** `frontend/dist/` (Vite build) on Cloudflare
  Pages (primary) or Netlify/Vercel. No server code, no secrets in the bundle.
- **Database:** existing Supabase PostgreSQL. Migrations run explicitly,
  never on boot, never in tests.
- **Ephemeral filesystems are fine:** all persistent game data lives in
  Supabase; containers hold no state.

## 2. Required environment variables (backend)

Set these in the hosting provider's **secret/env dashboard**, never in git.
Local `.env` is not used in production and is never overwritten by deploys.

| Variable | Production value |
|---|---|
| `BOT_TOKEN` | Real bot token (secret) |
| `DATABASE_URL` | Real Supabase URL, `postgresql+asyncpg://…` scheme (secret) |
| `WEBAPP_URL` | Permanent frontend HTTPS URL, e.g. `https://brainrush.pages.dev` |
| `API_HOST` | `0.0.0.0` (bind all interfaces inside the container) |
| `API_PORT` | `8000` (or omit; provider `PORT` overrides it automatically) |
| `API_CORS_ORIGINS` | Exactly the frontend origin, e.g. `https://brainrush.pages.dev` (no trailing slash, no wildcards) |
| `INIT_DATA_MAX_AGE` | Leave default (`86400`) |
| `ALLOW_DEV_AUTH` | **Unset / false. Never enable in production.** |
| `DEV_AUTH_TELEGRAM_ID` | **Unset in production.** |

Frontend build variable: `VITE_API_URL=https://<backend-host>` (baked in at
build time; see Block 4).

## 3. Database migration safety

```powershell
# Run ONCE per release that ships a migration, from any machine with .env
# pointing at Supabase. Never on container boot, never in CI/tests.
$env:PYTHONPATH="src"
python -m alembic upgrade head
python -m alembic current   # must print the new head
```

Rules: backward-compatible migrations only (additive preferred); review the
generated file for `drop_`/`alter` before applying; Supabase keeps all rows.
Current head history: `2ade8478df6d` (initial schema) → `18a3cc82f265`
(`webapp_game_states`). No data has ever been reset.

## 4. First deploy — backend on Fly.io (primary)

```powershell
fly auth login
fly launch --no-deploy        # reuse repo fly.toml; do not create a 2nd app
fly secrets set BOT_TOKEN="..." DATABASE_URL="..." WEBAPP_URL="https://<pages-url>" API_CORS_ORIGINS="https://<pages-url>"
# Apply any pending migration first (Block 3), then:
fly deploy
fly status                    # 1 machine running
fly logs                      # expect "Config + DB OK" + "Serving API on 0.0.0.0:8000"
curl https://<app>.fly.dev/health   # {"status":"ok"}
```

Alternative — Render Blueprint: connect repo → New → Blueprint (uses
`render.yaml`) → set the same four secrets in the dashboard → deploy. The
`PORT` variable Render injects is picked up automatically.

## 5. First deploy — frontend on Cloudflare Pages

```powershell
cd frontend
$env:VITE_API_URL="https://<backend-host>"   # permanent backend URL
npm ci
npm run build                                # tsc + vite -> dist/
```

Then: Cloudflare dashboard → Pages → Upload `dist/` (or connect the repo
with build command `npm run build`, output `dist/`). Copy the
`https://<name>.pages.dev` URL into backend `WEBAPP_URL` +
`API_CORS_ORIGINS`, redeploy backend, then BotFather → `/mybots` → bot →
Mini App URL → the Pages URL. No SPA rewrites needed (client-side tabs,
single `index.html` + assets).

## 6. Redeploys, logs, rollback, health

- Redeploy: push to main → `fly deploy` (or Render auto-deploys). Run Block 3
  first only if the release ships a new migration.
- Logs: `fly logs` (backend access log shows method/path/status/user id —
  never tokens or initData). Render: dashboard → Logs.
- Troubleshoot: 401s → clock skew or stale initData; CORS errors → exact
  `API_CORS_ORIGINS` match; double replies → more than one replica/poller
  running (scale back to 1); DB errors → Supabase pooler URL/password.
- Rollback: `fly releases` → `fly deploy --image <previous>` (Render:
  dashboard → deploys → Rollback). Migrations are one-way: never roll back
  past a migration that added a table the old code ignores (additive tables
  are safe to leave in place).
- Health: provider checks hit `/health`; also poll it manually and send
  `/start` in Telegram after each deploy.

## 7. Costs (estimates — verify on pricing pages before committing)

| Piece | Indicative cost |
|---|---|
| Fly.io `shared-cpu-1x` 256MB, always-on | ~$2–5/mo estimate |
| Supabase (existing project, current usage) | $0 on free tier; verify limits |
| Cloudflare Pages (static frontend) | $0 |
| Render alternative (needs always-on, no sleep) | paid tier, roughly ~$7/mo+ estimate |

These are **unverified estimates**, not quotes. Confirm current prices on
fly.io/pricing, render.com/pricing, supabase.com/pricing.

## 8. Remaining manual steps (not done)

1. Create/claim the Fly.io app (or Render Blueprint) and set the four
   secrets.
2. Apply pending migrations if any (`alembic upgrade head`).
3. Deploy backend; verify `/health` and logs.
4. Build + publish frontend with the permanent `VITE_API_URL`.
5. Set `WEBAPP_URL`/`API_CORS_ORIGINS`, redeploy backend.
6. Point BotFather Mini App URL at the Pages URL.
7. End-to-end Telegram test: `/start` button → dashboard → play → XP.
