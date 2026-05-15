# AIRA Social Media Agent

Telegram-driven Instagram carousel publisher for **Analytico Training Academy**.

Operator sends `/start` → bot fires **5 trend-based idea cards** with hand-written captions → operator taps **📤 Post / ✏️ Edit / 🗑 Dismiss** → on Post, a **2-slide branded carousel** (hook + reveal) is rendered from HTML templates and published live to Instagram via the Graph API.

End-to-end Telegram-tap → live IG post takes ~50–60 seconds.

---

## Live deploy

- **Service:** [aira-social-media-agent.onrender.com](https://aira-social-media-agent.onrender.com) (Render, free tier, Singapore region)
- **Bot:** [`@aira_social_bot`](https://t.me/aira_social_bot) (allowlisted via `TELEGRAM_CHAT_IDS`)
- **IG account:** `@aira.trendcast` (Business, linked to "AIRA Social Test" FB Page)
- **Auto-deploys on every push to `main`**

For the full deploy walkthrough see [`docs/DEPLOY.md`](docs/DEPLOY.md).

---

## Operator flow

1. `/start` → trend header + 5 idea cards (sequential, ~1s apart), each with:
   - Idea title, hook, reveal, course angle
   - Hand-written caption
   - `[📤 Post] [✏️ Edit] [🗑 Dismiss]` inline buttons
2. **Tap `✏️ Edit`** → reply with new caption text → card updates in place
3. **Tap `🗑 Dismiss`** → card deleted
4. **Tap `📤 Post`** → sub-card `[🟢 Now] [🌙 Tonight 7pm SGT] [☀️ Tmr 9am SGT]`
5. Pick a time → bot replies *"📅 Queued: <idea title> — Fires at: …"*
6. At fire time:
   - 🎨 Renders 2 branded slides from Jinja2 templates → Playwright screenshot → 1080×1080 JPGs
   - 📤 Publishes carousel via IG Graph API (3 calls: container per slide → carousel container → media_publish)
   - ✅ Replies with the live IG permalink

---

## Stack

| Layer | Choice | Why |
|---|---|---|
| HTTP server | Python 3.11 stdlib `HTTPServer` | No Flask/FastAPI — single-process webhook is enough |
| Captions / slide-2 copy | Hardcoded in `data/trends.json` | Demo-reliable, zero LLM cost. V2 = Gemini Flash with fallback (see [CLAUDE.md](CLAUDE.md)) |
| Slide rendering | Jinja2 HTML templates + Playwright headless Chromium | Pixel-perfect Analytico brand, deterministic, free. Replaces paid image-gen APIs |
| Image hosting | Same Render service at `GET /media/<post_id>/<n>.jpg` | No Cloudinary/S3 dependency for MVP |
| Publishing | Instagram Graph API v23.0 | Business account, long-lived Page token |
| Persistence | JSON files (`queue.json`, `posts_log.json`) | No database — fine for one-operator workflow |
| Deploy | Render Docker (free tier, Singapore region) | Auto-deploys from `main`; cold start ~30s if idle > 15 min |

Brand colour: teal `#03989e`. Typography: Inter (Google Fonts).

---

## Project structure

```
.
├── server.py                  HTTPServer + Telegram handlers (mirrors ClientPulse)
├── set_webhook.py             One-shot setWebhook helper
├── Dockerfile                 Playwright base image (Chromium preinstalled)
├── render.yaml                Render service definition + env var stubs
├── requirements.txt           Pinned Python deps
│
├── data/
│   └── trends.json            Trend + 5 ideas with captions, hashtags, slide2 blocks
│
├── renderer/
│   └── templates/
│       ├── _base.html.j2      Shared brand CSS (teal, Inter, layout)
│       ├── slide1_hook.html.j2   Hook slide (curiosity-gap question)
│       └── slide2_reveal.html.j2 Reveal slide (headline + 3 stats + CTA)
│
├── src/
│   ├── cards.py               Card text + inline keyboard builders
│   ├── caption.py             Reads captions from trends.json (v2: Gemini)
│   ├── images.py              Jinja2 + Playwright → 1080×1080 JPGs
│   ├── publisher.py           IG Graph API: child containers → carousel → publish
│   ├── scheduler.py           Background thread, polls queue.json every 20s
│   ├── schedule.py            SGT-aware slot calculation (Now / 7pm / Tmr 9am)
│   ├── state.py               JSON persistence (queue, posts_log, pending_edits)
│   └── prompts.py             Analytico brand context (kept for v2 LLM re-enablement)
│
└── docs/
    ├── DEPLOY.md              End-to-end Render deployment walkthrough
    └── META_SETUP.md          Meta App + IG Graph API setup (token exchange)
```

---

## Endpoints

| Path | Method | Purpose |
|---|---|---|
| `/telegram/callback` | POST | Telegram webhook — message + callback_query |
| `/media/<post_id>/<n>.jpg` | GET | Public slide image (consumed by IG Graph API fetcher) |
| `/health` | GET | Render health check |
| `/status` | GET | Live queue + posts log dump |

---

## Local development

Render is primary. Local dev needs an internet-reachable HTTPS tunnel (Telegram + IG can't reach `localhost`). VPNs (NordVPN especially) conflict with most tunneling tools — disable the VPN before launching a local tunnel, or just push to Render and iterate there.

```powershell
# 1. Configure
cp .env.example .env   # then fill in tokens

# 2. Install
pip install -r requirements.txt
playwright install chromium

# 3. Run
python server.py       # listens on $PORT (default 10000)

# 4. Tunnel (your choice — paid ngrok / Tailscale Funnel / Cloudflare named tunnel)
#    Free cloudflared quick-tunnels also work but break under VPN.

# 5. Register webhook against the tunnel URL
python set_webhook.py https://your-tunnel.example.com
```

For most iterations, push to `main` and let Render auto-deploy (~3 min) — simpler than fighting tunnels.

---

## Configuration

Secrets live in environment variables, never in code. See [`.env.example`](.env.example) for the full list. On Render, set these in the dashboard's **Environment** tab.

| Key | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_IDS` | Comma-separated allowlist of chat IDs |
| `GOOGLE_API_KEY` | Reserved for v2 LLM re-enablement (unused in v1 demo path) |
| `IG_USER_ID` | Instagram Business account ID |
| `IG_ACCESS_TOKEN` | Long-lived Page token (60-day expiry) |
| `IG_PAGE_ID` | Linked Facebook Page ID |
| `IG_GRAPH_VERSION` | Graph API version (e.g. `v23.0`) |
| `PUBLIC_BASE_URL` | The service's own public URL — used to generate slide URLs that IG can fetch |
| `TIMEZONE` | `Asia/Singapore` (all schedule slots interpreted in this zone) |
| `SCHEDULER_POLL_SECONDS` | Default 20s |

---

## Token renewal

`IG_ACCESS_TOKEN` is a long-lived Page token; it expires every **~60 days**. When it does, the publisher returns `OAuthException` and the operator gets a Telegram error message.

Re-issue process: [`docs/META_SETUP.md`](docs/META_SETUP.md) Steps 10–13 — generate a fresh user token in Graph API Explorer, exchange for long-lived, then update the env var in the Render dashboard.

Current token issued **2026-05-15**, expires **~2026-07-14**.

---

## V2 backlog (out of scope for the current demo)

- Re-enable LLM captions + slide-2 structurer with Gemini fallback to hardcoded copy
- Live trend discovery (web search / IG trends API) replacing the hardcoded trend
- Multi-trend rotation memory so the same trend doesn't repeat
- Other platforms: LinkedIn, X, TikTok
- Multi-account (multiple IG accounts per bot)
- Approval workflow (idea → reviewer → poster)
- Engagement feedback loop (post performance → trend / idea ranking)

See [`CLAUDE.md`](CLAUDE.md) for locked decisions and the exact swap points for v2 work.

---

## Implementation plan

The original phased plan that drove this build is at [`C:\Users\lucas\.claude\plans\using-clientpulse-workflow-i-ancient-pizza.md`](file:///C:/Users/lucas/.claude/plans/using-clientpulse-workflow-i-ancient-pizza.md).
