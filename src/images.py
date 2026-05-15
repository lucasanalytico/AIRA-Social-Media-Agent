"""Slide renderer — HTML + CSS via Jinja2, screenshot via Playwright.

Replaces the original Nano Banana Pro path because image-gen APIs are paid-only.
Public surface (called from server.py / publisher.py) is unchanged:
    generate_slides(idea, post_id) -> [Path, Path]
    public_urls_for(post_id, base_url) -> [str, str]

Generates 1080x1080 JPGs at:
    <repo>/media/<post_id>/1.jpg     (hook)
    <repo>/media/<post_id>/2.jpg     (reveal)

For slide 2 we use Gemini 2.5 Flash (text, free) to turn the idea's free-form
`slide2_reveal` line into a short headline + 2-3 bullet stat rows. Keeps the
on-brand structured layout without hardcoding per-idea copy.
"""
from __future__ import annotations

import io
import json
import os
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image as PILImage
from playwright.sync_api import sync_playwright

from google import genai
from google.genai import types


_REPO = Path(__file__).resolve().parent.parent
_TEMPLATE_DIR = _REPO / "renderer" / "templates"
_MEDIA_DIR = _REPO / "media"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)

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


# ---- slide-2 structurer (free Gemini Flash text call) ------------------------

_STRUCTURE_PROMPT = """
You are turning a free-form Instagram Swipe-to-Reveal idea into structured slide content
for **Analytico Training Academy** (Singapore training provider partnered with General Assembly).

Given the idea below, return JSON with:
  - "headline": 4-9 words. The REVEAL — the payoff for the swipe. Punchy, declarative.
                Never invent specific numbers. If the idea references stats, use phrases like
                "Based on MOM data" or "From GA outcomes" without hard figures.
  - "stats": list of EXACTLY 3 short bullet rows, each 4-10 words. Concrete, specific to
             Singapore where possible. Use <strong>...</strong> around 1-3 key words per row
             for emphasis. No emojis. No hashtags.
  - "cta": one short CTA line, 4-10 words. Imperative ("Apply now", "DM us SALARY", etc).

Return JSON ONLY, no markdown fences.
""".strip()


def _strip_fence(text: str) -> str:
    text = (text or "").strip()
    m = re.match(r"^```(?:json)?\s*(.+?)\s*```$", text, re.DOTALL)
    return m.group(1).strip() if m else text


def _structure_slide2(idea: dict) -> dict:
    """Return {'headline', 'stats': [str,str,str], 'cta'} for the reveal slide."""
    user_prompt = (
        f"Idea title: {idea['title']}\n"
        f"Slide 1 hook: {idea['slide1_hook']}\n"
        f"Slide 2 reveal (free text): {idea['slide2_reveal']}\n"
        f"Course angle: {idea['course_angle']}\n"
        f"Suggested CTA: {idea['cta']}\n\n"
        f"Return JSON only."
    )
    model_name = os.getenv("GEMINI_CAPTION_MODEL", "gemini-2.5-flash")
    resp = _get_client().models.generate_content(
        model=model_name,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=_STRUCTURE_PROMPT,
            temperature=0.7,
            top_p=0.9,
            max_output_tokens=2048,
            response_mime_type="application/json",
        ),
    )
    raw = _strip_fence(resp.text or "")
    if not raw:
        raise RuntimeError(f"empty structure response for {idea.get('id')}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"structure JSON parse failed for {idea.get('id')}: {raw[:200]}") from e

    headline = (data.get("headline") or "").strip()
    stats = data.get("stats") or []
    cta = (data.get("cta") or "").strip()
    if not headline or len(stats) < 2:
        raise RuntimeError(f"structure response incomplete for {idea.get('id')}: {data}")
    # Normalize to exactly 3 stat rows.
    stats = [str(s).strip() for s in stats if str(s).strip()][:3]
    while len(stats) < 3:
        stats.append("")
    return {"headline": headline, "stats": stats, "cta": cta}


# ---- HTML -> JPG pipeline ----------------------------------------------------

# Strip any trailing punctuation so the template can append its own accent "?".
_TRAILING_PUNCT = re.compile(r"[?!.\s]+$")


def _render_slide_html(template_name: str, ctx: dict) -> str:
    tmpl = _env.get_template(template_name)
    return tmpl.render(**ctx)


def _html_to_jpg(html: str, out_path: Path) -> None:
    """Render HTML in headless Chromium, screenshot 1080x1080, save as JPG."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    png_bytes: bytes = b""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(
                viewport={"width": 1080, "height": 1080},
                device_scale_factor=1,
            )
            page = ctx.new_page()
            page.set_content(html, wait_until="networkidle")
            # Small extra wait for web fonts to settle.
            page.wait_for_timeout(400)
            png_bytes = page.screenshot(
                type="png",
                clip={"x": 0, "y": 0, "width": 1080, "height": 1080},
            )
        finally:
            browser.close()

    img = PILImage.open(io.BytesIO(png_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(out_path, format="JPEG", quality=92, optimize=True)


def generate_slides(idea: dict, post_id: str, trends_meta: dict | None = None) -> list[Path]:
    """Render 2 branded slide JPGs for one idea.

    trends_meta: optional dict with 'name' for the small top-bar trend label.
                 Defaults to 'SWIPE TO REVEAL'.
    """
    root = _MEDIA_DIR / post_id
    trend_name = (trends_meta or {}).get("name", "Swipe to Reveal").upper()

    hook_text = _TRAILING_PUNCT.sub("", idea["slide1_hook"])
    slide1_html = _render_slide_html("slide1_hook.html.j2", {
        "hook_text": hook_text,
        "trend_name": trend_name,
    })

    structured = _structure_slide2(idea)
    slide2_html = _render_slide_html("slide2_reveal.html.j2", {
        "reveal_headline": structured["headline"],
        "stats": structured["stats"],
        "cta": structured["cta"],
    })

    slide1_path = root / "1.jpg"
    slide2_path = root / "2.jpg"
    _html_to_jpg(slide1_html, slide1_path)
    _html_to_jpg(slide2_html, slide2_path)
    return [slide1_path, slide2_path]


def public_urls_for(post_id: str, base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    return [f"{base}/media/{post_id}/1.jpg", f"{base}/media/{post_id}/2.jpg"]
