"""AIRA Social Media Agent — Telegram webhook server.

Mirrors c:\\Projects\\Client Pulse\\server.py:
  - stdlib HTTPServer, no framework
  - POST /telegram/callback for both messages and callback_query
  - Inline-keyboard cards with action|idea_id|message_id callback_data

Phase 1+2+5 scope (no LLM, no IG yet):
  - /start fires 5 idea cards
  - Post -> schedule sub-card -> queue.json entry (no actual posting yet)
  - Edit -> pending-edit reply flow updates caption in place
  - Dismiss -> deleteMessage
"""
import json
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from src import cards, schedule, state
from src.caption import generate_caption
from src.publisher import PublishError, publish_carousel


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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_IDS = [
    cid.strip()
    for cid in os.getenv("TELEGRAM_CHAT_IDS", "").split(",")
    if cid.strip()
]
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
MEDIA_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
os.makedirs(MEDIA_ROOT, exist_ok=True)


def _tg(endpoint: str, payload: dict) -> dict:
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{endpoint}",
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _is_allowed(chat_id: str) -> bool:
    return chat_id in TELEGRAM_CHAT_IDS


def _send_idea_card(chat_id: str, idea: dict, caption_parts: dict | None) -> None:
    """Send one idea card with action buttons.

    caption_parts is {'caption': str, 'hashtags': str} from Gemini, or None on failure.
    """
    caption_text = caption_parts["caption"] if caption_parts else None
    text = cards.build_card_text(idea, caption=caption_text)
    resp = _tg("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    })
    message_id = resp["result"]["message_id"]
    keyboard = cards.idea_action_keyboard(idea["id"], message_id)
    _tg("editMessageReplyMarkup", {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": keyboard,
    })
    state.set_draft(message_id, {
        "idea_id": idea["id"],
        "caption": caption_text,
        "hashtags": caption_parts.get("hashtags") if caption_parts else None,
        "chat_id": chat_id,
    })


def _fire_all_ideas(chat_id: str) -> None:
    trends = cards.load_trends()
    trend = trends["active_trend"]
    _tg("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"🔥 *Trend:* {trend['name']}\n"
            f"_{trend['description']}_\n\n"
            f"Generating 5 ATA-tailored captions in parallel…"
        ),
        "parse_mode": "Markdown",
    })

    # Generate all 5 captions in parallel so /start feels fast.
    ideas = trends["ideas"]
    captions: dict[str, dict | None] = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(generate_caption, idea): idea["id"] for idea in ideas}
        for fut in futures:
            idea_id = futures[fut]
            try:
                captions[idea_id] = fut.result(timeout=30)
            except Exception as e:
                print(f"[caption {idea_id}] failed: {e}")
                captions[idea_id] = None

    for i, idea in enumerate(ideas):
        try:
            _send_idea_card(chat_id, idea, captions.get(idea["id"]))
        except Exception as e:
            print(f"[card {idea['id']}] send failed: {e}")
        if i < len(ideas) - 1:
            time.sleep(1)


def _handle_post_tap(chat_id: str, idea_id: str, message_id: str) -> None:
    """Replace the action keyboard with the schedule sub-card."""
    keyboard = cards.schedule_keyboard(idea_id, message_id)
    try:
        _tg("editMessageReplyMarkup", {
            "chat_id": chat_id,
            "message_id": int(message_id),
            "reply_markup": keyboard,
        })
    except Exception as e:
        print(f"post -> schedule edit failed: {e}")


def _handle_back_tap(chat_id: str, idea_id: str, message_id: str) -> None:
    """Restore the Post/Edit/Dismiss keyboard."""
    try:
        _tg("editMessageReplyMarkup", {
            "chat_id": chat_id,
            "message_id": int(message_id),
            "reply_markup": cards.idea_action_keyboard(idea_id, message_id),
        })
    except Exception as e:
        print(f"back edit failed: {e}")


