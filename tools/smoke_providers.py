#!/usr/bin/env python
# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Quick provider smoke test using a BlindRSS config.json.

This script is intentionally read-only. It performs:
- provider.refresh(force=True)
- provider.get_feeds()
- provider.get_articles_page() (or get_articles()) for one feed and for "all" when supported

It avoids printing provider credentials (tokens/passwords/api keys).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from providers.local import LocalProvider
from providers.miniflux import MinifluxProvider
from providers.inoreader import InoreaderProvider
from providers.theoldreader import TheOldReaderProvider
from providers.bazqux import BazQuxProvider


def _safe(s: str) -> str:
    s = str(s or "")
    if len(s) > 160:
        return s[:157] + "..."
    return s


def _print_header(name: str) -> None:
    print("\n" + "=" * 72)
    print(f"PROVIDER: {name}")
    print("=" * 72)


def _smoke_provider(name: str, provider) -> None:
    try:
        ok = provider.refresh(force=True)
        print(f"refresh(force=True): {bool(ok)}")
    except Exception as e:
        print(f"refresh ERROR: {e}")

    try:
        feeds = provider.get_feeds() or []
        print(f"feeds: {len(feeds)}")
    except Exception as e:
        print(f"get_feeds ERROR: {e}")
        traceback.print_exc()
        return

    if not feeds:
        return

    f0 = feeds[0]
    print(f"first feed: title={_safe(getattr(f0,'title',''))} id={_safe(getattr(f0,'id',''))}")

    def _try_articles(view_id: str, label: str) -> None:
        try:
            if hasattr(provider, "get_articles_page"):
                arts, total = provider.get_articles_page(view_id, offset=0, limit=5)
            else:
                arts = (provider.get_articles(view_id) or [])[:5]
                total = None
            print(f"articles({label}): {len(arts)} total={total}")
            if arts:
                a0 = arts[0]
                print(
                    f"top article: title={_safe(getattr(a0,'title',''))} date={_safe(getattr(a0,'date',''))}"
                )
        except Exception as e:
            print(f"articles({label}) ERROR: {e}")

    _try_articles(getattr(f0, "id", ""), "first feed")
    # Many providers support "all" via special view id.
    _try_articles("all", "all")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--config",
        default=os.path.join(REPO_ROOT, "config.json"),
        help="Path to BlindRSS config.json (default: repo root config.json).",
    )
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    providers = [
        ("local", LocalProvider),
        ("miniflux", MinifluxProvider),
        ("inoreader", InoreaderProvider),
        ("theoldreader", TheOldReaderProvider),
        ("bazqux", BazQuxProvider),
    ]

    for name, cls in providers:
        _print_header(name)
        try:
            p = cls(cfg)
        except Exception as e:
            print(f"INIT ERROR: {e}")
            traceback.print_exc()
            continue
        _smoke_provider(name, p)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

