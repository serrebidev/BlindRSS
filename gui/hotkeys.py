import time
import sys
import ctypes
from typing import Callable, Dict, Tuple, Optional

import wx


# Canonical media action names returned by resolve_media_action(). The call
# sites map these to the concrete player callbacks; keeping the helper pure
# (platform + modifiers + keycode -> name) makes the modifier logic unit-testable
# without a wx.App.
ACTION_SEEK_BACK = "seek_back"
ACTION_SEEK_FORWARD = "seek_forward"
ACTION_VOLUME_UP = "volume_up"
ACTION_VOLUME_DOWN = "volume_down"

_ARROW_ACTIONS = {
    wx.WXK_LEFT: ACTION_SEEK_BACK,
    wx.WXK_RIGHT: ACTION_SEEK_FORWARD,
    wx.WXK_UP: ACTION_VOLUME_UP,
    wx.WXK_DOWN: ACTION_VOLUME_DOWN,
}


def _is_macos(platform: Optional[str] = None) -> bool:
    plat = sys.platform if platform is None else platform
    return str(plat) == "darwin"


def resolve_media_action(
    platform: str,
    *,
    ctrl: bool,
    alt: bool,
    shift: bool,
    meta: bool,
    keycode: int,
) -> Optional[str]:
    """Return the canonical media action for an arrow key, or None.

    Pure function (no wx.App / no event object) so the platform-specific
    modifier rules can be unit-tested deterministically.

    - Ctrl-only+Arrow maps to seek/volume on every platform (existing behavior).
    - On macOS, Alt(Option)+Arrow ALSO maps to the same actions, because the
      default Ctrl+Left/Right system shortcuts ("Move left/right a space")
      shadow the app there.
    - Ctrl+Alt is rejected so mixed-modifier shortcuts are never interpreted
      as Ctrl-only or macOS Alt-only media actions.
    - Shift or Meta(Cmd) being down disqualifies it (Ctrl+Shift+Arrow is the
      chapter shortcut; Cmd combos belong to the system).
    - No modifier -> None, so plain arrow navigation is never treated as a
      media key.
    """
    if shift or meta or (ctrl and alt):
        return None

    accel = bool(ctrl)
    if not accel and alt and _is_macos(platform):
        accel = True
    if not accel:
        return None

    try:
        return _ARROW_ACTIONS.get(int(keycode))
    except Exception:
        return None


