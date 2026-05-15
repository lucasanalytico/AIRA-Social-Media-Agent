# Deploy to Render

End-to-end walkthrough for getting AIRA Social Media Agent running on Render's free tier with a permanent public URL.

**Why Render:** Telegram webhooks + Instagram Graph API image-fetch both need a stable, internet-reachable HTTPS URL. Local cloudflared quick-tunnels work for dev but conflict with VPNs and rotate URLs on every restart. Render gives you a fixed URL forever.

**Time:** ~20 minutes.

---

## Pre-flight checklist

You should already have:
- ✅ A GitHub account (`Lucas-sam93` works fine)
- ✅ Render account linked to GitHub (the one running ClientPulse)
- ✅ All secrets in your local `.env` (validated working in local dev)
- ✅ Empty git repo at `c:\Projects\AIRA-Social-Media-Agent\` (already a git repo, no remote yet)

---

## Step 1 — Push to GitHub

```powershell
cd c:\Projects\AIRA-Social-Media-Agent

# Verify .env is gitignored (CRITICAL — never commit secrets)
git check-ignore .env
# Expected output: .env

# Stage and commit everything
git add -A
git commit -m "Initial: Telegram-driven Instagram carousel publisher for Analytico Training Academy"

# Create a new private repo on GitHub via the gh CLI:
gh repo create AIRA-Social-Media-Agent --private --source=. --remote=origin --push
```

If you don't have `gh` CLI installed, create the repo manually at https://github.com/new (named `AIRA-Social-Media-Agent`, **private**), then:

```powershell
git remote add origin https://github.com/Lucas-sam93/AIRA-Social-Media-Agent.git
git branch -M main
git push -u origin main
```

---

## Step 2 — Create the Render web service

1. Open https://dashboard.render.com/
2. Top-right → **`+ New`** → **`Web Service`**
3. **Connect a repository** → pick `AIRA-Social-Media-Agent`
   - If it's not listed: click **Configure account** → grant Render access to that specific repo, then come back
4. Fill in:
   - **Name:** `aira-social-media-agent` (must match `render.yaml`)
   - **Region:** Singapore (closest to you and to IG users)
   - **Branch:** `main`
   - **Runtime:** `Docker` (auto-detected via `Dockerfile`)
   - **Instance type:** `Free`
5. **Important:** Do NOT click "Create Web Service" yet. Scroll down to **Environment Variables** first.

---

## Step 3 — Set environment variables

In the Environment Variables section, click **`+ Add Environment Variable`** for each of the following. Copy values from your local `.env`:

| Key | Value source |
|---|---|
| `TELEGRAM_BOT_TOKEN` | from local `.env` |
| `TELEGRAM_CHAT_IDS` | from local `.env` (comma-separated) |
| `GOOGLE_API_KEY` | from local `.env` |
| `IG_USER_ID` | from local `.env` |
| `IG_ACCESS_TOKEN` | from local `.env` (long-lived Page token) |
| `IG_PAGE_ID` | from local `.env` |
| `PUBLIC_BASE_URL` | **leave empty for now** — we fill this in after Render assigns the URL (Step 5) |

Render auto-injects `PORT` (typically 10000), so don't add it.

Values pre-set in `render.yaml` (no action needed):
- `GEMINI_CAPTION_MODEL`, `IG_GRAPH_VERSION`, `TIMEZONE`, `SCHEDULER_POLL_SECONDS`

Click **`Create Web Service`** at the bottom.

---

## Step 4 — Wait for first build

Render now:
1. Clones your repo
2. Builds the Docker image (pulls Playwright base + installs Python deps) — ~3–5 min
3. Spins up the container
4. Hits `/health` to confirm it's up

Watch the **Logs** tab. You should eventually see:

```
AIRA Social Media Agent listening on 0.0.0.0:10000
  Allowed chat IDs: ['168473412', '7641029176']
  Public base URL:  (unset)
[scheduler] thread up — polling every 20s
```

`(unset)` is expected at this stage — we set it in Step 5.

The top of the page shows the service URL: `https://aira-social-media-agent.onrender.com` (or similar). **Copy it.**

---

## Step 5 — Set `PUBLIC_BASE_URL` + redeploy

1. Render dashboard → your service → **Environment** tab
2. Edit `PUBLIC_BASE_URL` → paste the URL from Step 4 (no trailing slash)
3. Click **Save changes**
4. Render auto-triggers a redeploy. Wait ~2 min.
5. After redeploy, logs should show:

```
  Public base URL:  https://aira-social-media-agent.onrender.com
```

That's the proof Render picked up the new env var.

---

## Step 6 — Register the Telegram webhook

From your local machine (one-off, ever):

```powershell
cd c:\Projects\AIRA-Social-Media-Agent
python set_webhook.py https://aira-social-media-agent.onrender.com
```

Expected output:
```
setWebhook: {'ok': True, 'result': True, 'description': 'Webhook was set'}
Webhook info: {'url': 'https://.../telegram/callback', ...}
```

If it says `Failed to resolve host`, the service isn't fully up yet — wait 30s and retry.

---

## Step 7 — End-to-end live test

Open Telegram → message **@aira_social_bot**:

1. **`/start`** → trend header + 5 idea cards with real Gemini captions
2. Pick any one → tap **`📤 Post`**
3. Buttons change to `[🟢 Now] [🌙 Tonight 7pm] [☀️ Tmr 9am]`
4. Tap **`🟢 Now`** → `📅 Queued <post_id>`
5. Within 20s → `🎨 Rendering slides…`
6. ~20s later → `📤 Publishing carousel…`
7. ~10s later → `✅ Posted — 🔗 https://www.instagram.com/p/…`

Open the permalink on your phone — branded teal 2-slide swipe carousel live on `@aira.trendcast`.

Total tap-to-IG: ~60s. The first run may be slower (Render free instance was idle and cold-started — ~30s extra).

---

## Cold start gotcha

Render free tier spins down after **15 minutes of inactivity**. First request after that wakes it back up (~30s).

For a demo, send any message to the bot 1–2 minutes before showing it off — that warms the instance and `/start` will feel instant.

If you want to permanently avoid this, options:
- **$7/mo Render Starter** plan — no spin-down
- **Free uptime pinger** (e.g. cron-job.org → ping `/health` every 10 min) — keeps it warm at no cost, mild abuse of free tier

---

## Token renewal (every ~60 days)

`IG_ACCESS_TOKEN` is a long-lived Page token that expires every 60 days.

- **Issued:** 2026-05-15
- **Expires:** ~2026-07-14

Renewal steps live in `docs/META_SETUP.md` (Steps 10–13). When the token expires, the publisher returns `OAuthException`; you regenerate via the Graph API Explorer and update the env var in the Render dashboard.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Webhook returns 502 | Container cold-starting | Wait 30s, retry |
| `OAuthException` from IG | Token expired or revoked | Regenerate per `docs/META_SETUP.md` Steps 10–13 |
| Slides render but IG returns "media URI doesn't meet requirements" | `PUBLIC_BASE_URL` wrong or `media/<post_id>/<n>.jpg` not 1:1 JPG | Check the Render URL is HTTPS, no trailing slash; check `media/` route works in browser |
| `[scheduler] PublishError: PUBLIC_BASE_URL not set` | Env var missing or empty | Set in Render dashboard → trigger redeploy |
| Bot silent | Webhook unregistered or pointing at old URL | Re-run `python set_webhook.py <render-url>` |
| `chromium.executable_path` errors at startup | Dockerfile drift from Playwright base image | Rebuild — base image version pin in Dockerfile should match `playwright==<version>` in requirements.txt |
