"""Background scheduler thread.

Polls queue.json every POLL_SECONDS. When an entry's fire_at_iso is <= now (UTC),
dispatch it: generate slides -> publish to IG -> log + remove from queue ->
notify the operator's Telegram chat.

Designed to be started once at server boot:
    start_scheduler(send_telegram=_tg)

The thread is a daemon — process exit kills it. State is durable via state.queue_*.
"""
from __future__ import annotations

import os
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Callable

from src import state
from src.caption import compose_ig_caption
from src.images import generate_slides, public_urls_for
from src.publisher import PublishError, publish_carousel


POLL_SECONDS = int(os.getenv("SCHEDULER_POLL_SECONDS", "20"))
_started = False
_started_lock = threading.Lock()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _due(entry: dict) -> bool:
    try:
        fire_at = datetime.fromisoformat(entry["fire_at_iso"])
    except Exception:
        return False
    if fire_at.tzinfo is None:
        fire_at = fire_at.replace(tzinfo=timezone.utc)
    return fire_at <= _now_utc()


def _load_idea(idea_id: str) -> dict | None:
    from src import cards
    trends = cards.load_trends()
    return next((i for i in trends["ideas"] if i["id"] == idea_id), None)


def _dispatch(entry: dict, send_telegram: Callable[[str, dict], dict]) -> None:
    """Run one queued post end-to-end. Notify on success or failure."""
    post_id = entry["post_id"]
    chat_id = entry["chat_id"]
    idea_id = entry["idea_id"]

    base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if not base_url:
        raise PublishError("PUBLIC_BASE_URL not set — cannot host slides for IG fetch")

    idea = _load_idea(idea_id)
    if idea is None:
        raise PublishError(f"idea_id {idea_id} not found in trends.json")

    idea_title = idea.get("title") or idea_id

    # 1. Render slides (~10-15s).
    send_telegram("sendMessage", {
        "chat_id": chat_id,
        "text": f"🎨 Rendering slides for *{idea_title}*…",
        "parse_mode": "Markdown",
    })
    generate_slides(idea, post_id)
    image_urls = public_urls_for(post_id, base_url)

    # 2. Build caption (draft from queue entry; fall back to trends.json pre-written copy).
    caption_text = (entry.get("caption") or "").strip()
    hashtags = (entry.get("hashtags") or "").strip()
    if not caption_text:
        # Draft was lost (server restart between /start and Post tap). Use pre-written copy.
        caption_text = (idea.get("caption") or "").strip()
        hashtags = hashtags or (idea.get("hashtags") or "").strip()
    ig_caption = compose_ig_caption({"caption": caption_text, "hashtags": hashtags})

    # 3. Publish to IG (~8-15s for container creation + status poll).
    send_telegram("sendMessage", {
        "chat_id": chat_id,
        "text": f"📤 Publishing *{idea_title}* to Instagram…",
        "parse_mode": "Markdown",
    })
    result = publish_carousel(image_urls, ig_caption)

    # 4. Log + notify.
    state.posts_log_set(post_id, {
        "ig_media_id": result["media_id"],
        "ig_permalink": result["permalink"],
        "idea_id": idea_id,
        "idea_title": idea_title,
        "posted_at_utc": _now_utc().isoformat(),
    })
    send_telegram("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"✅ *Posted: {idea_title}*\n"
            f"🔗 {result['permalink']}"
        ),
        "parse_mode": "Markdown",
    })


def _drain_due(send_telegram: Callable[[str, dict], dict]) -> None:
    """Pop and dispatch all due entries. Failed entries are removed and reported
    (no automatic retry — operator decides whether to re-queue).
    """
    queue = state.queue_load()
    if not queue:
        return
    due, remaining = [], []
    for entry in queue:
        (due if _due(entry) else remaining).append(entry)
    if not due:
        return

    # Persist the "not due yet" tail before dispatching so a crash mid-publish
    # doesn't double-fire the next tick.
    state.queue_replace(remaining)

    for entry in due:
        idea = _load_idea(entry.get("idea_id", "")) or {}
        label = idea.get("title") or entry.get("idea_id") or entry.get("post_id")
        try:
            _dispatch(entry, send_telegram)
        except PublishError as e:
            print(f"[scheduler] PublishError on {entry.get('post_id')}: {e}")
            try:
                send_telegram("sendMessage", {
                    "chat_id": entry["chat_id"],
                    "text": (
                        f"❌ *Publish failed: {label}*\n"
                        f"```\n{str(e)[:1500]}\n```"
                    ),
                    "parse_mode": "Markdown",
                })
            except Exception:
                pass
        except Exception as e:
            print(f"[scheduler] unexpected error on {entry.get('post_id')}: {e}")
            traceback.print_exc()
            try:
                send_telegram("sendMessage", {
                    "chat_id": entry["chat_id"],
                    "text": f"❌ Unexpected error firing *{label}*: {e}",
                    "parse_mode": "Markdown",
                })
            except Exception:
                pass


def _loop(send_telegram: Callable[[str, dict], dict]) -> None:
    print(f"[scheduler] thread up — polling every {POLL_SECONDS}s")
    while True:
        try:
            _drain_due(send_telegram)
        except Exception as e:
            print(f"[scheduler] outer loop error: {e}")
            traceback.print_exc()
        time.sleep(POLL_SECONDS)


def start_scheduler(send_telegram: Callable[[str, dict], dict]) -> None:
    """Start the background scheduler thread (idempotent)."""
    global _started
    with _started_lock:
        if _started:
            return
        t = threading.Thread(target=_loop, args=(send_telegram,), daemon=True, name="aira-scheduler")
        t.start()
        _started = True