def _handle_schedule_choice(chat_id: str, idea_id: str, message_id: str, slot_key: str) -> None:
    if slot_key == "now":
        fire_at = schedule.slot_now()
    elif slot_key == "7pm":
        fire_at = schedule.slot_tonight_7pm()
    elif slot_key == "9am":
        fire_at = schedule.slot_tomorrow_9am()
    else:
        return

    draft = state.get_draft(message_id) or {}
    post_id = secrets.token_hex(4)
    entry = {
        "post_id": post_id,
        "idea_id": idea_id,
        "chat_id": chat_id,
        "caption": draft.get("caption"),
        "fire_at_iso": fire_at.isoformat(),
        "card_message_id": int(message_id),
        "status": "queued",
    }
    state.queue_append(entry)

    # Clear keyboard on the idea card; reply with confirmation.
    try:
        _tg("editMessageReplyMarkup", {
            "chat_id": chat_id,
            "message_id": int(message_id),
            "reply_markup": {"inline_keyboard": []},
        })
    except Exception:
        pass

    _tg("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"📅 *Queued* `{post_id}`\n"
            f"🕐 Fires at: {schedule.format_sgt(fire_at)}\n"
            f"💡 Idea: {idea_id}\n\n"
            f"_(Image generation + IG publish wire up in Phase 4–6.)_"
        ),
        "parse_mode": "Markdown",
    })


def _handle_edit_tap(chat_id: str, idea_id: str, message_id: str) -> None:
    draft = state.get_draft(message_id) or {}
    current = draft.get("caption") or "_(no draft caption yet)_"
    state.set_pending_edit(chat_id, {
        "message_id": int(message_id),
        "idea_id": idea_id,
    })
    _tg("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"✏️ *Editing caption for {idea_id}*\n\n"
            f"Current draft:\n{current}\n\n"
            f"Reply to this message with the new caption."
        ),
        "parse_mode": "Markdown",
    })


def _handle_test_publish(chat_id: str) -> None:
    """Smoke-test the IG round-trip with 2 public sample JPGs.

    Proves: Telegram -> server -> IG Graph API -> live carousel post on aira.trendcast.
    Uses picsum.photos (no auth, returns a JPG, square crop) as the image source so
    we can prove the publisher works before wiring Nano Banana Pro.
    """
    _tg("sendMessage", {
        "chat_id": chat_id,
        "text": "🧪 *Test publish* — sending 2 placeholder slides to aira.trendcast…",
        "parse_mode": "Markdown",
    })
    # picsum.photos auto-redirects to a real JPG; stable IDs keep the same image each call.
    test_urls = [
        "https://picsum.photos/id/237/1080/1080.jpg",  # slide 1 (dog)
        "https://picsum.photos/id/1015/1080/1080.jpg",  # slide 2 (mountain)
    ]
    caption = (
        "🧪 AIRA Social Media Agent — end-to-end publish test.\n\n"
        "If you can see this on @aira.trendcast, the Telegram → Graph API pipeline works.\n\n"
        "#test #ignore"
    )
    try:
        result = publish_carousel(test_urls, caption)
        _tg("sendMessage", {
            "chat_id": chat_id,
            "text": (
                f"✅ *Published.*\n"
                f"`media_id={result['media_id']}`\n"
                f"🔗 {result['permalink']}"
            ),
            "parse_mode": "Markdown",
        })
    except PublishError as e:
        _tg("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ *Publish failed:*\n```\n{str(e)[:1500]}\n```",
            "parse_mode": "Markdown",
        })
    except Exception as e:
        _tg("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Unexpected error: {e}",
        })


def _handle_dismiss_tap(chat_id: str, message_id: str) -> None:
    try:
        _tg("deleteMessage", {"chat_id": chat_id, "message_id": int(message_id)})
    except Exception as e:
        print(f"dismiss failed: {e}")
    state.remove_draft(message_id)


