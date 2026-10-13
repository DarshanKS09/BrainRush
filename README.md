# BrainRush — Telegram Gaming Bot (Foundation)

Minimal, modular foundation using **aiogram 3.x**, **SQLAlchemy 2.x async + PostgreSQL**,
**Alembic**, and **pytest + pytest-asyncio**. No game features are implemented yet.

## Project structure

```text
BrainRush/
  src/brainrush/
    __main__.py        # entrypoint: validate config/DB, then poll
    config.py          # Settings (BOT_TOKEN, DATABASE_URL) + validation
    healthcheck.py     # startup validation (config + SELECT 1 DB check)
    bot/
      factory.py       # create_bot() / create_dispatcher()
      handlers.py      # minimal /start handler only
    db/
      base.py          # DeclarativeBase
      models.py        # placeholder (no tables yet)
      session.py       # async engine + check_connection()
      repository.py    # BaseRepository placeholder
    game/
      engine.py        # placeholder, raises NotImplementedError
  alembic/
    env.py             # async env, reads DATABASE_URL
    versions/
  tests/
    test_config.py test_healthcheck.py test_imports.py
  pyproject.toml requirements.txt alembic.ini .env.example
```

## Prerequisites (Windows)

- Python **3.12+** (`python --version`)
- PostgreSQL 15+ running locally
- PowerShell

> Note: this scaffold declares `requires-python = ">=3.12"`. If your local
> interpreter is older, install Python 3.12 from python.org before `pip install`.

## Setup (Windows PowerShell)

```powershell
cd C:\Users\darsh\OneDrive\Desktop\BrainRush
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# or: pip install -e ".[dev]"
copy .env.example .env
# edit .env and set real BOT_TOKEN and DATABASE_URL
```

`.env.example` contains placeholders only:

```text
BOT_TOKEN=put-your-telegram-bot-token-here
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/brainrush
```

## Database configuration

Create DB + user (example):

```sql
CREATE DATABASE brainrush;
CREATE USER brainrush WITH PASSWORD 'change-me';
GRANT ALL PRIVILEGES ON DATABASE brainrush TO brainrush;
```

`DATABASE_URL` format (async driver required):

```text
postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DBNAME
```

## Migrations (Alembic)

```powershell
$env:DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/brainrush"
alembic upgrade head        # apply
alembic revision --autogenerate -m "describe change"
alembic downgrade -1        # roll back one step
```

`alembic/env.py` reads `DATABASE_URL` from the environment and imports
`brainrush.db.models` so autogenerate sees `Base.metadata`.

## Run

```powershell
python -m brainrush --check-only              # validate config (+ DB SELECT 1)
python -m brainrush --check-only --no-db-check  # config-only, offline
python -m brainrush                           # validate, then start polling
```

Exit codes: `0` ok, `1` DB unreachable, `2` invalid config.
The startup check validates `BOT_TOKEN` non-empty and `DATABASE_URL` scheme
(`postgresql+asyncpg://`), then runs `SELECT 1` with a short timeout.

## Tests

```powershell
pytest -v
pytest tests/test_config.py -v
```

Tests are offline-safe: config/health tests use mocked engines, except one
negative test that asserts `check_connection()` returns `False` (not raises)
against an unreachable DB.

## Scope notes

- Foundation only: no game rules, no Telegram polling in tests, no real
  credentials bundled or contacted.
- Next milestones: real models, repositories, game engine, additional handlers.
```

## License

MIT (foundation scaffold).

---

# BrainRush Mini App (Telegram gaming platform)

The bot is now a full Mini App platform: visual arcade frontend + FastAPI
backend reusing the existing models, services, and Number Guessing rules.

## Architecture

```text
BrainRush/
  src/brainrush/
    api/               # FastAPI: auth.py (initData verify), deps.py,
                       # routes.py, app.py (create_app)
    services/miniapp.py# web game orchestration (owns transactions)
    game/progression.py# XP -> level math (pure)
    db/models.py       # + webapp_game_states (in-progress secrets)
  alembic/versions/
    2ade8478df6d_...   # initial schema (applied)
    18a3cc82f265_...   # webapp_game_states (applied)
  frontend/            # React 18 + TS + Vite 6 + Tailwind 3
    src/screens/       # Home, Games, Play, Leaderboard, Profile
    src/components/    # BottomNav, GameCard, Keypad, XpBar, ...
    src/api.ts         # typed API client (initData header)
    src/telegram.ts    # WebApp SDK bridge (+ DEV-only mock)
