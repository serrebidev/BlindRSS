# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from core import shortcuts as sc


def test_parse_and_normalize_basic():
    assert sc.parse_accel("Ctrl+P") == (("Ctrl",), "P")
    assert sc.parse_accel("ctrl+shift+p") == (("Ctrl", "Shift"), "P")
    # Modifier order is canonicalized regardless of input order.
    assert sc.normalize_accel("shift+ctrl+p") == "Ctrl+Shift+P"
    assert sc.normalize_accel("Control+Left") == "Ctrl+Left"


def test_parse_unbound_and_invalid():
    assert sc.parse_accel("") is None
    assert sc.parse_accel("   ") is None
    assert sc.parse_accel(None) is None
    assert sc.normalize_accel("") == ""
    # Unknown modifier -> invalid.
    assert sc.parse_accel("Hyper+X") is None


def test_named_and_punct_keys():
    assert sc.normalize_accel("Ctrl+Shift+,") == "Ctrl+Shift+,"
    assert sc.normalize_accel("Ctrl+Shift+comma") == "Ctrl+Shift+,"
    assert sc.normalize_accel("Ctrl+Space") == "Ctrl+Space"
    assert sc.normalize_accel("ctrl+f5") == "Ctrl+F5"
    # literal plus key
    assert sc.normalize_accel("Ctrl+Shift++") == "Ctrl+Shift++"


def test_default_bindings_present():
    d = sc.default_bindings()
    assert d["player.play_pause"] == "Ctrl+P"
    assert d["player.stop"] == "Ctrl+S"
    assert d["player.show_hide"] == "Ctrl+Shift+P"
    assert d["queue.open"] == "Ctrl+Shift+C"
    assert d["queue.next"] == "Ctrl+Shift+T"
    assert d["queue.prev"] == "Ctrl+Shift+V"
    # Letters on purpose: Ctrl+Shift+./,/0 get eaten system-wide by NVDA
    # add-on gestures and Windows input-language hotkeys (see core.shortcuts).
    assert d["speed.up"] == "Ctrl+Shift+U"
    assert d["speed.down"] == "Ctrl+Shift+D"
    assert d["speed.reset"] == "Ctrl+Shift+N"
    # Migrated historical accelerators keep their keys.
    assert d["feeds.refresh_all"] == "F5"
    assert d["feeds.add"] == "Ctrl+N"
    assert d["article.toggle_favorite"] == "Ctrl+D"
    assert d["filter.read_all"] == "Ctrl+1"
    # Commands that never had a key ship unbound (user can assign one).
    assert d["feeds.video_search"] == ""
    assert d["article.copy_link"] == ""
    # Every command still resolves (empty string means unbound, not missing).
    from core import shortcuts as _sc
    assert set(d) == {c.id for c in _sc.iter_commands()}


def test_resolve_overrides_and_unbind():
    ov = {"player.play_pause": "Ctrl+Shift+Space", "player.stop": ""}
    b = sc.resolve_bindings(ov)
    assert b["player.play_pause"] == "Ctrl+Shift+Space"
    assert b["player.stop"] == ""  # explicitly unbound
    assert b["player.show_hide"] == "Ctrl+Shift+P"  # untouched default


def test_conflicts_and_inversion():
    ov = {"queue.next": "Ctrl+P"}  # collide with play_pause
    b = sc.resolve_bindings(ov)
    conflicts = sc.find_conflicts(b)
    assert "Ctrl+P" in conflicts
    assert set(conflicts["Ctrl+P"]) == {"player.play_pause", "queue.next"}
    inv = sc.invert_bindings(sc.default_bindings())
    assert inv["Ctrl+S"] == "player.stop"


def test_defaults_have_no_self_conflict():
    assert sc.find_conflicts(sc.default_bindings()) == {}
