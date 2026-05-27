# AIRA Social Media Agent — Project Instructions

## Purpose

Telegram-driven Instagram carousel publisher for **Meridian Digital** (fictitious demo brand). Operator sends `/start` → bot fires 5 idea cards based on a curated social-media trend → operator taps `Post`/`Edit`/`Dismiss` → on Post, a 2-slide carousel is generated (Nano Banana Pro) and published to IG (Graph API). UX mirrors **ClientPulse** (`c:\Projects\Client Pulse\server.py`).

## Tech stack

- Python 3.11
- stdlib `HTTPServer` (no Flask/FastAPI)
- **Captions + slide-2 copy:** hardcoded in `data/trends.json` (v1 demo). LLM re-enablement is a v2 task — see "V2: LLM re-enablement" below.
- **Slide rendering:** Jinja2 HTML templates + Playwright (headless Chromium) → 1080×1080 JPG
- Instagram Graph API (Business/Creator account, long-lived token)
- Deploy: Render (Docker), free tier

## Locked decisions (do not change without flagging)

1. **Trend + 5 ideas are hardcoded** in `data/trends.json` for MVP. No live trend discovery.
2. **2 slides per carousel** — hook + reveal. Fixed count.
3. **Caption source (v1):** pre-written in `trends.json` per idea. Zero LLM calls in the demo path.
4. **Image gen (v1):** HTML + CSS via Jinja2 + Playwright. Pixel-perfect Meridian Digital brand, deterministic, free. LLM image gen (Nano Banana Pro, Imagen, etc.) is paid-only — deferred to v2.
5. **Image hosting:** same Render service at `GET /media/<post_id>/<n>.jpg`. No Cloudinary/S3 for MVP.
6. **Schedule options:** Now / Tonight 7pm SGT / Tomorrow 9am SGT. Fixed three.
7. **Auth:** `TELEGRAM_CHAT_IDS` allowlist. No public access.
8. **No DB.** State in JSON files (`queue.json`, `posts_log.json`, `pending_edits.json`).
9. **Edit scope:** caption only. Slides are not re-rolled on Edit.
10. **Meridian Digital brand context** baked into `src/prompts.py` — kept as the source of truth even though v1 doesn't call an LLM (v2 reuses it verbatim).

## V2: LLM re-enablement (deferred)

Two LLM call sites exist in earlier drafts and remain ready to re-enable. v1 swaps both for hardcoded reads from `data/trends.json` because Gemini 2.5 Flash free tier dropped to 20 req/day — too tight for a demo where one /start burns 5 requests. v2 plan:

- **Caption regeneration:** `src/caption.py::generate_caption` swaps back to the Gemini SDK call, reusing `CAPTION_SYSTEM_INSTRUCTION` from `src/prompts.py`. Falls back to `trends.json` caption on any quota/timeout/parse error so the demo path never breaks.
- **Slide-2 structuring:** `src/images.py::_structure_slide2` swaps back to Gemini, reusing the structurer prompt. Same fallback semantics.
- **Trigger to re-enable:** either enable billing on the Google API key (caption cost ~$0.00015/call, trivial) OR move to a higher-quota model. Either way, just flip the function bodies; the public surface and `trends.json` schema don't change.

## Project structure

```
server.py               # HTTPServer + Telegram handlers
set_webhook.py          # one-shot setWebhook
src/
  cards.py              # idea card text + inline keyboard builders
  caption.py            # Gemini caption generation
  images.py             # Nano Banana Pro slide generation
  publisher.py          # IG Graph API publish
  scheduler.py          # background queue thread
  state.py              # JSON persistence
  prompts.py            # Meridian Digital brand prompts
data/trends.json        # trend + 5 ideas
media/<post_id>/<n>.jpg # generated slides (gitignored)
```

## Conventions

- snake_case Python, PEP 8.
- All inter-service config via env vars (see `.env.example`).
- All datetime math via `zoneinfo.ZoneInfo("Asia/Singapore")` — never naive.
- `callback_data` format: `action|idea_id|message_id` (3 parts, `|` delimited).
- New post IDs: `nanoid` style — `secrets.token_hex(4)` (8 hex chars).

## Operator flow

1. `/start` → 5 idea cards (sequential, 1s apart) with `[📤 Post] [✏️ Edit] [🗑 Dismiss]`
2. Tap `Edit` → reply with new caption → card updates in place
3. Tap `Dismiss` → card deleted
4. Tap `Post` → sub-card `[🟢 Now] [🌙 Tonight 7pm SGT] [☀️ Tomorrow 9am SGT]`
5. Pick time → queued; bot replies with confirmation
6. At fire time → slides generated → IG published → permalink replied in Telegram

## Out of scope (MVP)

Live trend discovery, multi-trend rotation, other platforms (LinkedIn/X/TikTok), analytics, slide re-roll on Edit, multi-account, approval workflow.
