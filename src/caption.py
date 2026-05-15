"""Gemini 2.5 Flash caption generation for Analytico Training Academy carousel ideas.

Uses the new google-genai SDK (the old google.generativeai package is deprecated).
Returns {"caption": str, "hashtags": str}. Fails loud — caller decides whether
to fall back to a placeholder so the Telegram card flow still works.
"""
import json
import os
import re

from google import genai
from google.genai import types

from src.prompts import CAPTION_SYSTEM_INSTRUCTION, build_caption_prompt

_MODEL_NAME = os.getenv("GEMINI_CAPTION_MODEL", "gemini-2.5-flash")
_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is not None:
        return _client
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY not set in environment")
    _client = genai.Client(api_key=key)
    return _client


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.+?)\s*```$", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text


def generate_caption(idea: dict) -> dict:
    """Return {'caption': str, 'hashtags': str} for one idea.

    Raises RuntimeError on Gemini API failure or malformed response.
    """
    client = _get_client()
    config = types.GenerateContentConfig(
        system_instruction=CAPTION_SYSTEM_INSTRUCTION,
        temperature=0.85,
        top_p=0.95,
        max_output_tokens=2048,
        response_mime_type="application/json",
    )
    prompt = build_caption_prompt(idea)
    resp = client.models.generate_content(
        model=_MODEL_NAME,
        contents=prompt,
        config=config,
    )
    raw = (resp.text or "").strip()
    if not raw:
        raise RuntimeError(f"empty Gemini response for idea {idea.get('id')}")
    cleaned = _strip_json_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini returned non-JSON for {idea.get('id')}: {cleaned[:200]}") from e

    caption = (data.get("caption") or "").strip()
    hashtags = (data.get("hashtags") or "").strip()
    if not caption:
        raise RuntimeError(f"Gemini response missing 'caption' for {idea.get('id')}")
    return {"caption": caption, "hashtags": hashtags}


def compose_ig_caption(parts: dict) -> str:
    """Combine caption + hashtags for the actual IG post (within 2200 chars)."""
    caption = parts.get("caption", "").strip()
    hashtags = parts.get("hashtags", "").strip()
    if hashtags:
        return f"{caption}\n\n{hashtags}"[:2200]
    return caption[:2200]
