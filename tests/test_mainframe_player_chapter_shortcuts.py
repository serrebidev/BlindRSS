import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe


class _DummyKeyEvent:
    def __init__(self, key, *, ctrl=False, shift=False, alt=False, meta=False):
        self._key = int(key)
        self._ctrl = bool(ctrl)
        self._shift = bool(shift)
        self._alt = bool(alt)
        self._meta = bool(meta)
        self.skipped = False

    def GetKeyCode(self):
        return int(self._key)

    def ControlDown(self):
        return bool(self._ctrl)

    def ShiftDown(self):
        return bool(self._shift)

    def AltDown(self):
        return bool(self._alt)

    def MetaDown(self):
        return bool(self._meta)

    def Skip(self):
        self.skipped = True


class _HotkeysStub:
    def __init__(self):
        self.calls = []

    def handle_ctrl_key(self, event, actions):
        key = int(event.GetKeyCode())
        self.calls.append(key)
        action = actions.get(key)
        if action is not None:
            action()
            return True
        return False


class _HotkeysAlwaysFalse:
    def __init__(self):
        self.calls = []

    def handle_ctrl_key(self, event, actions):
        self.calls.append(int(event.GetKeyCode()))
        _ = actions
        return False


class _PlayerStub:
    def __init__(self):
        self.volume_step = 6
        self.seek_back_ms = 9000
        self.seek_forward_ms = 12000
        self.calls = []

    def is_audio_playing(self):
        return True

    def adjust_volume(self, delta):
        self.calls.append(("volume", int(delta)))

    def seek_relative_ms(self, delta):
        self.calls.append(("seek", int(delta)))

    def has_media_loaded(self):
        return True


class _DummyMain:
    on_char_hook = mainframe.MainFrame.on_char_hook
    _is_text_input_focused = mainframe.MainFrame._is_text_input_focused

    def __init__(self):
        self.list_ctrl = object()
        self.tree = object()
        self.player_window = type(
            "_ChapterPlayer",
            (),
            {
                "current_chapters": [{"start": 0.0}, {"start": 10.0}, {"start": 20.0}],
                "get_active_chapter_index": lambda _self: 1,
            },
        )()
        self.content_ctrl = object()
        self.search_ctrl = object()
        self._focus = None
        self.calls = []
        self._media_hotkeys = None

    def _get_focused_window(self):
        return self._focus

    def on_player_prev_chapter(self, _event):
        self.calls.append("prev")

    def on_player_next_chapter(self, _event):
        self.calls.append("next")


def test_mainframe_ctrl_shift_arrows_trigger_player_chapter_shortcuts():
    host = _DummyMain()
    left_evt = _DummyKeyEvent(mainframe.wx.WXK_LEFT, ctrl=True, shift=True)
    right_evt = _DummyKeyEvent(mainframe.wx.WXK_RIGHT, ctrl=True, shift=True)

    host.on_char_hook(left_evt)
    host.on_char_hook(right_evt)

    assert host.calls == ["prev", "next"]
    assert left_evt.skipped is False
    assert right_evt.skipped is False


def test_mainframe_ctrl_shift_arrows_are_not_swallowed_without_chapters():
    host = _DummyMain()
    host.player_window.current_chapters = []
    left_evt = _DummyKeyEvent(mainframe.wx.WXK_LEFT, ctrl=True, shift=True)
    right_evt = _DummyKeyEvent(mainframe.wx.WXK_RIGHT, ctrl=True, shift=True)

    host.on_char_hook(left_evt)
    host.on_char_hook(right_evt)

    assert host.calls == []
    assert left_evt.skipped is True
    assert right_evt.skipped is True


def test_mainframe_ctrl_shift_arrows_are_not_swallowed_at_chapter_boundaries():
    host = _DummyMain()
    host.player_window.get_active_chapter_index = lambda: 0
    left_evt = _DummyKeyEvent(mainframe.wx.WXK_LEFT, ctrl=True, shift=True)
    host.on_char_hook(left_evt)

    host.player_window.get_active_chapter_index = lambda: 2
    right_evt = _DummyKeyEvent(mainframe.wx.WXK_RIGHT, ctrl=True, shift=True)
    host.on_char_hook(right_evt)

    assert host.calls == []
    assert left_evt.skipped is True
    assert right_evt.skipped is True


def test_mainframe_ctrl_arrows_trigger_player_volume_and_seek_shortcuts():
    host = _DummyMain()
    player = _PlayerStub()
    host.player_window = player
    host._media_hotkeys = _HotkeysStub()

    host.on_char_hook(_DummyKeyEvent(mainframe.wx.WXK_UP, ctrl=True))
    host.on_char_hook(_DummyKeyEvent(mainframe.wx.WXK_DOWN, ctrl=True))
    host.on_char_hook(_DummyKeyEvent(mainframe.wx.WXK_LEFT, ctrl=True))
    host.on_char_hook(_DummyKeyEvent(mainframe.wx.WXK_RIGHT, ctrl=True))

    assert player.calls == [
        ("volume", 6),
        ("volume", -6),
        ("seek", -9000),
        ("seek", 12000),
    ]


def test_mainframe_ctrl_up_down_fallback_runs_when_hotkeys_returns_false():
    host = _DummyMain()
    player = _PlayerStub()
    host.player_window = player
    host._media_hotkeys = _HotkeysAlwaysFalse()

    host.on_char_hook(_DummyKeyEvent(mainframe.wx.WXK_UP, ctrl=True))
    host.on_char_hook(_DummyKeyEvent(mainframe.wx.WXK_DOWN, ctrl=True))

    assert player.calls == [
        ("volume", 6),
        ("volume", -6),
    ]


def test_mainframe_ctrl_shift_arrows_do_not_override_content_word_selection():
    host = _DummyMain()
    host._focus = host.content_ctrl

    left_evt = _DummyKeyEvent(mainframe.wx.WXK_LEFT, ctrl=True, shift=True)
    right_evt = _DummyKeyEvent(mainframe.wx.WXK_RIGHT, ctrl=True, shift=True)

    host.on_char_hook(left_evt)
    host.on_char_hook(right_evt)

    assert host.calls == []
    assert left_evt.skipped is True
    assert right_evt.skipped is True


def test_mainframe_ctrl_arrows_do_not_override_text_navigation_when_content_focused():
    host = _DummyMain()
    player = _PlayerStub()
    host.player_window = player
    host._focus = host.content_ctrl

    left_evt = _DummyKeyEvent(mainframe.wx.WXK_LEFT, ctrl=True)
    right_evt = _DummyKeyEvent(mainframe.wx.WXK_RIGHT, ctrl=True)
    up_evt = _DummyKeyEvent(mainframe.wx.WXK_UP, ctrl=True)
    down_evt = _DummyKeyEvent(mainframe.wx.WXK_DOWN, ctrl=True)

    host.on_char_hook(left_evt)
    host.on_char_hook(right_evt)
    host.on_char_hook(up_evt)
    host.on_char_hook(down_evt)

    assert player.calls == []
    assert left_evt.skipped is True
    assert right_evt.skipped is True
    assert up_evt.skipped is True
    assert down_evt.skipped is True
