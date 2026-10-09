# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""SponsorBlock: skip crowdsourced sponsor/intro/etc. segments in YouTube videos.

GUI-free. Lookups use the privacy-preserving hash-prefix endpoint, so the
service only learns the first four hex digits of SHA-256(video id), never
which video is playing. Segment data is volunteer-submitted and the service
is sometimes down: every failure returns no segments and playback carries on.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict

from core import utils
from core.youtube_fulltext import video_id_from_url

LOG = logging.getLogger(__name__)

API_URL = "https://sponsor.ajay.app/api/skipSegments/{prefix}"

# category id -> English label (msgid; the GUI wraps it with _()).
CATEGORIES: OrderedDict[str, str] = OrderedDict(
    (
        ("sponsor", "Sponsor"),
        ("selfpromo", "Unpaid or self promotion"),
        ("interaction", "Interaction reminder (subscribe)"),
        ("intro", "Intermission or intro animation"),
        ("outro", "Endcards or credits"),
        ("preview", "Preview or recap"),
        ("filler", "Filler or tangent"),
        ("music_offtopic", "Non-music section of a music video"),
    )
)

# Skipped out of the box: the categories people almost always want gone.
DEFAULT_SKIP = ("sponsor", "selfpromo", "interaction")


def _(text):
    return text


_POT_ANCHORS = (
    _("Sponsor"),
    _("Unpaid or self promotion"),
    _("Interaction reminder (subscribe)"),
    _("Intermission or intro animation"),
    _("Endcards or credits"),
    _("Preview or recap"),
    _("Filler or tangent"),
    _("Non-music section of a music video"),
)


def skip_categories(config_get) -> list[str]:
    """Categories the user has chosen to skip; empty when SponsorBlock is off."""
    if not config_get("sponsorblock_enabled", False):
        return []
    chosen = config_get("sponsorblock_categories", list(DEFAULT_SKIP))
    if not isinstance(chosen, (list, tuple)):
        return list(DEFAULT_SKIP)
    return [c for c in CATEGORIES if c in chosen]


def fetch_segments(video_id: str, categories, timeout: float = 10.0) -> list[dict]:
    """Return ``[{"start": s, "end": s, "category": c, "uuid": u}]`` sorted by start."""
    if not video_id or not categories:
        return []
    prefix = hashlib.sha256(video_id.encode("utf-8")).hexdigest()[:4]
    try:
        resp = utils.safe_requests_get(
            API_URL.format(prefix=prefix),
            params={"categories": json.dumps(list(categories)), "actionTypes": json.dumps(["skip"])},
            timeout=timeout,
            site_cookies=False,
        )
        if resp.status_code == 404:  # no segments for any video under this prefix
            return []
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        LOG.debug("SponsorBlock lookup failed: %s", exc)
        return []
    return parse_segments(data, video_id)


def parse_segments(data, video_id: str) -> list[dict]:
    out = []
    for video in data if isinstance(data, list) else []:
        if not isinstance(video, dict) or video.get("videoID") != video_id:
            continue
        for seg in video.get("segments") or []:
            try:
                start, end = (float(x) for x in seg["segment"])
            except Exception:
                continue
            if seg.get("actionType", "skip") != "skip" or end - start < 0.5:
                continue
            out.append({"start": start, "end": end, "category": str(seg.get("category") or ""), "uuid": str(seg.get("UUID") or "")})
    out.sort(key=lambda s: s["start"])
    return out


def segments_for_url(url: str, config_get) -> list[dict]:
    """Segments to skip for a media/page URL, or [] for non-YouTube media."""
    categories = skip_categories(config_get)
    if not categories:
        return []
    return fetch_segments(video_id_from_url(url), categories)


def segment_at(segments, pos_s: float, done=()) -> dict | None:
    """The segment playback is inside (and has not already skipped), if any.

    The last half second of a segment does not count: skipping there would
    land past content the user already heard begin.
    """
    for seg in segments or ():
        if seg["start"] > pos_s:
            break
        if pos_s < seg["end"] - 0.5 and seg["uuid"] not in done:
            return seg
    return None
