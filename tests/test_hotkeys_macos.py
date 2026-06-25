"""macOS playback-hotkey behavior.

Two things are locked in here:

1. `resolve_media_action` — the pure modifier->action helper. On macOS,
   Alt(Option)+Arrow must map to the same seek/volume actions as Ctrl+Arrow,
   because the default Ctrl+Left/Right system shortcuts (Mission Control)
   shadow the app. Off macOS, only Ctrl+Arrow counts.

2. `HoldRepeatHotkeys` press -> hold -> repeat -> release, driven
   deterministically via an injected clock and key-state probe so no real
   wx.App / wx.Timer is needed (mirrors the monkeypatch-platform style of
   tests/test_macos_notifications.py).
"""

import wx

import gui.hotkeys as hotkeys
from gui.hotkeys import (
    HoldRepeatHotkeys,
    resolve_media_action,
    ACTION_SEEK_BACK,
    ACTION_SEEK_FORWARD,
    ACTION_VOLUME_UP,
    ACTION_VOLUME_DOWN,
)


# ---------------------------------------------------------------------------
# resolve_media_action (pure helper)
# ---------------------------------------------------------------------------


def test_ctrl_arrow_maps_on_every_platform():
    for plat in ("darwin", "win32", "linux"):
        assert (
            resolve_media_action(plat, ctrl=True, alt=False, shift=False, meta=False, keycode=wx.WXK_LEFT)
            == ACTION_SEEK_BACK
        )
        assert (
            resolve_media_action(plat, ctrl=True, alt=False, shift=False, meta=False, keycode=wx.WXK_RIGHT)
            == ACTION_SEEK_FORWARD
        )
        assert (
            resolve_media_action(plat, ctrl=True, alt=False, shift=False, meta=False, keycode=wx.WXK_UP)
            == ACTION_VOLUME_UP
        )
        assert (
            resolve_media_action(plat, ctrl=True, alt=False, shift=False, meta=False, keycode=wx.WXK_DOWN)
            == ACTION_VOLUME_DOWN
        )


def test_alt_arrow_maps_only_on_macos():
    # macOS: Alt(Option)+Arrow is the non-shadowed alternative -> same actions.
    assert (
        resolve_media_action("darwin", ctrl=False, alt=True, shift=False, meta=False, keycode=wx.WXK_LEFT)
        == ACTION_SEEK_BACK
    )
    assert (
        resolve_media_action("darwin", ctrl=False, alt=True, shift=False, meta=False, keycode=wx.WXK_RIGHT)
        == ACTION_SEEK_FORWARD
    )
    # win32 / linux: Alt+Arrow is NOT a media key (leave text navigation alone).
    assert resolve_media_action("win32", ctrl=False, alt=True, shift=False, meta=False, keycode=wx.WXK_LEFT) is None
    assert resolve_media_action("linux", ctrl=False, alt=True, shift=False, meta=False, keycode=wx.WXK_RIGHT) is None


def test_no_modifier_arrows_are_not_media_keys():
    for plat in ("darwin", "win32", "linux"):
        for kc in (wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_UP, wx.WXK_DOWN):
            assert resolve_media_action(plat, ctrl=False, alt=False, shift=False, meta=False, keycode=kc) is None


def test_shift_or_meta_disqualifies():
    # Ctrl+Shift+Arrow is the chapter shortcut, not seek; Cmd combos are system.
    assert resolve_media_action("darwin", ctrl=True, alt=False, shift=True, meta=False, keycode=wx.WXK_LEFT) is None
    assert resolve_media_action("darwin", ctrl=False, alt=True, shift=True, meta=False, keycode=wx.WXK_LEFT) is None
    assert resolve_media_action("darwin", ctrl=True, alt=False, shift=False, meta=True, keycode=wx.WXK_LEFT) is None


def test_ctrl_alt_arrow_is_not_a_media_action():
    for plat in ("darwin", "win32", "linux"):
        for kc in (wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_UP, wx.WXK_DOWN):
            assert resolve_media_action(
                plat,
                ctrl=True,
                alt=True,
                shift=False,
                meta=False,
                keycode=kc,
            ) is None


