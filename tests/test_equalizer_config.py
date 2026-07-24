# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from core import equalizer as eq


def test_flat_config_shape():
    c = eq.flat_config()
    assert c["enabled"] is False
    assert c["preamp"] == 0.0
    assert len(c["bands"]) == eq.BAND_COUNT
    assert all(b == 0.0 for b in c["bands"])
    assert eq.is_flat(c)


def test_normalize_clamps_and_pads():
    c = eq.normalize_config({"enabled": 1, "preamp": 99, "bands": [50, -50, 3]})
    assert c["enabled"] is True
    assert c["preamp"] == eq.AMP_MAX
    assert c["bands"][0] == eq.AMP_MAX
    assert c["bands"][1] == eq.AMP_MIN
    assert c["bands"][2] == 3.0
    # padded to full band count with zeros
    assert len(c["bands"]) == eq.BAND_COUNT
    assert c["bands"][3] == 0.0


def test_normalize_bad_input():
    c = eq.normalize_config(None)
    assert c == eq.flat_config()
    c2 = eq.normalize_config({"bands": "nonsense", "preamp": "x"})
    assert c2["preamp"] == 0.0
    assert len(c2["bands"]) == eq.BAND_COUNT


def test_extra_bands_truncated():
    c = eq.normalize_config({"bands": list(range(20))})
    assert len(c["bands"]) == eq.BAND_COUNT


def test_is_flat_detects_nonflat():
    assert not eq.is_flat({"bands": [0, 0, 5, 0, 0, 0, 0, 0, 0, 0]})
    assert not eq.is_flat({"preamp": 2.0})


def test_band_frequencies_match_libvlc_defaults():
    # The engine's real band centers, not the old mislabeled 60/170/310 list.
    assert eq.BAND_FREQUENCIES[0] == 31.25
    assert eq.BAND_FREQUENCIES[5] == 1000
    assert eq.BAND_FREQUENCIES[-1] == 16000
    assert len(eq.BAND_FREQUENCIES) == eq.BAND_COUNT


def test_format_band_label():
    assert eq.format_band_label(31.25) == "31.25 Hz"
    assert eq.format_band_label(500) == "500 Hz"
    assert eq.format_band_label(1000) == "1 kHz"
    assert eq.format_band_label(16000) == "16 kHz"
    assert eq.format_band_label("bad") == ""


def test_normalize_user_presets_dedupes_and_clamps():
    raw = [
        {"name": "Boost", "preamp": 99, "bands": [50, -50, 3]},
        {"name": "boost", "preamp": 0, "bands": []},   # dup (case-insensitive)
        {"name": "", "preamp": 1},                       # dropped: empty name
        "junk",                                          # dropped: not a dict
    ]
    out = eq.normalize_user_presets(raw)
    assert [p["name"] for p in out] == ["Boost"]
    assert out[0]["preamp"] == eq.AMP_MAX
    assert out[0]["bands"][0] == eq.AMP_MAX
    assert len(out[0]["bands"]) == eq.BAND_COUNT


def test_upsert_user_preset_overwrites_in_place():
    raw = [{"name": "A", "preamp": 1.0, "bands": [1.0] * eq.BAND_COUNT}]
    out = eq.upsert_user_preset(raw, "A", 5.0, [2.0] * eq.BAND_COUNT)
    assert len(out) == 1
    assert out[0]["preamp"] == 5.0
    assert out[0]["bands"][0] == 2.0
    out2 = eq.upsert_user_preset(out, "B", 0.0, [0.0] * eq.BAND_COUNT)
    assert [p["name"] for p in out2] == ["A", "B"]
    # blank name is a no-op
    assert eq.upsert_user_preset(out2, "  ", 0, []) == eq.normalize_user_presets(out2)


def test_remove_user_preset():
    raw = [
        {"name": "A", "preamp": 0.0, "bands": [0.0] * eq.BAND_COUNT},
        {"name": "B", "preamp": 0.0, "bands": [0.0] * eq.BAND_COUNT},
    ]
    out = eq.remove_user_preset(raw, "a")  # case-insensitive
    assert [p["name"] for p in out] == ["B"]
    # removing a missing name leaves the list unchanged
    assert [p["name"] for p in eq.remove_user_preset(out, "Z")] == ["B"]