def _handle_callback_query(cq: dict) -> None:
    callback_query_id = cq["id"]
    from_chat_id = str(cq["from"]["id"])
    data = cq.get("data", "")

    try:
        _tg("answerCallbackQuery", {"callback_query_id": callback_query_id})
    except Exception:
        pass

    if not _is_allowed(from_chat_id):
        return

    parts = data.split("|")
    if len(parts) != 3:
        return
    action, idea_id, message_id = parts

    if action == "post":
        _handle_post_tap(from_chat_id, idea_id, message_id)
    elif action == "back":
        _handle_back_tap(from_chat_id, idea_id, message_id)
    elif action == "sched_now":
        _handle_schedule_choice(from_chat_id, idea_id, message_id, "now")
    elif action == "sched_7pm":
        _handle_schedule_choice(from_chat_id, idea_id, message_id, "7pm")
    elif action == "sched_9am":
        _handle_schedule_choice(from_chat_id, idea_id, message_id, "9am")
    elif action == "edit":
        _handle_edit_tap(from_chat_id, idea_id, message_id)
    elif action == "dismiss":
        _handle_dismiss_tap(from_chat_id, message_id)


def _handle_message(msg: dict) -> None:
    chat_id = str(msg["chat"]["id"])
    text = (msg.get("text") or "").strip()

    # Pending-edit reply takes precedence (allowlist still enforced — only owners can leave drafts).
    pending = state.get_pending_edit(chat_id)
    if pending and text and _is_allowed(chat_id):
        message_id = pending["message_id"]
        idea_id = pending["idea_id"]
        state.update_draft_caption(message_id, text)

        trends = cards.load_trends()
        idea = next((i for i in trends["ideas"] if i["id"] == idea_id), None)
        if idea:
            new_text = cards.build_card_text(idea, caption=text)
            try:
                _tg("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": new_text,
                    "parse_mode": "Markdown",
                    "reply_markup": cards.idea_action_keyboard(idea_id, message_id),
                })
            except Exception as e:
                print(f"edit apply failed: {e}")
        _tg("sendMessage", {"chat_id": chat_id, "text": "✓ Caption updated."})
        return

    if not _is_allowed(chat_id):
        return

    lower = text.lower()
    if lower in ("/start", "start"):
        _fire_all_ideas(chat_id)
    elif lower in ("/status", "status"):
        q = state.queue_load()
        posted = state.posts_log_load()
        _tg("sendMessage", {
            "chat_id": chat_id,
            "text": f"📊 Queue: {len(q)} pending\n✅ Posted: {len(posted)}",
        })
    elif lower in ("/test_publish", "test_publish"):
        _handle_test_publish(chat_id)
    elif lower in ("/help", "help"):
        _tg("sendMessage", {
            "chat_id": chat_id,
            "text": (
                "Commands:\n"
                "/start — fire 5 idea cards\n"
                "/status — queue + posted counts\n"
                "/test_publish — IG smoke test (2 placeholder slides)\n"
                "/help — this message"
            ),
        })


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(fmt % args)

    def _send_json(self, status: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: str, content_type: str):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            self._send_json(404, {"error": "not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "service": "aira-social-media-agent"})
        elif self.path == "/status":
            self._send_json(200, {
                "queue": state.queue_load(),
                "posted": state.posts_log_load(),
            })
        elif self.path.startswith("/media/"):
            # /media/<post_id>/<n>.jpg — only allow simple [a-f0-9]+/[0-9]+.jpg shapes
            rest = self.path[len("/media/"):]
            parts = rest.split("/")
            if len(parts) != 2 or not parts[0].isalnum() or not parts[1].endswith(".jpg"):
                self._send_json(404, {"error": "not found"})
                return
            safe_path = os.path.join(MEDIA_ROOT, parts[0], parts[1])
            self._send_file(safe_path, "image/jpeg")
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/telegram/callback":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                update = json.loads(raw)
                if "callback_query" in update:
                    _handle_callback_query(update["callback_query"])
                elif "message" in update:
                    _handle_message(update["message"])
            except Exception as e:
                print(f"update handling error: {e}")
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"AIRA Social Media Agent listening on 0.0.0.0:{port}")
    print(f"  Allowed chat IDs: {TELEGRAM_CHAT_IDS}")
    print(f"  Public base URL:  {PUBLIC_BASE_URL or '(unset)'}")
    server.serve_forever()
