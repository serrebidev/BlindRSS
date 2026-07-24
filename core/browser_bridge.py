# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from typing import Callable, Optional

_browser_fetcher: Optional[Callable[[str], str]] = None

def register_browser_fetcher(fetcher: Callable[[str], str]):
    global _browser_fetcher
    _browser_fetcher = fetcher

def fetch_with_browser(url: str) -> Optional[str]:
    if _browser_fetcher:
        try:
            return _browser_fetcher(url)
        except Exception:
            return None
    return None
