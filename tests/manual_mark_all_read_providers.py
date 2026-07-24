# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import json
import time
from pathlib import Path

from providers.local import LocalProvider
from providers.miniflux import MinifluxProvider
from providers.inoreader import InoreaderProvider
from providers.theoldreader import TheOldReaderProvider
from providers.bazqux import BazQuxProvider


def _load_config(repo_root: Path) -> dict:
    config_path = repo_root / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing config.json at {config_path}")
    return json.loads(config_path.read_text(encoding="utf-8"))


def _collect_unread_ids(provider, feed_id: str) -> list[str]:
    ids = []
    seen = set()
    page_size = 500
    offset = 0
    last_offset = -1
    while True:
        if offset <= last_offset:
            break
        last_offset = offset
        page, total = provider.get_articles_page(feed_id, offset=offset, limit=page_size)
        page = page or []
        if not page:
            break
        for article in page:
            aid = getattr(article, "id", None)
            if not aid or aid in seen:
                continue
            seen.add(aid)
            if not getattr(article, "is_read", False):
                ids.append(aid)
        offset += len(page)
        if total is not None:
            try:
                if offset >= int(total):
                    break
            except Exception:
                pass
        if total is None and len(page) < page_size:
            break
    return ids


def _mark_all_for_view(provider, feed_id: str) -> dict:
    result = {
        "feed_id": feed_id,
        "direct": False,
        "ok": False,
        "unread_ids": 0,
        "error": "",
        "duration_s": 0.0,
    }
    start = time.time()
    try:
        mark_all = getattr(provider, "mark_all_read", None)
        if callable(mark_all):
            try:
                result["direct"] = bool(mark_all(feed_id))
            except Exception as e:
                result["direct"] = False
                result["error"] = str(e)
        if not result["direct"]:
            unread_ids = _collect_unread_ids(provider, feed_id)
            result["unread_ids"] = len(unread_ids)
            if unread_ids:
                try:
                    result["ok"] = bool(provider.mark_read_batch(unread_ids))
                except Exception as e:
                    result["ok"] = False
                    result["error"] = str(e)
            else:
                result["ok"] = True
        else:
            result["ok"] = True
    finally:
        result["duration_s"] = time.time() - start
    return result


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config = _load_config(repo_root)

    # Point LocalProvider at the repo's rss.db (not tests/).
    try:
        import core.db as db
        db.DB_FILE = str(repo_root / "rss.db")
    except Exception:
        pass

    providers = [
        ("local", LocalProvider),
        ("miniflux", MinifluxProvider),
        ("inoreader", InoreaderProvider),
        ("theoldreader", TheOldReaderProvider),
        ("bazqux", BazQuxProvider),
    ]

    for name, cls in providers:
        print(f"\n== {name} ==")
        try:
            provider = cls(config)
        except Exception as e:
            print(f"Init failed: {e}")
            continue

        try:
            feeds = provider.get_feeds() or []
        except Exception as e:
            print(f"get_feeds failed: {e}")
            feeds = []

        feed_id = feeds[0].id if feeds else None
        views = ["all"]
        if feed_id:
            views.append(feed_id)

        for view_id in views:
            result = _mark_all_for_view(provider, view_id)
            print(
                f"view={view_id} direct={result['direct']} ok={result['ok']} "
                f"unread_ids={result['unread_ids']} duration={result['duration_s']:.2f}s "
                f"err={result['error']}"
            )


if __name__ == "__main__":
    main()
