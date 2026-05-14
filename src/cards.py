"""Builders for Telegram idea cards and inline keyboards."""
import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_trends() -> dict:
    with open(os.path.join(_ROOT, "data", "trends.json")) as f:
        return json.load(f)


def build_card_text(idea: dict, caption: str | None = None) -> str:
    """Card body shown in Telegram before Post/Edit/Dismiss decision."""
    lines = [
        f"💡 *{idea['title']}*",
        "",
        f"🪝 *Slide 1 (hook):* {idea['slide1_hook']}",
        f"🎯 *Slide 2 (reveal):* {idea['slide2_reveal']}",
        f"📚 *Course angle:* {idea['course_angle']}",
    ]
    if caption:
        lines += ["", "✍️ *Draft caption:*", caption]
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
