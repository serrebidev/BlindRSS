"""Accessible-name coverage for the player transport controls.

A blind VoiceOver user drives playback entirely by keyboard, so every transport
control in the player window must announce its purpose. Symbol-only or numeric
controls (``-10s``/``+10s`` buttons, the bare ``00:00`` time readouts, the ``%``
volume readout, the position/volume sliders, the chapter list) carry no useful
visible text on their own, so they are given an explicit accessible name via
``SetName``. Buttons whose visible label already reads well (Play/Pause, Stop,
Cast) are intentionally left unnamed so VoiceOver reads the label and the
Play/Pause state toggle is not masked.

Constructing a real ``PlayerFrame`` pulls in VLC and worker threads, so these
tests assert the naming contract from the ``init_ui`` source plus a guarded live
check that ``SetName``/``GetName`` round-trips on the widget types used.
"""

import inspect

import gui.player as player


def _init_ui_source() -> str:
    return inspect.getsource(player.PlayerFrame.init_ui)


def test_player_module_imports():
    # Import smoke: the player module must load even where VLC is unavailable.
    assert hasattr(player, "PlayerFrame")


def test_ambiguous_controls_have_accessible_names():
    """Symbol-only / numeric controls must each set a descriptive name."""
    src = _init_ui_source()
    # (attribute, expected accessible name) for controls whose visible content is
    # not self-describing for a screen reader.
    expected = {
        "current_time_lbl": "Elapsed Time",
        "total_time_lbl": "Total Time",
        "volume_value_lbl": "Volume Level",
        "status_lbl": "Playback Status",
        "slider": "Playback Position",
        "volume_slider": "Volume",
        "speed_combo": "Playback Speed",
        "chapter_choice": "Chapters",
        "chapters_btn": "Chapters Menu",
    }
    for attr, name in expected.items():
        assert f'self.{attr}.SetName("{name}")' in src, f"missing accessible name for {attr}"


def test_seek_buttons_named_despite_symbolic_labels():
    """The -10s / +10s buttons read as symbols, so they carry spoken names."""
    src = _init_ui_source()
    assert 'rewind_btn.SetName("Rewind 10 seconds")' in src
    assert 'forward_btn.SetName("Fast Forward 10 seconds")' in src


def test_clear_text_buttons_not_renamed():
    """Buttons with descriptive visible text must not get redundant names.

    The Play button in particular relabels itself Play/Pause to announce state;
    a static SetName would mask that, so it (and Stop/Cast) stay unnamed.
    """
    src = _init_ui_source()
    assert "self.play_btn.SetName(" not in src
    assert "self.stop_btn.SetName(" not in src
    assert "self.cast_btn.SetName(" not in src


def test_setname_roundtrips_on_widget_types_used():
    """Guarded live check that the accessible-naming mechanism works here.

    Skips cleanly if a headless wx.App cannot be created in this environment.
    """
    import pytest

    wx = pytest.importorskip("wx")
    try:
        app = wx.App()
    except Exception as e:  # pragma: no cover - depends on display availability
        pytest.skip(f"wx.App unavailable: {e}")

    frame = wx.Frame(None)
    try:
        panel = wx.Panel(frame)
        # StaticText and Slider report the name set via SetName...
        label = wx.StaticText(panel, label="00:00")
        label.SetName("Elapsed Time")
        assert label.GetName() == "Elapsed Time"

        slider = wx.Slider(panel, value=0, minValue=0, maxValue=100)
        slider.SetName("Volume")
        assert slider.GetName() == "Volume"

        # ...while a plain button's accessible name comes from its visible label,
        # which is why descriptive-text buttons are left unnamed.
        button = wx.Button(panel, label="Play")
        assert button.GetLabel() == "Play"
    finally:
        frame.Destroy()
        app.Destroy()