class HoldRepeatHotkeys:
    """Hold-to-repeat behavior for Ctrl+key (and, on macOS, Alt+key) shortcuts.

    Goals:
    - Quick tap fires exactly once.
    - Holding repeats after hold_delay_s, then every repeat_interval_s.
    - Repeat should not randomly stop on Windows.
    - Release detection stays reliable on macOS where wx.GetKeyState can be
      flaky (KEY_UP / focus / activate events back up the polling).

    The time source (`clock`) and the physical key-state probe (`key_state_fn`)
    are injectable so press -> hold -> repeat -> release can be driven
    deterministically in tests without a real wx.App / wx.Timer.
    """

    def __init__(
        self,
        owner,
        hold_delay_s: float = 0.20,
        repeat_interval_s: float = 0.12,
        poll_interval_ms: int = 15,
        release_grace_polls: int = 6,
        clock: Callable[[], float] = time.monotonic,
        key_state_fn: Optional[Callable[[int], bool]] = None,
    ):
        self._owner = owner
        self._hold_delay_s = float(hold_delay_s)
        self._repeat_interval_s = float(repeat_interval_s)
        self._poll_interval_ms = int(poll_interval_ms)
        self._release_grace_polls = max(1, int(release_grace_polls))
        self._clock = clock if callable(clock) else time.monotonic
        # Probe used to detect whether a single keycode is physically down.
        # Tests inject a fake; production falls back to the wx/Win32 probe.
        self._key_state_fn = key_state_fn if callable(key_state_fn) else self._default_key_state

        # Active combos: (mods_mask, keycode) -> state dict
        # mods_mask: bit1 == CTRL, bit2 == ALT (macOS alternative).
        self._active: Dict[Tuple[int, int], Dict[str, object]] = {}

        # Timer creation is lazy/guarded so a fake owner (no Bind / no wx loop)
        # can be used in tests. _make_timer can also be overridden.
        self._timer = None
        try:
            self._timer = self._make_timer(owner)
        except Exception:
            self._timer = None

        if self._timer is not None:
            self._bind_owner_events(owner)

    def _make_timer(self, owner):
        """Create the polling timer. Returns None if not possible (e.g. tests).

        Overridable; guarded so a fake owner without wx wiring is safe.
        """
        if owner is None or not hasattr(owner, "Bind"):
            return None
        timer = wx.Timer(owner)
        owner.Bind(wx.EVT_TIMER, self._on_timer, timer)
        return timer

    def _bind_owner_events(self, owner) -> None:
        # Best-effort KEY_UP / focus stopping (helps when key-state polling is
        # flaky, notably on macOS).
        for evt, handler in (
            (getattr(wx, "EVT_KEY_UP", None), self._on_key_up),
            (getattr(wx, "EVT_KILL_FOCUS", None), self._on_kill_focus),
            (getattr(wx, "EVT_ACTIVATE", None), self._on_activate),
        ):
            if evt is None:
                continue
            try:
                owner.Bind(evt, handler)
            except Exception:
                pass

    def stop(self) -> None:
        try:
            if self._timer is not None and self._timer.IsRunning():
                self._timer.Stop()
        except Exception:
            pass
        self._active.clear()

    def _ensure_timer_running(self) -> None:
        try:
            if self._timer is not None and not self._timer.IsRunning():
                self._timer.Start(self._poll_interval_ms)
        except Exception:
            pass

    def _stop_timer_if_idle(self) -> None:
        try:
            if not self._active and self._timer is not None and self._timer.IsRunning():
                self._timer.Stop()
        except Exception:
            pass

    # ------------------------------------------------------------
    # Key state helpers
    # ------------------------------------------------------------

    def _win_key_down_vk(self, vk: int) -> bool:
        try:
            if not sys.platform.startswith("win"):
                return False
            state = ctypes.windll.user32.GetAsyncKeyState(int(vk))
            return bool(state & 0x8000)
        except Exception:
            return False

    def _keycode_to_vk(self, keycode: int) -> Optional[int]:
        # Virtual key codes for common special keys
        if keycode == wx.WXK_LEFT:
            return 0x25
        if keycode == wx.WXK_UP:
            return 0x26
        if keycode == wx.WXK_RIGHT:
            return 0x27
        if keycode == wx.WXK_DOWN:
            return 0x28
        if keycode == wx.WXK_CONTROL:
            return 0x11
        if keycode == wx.WXK_ALT:
            return 0x12
        return None

    def _default_key_state(self, keycode: int) -> bool:
        """Return best-effort physical key state.

        Prefer wx.GetKeyState (works well with wx focus routing), and OR it with
        Win32 GetAsyncKeyState as a fallback. This is the production probe;
        tests inject `key_state_fn` instead.
        """
        down = False
        try:
            down = bool(wx.GetKeyState(int(keycode)))
        except Exception:
            down = False

        # Win32 fallback
        if not down and sys.platform.startswith("win"):
            vk = self._keycode_to_vk(int(keycode))
            if vk is not None:
                down = down or self._win_key_down_vk(vk)
            else:
                # For alphanumerics, VK codes match ASCII for A-Z and 0-9.
                try:
                    kc = int(keycode)
                    if 0x30 <= kc <= 0x39 or 0x41 <= kc <= 0x5A:
                        down = down or self._win_key_down_vk(kc)
                except Exception:
                    pass

        return bool(down)

    def _is_key_down(self, keycode: int) -> bool:
        try:
            return bool(self._key_state_fn(int(keycode)))
        except Exception:
            return False

    def _accel_is_down(self, mods: int) -> bool:
        """Is the accelerator modifier for this combo still held?

        mods bit1 == CTRL, bit2 == ALT. Either being down keeps the combo
        alive so the macOS Alt path and the Ctrl path both repeat reliably.
        """
        try:
            if (int(mods) & 1) and self._is_key_down(wx.WXK_CONTROL):
                return True
            if (int(mods) & 2) and self._is_key_down(wx.WXK_ALT):
                return True
        except Exception:
            # If the probe blows up, assume held so we don't kill an active
            # repeat on a transient error (the KEY_UP handler still stops it).
            return True
        return False

    def _combo_is_down(self, mods: int, keycode: int) -> bool:
        try:
            return bool(self._accel_is_down(mods) and self._is_key_down(int(keycode)))
        except Exception:
            return False

    # ------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------

    def _event_mods_mask(self, event: wx.KeyEvent) -> int:
        """Compute the accelerator mask for an event.

        bit1 == CTRL, bit2 == ALT (only honored as an accelerator on macOS so
        Alt+Arrow text navigation is untouched elsewhere). Returns 0 when no
        usable accelerator is down.
        """
        mask = 0
        try:
            ctrl_down = bool(event.ControlDown())
        except Exception:
            ctrl_down = False
        try:
            alt_down = bool(event.AltDown())
        except Exception:
            alt_down = False

        # Accelerator shortcuts are deliberately modifier-exclusive:
        # Ctrl-only everywhere, or Alt-only on macOS.
        if ctrl_down and alt_down:
            return 0
        if ctrl_down:
            mask |= 1
        elif _is_macos() and alt_down:
            mask |= 2
        return mask

    def handle_ctrl_key(
        self,
        event: wx.KeyEvent,
        actions_by_keycode: Dict[int, Callable[[], None]],
    ) -> bool:
        """Handle Ctrl+<key> (and Alt+<key> on macOS) with hold-to-repeat.

        Returns True if handled and the event should be swallowed.
        """
        try:
            mods = self._event_mods_mask(event)
            if not mods:
                return False
            key = int(event.GetKeyCode())
        except Exception:
            return False

        cb = actions_by_keycode.get(key)
        if cb is None:
            return False

        combo_id = (mods, key)
        now = self._clock()

        is_auto_repeat = False
        try:
            is_auto_repeat = bool(getattr(event, "IsAutoRepeat", lambda: False)())
        except Exception:
            is_auto_repeat = False

        st = self._active.get(combo_id)

        # Treat any non-auto-repeat event as a fresh press so taps never feel delayed.
        if st is None or not is_auto_repeat:
            st = {}
            self._active[combo_id] = st
            st["start"] = now
            st["last_fire"] = 0.0
            st["cb"] = cb
            st["key"] = key
            st["miss"] = 0
            st["last_event"] = now

            # Fire immediately once.
            try:
                cb()
            except Exception:
                pass
            st["last_fire"] = now
        else:
            # Auto-repeat keydown: just refresh callback and keep-alive.
            try:
                st["cb"] = cb
                st["last_event"] = now
            except Exception:
                pass

        # Ensure polling is running.
        self._ensure_timer_running()

        return True

    def _on_key_up(self, event: wx.KeyEvent) -> None:
        try:
            key = int(event.GetKeyCode())
        except Exception:
            key = None

        try:
            to_remove = []
            for (mods, k), st in list(self._active.items()):
                # Releasing an accelerator modifier stops its combos.
                if key == wx.WXK_CONTROL and (mods & 1):
                    to_remove.append((mods, k))
                    continue
                if key == wx.WXK_ALT and (mods & 2):
                    to_remove.append((mods, k))
                    continue
                # If the combo key released, stop that combo.
                if key is not None and key == k:
                    to_remove.append((mods, k))
            for cid in to_remove:
                self._active.pop(cid, None)
        except Exception:
            pass

        self._stop_timer_if_idle()

        try:
            event.Skip()
        except Exception:
            pass

    def _on_kill_focus(self, event) -> None:
        try:
            self.stop()
        except Exception:
            pass
        try:
            event.Skip()
        except Exception:
            pass

    def _on_activate(self, event) -> None:
        try:
            if hasattr(event, "GetActive") and not event.GetActive():
                self.stop()
        except Exception:
            pass
        try:
            event.Skip()
        except Exception:
            pass

    def _on_timer(self, _evt) -> None:
        self.poll()

    def poll(self) -> None:
        """Run one release/repeat poll cycle.

        Exposed (not just bound to the timer) so tests can drive repeats
        deterministically via the injected clock.
        """
        if not self._active:
            self._stop_timer_if_idle()
            return

        now = self._clock()

        for combo_id, st in list(self._active.items()):
            mods, key = combo_id
            if not mods:
                self._active.pop(combo_id, None)
                continue

            try:
                start = float(st.get("start", now))
            except Exception:
                start = now
            try:
                last_fire = float(st.get("last_fire", 0.0))
            except Exception:
                last_fire = 0.0
            try:
                miss = int(st.get("miss", 0))
            except Exception:
                miss = 0

            cb = st.get("cb")
            if not callable(cb):
                self._active.pop(combo_id, None)
                continue

            # Check for release. Use a small grace window to avoid random false negatives.
            down = True
            try:
                down = self._combo_is_down(int(mods), int(key))
            except Exception:
                down = True

            if not down:
                miss += 1
                st["miss"] = miss
                if miss >= self._release_grace_polls:
                    self._active.pop(combo_id, None)
                    continue
            else:
                st["miss"] = 0

            if (now - start) < self._hold_delay_s:
                continue
            if (now - last_fire) < self._repeat_interval_s:
                continue

            try:
                cb()
            except Exception:
                pass
            st["last_fire"] = now

        # Stop timer if nothing active.
        self._stop_timer_if_idle()
