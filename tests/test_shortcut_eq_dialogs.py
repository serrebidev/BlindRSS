# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Construction + handler smoke tests for the new dialogs (needs a wx.App)."""
import pytest

wx = pytest.importorskip("wx")

from core import shortcuts as sc
from core import equalizer as eqmod
from gui.dialogs import KeyboardShortcutsDialog, EqualizerDialog


@pytest.fixture(scope="module")
def app():
    try:
        a = wx.App()
    except Exception as e:  # pragma: no cover - headless
        pytest.skip(f"no wx display: {e}")
    yield a


class _ShortcutController:
    def __init__(self):
        self.overrides = {}
        self.saved = []

    def get_shortcut_overrides(self):
        return dict(self.overrides)

    def save_shortcut_overrides(self, ov):
        self.overrides = dict(ov)
        self.saved.append(dict(ov))


def test_keyboard_shortcuts_dialog_lists_all_commands(app):
    parent = wx.Frame(None)
    try:
        ctl = _ShortcutController()
        dlg = KeyboardShortcutsDialog(parent, ctl)
        try:
            # Every registry command, plus the read-only fixed-key reference rows.
            assert dlg.list_ctrl.GetItemCount() == len(sc.iter_commands()) + len(dlg._fixed_rows())
            # Row 0 shows the first command's default in the Shortcut column.
            first_default = sc.default_bindings()[sc.iter_commands()[0].id]
            assert dlg.list_ctrl.GetItemText(0, 2) == first_default

            # Remove the selected command's binding -> persisted as unbound.
            dlg.list_ctrl.Select(0)
            dlg.on_remove()
            first_id = sc.iter_commands()[0].id
            assert ctl.overrides.get(first_id) == ""
            assert sc.resolve_bindings(ctl.overrides)[first_id] == ""
        finally:
            dlg.Destroy()
    finally:
        parent.Destroy()


class _EqPlayer:
    def __init__(self):
        self.cfg = eqmod.flat_config()
        self.applied = []
        self._user_raw = []

    def get_equalizer_config(self):
        return dict(self.cfg)

    def set_equalizer_config(self, cfg, *, persist=True, apply=True):
        self.cfg = eqmod.normalize_config(cfg)
        self.applied.append(dict(self.cfg))

    def list_equalizer_presets(self):
        return [("Rock", 0.0, [4.0] * eqmod.BAND_COUNT)]

    def get_equalizer_band_frequencies(self):
        return list(eqmod.BAND_FREQUENCIES)

    def list_user_equalizer_presets(self):
        return [
            (p["name"], p["preamp"], list(p["bands"]))
            for p in eqmod.normalize_user_presets(self._user_raw)
        ]

    def save_user_equalizer_preset(self, name, preamp, bands):
        self._user_raw = eqmod.upsert_user_preset(self._user_raw, name, preamp, bands)
        return True

    def delete_user_equalizer_preset(self, name):
        before = len(eqmod.normalize_user_presets(self._user_raw))
        self._user_raw = eqmod.remove_user_preset(self._user_raw, name)
        return len(eqmod.normalize_user_presets(self._user_raw)) != before


def test_equalizer_dialog_enable_and_adjust(app):
    parent = wx.Frame(None)
    try:
        player = _EqPlayer()
        dlg = EqualizerDialog(parent, player)
        try:
            assert len(dlg.band_sliders) == eqmod.BAND_COUNT

            # Enabling pushes an enabled config to the player.
            dlg.enable_cb.SetValue(True)
            dlg.on_enable(None)
            assert player.cfg["enabled"] is True

            # Moving a band updates that band's gain.
            dlg.band_sliders[0].SetValue(6)
            dlg.on_slider(None)
            assert player.cfg["bands"][0] == 6.0

            # Applying a preset copies its gains in.
            dlg.preset_choice.SetSelection(1)
            dlg.on_preset(None)
            assert player.cfg["bands"][0] == 4.0
            assert player.cfg["preset"] == "Rock"

            # Reset flattens everything.
            dlg.on_reset()
            assert all(b == 0.0 for b in player.cfg["bands"])
            assert player.cfg["preamp"] == 0.0
        finally:
            dlg.Destroy()
    finally:
        parent.Destroy()


def test_equalizer_sliders_are_labeled_for_screen_readers(app):
    """Each slider must carry a meaningful accessible name (not a value)."""
    parent = wx.Frame(None)
    try:
        player = _EqPlayer()
        dlg = EqualizerDialog(parent, player)
        try:
            # Preamp + the first band read as their labels, never a bare number.
            assert dlg.preamp_slider.GetName() == "Preamp"
            for s in dlg.band_sliders:
                name = s.GetName()
                assert name and not name.strip().lstrip("+-").isdigit()

            # The custom accessible reports the value in dB, signed.
            acc = getattr(dlg.band_sliders[0], "_acc", None)
            if acc is not None:
                dlg.band_sliders[0].SetValue(3)
                assert acc.GetValue(wx.ACC_SELF)[1] == "+3 dB"
                dlg.band_sliders[0].SetValue(0)
                assert acc.GetValue(wx.ACC_SELF)[1] == "0 dB"
        finally:
            dlg.Destroy()
    finally:
        parent.Destroy()


def test_equalizer_band_labels_use_real_frequencies(app):
    parent = wx.Frame(None)
    try:
        dlg = EqualizerDialog(parent, _EqPlayer())
        try:
            names = [s.GetName() for s in dlg.band_sliders]
            # Matches libVLC's real band centers, not the old 60/170/310 labels.
            assert names[0] == "31.25 Hz"
            assert names[-1] == "16 kHz"
            assert "60 Hz" not in names
        finally:
            dlg.Destroy()
    finally:
        parent.Destroy()


def test_equalizer_user_presets_save_and_delete(app):
    parent = wx.Frame(None)
    try:
        player = _EqPlayer()
        dlg = EqualizerDialog(parent, player)
        try:
            dlg.enable_cb.SetValue(True)
            dlg.on_enable(None)

            # Dial in a custom curve and save it as a user preset.
            dlg.band_sliders[0].SetValue(6)
            dlg.on_slider(None)
            player.save_user_equalizer_preset("My EQ", 2.0, [6.0] + [0.0] * (eqmod.BAND_COUNT - 1))
            dlg._rebuild_preset_choice(select_name="My EQ", select_kind="user")

            # The user preset is selectable and Delete is enabled for it.
            entry = dlg._selected_preset_entry()
            assert entry is not None and entry[0] == "user" and entry[1] == "My EQ"
            assert dlg.delete_preset_btn.IsEnabled()

            # Applying it pushes the saved gains onto the player.
            dlg.on_preset(None)
            assert player.cfg["bands"][0] == 6.0
            assert player.cfg["preamp"] == 2.0

            # Deleting removes it from the store and falls back to Custom.
            assert player.delete_user_equalizer_preset("My EQ") is True
            dlg._rebuild_preset_choice(select_name=None)
            assert all(e[1] != "My EQ" for e in dlg._preset_entries)
            assert not dlg.delete_preset_btn.IsEnabled()
        finally:
            dlg.Destroy()
    finally:
        parent.Destroy()
