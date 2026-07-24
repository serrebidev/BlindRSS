# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from core.config import DEFAULT_CONFIG
from core import range_cache_proxy


def test_default_range_cache_debug_is_disabled():
    assert bool(DEFAULT_CONFIG.get("range_cache_debug", True)) is False


def test_range_cache_singleton_debug_flag_updates():
    original = range_cache_proxy._RANGE_PROXY_SINGLETON
    range_cache_proxy._RANGE_PROXY_SINGLETON = None
    try:
        p = range_cache_proxy.get_range_cache_proxy(debug_logs=False)
        assert bool(getattr(p, "debug_logs", True)) is False

        p2 = range_cache_proxy.get_range_cache_proxy(debug_logs=True)
        assert p2 is p
        assert bool(getattr(p2, "debug_logs", False)) is True
    finally:
        try:
            if range_cache_proxy._RANGE_PROXY_SINGLETON is not None:
                range_cache_proxy._RANGE_PROXY_SINGLETON.stop()
        except Exception:
            pass
        range_cache_proxy._RANGE_PROXY_SINGLETON = original

