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


def test_lru_dict_char_budget_evicts_oldest_but_keeps_newest():
    d = LRUDict(10, max_chars=10)
    d["a"] = "xxxx"
    d["b"] = "yyyy"
    d["c"] = "zzzz"  # 12 chars > 10: "a" goes
    assert list(d) == ["b", "c"]
    d["huge"] = "w" * 50  # over budget alone: newest entry is still kept
    assert list(d) == ["huge"]
