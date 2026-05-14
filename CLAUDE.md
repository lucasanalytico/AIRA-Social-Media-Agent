# AIRA Social Media Agent — Project Instructions

## Purpose

Telegram-driven Instagram carousel publisher for **Analytico Training Academy (ATA)**. Operator sends `/start` → bot fires 5 idea cards based on a curated social-media trend → operator taps `Post`/`Edit`/`Dismiss` → on Post, a 2-slide carousel is generated (Nano Banana Pro) and published to IG (Graph API). UX mirrors **ClientPulse** (`c:\Projects\Client Pulse\server.py`).

## Tech stack

- Python 3.11
- stdlib `HTTPServer` (no Flask/FastAPI)
- `google-generativeai` — Gemini 2.5 Flash (captions) + Nano Banana Pro (slides)
- Instagram Graph API (Business/Creator account, long-lived token)
- Deploy: Render (Docker), free tier

## Locked decisions (do not change without flagging)

1. **Trend + 5 ideas are hardcoded** in `data/trends.json` for MVP. No live trend discovery.
2. **2 slides per carousel** — hook + reveal. Fixed count.
3. **Caption LLM:** Gemini 2.5 Flash. Not Claude, not GPT.
4. **Image gen:** Nano Banana Pro (`gemini-3-pro-image`), 1:1 1K.
5. **Image hosting:** same Render service at `GET /media/<post_id>/<n>.jpg`. No Cloudinary/S3 for MVP.
6. **Schedule options:** Now / Tonight 7pm SGT / Tomorrow 9am SGT. Fixed three.
7. **Auth:** `TELEGRAM_CHAT_IDS` allowlist. No public access.
8. **No DB.** State in JSON files (`queue.json`, `posts_log.json`, `pending_edits.json`).
9. **Edit scope:** caption only. Slides are not re-rolled on Edit.
10. **ATA context** baked into `src/prompts.py` — single source of truth for brand voice.

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
  prompts.py            # ATA-locked brand prompts
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
