# AIRA Social Media Agent

Telegram-driven Instagram carousel publisher for Analytico Training Academy.

Operator sends `/start` → bot fires 5 trend-based idea cards → operator taps **Post / Edit / Dismiss** → on Post, a 2-slide IG carousel (hook + reveal) is generated with Nano Banana Pro and published via the Instagram Graph API.

## Quick start (local)

1. `cp .env.example .env` and fill in tokens
2. `pip install -r requirements.txt`
3. `python server.py` (listens on `PORT`, default 10000)
4. Expose via ngrok/cloudflare tunnel: `ngrok http 10000`
5. Register webhook: `python set_webhook.py https://your-tunnel.example.com`
6. In Telegram, message your bot: `/start`

## Endpoints

| Path | Purpose |
|---|---|
| `POST /telegram/callback` | Telegram webhook (message + callback_query) |
| `GET /media/<post_id>/<n>.jpg` | Public slide image (consumed by IG Graph API) |
| `GET /health` | Render health check |
| `GET /status` | Posts log dump |

## Architecture

See `CLAUDE.md` for locked decisions, project structure, and operator flow.

Plan: `C:\Users\lucas\.claude\plans\using-clientpulse-workflow-i-ancient-pizza.md`
