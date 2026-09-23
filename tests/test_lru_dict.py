# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from core.utils import LRUDict


def test_lru_dict_evicts_least_recently_used():
    d = LRUDict(2)
    d["a"] = 1
    d["b"] = 2
    assert d.get("a") == 1  # read refreshes "a"
    d["c"] = 3
    assert list(d) == ["a", "c"]
    assert d.get("b") is None
    assert d.get("b", "x") == "x"
    assert "a" in d and d["c"] == 3
    d.pop("a")
    d.clear()
    assert len(d) == 0
