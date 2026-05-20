"""Slide renderer — HTML + CSS via Jinja2, screenshot via Playwright.

Public surface (called from server.py / publisher.py):
    generate_slides(idea, post_id) -> [Path, Path]
    public_urls_for(post_id, base_url) -> [str, str]

Generates 1080x1080 JPGs at:
    <repo>/media/<post_id>/1.jpg     (hook)
    <repo>/media/<post_id>/2.jpg     (reveal)

Slide-2 content (headline + 3 stat rows + cta) is read directly from each idea's
`slide2` block in data/trends.json. Zero LLM calls — fully deterministic for the
demo. V2 plan: optionally regenerate slide-2 copy with Gemini at /start time,
falling back to the trends.json defaults on any LLM failure.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image as PILImage
from playwright.sync_api import sync_playwright


_REPO = Path(__file__).resolve().parent.parent
_TEMPLATE_DIR = _REPO / "renderer" / "templates"
_MEDIA_DIR = _REPO / "media"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


# Strip any trailing punctuation so the template can append its own accent "?".
_TRAILING_PUNCT = re.compile(r"[?!.\s]+$")


def _structure_slide2(idea: dict) -> dict:
    """Return {'headline', 'stats': [str,str,str], 'cta'} for the reveal slide.

    Reads pre-written content from data/trends.json's `slide2` field on each idea.
    Falls back to deriving content from the idea's free-form fields if `slide2`
    isn't present (defensive — should always be present in this repo).
    """
    s2 = idea.get("slide2")
    if isinstance(s2, dict):
        stats = [str(x).strip() for x in (s2.get("stats") or []) if str(x).strip()][:3]
        while len(stats) < 3:
            stats.append("")
        return {
            "headline": (s2.get("headline") or "").strip(),
            "stats": stats,
            "cta": (s2.get("cta") or "").strip(),
        }

    # Defensive fallback: derive a reasonable structure from idea fields.
    return {
        "headline": idea.get("slide2_reveal", "").strip() or "The Reveal",
        "stats": [
            idea.get("course_angle", "").strip() or "",
            "",
            "",
        ],
        "cta": idea.get("cta", "").strip(),
    }


# ---- HTML -> JPG pipeline ----------------------------------------------------

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


def generate_slide1(idea: dict, post_id: str, trends_meta: dict | None = None) -> Path:
    """Render the hook (slide 1) only — used by /start so cards can show a preview.

    Skips re-rendering if the JPG already exists. The scheduler reuses the file
    when it fires the post, so the slide is only built once per idea per session.
    """
    out_path = _MEDIA_DIR / post_id / "1.jpg"
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path
    trend_name = (trends_meta or {}).get("name", "Swipe to Reveal").upper()
    hook_text = _TRAILING_PUNCT.sub("", idea["slide1_hook"])
    html = _render_slide_html("slide1_hook.html.j2", {
        "hook_text": hook_text,
        "trend_name": trend_name,
    })
    _html_to_jpg(html, out_path)
    return out_path


def generate_slide2(idea: dict, post_id: str) -> Path:
    """Render the reveal (slide 2). Skips if already on disk."""
    out_path = _MEDIA_DIR / post_id / "2.jpg"
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path
    structured = _structure_slide2(idea)
    html = _render_slide_html("slide2_reveal.html.j2", {
        "reveal_headline": structured["headline"],
        "stats": structured["stats"],
        "cta": structured["cta"],
    })
    _html_to_jpg(html, out_path)
    return out_path


def generate_slides(idea: dict, post_id: str, trends_meta: dict | None = None) -> list[Path]:
    """Render both slides for one idea. Slide 1 may already exist from /start;
    in that case it's reused (no re-render). Slide 2 is rendered fresh."""
    return [
        generate_slide1(idea, post_id, trends_meta=trends_meta),
        generate_slide2(idea, post_id),
    ]


def public_urls_for(post_id: str, base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    return [f"{base}/media/{post_id}/1.jpg", f"{base}/media/{post_id}/2.jpg"]
