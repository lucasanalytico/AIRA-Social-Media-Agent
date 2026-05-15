"""Caption provider — reads pre-written copy from data/trends.json.

For MVP / demo: deterministic. Every idea ships with a hand-edited caption +
hashtags string. Zero LLM calls, zero quota risk, zero API outage risk during
the live demo. The brand voice is locked at the data layer.

V2 plan (see CLAUDE.md): re-enable Gemini 2.5 Flash generation with the
ANALYTICO_BRAND_CONTEXT prompt from src/prompts.py, falling back to the
pre-written copy on quota error. The public signature here is intentionally
identical to the LLM version so the swap is a one-file change.
"""
from src import cards


class _MissingIdea(Exception):
    pass


def _find_idea(idea: dict) -> dict:
    """Look up the full idea record from trends.json (which has the caption fields)."""
    trends = cards.load_trends()
    for stored in trends["ideas"]:
        if stored["id"] == idea["id"]:
            return stored
    raise _MissingIdea(f"idea_id {idea.get('id')} not in trends.json")


def generate_caption(idea: dict) -> dict:
    """Return {'caption': str, 'hashtags': str} for one idea.

    Reads pre-written content from data/trends.json. Drop-in compatible with the
    earlier LLM version — same return shape, same caller expectations.
    """
    stored = _find_idea(idea)
    return {
        "caption": (stored.get("caption") or "").strip(),
        "hashtags": (stored.get("hashtags") or "").strip(),
    }


def compose_ig_caption(parts: dict) -> str:
    """Combine caption + hashtags for the IG post (clipped at 2200 chars, IG's max)."""
    caption = parts.get("caption", "").strip()
    hashtags = parts.get("hashtags", "").strip()
    if hashtags:
        return f"{caption}\n\n{hashtags}"[:2200]
    return caption[:2200]
