# Status — what's running and how to use it

_Last updated during the overnight/lunch session._

## Everything is running right now

| Service | Where | Status |
|---|---|---|
| Web app | http://localhost:3000 | up |
| API | http://localhost:8000 | up (`/healthz`) |
| Worker | background (arq) | up |
| Postgres + pgvector | docker, port 5432 | up |
| Redis | docker, port 6379 | up |

If any restarted, see "Restarting the stack" below.

## What you can do in the UI

Open **http://localhost:3000** in a normal browser (not the automated one — YouTube
embeds are blocked there, they play fine in yours).

1. **Browse built pages** — the home page lists them. Click one:
   - A **Learn** page (e.g. "How Neural Networks Actually Work") — chapters, real
     clips jumped to timestamps, "why this clip", creator credit, a report button,
     an "ask about this clip" tutor, and a "did you get what you came for" tap.
   - The **Entertain** feed ("Legendary Internet Moments") — full-screen snap
     scroll, autoplay, and it ENDS with an end-card.
2. **Watch clips** — every clip is a real YouTube embed at the exact timestamp.
3. **Type a query and Build** — the search box runs the real pipeline
   (YouTube → transcripts → moments → ranking → assembly). You'll see live
   progress. **This is slow right now** — see the transcript note below.
4. **Paste a clip** ("paste a clip you already loved") — the reel-import wedge.
5. **Report / tutor / satisfaction** — all wired and recording to the database.

## The one big caveat: transcripts

YouTube IP-blocked the caption endpoint after heavy testing. The pipeline now
falls back to **Whisper** (downloads audio from a different, unblocked host and
transcribes it locally). That works — but it's **slow** (~20-40s per video on
CPU), so a live build takes a few minutes instead of seconds.

- Captions come back automatically once the IP block lifts (hours) — then builds
  are fast again.
- For fast reliable builds in production, the fix is residential proxies for the
  caption endpoint (a few $/mo). That's a business decision, not more code.

## What's real vs. demo

- The two pre-built pages are **fixtures**: real videos/channels (verified), but
  the clip **timestamps** were not hand-picked — they're placeholders. The UI
  says so with a banner.
- Any page you **Build** yourself is **fully real** — real transcripts, real
  moment detection, real ranking. Those are the ones to judge quality on.

## Restarting the stack

```bash
cd /Users/akshatsingh/Desktop/Startup/ClipMedia/deepclip

# infra
docker compose up -d postgres redis

# load env (keys live in .env)
set -a; . ./.env; set +a
export DATABASE_URL=postgresql://deepclip:deepclip@localhost:5432/deepclip
export REDIS_URL=redis://localhost:6379
export DEEPCLIP_WHISPER=1 WHISPER_MODEL=base

# API + worker
python3 -m uvicorn services.api.main:app --port 8000 &
arq services.worker.main.WorkerSettings &

# web
cd apps/web && npm run dev
```

## Tests

```bash
cd deepclip
python3 -m pytest -q                                    # 382 offline
DEEPCLIP_DB=1 python3 -m pytest tests/test_db_integration.py -q   # 33 real-Postgres
```