```

Key rules enforced by the backend (never the frontend):
- Secret numbers live in `webapp_game_states` and are never serialized
  before completion. Difficulties: Easy 15 / Medium 10 / Hard 7 attempts.
- XP: win = `(max_attempts - attempts_used + 1) * 10` (Easy 150..10,
  Medium 100..10, Hard 70..10); loss = +5 XP; abandoned/cancelled = 0 XP.
- Levels: cumulative thresholds `100*L*(L-1)/2` (L1 0, L2 100, L3 300, …).
  Displayed level always derives from `total_xp`.
- Guesses carry a client-generated idempotency id: Telegram retries never
  consume twice or award double XP. Row locks + guarded `started→terminal`
  transitions + unique `game_results.session_id` protect concurrency.
- Every session operation checks player ownership (foreign ids → 404).
- Timestamps UTC; daily buckets use the UTC calendar date (existing policy).

Implemented vs Coming Soon: Number Guessing is fully playable (bot text game
+ Mini App). Memory Match, Reaction Test, Math Challenge, Word Puzzle are
Coming Soon cards (no fake gameplay). Leaderboard is real (top by XP,
paginated). Daily challenges are Coming Soon (no fake rewards).

## Backend setup (Windows PowerShell)

```powershell
cd C:\Users\darsh\OneDrive\Desktop\BrainRush
.\.venv\Scripts\Activate.ps1                      # Python 3.12 venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

`.env` keeps working; new optional keys (see `.env.example`):
`WEBAPP_URL` (public frontend URL, enables bot WebApp buttons),
`API_HOST`/`API_PORT` (default 127.0.0.1:8000),
`API_CORS_ORIGINS` (comma-separated frontend origins).
Dev-only mock identity (NEVER in production):
`ALLOW_DEV_AUTH=1` + `DEV_AUTH_TELEGRAM_ID=<id>` (backend logs a warning).

```powershell
$env:PYTHONPATH="src"
.venv/Scripts/python.exe -m alembic upgrade head  # apply migrations
.venv/Scripts/python.exe -m pytest                 # full suite (113+ tests)
.venv/Scripts/python.exe -m brainrush --check-only # config + DB check
.venv/Scripts/python.exe -m brainrush              # bot polling only
.venv/Scripts/python.exe -m brainrush --serve-api  # polling + API :8000
```

## Frontend setup

```powershell
cd C:\Users\darsh\OneDrive\Desktop\BrainRush\frontend
npm install
copy .env.example .env          # set VITE_API_URL for production builds
npm run dev                     # http://localhost:5173 (/api proxied to :8000)
npm test                        # vitest (10 tests)
npm run build                   # tsc + production bundle -> dist/
```

Local browser dev without Telegram: `npm run dev`, then open
`http://localhost:5173/?devuser=1` (DEV builds only; stripped from prod).

## Mini App local test via HTTPS tunnel

```powershell
# terminal 1: backend (ALLOW_DEV_AUTH unset; real initData from Telegram)
$env:PYTHONPATH="src"; .venv/Scripts/python.exe -m brainrush --serve-api
# terminal 2: frontend pointing at the public API URL
#   set VITE_API_URL=https://<api-tunnel>/ then: npm run build
# terminal 3: expose both, e.g. cloudflared (one tunnel per service)
cloudflared tunnel --url http://127.0.0.1:8000   # API -> https URL
# serve frontend/dist over HTTPS too (any static host/tunnel), then:
```

Telegram config (BotFather): `/mybots` → your bot → Mini App / Web App URL →
paste the frontend HTTPS URL. In `.env`, set `WEBAPP_URL` to the same URL
and `API_CORS_ORIGINS` to it, restart the bot: `/start` shows
Open BrainRush. Never commit tunnel URLs; they change every restart.

## Deployment notes

> Production runbook: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** — Fly.io
> backend (single poller, `Dockerfile` + `fly.toml`), Cloudflare Pages
> frontend, explicit migration step, env table, logs/rollback/health.
> Render alternative via `render.yaml`. CI (`.github/workflows/ci.yml`) runs
> pytest, `alembic heads`, a Docker build check, vitest, and the prod build.

- Backend: any Python host (Railway/Render/Fly/VPS): `pip install -r
  requirements.txt`, `alembic upgrade head`, run `python -m brainrush
  --serve-api` (or split polling/API processes sharing the database).
  Provider-injected `PORT` overrides `API_PORT` automatically; run exactly
  one backend replica so Telegram has a single poller.
- Frontend: any static host (Vercel/Netlify/Cloudflare Pages): build with
  `VITE_API_URL=https://<your-api-host>` set at build time.
- Keep `BOT_TOKEN` and the database URL server-side only. The frontend
  never sees them; it only sends Telegram `initData`.
- Supabase pooler URLs work as `DATABASE_URL` (verified with the session
  pooler string + `postgresql+asyncpg://` scheme).

## Verified live (2026-10-12)

API smoke-tested against real Supabase with dev auth: health, games catalog
(5 entries), dashboard, start (Easy/15), secret absent from all pre-finish
payloads, invalid guess → 422, hint correct, retry idempotent (1 attempt),
cancel → abandoned, leaderboard + history → 200. Residue: one dev user +
abandoned session (no drops). Browser/Telegram-client verification and
production deployment are NOT done (remaining tasks below).
