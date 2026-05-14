"""Register the Telegram webhook.

Usage:
    python set_webhook.py https://your-tunnel.example.com
    python set_webhook.py https://aira-social-media-agent.onrender.com
"""
import os
import sys

import requests


def _load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN not set (check .env)")
    sys.exit(1)

if len(sys.argv) != 2:
    print(f"Usage: python {sys.argv[0]} <base-url>")
    print(f"  e.g. python {sys.argv[0]} https://aira-social-media-agent.onrender.com")
    sys.exit(1)

base_url = sys.argv[1].rstrip("/")
webhook_url = f"{base_url}/telegram/callback"

resp = requests.post(
    f"https://api.telegram.org/bot{TOKEN}/setWebhook",
    json={"url": webhook_url, "allowed_updates": ["message", "callback_query"]},
    timeout=10,
)
print("setWebhook:", resp.json())

info = requests.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo", timeout=10).json()
print("Webhook info:", info.get("result"))
