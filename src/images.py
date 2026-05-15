"""Nano Banana Pro (Gemini 3 Pro Image) slide generation.

Generates the 2-slide Swipe-to-Reveal carousel for one idea:
  slide 1 = hook (the curiosity-gap question)
  slide 2 = reveal (the payoff)

Files written to:  <repo>/media/<post_id>/1.jpg  and  .../2.jpg
Served by server.py at GET /media/<post_id>/<n>.jpg — Instagram Graph API
fetches them from there.

IG carousel media constraints (validated at save time):
  - JPG (not PNG)
  - 1:1 or 4:5 aspect — we generate 1:1 (1024x1024)
  - <= 8 MB per image
  - >= 320 px wide
"""
import io
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image as PILImage

from src.prompts import build_slide1_image_prompt, build_slide2_image_prompt


_MODEL_NAME = os.getenv("NANO_BANANA_MODEL", "gemini-3-pro-image-preview")
_RESOLUTION = "1K"  # 1024x1024 — square, fits IG carousel constraint
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


def _media_root() -> Path:
    """Repo-relative media/ dir. Created on first use."""
    root = Path(__file__).resolve().parent.parent / "media"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _generate_one_slide(prompt: str, out_path: Path) -> Path:
    """Call Nano Banana Pro for one image, save as JPG (Instagram-ready)."""
    client = _get_client()
    response = client.models.generate_content(
        model=_MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(image_size=_RESOLUTION),
        ),
    )
    img_bytes: bytes | None = None
    for part in response.parts:
        inline = getattr(part, "inline_data", None)
        if inline is None or inline.data is None:
            continue
        data = inline.data
        if isinstance(data, str):
            import base64
            data = base64.b64decode(data)
        img_bytes = data
        break
    if img_bytes is None:
        raise RuntimeError(f"No image part in Nano Banana Pro response for {out_path.name}")

    img = PILImage.open(io.BytesIO(img_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # quality=92 — IG re-compresses anyway; under 8MB easily at 1024x1024.
    img.save(out_path, format="JPEG", quality=92, optimize=True)
    return out_path


def generate_slides(idea: dict, post_id: str) -> list[Path]:
    """Generate both slides for one idea, in parallel.

    Returns absolute paths [slide1_path, slide2_path].
    Raises if either slide fails (carousel needs both).
    """
    root = _media_root() / post_id
    targets = [
        (build_slide1_image_prompt(idea), root / "1.jpg"),
        (build_slide2_image_prompt(idea), root / "2.jpg"),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_generate_one_slide, p, op) for p, op in targets]
        results = [f.result(timeout=180) for f in futures]
    return results


def public_urls_for(post_id: str, base_url: str) -> list[str]:
    """Return [slide1_url, slide2_url] using the public-facing base URL.

    Instagram Graph API will fetch these directly, so base_url must be reachable
    from Meta's servers (Render deploy URL or ngrok HTTPS in dev).
    """
    base = base_url.rstrip("/")
    return [f"{base}/media/{post_id}/1.jpg", f"{base}/media/{post_id}/2.jpg"]
