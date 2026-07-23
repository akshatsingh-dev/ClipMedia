# Status — what's running, what's blocked, what's next

_Last updated 2026-07-23._

## First command, every session

```bash
cd /Users/akshatsingh/Desktop/Startup/ClipMedia/deepclip
set -a; . ./.env; set +a
export DATABASE_URL=postgresql://deepclip:deepclip@localhost:5432/deepclip
export REDIS_URL=redis://localhost:6379 DEEPCLIP_WHISPER=1 WHISPER_MODEL=base
python3 -m scripts.doctor
```

It probes every external dependency (keys, Postgres, Redis, API, web, YouTube
quota, both transcript paths, Whisper, Gemini) and ends with either "Live builds
work" or exactly what is blocking and what is still buildable without it. Every
stall in this project so far has been one of those, so check it before debugging
anything.

## What's built (all of it verified against real infra)

| Area | State |
|---|---|
| Pipeline stages 1–7 | working end to end on real YouTube + Gemini + Postgres |
| Stage 8 (vision) | built, feature-flagged off |
| Learn pages `/q/[slug]` | chapters, real clips at exact timestamps, credit, "why this clip" |
| Entertain feed `/e/[slug]` | snap scroll, autoplay, end-card (never infinite) |
| Perspectives `/q/[slug]` multi-lens | supportive/critical/neutral lenses, ≥2 lenses or the build fails |
| Perspective streams | create, add clips, reorder, remove, delete, share `/stream/[id]` |
| Saved pages | anon_id keyed, no login |
| Reel import | YouTube seed full pipeline; Instagram oEmbed display only |
| Clip tutor | grounded Q&A on one clip, `grounded` flag when the clip doesn't cover it |
| Credibility + contested sources | channel scoring, ≥2 framings on contested chapters |
| Analytics, rate limits, report queue | wired, recording |
| Tests | 418 offline + 33 real-Postgres (dedicated `deepclip_test` DB) |

## The external constraints (the actual bottleneck, not the code)

1. **Captions are IP-blocked** from this address, and have been for a day.
   Whisper covers it (~20–40s/video), so builds take minutes, not seconds.
2. **Whisper's audio path works** — but only because yt-dlp now fails over
   between player clients (android/ios/web). The default client is blocked.
3. **YouTube search quota** is 10k units/day; one 8-chapter build ≈ 1.6k. A
   handful of builds exhausts the day. Resets midnight Pacific.
4. **Gemini free tier** runs out under sustained building.

The real fixes are all ops, not code: residential proxies (~$3/mo, env already
wired: `WEBSHARE_PROXY_USER/PASS`, `DEEPCLIP_YTDLP_PROXY`), a YouTube quota
increase request, and billing on the Gemini key.

## What's left

- **Golden picks** (`eval/golden/picks/` is empty). The C7 ship gate is ≥80% of
  a hand-curated golden page's judge score, and the tooling deliberately refuses
  to fake human judgement — this needs a person picking timestamps.
- **Prebuild the top pages** (`scripts/prebuild.py`) once quota allows: a cached
  page costs ~$0 to serve, and the cache is the moat.
- **Accounts** — deliberately deferred; anon_id carries saves and streams today.
- **Deployment** — Dockerfiles exist, nothing is hosted; there is no public URL.
- **Family/parental direction** — researched (`research/parental-control-*.md`),
  transparent-curation only, no code committed.

## Restarting the stack

```bash
docker compose up -d postgres redis
# API and worker (worker must be detached — a tracked task gets reaped, D56)
python3 -m uvicorn services.api.main:app --port 8000 &
arq services.worker.main.WorkerSettings &
cd apps/web && npm run dev
```

Open **http://localhost:3000** in a normal browser — YouTube embeds are blocked
in the automated one.

## Tests

```bash
python3 -m pytest -q                                              # 418 offline
DEEPCLIP_DB=1 python3 -m pytest tests/test_db_integration.py -q    # 33, real Postgres
```
