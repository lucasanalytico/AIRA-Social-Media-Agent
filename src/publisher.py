"""Instagram Graph API publisher for 2-slide Swipe-to-Reveal carousels.

Publish flow (3 calls):
  1. For each slide JPG URL: POST /{ig_user_id}/media with is_carousel_item=true
     → returns child container id
  2. POST /{ig_user_id}/media with media_type=CAROUSEL, children=<ids>, caption=<text>
     → returns parent container id
  3. POST /{ig_user_id}/media_publish with creation_id=<parent_id>
     → returns published media id (and we fetch its permalink)

Requires env: IG_USER_ID, IG_ACCESS_TOKEN, IG_GRAPH_VERSION (default v23.0).
"""
import os
import time

import requests


class PublishError(RuntimeError):
    pass


def _base_url() -> str:
    version = os.getenv("IG_GRAPH_VERSION", "v23.0")
    return f"https://graph.facebook.com/{version}"


def _ig_user_id() -> str:
    uid = os.getenv("IG_USER_ID")
    if not uid:
        raise PublishError("IG_USER_ID not set")
    return uid


def _token() -> str:
    tok = os.getenv("IG_ACCESS_TOKEN")
    if not tok:
        raise PublishError("IG_ACCESS_TOKEN not set")
    return tok


def _post(path: str, payload: dict) -> dict:
    """POST to Graph API and raise PublishError with the FB error body on failure."""
    url = f"{_base_url()}/{path.lstrip('/')}"
    resp = requests.post(url, data={**payload, "access_token": _token()}, timeout=30)
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}
    if not resp.ok or "error" in body:
        raise PublishError(f"POST {path} failed: {resp.status_code} {body}")
    return body


def _get(path: str, params: dict | None = None) -> dict:
    url = f"{_base_url()}/{path.lstrip('/')}"
    p = {**(params or {}), "access_token": _token()}
    resp = requests.get(url, params=p, timeout=30)
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}
    if not resp.ok or "error" in body:
        raise PublishError(f"GET {path} failed: {resp.status_code} {body}")
    return body


def _create_child_container(image_url: str) -> str:
    body = _post(f"/{_ig_user_id()}/media", {
        "image_url": image_url,
        "is_carousel_item": "true",
    })
    cid = body.get("id")
    if not cid:
        raise PublishError(f"no child container id returned: {body}")
    return cid


def _create_carousel_container(child_ids: list[str], caption: str) -> str:
    body = _post(f"/{_ig_user_id()}/media", {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "caption": caption,
    })
    cid = body.get("id")
    if not cid:
        raise PublishError(f"no parent container id returned: {body}")
    return cid


def _wait_for_container_ready(container_id: str, max_wait_s: int = 60) -> None:
    """IG containers can take a few seconds to become FINISHED. Poll status_code."""
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        body = _get(f"/{container_id}", {"fields": "status_code"})
        status = body.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise PublishError(f"container {container_id} entered ERROR state: {body}")
        time.sleep(2)
    raise PublishError(f"container {container_id} not FINISHED within {max_wait_s}s")


def _publish(container_id: str) -> str:
    body = _post(f"/{_ig_user_id()}/media_publish", {"creation_id": container_id})
    mid = body.get("id")
    if not mid:
        raise PublishError(f"no media id returned from publish: {body}")
    return mid


def _fetch_permalink(media_id: str) -> str:
    body = _get(f"/{media_id}", {"fields": "permalink"})
    return body.get("permalink") or f"(no permalink, media_id={media_id})"


def publish_carousel(image_urls: list[str], caption: str) -> dict:
    """End-to-end publish. Returns {'media_id', 'permalink'}.

    Raises PublishError if any step fails.
    """
    if len(image_urls) < 2:
        raise PublishError("Instagram carousels need at least 2 images")
    if len(image_urls) > 10:
        raise PublishError("Instagram carousels max 10 images")

    child_ids = [_create_child_container(url) for url in image_urls]
    parent_id = _create_carousel_container(child_ids, caption)
    _wait_for_container_ready(parent_id)
    media_id = _publish(parent_id)
    permalink = _fetch_permalink(media_id)
    return {"media_id": media_id, "permalink": permalink}
