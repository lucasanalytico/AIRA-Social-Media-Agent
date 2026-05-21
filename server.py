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
import re
import secrets
import time

_SAFE_POST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer

# In-memory dedupe of Telegram update_ids. Telegram retries deliveries on cold
# starts / >60s response times — without dedupe each retry would re-fire /start
# and burn another batch of 5 slide renders + sendPhoto calls. 512 IDs is plenty
# of headroom (Telegram caps retries at ~24h; even a chatty operator session
# stays well under that).
_SEEN_UPDATES: deque = deque(maxlen=512)
_SEEN_LOCK = threading.Lock()


def _already_seen(update_id: int | None) -> bool:
    """True if we've processed this update_id before. Updates the recent-set as a side effect."""
    if update_id is None:
        return False
    with _SEEN_LOCK:
        if update_id in _SEEN_UPDATES:
            return True
        _SEEN_UPDATES.append(update_id)
        return False

import requests

from src import cards, schedule, state
from src.caption import generate_caption
from src.images import generate_slide1
from src.publisher import PublishError, publish_carousel
from src.scheduler import start_scheduler


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


def _tg_send_photo(chat_id: str, photo_path: str, caption: str, parse_mode: str = "Markdown") -> dict:
    """sendPhoto with a local file as multipart upload.

    Returns the parsed Telegram response. Raises on HTTP error so callers can
    fall back to a text-only sendMessage.
    """
    with open(photo_path, "rb") as f:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
            data={
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": parse_mode,
            },
            files={"photo": (os.path.basename(photo_path), f, "image/jpeg")},
            timeout=30,
        )
    resp.raise_for_status()
    return resp.json()


def _is_allowed(chat_id: str) -> bool:
    return chat_id in TELEGRAM_CHAT_IDS


def _send_idea_card(
    chat_id: str,
    idea: dict,
    caption_parts: dict | None,
    slide1_path: str | None = None,
    post_id: str | None = None,
) -> None:
    """Send one idea card with action buttons.

    caption_parts is {'caption': str, 'hashtags': str} from Gemini, or None on failure.
    slide1_path is a local JPG path. When present, the card is sent as a sendPhoto
    so the operator can see the rendered hook before tapping Post. Falls back to
    text-only sendMessage on any render/upload failure so a single bad slide
    doesn't drop the whole card.
    post_id is pre-allocated at /start time so the slide-1 JPG is already keyed
    by it; the same id flows through to the schedule entry — no rename later.
    """
    caption_text = caption_parts["caption"] if caption_parts else None
    text = cards.build_card_text(idea, caption=caption_text, source=idea.get("source"))
    has_photo = False

    if slide1_path and os.path.exists(slide1_path):
        try:
            resp = _tg_send_photo(chat_id, slide1_path, caption=text)
            has_photo = True
        except Exception as e:
            print(f"[card {idea['id']}] sendPhoto failed, falling back to text: {e}")
            resp = _tg("sendMessage", {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            })
    else:
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
        "has_photo": has_photo,
        "post_id": post_id,
    })


def _fire_all_ideas(chat_id: str) -> None:
    trends = cards.load_trends()
    trend = trends["active_trend"]
    _tg("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"✨ *This week's trend:* {trend['name']}\n"
            f"_{trend['description']}_\n\n"
            f"Here are 5 content ideas ready to post:"
        ),
        "parse_mode": "Markdown",
    })

    ideas = trends["ideas"]
    # Stable post_id per idea — slides render under this path now, and the
    # same id is reused when the operator taps Post -> schedule slot.
    post_ids: dict[str, str] = {idea["id"]: secrets.token_hex(4) for idea in ideas}

    # Captions: pre-written in trends.json today; this still works if generate_caption
    # is swapped back to a live LLM call in v2.
    captions: dict[str, dict | None] = {}
    # Slide-1 JPGs rendered ahead of time so the operator sees the hook in Telegram.
    slide1_paths: dict[str, str | None] = {}

    def _render_one(idea: dict) -> tuple[str, str]:
        """Worker: return (idea_id, path-as-str) — strings are picklable + path-safe."""
        path = generate_slide1(idea, post_ids[idea["id"]], trends_meta=trend)
        return idea["id"], str(path)

    # Captions are cheap (pre-written); fire them sequentially, no pool needed.
    for idea in ideas:
        try:
            captions[idea["id"]] = generate_caption(idea)
        except Exception as e:
            print(f"[caption {idea['id']}] failed: {e}")
            captions[idea["id"]] = None

    # Slide-1 renders are the expensive part (~3s each, Playwright launches a Chromium).
    # max_workers=3 caps memory on Render's 512 MB free tier; 5 parallel Chromiums OOMs.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_render_one, idea): idea["id"] for idea in ideas}
        for fut in futures:
            idea_id = futures[fut]
            try:
                _, path = fut.result(timeout=60)
                slide1_paths[idea_id] = path
            except Exception as e:
                print(f"[slide1 {idea_id}] failed: {e}")
                slide1_paths[idea_id] = None

    for i, idea in enumerate(ideas):
        try:
            _send_idea_card(
                chat_id,
                idea,
                captions.get(idea["id"]),
                slide1_path=slide1_paths.get(idea["id"]),
                post_id=post_ids[idea["id"]],
            )
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
    # Reuse the eager post_id allocated at /start so the slide-1 JPG already
    # on disk under media/<post_id>/1.jpg flows through to the IG publish step
    # without copy/rename. Fallback to a fresh id if draft is missing one.
    post_id = draft.get("post_id") or secrets.token_hex(4)
    entry = {
        "post_id": post_id,
        "idea_id": idea_id,
        "chat_id": chat_id,
        "caption": draft.get("caption"),
        "hashtags": draft.get("hashtags"),
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

    # Resolve idea title for the confirmation message (post_id stays hidden — internal only).
    trends = cards.load_trends()
    idea_obj = next((i for i in trends["ideas"] if i["id"] == idea_id), None)
    idea_title = idea_obj["title"] if idea_obj else idea_id

    _tg("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"📅 *Queued: {idea_title}*\n"
            f"🕐 Fires at: {schedule.format_sgt(fire_at)}\n\n"
            f"_The scheduler will render slides + publish to Instagram automatically._"
        ),
        "parse_mode": "Markdown",
    })