def test_non_arrow_key_returns_none():
    assert resolve_media_action("darwin", ctrl=True, alt=False, shift=False, meta=False, keycode=ord("P")) is None


# ---------------------------------------------------------------------------
# HoldRepeatHotkeys (deterministic, no wx.App / wx.Timer)
# ---------------------------------------------------------------------------


class _FakeOwner:
    """Owner with no Bind -> HoldRepeatHotkeys skips real timer creation."""


class _FakeClock:
    def __init__(self, start=0.0):
        self.t = float(start)

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += float(dt)


class _FakeKeyState:
    """Injectable physical key-state probe keyed by wx keycode."""

    def __init__(self):
        self.down = set()

    def press(self, *keycodes):
        for kc in keycodes:
            self.down.add(int(kc))

    def release(self, *keycodes):
        for kc in keycodes:
            self.down.discard(int(kc))

    def __call__(self, keycode):
        return int(keycode) in self.down


class _FakeKeyEvent:
    """Minimal wx.KeyEvent stand-in for handle_ctrl_key."""

    def __init__(self, keycode, ctrl=False, alt=False, shift=False, meta=False, auto_repeat=False):
        self._keycode = int(keycode)
        self._ctrl = ctrl
        self._alt = alt
        self._shift = shift
        self._meta = meta
        self._auto = auto_repeat

    def ControlDown(self):
        return self._ctrl

    def AltDown(self):
        return self._alt

    def ShiftDown(self):
        return self._shift

    def MetaDown(self):
        return self._meta

    def GetKeyCode(self):
        return self._keycode

    def IsAutoRepeat(self):
        return self._auto


def _make_hk(clock, key_state, **kwargs):
    params = dict(hold_delay_s=0.20, repeat_interval_s=0.12, release_grace_polls=3)
    params.update(kwargs)
    hk = HoldRepeatHotkeys(_FakeOwner(), clock=clock, key_state_fn=key_state, **params)
    assert hk._timer is None  # fake owner -> no real wx.Timer was created
    return hk


def test_tap_fires_exactly_once():
    clock = _FakeClock()
    keys = _FakeKeyState()
    fired = []
    hk = _make_hk(clock, keys)

    keys.press(wx.WXK_CONTROL, wx.WXK_LEFT)
    assert hk.handle_ctrl_key(_FakeKeyEvent(wx.WXK_LEFT, ctrl=True), {wx.WXK_LEFT: lambda: fired.append(1)}) is True
    assert len(fired) == 1  # immediate single fire on press

    # Poll before hold_delay elapses: still held, but no repeat yet.
    clock.advance(0.05)
    hk.poll()
    assert len(fired) == 1

    # Release before the delay -> tap stays a single fire even after polling.
    keys.release(wx.WXK_LEFT)
    for _ in range(5):
        clock.advance(0.05)
        hk.poll()
    assert len(fired) == 1


def test_hold_repeats_then_release_stops():
    clock = _FakeClock()
    keys = _FakeKeyState()
    fired = []
    hk = _make_hk(clock, keys)

    keys.press(wx.WXK_CONTROL, wx.WXK_LEFT)
    hk.handle_ctrl_key(_FakeKeyEvent(wx.WXK_LEFT, ctrl=True), {wx.WXK_LEFT: lambda: fired.append(1)})
    assert len(fired) == 1

    # Not enough time elapsed for the first repeat.
    clock.advance(0.10)
    hk.poll()
    assert len(fired) == 1

    # Past hold_delay + interval -> repeats begin.
    clock.advance(0.20)  # now 0.30 > hold_delay 0.20
    hk.poll()
    assert len(fired) == 2
    clock.advance(0.12)
    hk.poll()
    assert len(fired) == 3

    # Release the key: after the grace window the repeat stops for good.
    keys.release(wx.WXK_LEFT)
    for _ in range(4):
        clock.advance(0.12)
        hk.poll()
    count_after_release = len(fired)
    # Drive several more polls; count must not climb.
    for _ in range(5):
        clock.advance(0.12)
        hk.poll()
    assert len(fired) == count_after_release
    assert hk._active == {}  # combo fully cleared


