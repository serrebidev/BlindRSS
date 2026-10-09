# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Sign in to YouTube and follow the account's channel subscriptions.

Sign-in is the device-code flow the YouTube TV app uses (the same one
SmartTube uses): BlindRSS shows a short code, the user enters it at
google.com/device in their own browser, and no password ever passes through
BlindRSS. Only the long-lived refresh token is stored, in local config.

The subscription list comes from the TV client's ``FEchannels`` browse page.
The public YouTube Data API is not enabled for the TV client, and cookie
exports are rotated by YouTube within hours, so neither works for an
unattended sync.

Sync adds each newly subscribed channel once, as the channel's native RSS
feed. ``known`` remembers every channel ever seen, so a feed the user deleted
in BlindRSS is not added back, and unsubscribing on YouTube removes nothing.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
import uuid

import requests

from core.youtube_takeout import TakeoutFeed, TakeoutImport, _channel_feed

LOG = logging.getLogger(__name__)

# The YouTube TV app's installed-app OAuth client. Google documents that an
# installed app's client secret is not confidential.
CLIENT_ID = "861556708454-d6dlm3lh05idd8npek18k6be8ba3oc68.apps.googleusercontent.com"
CLIENT_SECRET = "SboVhoG9s0rNafixCSGGKXAT"
SCOPE = "http://gdata.youtube.com https://www.googleapis.com/auth/youtube-paid-content"
DEVICE_CODE_URL = "https://www.youtube.com/o/oauth2/device/code"
TOKEN_URL = "https://www.youtube.com/o/oauth2/token"
BROWSE_URL = "https://www.youtube.com/youtubei/v1/browse"
TV_CLIENT = {"clientName": "TVHTML5", "clientVersion": "7.20250101.00.00", "hl": "en", "gl": "US"}
TIMEOUT = 20
SYNC_INTERVAL_SECONDS = 6 * 3600


class SignInError(RuntimeError):
    pass


def start_sign_in() -> dict:
    """Return ``{user_code, verification_url, device_code, interval, expires_in}``."""
    resp = requests.post(
        DEVICE_CODE_URL,
        data={"client_id": CLIENT_ID, "scope": SCOPE, "device_id": str(uuid.uuid4()), "device_model": "ytlr::"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def poll_sign_in(device_code: str) -> str | None:
    """The refresh token once the user has approved, None while still pending."""
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": device_code,
            "grant_type": "http://oauth.net/grant_type/device/1.0",
        },
        timeout=TIMEOUT,
    )
    data = resp.json()
    if data.get("refresh_token"):
        return str(data["refresh_token"])
    error = data.get("error")
    if error in ("authorization_pending", "slow_down"):
        return None
    raise SignInError(str(error or f"HTTP {resp.status_code}"))


def access_token(refresh_token: str) -> str:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=TIMEOUT,
    )
    data = resp.json()
    if not data.get("access_token"):
        # invalid_grant = the user revoked access or the token expired.
        raise SignInError(str(data.get("error") or f"HTTP {resp.status_code}"))
    return str(data["access_token"])


def parse_channels(data) -> list[tuple[str, str]]:
    """``[(channel_id, title)]`` from a TV ``FEchannels`` browse response."""
    found: dict[str, str] = {}
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            tile = node.get("tileRenderer")
            if isinstance(tile, dict) and tile.get("contentType") == "TILE_CONTENT_TYPE_CHANNEL":
                cid = str(tile.get("contentId") or "")
                title = (((tile.get("metadata") or {}).get("tileMetadataRenderer") or {}).get("title") or {}).get("simpleText")
                if cid.startswith("UC"):
                    found.setdefault(cid, str(title or "").strip() or cid)
            stack.extend(reversed(list(node.values())))
        elif isinstance(node, list):
            stack.extend(reversed(node))  # document order, so the first title wins
    return sorted(found.items(), key=lambda item: item[1].casefold())


def list_subscriptions(refresh_token: str) -> list[tuple[str, str]]:
    token = access_token(refresh_token)
    resp = requests.post(
        BROWSE_URL,
        json={"context": {"client": TV_CLIENT}, "browseId": "FEchannels"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    resp.raise_for_status()
    channels = parse_channels(resp.json())
    if not channels:
        # An empty list from a changed response shape must not look like
        # "unsubscribed from everything".
        raise SignInError("YouTube returned no subscriptions")
    return channels


def plan_sync(subscriptions, known, existing_channel_ids) -> TakeoutImport:
    """Channels to add: subscribed, never seen before, and not already a feed."""
    skip = set(known) | set(existing_channel_ids)
    feeds = tuple(
        TakeoutFeed(title=title, url=_channel_feed(cid), source="subscriptions")
        for cid, title in subscriptions
        if cid not in skip
    )
    return TakeoutImport(feeds=feeds, subscriptions=len(feeds))


def sync(config, provider) -> int:
    """Add newly subscribed channels to ``provider``; return how many were added.

    ``config`` is a ConfigManager. Runs network and provider calls, so call it
    off the UI thread.
    """
    from core.discovery import youtube_channel_id_from_feed_url
    from core.youtube_takeout import write_takeout_opml

    token = str(config.get("youtube_account_refresh_token", "") or "")
    if not token:
        raise SignInError("not signed in")
    subscriptions = list_subscriptions(token)
    known = list(config.get("youtube_account_known_channels", []) or [])
    existing = set()
    for feed in provider.get_feeds() or []:
        cid = youtube_channel_id_from_feed_url(str(getattr(feed, "url", "") or ""))
        if cid:
            existing.add(cid)
    plan = plan_sync(subscriptions, known, existing)
    if plan.feeds:
        fd, path = tempfile.mkstemp(suffix=".opml", prefix="blindrss-youtube-account-")
        os.close(fd)
        try:
            write_takeout_opml(plan, path)
            category = str(config.get("youtube_account_category", "") or "").strip() or "YouTube"
            if not provider.import_opml(path, category):
                raise RuntimeError("adding the new channels failed")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    config.set("youtube_account_known_channels", sorted(set(known) | {cid for cid, _title in subscriptions}))
    config.set("youtube_account_last_sync", time.time())
    return len(plan.feeds)


def sync_due(config, now: float) -> bool:
    return bool(
        config.get("youtube_account_refresh_token")
        and config.get("youtube_account_auto_add", True)
        and now - float(config.get("youtube_account_last_sync", 0) or 0) >= SYNC_INTERVAL_SECONDS
    )
