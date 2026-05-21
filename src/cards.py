"""Builders for Telegram idea cards and inline keyboards."""
import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_trends() -> dict:
    with open(os.path.join(_ROOT, "data", "trends.json"), encoding="utf-8") as f:
        return json.load(f)


def build_card_text(
    idea: dict,
    caption: str | None = None,
    source: dict | None = None,
) -> str:
    """Card body shown in Telegram before Post/Edit/Dismiss decision.

    `source` is the optional per-idea {label, url, _placeholder?} block from
    data/trends.json. When present, a final 'Inspired by: <label>' line is
    appended as a Markdown link. `_placeholder=True` adds a discreet
    ⚠️ marker so the operator knows the URL is a stand-in until replaced.
    """
    lines = [
        f"💡 *{idea['title']}*",
        "",
        f"🪝 *Hook:* {idea['slide1_hook']}",
        f"🎯 *Reveal:* {idea['slide2_reveal']}",
        f"📚 *Course:* {idea['course_angle']}",
    ]
    if caption:
        caption_lines = caption.splitlines()
        preview = "\n".join(caption_lines[:2])
        if len(caption_lines) > 2:
            preview += "…"
        lines += ["", "✍️ *Draft caption:*", preview]
    if source and source.get("url"):
        label = (source.get("label") or "source").strip()[:80]
        url = source["url"].strip()
        marker = " ⚠️" if source.get("_placeholder") else ""
        lines += ["", f"🔗 *Inspired by:* [{label}]({url}){marker}"]
    return "\n".join(lines)


def idea_action_keyboard(idea_id: str, message_id: int | str) -> dict:
    """Post / Edit / Dismiss row."""
    return {
        "inline_keyboard": [[
            {"text": "📤 Post", "callback_data": f"post|{idea_id}|{message_id}"},
            {"text": "✏️ Edit", "callback_data": f"edit|{idea_id}|{message_id}"},
            {"text": "🗑 Dismiss", "callback_data": f"dismiss|{idea_id}|{message_id}"},
        ]]
    }


def schedule_keyboard(idea_id: str, message_id: int | str) -> dict:
    """Now / Tonight 7pm SGT / Tomorrow 9am SGT row."""
    return {
        "inline_keyboard": [[
            {"text": "🟢 Now", "callback_data": f"sched_now|{idea_id}|{message_id}"},
            {"text": "🌙 Tonight 7pm", "callback_data": f"sched_7pm|{idea_id}|{message_id}"},
            {"text": "☀️ Tmr 9am", "callback_data": f"sched_9am|{idea_id}|{message_id}"},
        ], [
            {"text": "← Back", "callback_data": f"back|{idea_id}|{message_id}"},
        ]]
    }
