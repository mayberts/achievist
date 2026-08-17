# Achievist

A self-hosted, single-user cross-platform achievement aggregator. Track achievements, trophies, and playtime across Steam, Xbox, PlayStation, Epic Games, RetroAchievements, Ubisoft Connect, Guild Wars 2, and Wargaming titles — one dashboard, running on your own box.

## Stack

FastAPI + APScheduler backend in one container, Postgres for storage, a React + Tailwind SPA frontend. No login, no leaderboards, no multi-tenancy: it's yours alone.

## Quick start

```bash
docker compose up -d --build
```

Open `http://<host>:8744`. Everything else — connecting platforms, credentials, sync — happens in the **Accounts** tab of the app itself. There's no `.env` setup required to get the app running; `.env` is only for a handful of optional app-level settings (see below).

## Connecting platforms

Every platform is connected from the **Accounts** tab in the UI, not `.env`. Click **Connect** on a platform card and follow its prompt:

| Platform | What you need | Notes |
|---|---|---|
| **Steam** | SteamID64 + API key | Profile & game details must be public |
| **Xbox** | "Sign in with Xbox" (device code) or a public gamertag | Needs `XBOX_CLIENT_ID` set — see below |
| **PlayStation** | A one-time `npsso` token, then any public Online ID | Trophy privacy must be "Anyone" |
| **Epic Games** | Your Epic account ID (from your profile URL) | Profile must be public |
| **RetroAchievements** | Username + API key | |
| **Ubisoft Connect** | A one-time browser session ticket, then any public username | Only legacy "Uplay units" achievements are available — see [Platform notes](#platform-notes) |
| **Guild Wars 2** | An API key (progression scope) | |
| **Wargaming** (WoT/WoWS) | Application ID + nickname/region | |

Once connected, an account syncs automatically on the schedule (`SYNC_INTERVAL_HOURS`, default 12h) or on demand via **Sync all** / the per-account **Sync** button.

### Xbox setup

Xbox sign-in needs a free, one-time Azure app registration — Microsoft doesn't allow the device-code flow for a shared/borrowed client ID:

1. [portal.azure.com](https://portal.azure.com) → **App registrations** → **New registration**
   - Supported account types: *Personal Microsoft accounts only*
   - No redirect URI needed
2. **Authentication** → **Allow public client flows** → **Yes** → Save
3. Copy the **Application (client) ID** into `.env` as `XBOX_CLIENT_ID`
4. `docker compose up -d --build`, then Accounts → Xbox → **Sign in with Xbox**

After that, you can also add other public gamertags as separate accounts.

### PlayStation setup

1. Log into [playstation.com](https://playstation.com) in a browser
2. Visit `https://ca.account.sony.com/api/v1/ssocookie` in the same browser — copy the `npsso` value from the JSON
3. Accounts → PlayStation → Connect → paste it (one-time backend session)
4. Add accounts by **PSN Online ID** (trophy privacy must be public)

### Ubisoft Connect setup

1. Log into [connect.ubisoft.com](https://connect.ubisoft.com), open DevTools → Network, and grab a `Ubi_v1 t=…` session ticket from any `public-ubiservices.ubi.com` request
2. Accounts → Ubisoft → Connect → paste it (expires after a few hours — you'll re-paste occasionally)
3. Add accounts by **username** (public profile required)

## Platform notes

- **Ubisoft achievements are limited to legacy "Uplay units"**, not the modern achievement set Ubisoft's own apps show. Ubisoft's modern achievement API is locked to a private client ID only their desktop app holds, and their local caches are encrypted — there is no public path to full parity. Games and legacy unit progress still sync correctly.
- **GOG is not supported.** GOG's achievement API requires a separate developer-issued secret *per game*, extracted individually from each game's files — there's no universal token, so it isn't a one-time integration.
- **Epic Games** achievement data is fully public (no auth beyond your account ID) via Epic's Store GraphQL API.

## Optional app-level settings (`.env`)

Copy `.env.example` to `.env` for these — none are required to start the app:

| Variable | Purpose |
|---|---|
| `XBOX_CLIENT_ID` | Required for Xbox sign-in (see above) |
| `SYNC_INTERVAL_HOURS`, `REQUEST_DELAY_SECONDS` | Sync scheduling / per-request throttling |
| `IGDB_CLIENT_ID` / `IGDB_CLIENT_SECRET` | Portrait cover art fallback (Twitch dev app) |
| `SGDB_API_KEY` | SteamGridDB landscape cover art (preferred over IGDB) |
| `EXOPHASE_*` | Xbox 360 locked-achievement import from exophase.com |
| `BACKUP_KEEP_COUNT`, `BACKUP_INTERVAL_HOURS` | Backup retention count / schedule (defaults: 14 kept, every 24h) |

## Backups

Everything Achievist knows — synced games/achievements *and* connected-account
credentials — lives in a single Postgres database, so backups are a `pg_dump`
away. This happens automatically:

- A `pg_dump -Fc` runs on a schedule (`BACKUP_INTERVAL_HOURS`, default 24h) and
  is written to a `/backups` volume, keeping the most recent `BACKUP_KEEP_COUNT`
  (default 14).
- The **Maintenance** page has a **Backups** section to trigger a backup on
  demand, download any backup, or delete old ones.
- The same is available directly: `POST /api/backups` (create), `GET
  /api/backups` (list), `GET /api/backups/{filename}` (download), `DELETE
  /api/backups/{filename}` (delete).

The **Maintenance** page also has a **Cover Art** section to re-fetch every
game's SteamGridDB cover art from scratch (`POST /api/sgdb-refresh?force=true`)
— useful after a change to which art is preferred, or if a batch of covers
still look wrong.

**Restore** a downloaded `.dump` file into a running stack:

```sh
docker compose exec -T db pg_restore -U pantheon -d pantheon --clean --if-exists < backup.dump
```

**Security note:** backup files contain plaintext account credentials (API
keys, tokens) for every connected platform. Treat them like secrets — store
downloaded copies somewhere access-controlled, not in a shared or public
location.

## Cover art priority

For non-Steam games, covers are resolved in this order:
1. **SteamGridDB** landscape grid (460×215 or 920×430)
2. **IGDB** portrait cover (cropped to landscape)
3. **Platform icon**

Use the **Change Cover** action on a game's detail page to search SGDB manually and pin a specific image.

## API reference

The frontend is a full SPA; these are the main endpoints it talks to (see `app/main.py` for the complete set):

| Method | Path | Purpose |
|---|---|---|
| GET / PUT | `/api/profile` | Your display name and avatar (shown in the header — click it to edit) |
| GET | `/api/summary` | Overall + per-platform stats |
| GET | `/api/games` | Library, paginated (`sort`, `platform`, `completion`, `search`) |
| GET | `/api/achievements/search` | Achievement search across the whole library (`q`, `rarity`, `platform`, `unlocked`, `sort`) |
| GET | `/api/games/{id}` | Game detail with achievements and rarity |
| GET | `/api/activity` | Unlock heatmap, streaks, recent-activity feed |
| GET | `/api/statistics` | Rarity/completion breakdowns, records, progression |
| GET | `/api/platforms` | Connect-schema for every supported platform |
| GET / POST / DELETE | `/api/accounts` | List / connect / disconnect accounts |
| POST | `/api/accounts/{id}/sync` | Sync a single account |
| POST | `/api/sync` | Sync all accounts (202, or 409 if busy) |
| GET | `/api/sync/progress` | Live sync status |
| GET / POST | `/api/backups` | List backups / trigger one now |
| GET / DELETE | `/api/backups/{filename}` | Download / delete a backup |

## Development

### Backend tests

```bash
pip install -r requirements-dev.txt
pytest
```

Most tests cover pure parsing/auth helpers, the platform-registry contract, and API routes that don't touch the database — they run with no setup. A smaller set of integration tests (account dedup, achievement-unlock detection, schema migrations) needs a real Postgres connection; those skip automatically if none is reachable. To run them locally, point `TEST_DATABASE_URL` at a throwaway database:

```bash
createdb pantheon_test   # or: docker run --rm -d -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16-alpine
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/pantheon_test pytest
```

CI runs these against a Postgres service container automatically.

### Frontend

```bash
cd frontend
npm install
npm run dev      # dev server with API proxy to :8000
npm run build    # production build → app/webdist (what Docker serves)
```

### Frontend tests

```bash
cd frontend
npm test         # once
npm run test:watch
```

Vitest with Testing Library, running against jsdom, so they need no browser and
no database. They cover the formatting/rarity/platform helpers and component
rendering — the empty states, milestone wording, and the panels on the Home
page. Note the limit: jsdom has no real layout engine, so a purely visual
regression (an element wrapping onto two lines, a colour that's hard to read)
will pass here and still needs a look in a browser.

### Full stack locally

```bash
docker compose up -d --build
```

CI (`.github/workflows/test.yml`) runs the backend suite against a Postgres service container, plus the frontend tests and a production build, on every push and PR.

## Version control and updates

### One-time: publish to GitHub

```bash
git init
git add .
git commit -m "Initial Achievist"
git branch -M main
git remote add origin git@github.com:<you>/pantheon.git
git push -u origin main
```

`.env` and `pgdata/` are gitignored — secrets and the database are never committed. Platform credentials live in the database, not in git, either way.

### Tier 1: pull and rebuild on the box

```bash
chmod +x update.sh   # once
./update.sh          # git pull --ff-only + docker compose up -d --build + prune
```

### Tier 2: build in CI, pull the image

`.github/workflows/build.yml` builds on every push to `main` and pushes to GHCR.

1. Push to `main` — GitHub Actions publishes `ghcr.io/<you>/pantheon:latest`
2. Deploy with `docker-compose.ghcr.yml` (set `<youruser>` first, `docker login ghcr.io` once if private)
3. Update: `docker compose -f docker-compose.ghcr.yml pull && docker compose -f docker-compose.ghcr.yml up -d`

`.gitattributes` pins shell and code files to LF so Windows checkouts don't break Linux scripts.
