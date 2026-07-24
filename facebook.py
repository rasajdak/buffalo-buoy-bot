"""Facebook Graph API posting (photo, video, text). Honors DRY_RUN."""

from __future__ import annotations

from pathlib import Path

import requests

import config
import notify

GRAPH = "https://graph.facebook.com"
GRAPH_VIDEO = "https://graph-video.facebook.com"

# Alert key shared with main.py: a successful publish clears it, a fatal one raises it.
PUBLISH_BLOCKED = "publish_blocked"


class GraphError(RuntimeError):
    """A Graph API failure that carries the parsed error code/subcode so callers
    can distinguish a needs-a-human block (368 checkpoint, 190 dead token) from a
    transient hiccup."""

    def __init__(self, status: int, error) -> None:
        err = error if isinstance(error, dict) else {}
        self.status = status
        self.code = err.get("code")
        self.subcode = err.get("error_subcode")
        self.fb_message = err.get("message", "") if err else str(error)
        super().__init__(f"Graph API error {status}: {error}")


def _dry(kind: str, message: str, media: Path | None) -> dict:
    print("\n" + "=" * 64)
    print(f"[DRY RUN] would post {kind.upper()} to page {config.FB_PAGE_ID or '(unset)'}")
    if media:
        print(f"media: {media} ({media.stat().st_size} bytes)" if media.exists() else f"media: {media}")
    print("-" * 64)
    print(message)
    print("=" * 64 + "\n")
    return {"dry_run": True, "kind": kind}


def _check(r: requests.Response) -> dict:
    data = r.json()
    if r.status_code >= 400 or "error" in data:
        raise GraphError(r.status_code, data.get("error", data))
    notify.clear(PUBLISH_BLOCKED)  # a real publish went through — we're not blocked
    return data


def post_text(message: str) -> dict:
    if config.DRY_RUN:
        return _dry("text", message, None)
    r = requests.post(
        f"{GRAPH}/{config.GRAPH_VERSION}/{config.FB_PAGE_ID}/feed",
        data={"message": message, "access_token": config.FB_PAGE_TOKEN},
        timeout=60,
    )
    return _check(r)


def post_photo(image_path: Path, message: str) -> dict:
    image_path = Path(image_path)
    if config.DRY_RUN:
        return _dry("photo", message, image_path)
    with open(image_path, "rb") as f:
        r = requests.post(
            f"{GRAPH}/{config.GRAPH_VERSION}/{config.FB_PAGE_ID}/photos",
            data={"message": message, "access_token": config.FB_PAGE_TOKEN},
            files={"source": f},
            timeout=120,
        )
    return _check(r)


def post_video(video_path: Path, description: str, title: str | None = None) -> dict:
    video_path = Path(video_path)
    if config.DRY_RUN:
        return _dry("video", description, video_path)
    data = {"description": description, "access_token": config.FB_PAGE_TOKEN}
    if title:
        data["title"] = title
    with open(video_path, "rb") as f:
        r = requests.post(
            f"{GRAPH_VIDEO}/{config.GRAPH_VERSION}/{config.FB_PAGE_ID}/videos",
            data=data,
            files={"source": f},
            timeout=300,
        )
    return _check(r)