def _handle_edit_tap(chat_id: str, idea_id: str, message_id: str) -> None:
    draft = state.get_draft(message_id) or {}
    current = draft.get("caption") or "_(no draft caption yet)_"
    trends = cards.load_trends()
    idea = next((i for i in trends["ideas"] if i["id"] == idea_id), None)
    idea_title = idea["title"] if idea else idea_id
    state.set_pending_edit(chat_id, {
        "message_id": int(message_id),
        "idea_id": idea_id,
    })
    _tg("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"✏️ *Editing: {idea_title}*\n\n"
            f"Current draft:\n{current}\n\n"
            f"Reply with the new caption."
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
            new_text = cards.build_card_text(idea, caption=text, source=idea.get("source"))
            # Photo cards (sendPhoto) require editMessageCaption, not editMessageText —
            # Telegram returns 400 if you mix them.
            draft = state.get_draft(message_id) or {}
            method = "editMessageCaption" if draft.get("has_photo") else "editMessageText"
            payload = {
                "chat_id": chat_id,
                "message_id": message_id,
                "parse_mode": "Markdown",
                "reply_markup": cards.idea_action_keyboard(idea_id, message_id),
            }
            if draft.get("has_photo"):
                payload["caption"] = new_text
            else:
                payload["text"] = new_text
            try:
                _tg(method, payload)
            except Exception as e:
                print(f"edit apply failed ({method}): {e}")
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
            # /media/<post_id>/<n>.jpg — allow alphanumeric + underscore/hyphen
            rest = self.path[len("/media/"):]
            parts = rest.split("/")
            if (
                len(parts) != 2
                or not _SAFE_POST_ID.match(parts[0])
                or not parts[1].endswith(".jpg")
                or not parts[1][:-4].isdigit()
            ):
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
            update: dict = {}
            try:
                update = json.loads(raw)
            except Exception as e:
                print(f"webhook parse error: {e}")
                self._send_json(200, {"ok": True})
                return

            # Always ack 200 immediately — work runs in a background thread so
            # Telegram never times out waiting for slide rendering or IG calls.
            # Without this, a cold-start /start (slide-1 renders take ~12s warm
            # but the cold container can sit silent for 30-90s before Python
            # boots) makes Telegram retry, which would fire /start again.
            self._send_json(200, {"ok": True})

            update_id = update.get("update_id")
            if _already_seen(update_id):
                # Telegram retried a delivery we already processed. Silently drop.
                print(f"dropped duplicate update_id={update_id}")
                return

            def _process():
                try:
                    if "callback_query" in update:
                        _handle_callback_query(update["callback_query"])
                    elif "message" in update:
                        _handle_message(update["message"])
                except Exception as e:
                    print(f"update handling error (update_id={update_id}): {e}")

            threading.Thread(target=_process, daemon=True).start()
        else:
            self._send_json(404, {"error": "not found"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"AIRA Social Media Agent listening on 0.0.0.0:{port}")
    print(f"  Allowed chat IDs: {TELEGRAM_CHAT_IDS}")
    print(f"  Public base URL:  {PUBLIC_BASE_URL or '(unset)'}")
    start_scheduler(_tg)
    server.serve_forever()
