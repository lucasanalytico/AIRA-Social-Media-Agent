"""JSON-file persistence with a process-wide lock.

Mirrors ClientPulse's sent_log pattern. All state lives in the repo root
so a Render redeploy preserves it (Render's free disk is ephemeral on
restart — flag if this becomes a problem for queue.json).
"""
import json
import os
import threading
from typing import Any

_LOCK = threading.Lock()
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(name: str) -> str:
    return os.path.join(_ROOT, name)


def _load(name: str, default: Any) -> Any:
    try:
        with open(_path(name)) as f:
            return json.load(f)
    except Exception:
        return default


def _save(name: str, data: Any) -> None:
    with open(_path(name), "w") as f:
        json.dump(data, f, indent=2)


# Idea drafts: {message_id: {idea_id, caption, chat_id}}
# Held in memory only — drafts are short-lived between /start and Post/Edit/Dismiss.
_drafts: dict[str, dict] = {}

# Pending edit replies: {chat_id: {message_id, idea_id}}
_pending_edits: dict[str, dict] = {}

# Pending schedule choice: {message_id: {idea_id, chat_id, original_message_id}}
_pending_schedules: dict[str, dict] = {}


def get_draft(message_id: str | int) -> dict | None:
    with _LOCK:
        return _drafts.get(str(message_id))


def set_draft(message_id: str | int, draft: dict) -> None:
    with _LOCK:
        _drafts[str(message_id)] = draft


def update_draft_caption(message_id: str | int, caption: str) -> dict | None:
    with _LOCK:
        d = _drafts.get(str(message_id))
        if d:
            d["caption"] = caption
        return d


def remove_draft(message_id: str | int) -> None:
    with _LOCK:
        _drafts.pop(str(message_id), None)


def get_pending_edit(chat_id: str) -> dict | None:
    with _LOCK:
        return _pending_edits.pop(chat_id, None)


def set_pending_edit(chat_id: str, payload: dict) -> None:
    with _LOCK:
        _pending_edits[chat_id] = payload


def queue_load() -> list:
    with _LOCK:
        return _load("queue.json", [])


def queue_append(entry: dict) -> None:
    with _LOCK:
        q = _load("queue.json", [])
        q.append(entry)
        _save("queue.json", q)


def queue_replace(entries: list) -> None:
    with _LOCK:
        _save("queue.json", entries)


def posts_log_load() -> dict:
    with _LOCK:
        return _load("posts_log.json", {})


def posts_log_set(post_id: str, value: dict) -> None:
    with _LOCK:
        log = _load("posts_log.json", {})
        log[post_id] = value
        _save("posts_log.json", log)