def test_release_grace_tolerates_transient_miss():
    clock = _FakeClock()
    keys = _FakeKeyState()
    fired = []
    hk = _make_hk(clock, keys, release_grace_polls=3)

    keys.press(wx.WXK_CONTROL, wx.WXK_LEFT)
    hk.handle_ctrl_key(_FakeKeyEvent(wx.WXK_LEFT, ctrl=True), {wx.WXK_LEFT: lambda: fired.append(1)})

    # Get into the repeating regime.
    clock.advance(0.30)
    hk.poll()
    assert len(fired) >= 2
    baseline = len(fired)

    # A single missed read (grace=3) must not drop the combo.
    keys.release(wx.WXK_LEFT)
    clock.advance(0.12)
    hk.poll()
    assert hk._active != {}
    # Key "comes back" before grace is exhausted -> miss counter resets, repeats resume.
    keys.press(wx.WXK_LEFT)
    clock.advance(0.12)
    hk.poll()
    assert len(fired) > baseline


def test_macos_alt_arrow_holds_and_repeats(monkeypatch):
    monkeypatch.setattr(hotkeys.sys, "platform", "darwin")
    clock = _FakeClock()
    keys = _FakeKeyState()
    fired = []
    hk = _make_hk(clock, keys)

    # Alt+Left on macOS must be accepted by the hold-repeat gate.
    keys.press(wx.WXK_ALT, wx.WXK_LEFT)
    handled = hk.handle_ctrl_key(
        _FakeKeyEvent(wx.WXK_LEFT, alt=True), {wx.WXK_LEFT: lambda: fired.append(1)}
    )
    assert handled is True
    assert len(fired) == 1

    clock.advance(0.30)
    hk.poll()
    assert len(fired) == 2  # repeats while Alt+Left held

    # Releasing Alt stops the combo (modifier release path).
    keys.release(wx.WXK_ALT)
    hk._on_key_up(_FakeKeyEvent(wx.WXK_ALT, alt=False))
    after = len(fired)
    for _ in range(4):
        clock.advance(0.12)
        hk.poll()
    assert len(fired) == after
    assert hk._active == {}


def test_alt_arrow_ignored_off_macos(monkeypatch):
    monkeypatch.setattr(hotkeys.sys, "platform", "win32")
    clock = _FakeClock()
    keys = _FakeKeyState()
    fired = []
    hk = _make_hk(clock, keys)

    # Alt+Left without Ctrl is NOT a media combo off macOS.
    handled = hk.handle_ctrl_key(
        _FakeKeyEvent(wx.WXK_LEFT, alt=True), {wx.WXK_LEFT: lambda: fired.append(1)}
    )
    assert handled is False
    assert fired == []


def test_ctrl_alt_arrow_is_rejected_by_hold_repeat(monkeypatch):
    monkeypatch.setattr(hotkeys.sys, "platform", "darwin")
    clock = _FakeClock()
    keys = _FakeKeyState()
    fired = []
    hk = _make_hk(clock, keys)

    handled = hk.handle_ctrl_key(
        _FakeKeyEvent(wx.WXK_LEFT, ctrl=True, alt=True),
        {wx.WXK_LEFT: lambda: fired.append(1)},
    )

    assert handled is False
    assert fired == []
    assert hk._active == {}


def test_keyup_on_modifier_stops_repeat():
    clock = _FakeClock()
    keys = _FakeKeyState()
    fired = []
    hk = _make_hk(clock, keys)

    keys.press(wx.WXK_CONTROL, wx.WXK_LEFT)
    hk.handle_ctrl_key(_FakeKeyEvent(wx.WXK_LEFT, ctrl=True), {wx.WXK_LEFT: lambda: fired.append(1)})
    clock.advance(0.30)
    hk.poll()
    assert len(fired) >= 2

    # Ctrl KEY_UP must clear the Ctrl combo even if the probe still reads down.
    hk._on_key_up(_FakeKeyEvent(wx.WXK_CONTROL, ctrl=False))
    assert hk._active == {}
