"""Facebook Graph API posting (photo, video, text). Honors DRY_RUN."""

from __future__ import annotations

from pathlib import Path

import requests

import config

GRAPH = "https://graph.facebook.com"
GRAPH_VIDEO = "https://graph-video.facebook.com"


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
        raise RuntimeError(f"Graph API error {r.status_code}: {data.get('error', data)}")
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
