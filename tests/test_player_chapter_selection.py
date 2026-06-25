import pytest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

wx = pytest.importorskip("wx")
pytest.importorskip("vlc")

from gui.player import (
    PlayerFrame,
    _chapter_index_for_position,
    _format_chapter_timestamp,
    _validated_chapter_href,
)


class _DummyChoice:
    def __init__(self, selection: int = 0, client_data: dict | None = None):
        self._selection = int(selection)
        self._client_data = client_data or {0: {"start": 0.0}}
        self.items = []
        self.enabled = True
        self.name = ""

    def GetSelection(self):
        return int(self._selection)

    def GetClientData(self, idx):
        return self._client_data.get(int(idx))

    def SetSelection(self, idx):
        self._selection = int(idx)

    def Clear(self):
        self.items.clear()
        self._client_data.clear()
        self._selection = wx.NOT_FOUND

    def Append(self, label, data):
        idx = len(self.items)
        self.items.append(str(label))
        self._client_data[idx] = data

    def Enable(self):
        self.enabled = True

    def Disable(self):
        self.enabled = False

    def SetName(self, name):
        self.name = str(name)


class _DummyEvent:
    def __init__(self):
        self.skipped = False

    def Skip(self):
        self.skipped = True


class _DummyMenuItem:
    def __init__(self):
        self.enabled = None

    def Enable(self, enabled):
        self.enabled = bool(enabled)


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


def test_on_chapter_select_keeps_keyboard_browse_safe_when_closeup_supported():
    class _Frame:
        def __init__(self):
            self.chapter_choice = _DummyChoice(selection=2)
            self._chapter_closeup_supported = True
            self._chapter_pending_idx = None
            self.commit_calls = 0

        def _commit_chapter_selection(self):
            self.commit_calls += 1

    frame = _Frame()
    PlayerFrame.on_chapter_select(frame, None)

    assert frame._chapter_pending_idx == 2
    assert frame.commit_calls == 0


def test_on_chapter_select_commits_when_closeup_event_unavailable():
    class _Frame:
        def __init__(self):
            self.chapter_choice = _DummyChoice(selection=1)
            self._chapter_closeup_supported = False
            self._chapter_pending_idx = None
            self.commit_calls = 0

        def _commit_chapter_selection(self):
            self.commit_calls += 1

    frame = _Frame()
    PlayerFrame.on_chapter_select(frame, None)

    assert frame._chapter_pending_idx == 1
    assert frame.commit_calls == 1


def test_on_chapter_closeup_commits_selected_chapter():
    class _Frame:
        def __init__(self):
            self.commit_calls = 0

        def _commit_chapter_selection(self):
            self.commit_calls += 1

    frame = _Frame()
    event = _DummyEvent()

    PlayerFrame.on_chapter_closeup(frame, event)

    assert frame.commit_calls == 1
    assert event.skipped is True


def test_commit_chapter_selection_dedupes_back_to_back_commits():
    class _Frame:
        def __init__(self):
            self.chapter_choice = _DummyChoice(selection=0, client_data={0: {"start": 12.5}})
            self.is_casting = False
            self._chapter_last_commit_idx = None
            self._chapter_last_commit_ts = 0.0
            self.seek_calls = []
            self.note_calls = 0
            self.save_calls = 0

        def _note_user_seek(self):
            self.note_calls += 1

        def _apply_seek_time_ms(self, target_ms, force=False, reason=None):
            self.seek_calls.append((int(target_ms), bool(force), reason))

        def _schedule_resume_save_after_seek(self, delay_ms=0):
            self.save_calls += 1

    frame = _Frame()

    PlayerFrame._commit_chapter_selection(frame)
    PlayerFrame._commit_chapter_selection(frame)

    assert frame.seek_calls == [(12500, True, "chapter")]
    assert frame.note_calls == 1
    assert frame.save_calls == 1


def test_jump_to_chapter_index_selects_and_commits():
    class _Frame:
        def __init__(self):
            self.current_chapters = [{"start": 0.0}, {"start": 20.0}]
            self.chapter_choice = _DummyChoice(selection=0)
            self._chapter_pending_idx = None
            self.committed = 0

        def _commit_chapter_selection(self):
            self.committed += 1

    frame = _Frame()
    PlayerFrame._jump_to_chapter_index(frame, 1)

    assert frame.chapter_choice.GetSelection() == 1
    assert frame._chapter_pending_idx == 1
    assert frame.committed == 1


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("https://example.com/chapter", "https://example.com/chapter"),
        (" http://example.com/path?q=1 ", "http://example.com/path?q=1"),
        ("javascript:alert(1)", None),
        ("file:///tmp/chapter", None),
        ("https:///missing-host", None),
        ("https://example.com/\nunsafe", None),
        ("https://example.com/not safe", None),
        ("https://user:secret@example.com/chapter", None),
        (r"https://example.com\@evil.test/chapter", None),
        ("https://example.com:invalid/chapter", None),
        ("", None),
        (None, None),
    ],
)
def test_validated_chapter_href_allows_only_safe_web_urls(href, expected):
    assert _validated_chapter_href(href) == expected


def test_open_chapter_link_uses_selected_chapter_without_seeking(monkeypatch):
    opened = []

    class _Frame:
        current_chapters = [
            {"start": 0.0, "href": "https://example.com/active"},
            {"start": 30.0, "href": "https://example.com/selected"},
        ]
        chapter_choice = _DummyChoice(selection=1)

        def _active_chapter_index(self):
            return 0

        def _chapter_link_action_index(self):
            return PlayerFrame._chapter_link_action_index(self)

        def _chapter_href_at_index(self, idx):
            return PlayerFrame._chapter_href_at_index(self, idx)

        def _open_chapter_link_at_index(self, idx):
            return PlayerFrame._open_chapter_link_at_index(self, idx)

    monkeypatch.setattr(
        "gui.player.webbrowser.open",
        lambda href, new=0: opened.append((href, new)) or True,
    )
    frame = _Frame()

    assert PlayerFrame.open_chapter_link(frame) is True
    assert opened == [("https://example.com/selected", 2)]


def test_open_chapter_link_rejects_unsafe_href_without_launching(monkeypatch):
    opened = []

    class _Frame:
        current_chapters = [{"start": 0.0, "href": "javascript:alert(1)"}]
        chapter_choice = _DummyChoice(selection=0)

        def _chapter_href_at_index(self, idx):
            return PlayerFrame._chapter_href_at_index(self, idx)

        def _set_status(self, text):
            self.status = text

    monkeypatch.setattr(
        "gui.player.webbrowser.open",
        lambda *args, **kwargs: opened.append((args, kwargs)),
    )
    frame = _Frame()

    assert PlayerFrame._open_chapter_link_at_index(frame, 0) is False
    assert opened == []
    assert frame.status == "Chapter link unavailable"


def test_chapter_menu_enablement_tracks_active_direction_and_selected_href():
    class _Frame:
        def __init__(self):
            self.current_chapters = [
                {"start": 0.0, "href": "https://example.com/intro"},
                {"start": 30.0, "href": "javascript:alert(1)"},
                {"start": 60.0, "href": "https://example.com/end"},
            ]
            self.chapter_choice = _DummyChoice(selection=1)
            self.active_idx = 1
            self._chapter_menu_open_link_item = _DummyMenuItem()
            self._chapter_menu_prev_item = _DummyMenuItem()
            self._chapter_menu_next_item = _DummyMenuItem()

        def _active_chapter_index(self):
            return self.active_idx

        def _chapter_link_action_index(self):
            return PlayerFrame._chapter_link_action_index(self)

        def _chapter_href_at_index(self, idx):
            return PlayerFrame._chapter_href_at_index(self, idx)

    frame = _Frame()
    PlayerFrame._refresh_chapter_controls_state(frame)
    assert frame._chapter_menu_open_link_item.enabled is False
    assert frame._chapter_menu_prev_item.enabled is True
    assert frame._chapter_menu_next_item.enabled is True

    frame.chapter_choice.SetSelection(2)
    frame.active_idx = 2
    PlayerFrame._refresh_chapter_controls_state(frame)
    assert frame._chapter_menu_open_link_item.enabled is True
    assert frame._chapter_menu_prev_item.enabled is True
    assert frame._chapter_menu_next_item.enabled is False


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00"),
        (65.9, "01:05"),
        (3600, "1:00:00"),
        (360000, "100:00:00"),
        (-12, "00:00"),
        (float("nan"), "00:00"),
        (float("inf"), "00:00"),
    ],
)
def test_format_chapter_timestamp_handles_zero_long_and_invalid_values(seconds, expected):
    assert _format_chapter_timestamp(seconds) == expected


def test_chapter_index_tracks_playback_position_not_browsed_selection():
    chapters = [
        {"start": 0.0},
        {"start": 30.0},
        {"start": 90.0},
    ]

    assert _chapter_index_for_position(chapters, 0) == 0
    assert _chapter_index_for_position(chapters, 89_999) == 1
    assert _chapter_index_for_position(chapters, 90_000) == 2

    class _Frame:
        current_chapters = chapters
        chapter_choice = _DummyChoice(selection=2)

        def _current_position_ms(self):
            return 35_000

    assert PlayerFrame._active_chapter_index(_Frame()) == 1


def test_current_position_uses_cast_position_without_local_extrapolation(monkeypatch):
    class _Frame:
        is_casting = True
        is_playing = True
        _cast_last_pos_ms = 65_000
        _pos_ms = 10_000
        _pos_ts = 1.0
        _seek_target_ms = 20_000
        _seek_target_ts = 999.0
        duration = 60_000

    monkeypatch.setattr("gui.player.time.monotonic", lambda: 1_000.0)

    assert PlayerFrame._current_position_ms(_Frame()) == 60_000


def test_current_position_keeps_local_tracking_when_not_casting(monkeypatch):
    class _Frame:
        is_casting = False
        is_playing = True
        _pos_ms = 10_000
        _pos_ts = 99.0
        _seek_target_ms = None
        _seek_target_ts = 0.0
        duration = 60_000

    monkeypatch.setattr("gui.player.time.monotonic", lambda: 100.5)

    assert PlayerFrame._current_position_ms(_Frame()) == 11_500


def test_cast_timer_syncs_elapsed_chapter_accessibility_and_menu_boundaries():
    class _Casting:
        def __init__(self):
            self.positions = iter((65.0, 125.0))

        def get_position(self):
            return next(self.positions)

    class _Slider:
        def __init__(self):
            self.value = 0

        def SetValue(self, value):
            self.value = int(value)

    class _Frame:
        def __init__(self):
            self.is_casting = True
            self.casting_manager = _Casting()
            self._cast_poll_ts = 0.0
            self._cast_last_pos_ms = 0
            self._is_dragging_slider = False
            self.duration = 180_000
            self.current_chapters = [
                {"start": 0.0, "title": "Opening"},
                {"start": 60.0, "title": "Middle"},
                {"start": 120.0, "title": "Ending"},
            ]
            self.chapter_choice = _DummyChoice(selection=0)
            self.slider = _Slider()
            self._chapter_menu_open_link_item = _DummyMenuItem()
            self._chapter_menu_prev_item = _DummyMenuItem()
            self._chapter_menu_next_item = _DummyMenuItem()
            self.elapsed = None
            self.persist_calls = 0

        def _current_position_ms(self):
            return PlayerFrame._current_position_ms(self)

        def _format_time(self, position_ms):
            return PlayerFrame._format_time(self, position_ms)

        def _set_elapsed_time_label(self, value):
            self.elapsed = str(value)

        def _is_focus_in_chapter_choice(self):
            return False

        def _format_chapter_menu_label(self, chapter):
            return PlayerFrame._format_chapter_menu_label(self, chapter)

        def _update_chapter_accessibility_label(self, active_idx=None):
            return PlayerFrame._update_chapter_accessibility_label(self, active_idx)

        def _active_chapter_index(self):
            return PlayerFrame._active_chapter_index(self)

        def _chapter_link_action_index(self):
            return PlayerFrame._chapter_link_action_index(self)

        def _chapter_href_at_index(self, idx):
            return PlayerFrame._chapter_href_at_index(self, idx)

        def _refresh_chapter_controls_state(self):
            return PlayerFrame._refresh_chapter_controls_state(self)

        def _persist_playback_position(self, force=False):
            self.persist_calls += 1

    frame = _Frame()

    PlayerFrame.on_timer(frame, None)

    assert frame._cast_last_pos_ms == 65_000
    assert frame.elapsed == "01:05"
    assert frame.slider.value == 361
    assert frame.chapter_choice.GetSelection() == 1
    assert "current chapter 01:00  Middle" in frame.chapter_choice.name
    assert frame._chapter_menu_prev_item.enabled is True
    assert frame._chapter_menu_next_item.enabled is True

    frame._cast_poll_ts = 0.0
    PlayerFrame.on_timer(frame, None)

    assert frame._cast_last_pos_ms == 125_000
    assert frame.elapsed == "02:05"
    assert frame.chapter_choice.GetSelection() == 2
    assert "current chapter 02:00  Ending" in frame.chapter_choice.name
    assert frame._chapter_menu_prev_item.enabled is True
    assert frame._chapter_menu_next_item.enabled is False
    assert frame.persist_calls == 2


def test_update_chapters_normalizes_orders_labels_and_preserves_href():
    class _Frame:
        def __init__(self):
            self._active_load_seq = 4
            self.current_chapters = []
            self.chapter_choice = _DummyChoice()
            self._chapter_pending_idx = 2
            self._chapter_last_commit_idx = 2
            self._chapter_last_commit_ts = 5.0

        def _current_position_ms(self):
            return 3_700_000

        def _active_chapter_index(self):
            return PlayerFrame._active_chapter_index(self)

        def _format_chapter_menu_label(self, chapter):
            return PlayerFrame._format_chapter_menu_label(self, chapter)

        def _update_chapter_accessibility_label(self, active_idx=None):
            return PlayerFrame._update_chapter_accessibility_label(self, active_idx)

        def _refresh_chapter_controls_state(self):
            pass

    frame = _Frame()
    chapters = [
        {"start": 7205, "title": "Long chapter", "href": "https://example.com/long"},
        {"start": float("nan"), "title": "Opening", "href": "https://example.com/open"},
        {"start": 65, "title": ""},
    ]

    assert PlayerFrame.update_chapters(frame, chapters, load_seq=4) is True
    assert [chapter["start"] for chapter in frame.current_chapters] == [0.0, 65.0, 7205.0]
    assert frame.current_chapters[0]["href"] == "https://example.com/open"
    assert frame.chapter_choice.items == [
        "00:00  Opening",
        "01:05  Chapter at 01:05",
        "2:00:05  Long chapter",
    ]
    assert frame.chapter_choice.GetSelection() == 1
    assert frame.chapter_choice.name == (
        "Chapters, 3 available, current chapter 01:05  Chapter at 01:05"
    )


def test_update_chapters_rejects_stale_async_result():
    class _Frame:
        _active_load_seq = 8
        current_chapters = [{"start": 0.0, "title": "Current"}]
        chapter_choice = _DummyChoice()

    frame = _Frame()
    result = PlayerFrame.update_chapters(
        frame,
        [{"start": 0.0, "title": "Stale"}],
        load_seq=7,
    )

    assert result is False
    assert frame.current_chapters == [{"start": 0.0, "title": "Current"}]


def test_commit_chapter_selection_clamps_to_duration_and_updates_accessibility():
    class _Frame:
        def __init__(self):
            self.chapter_choice = _DummyChoice(
                selection=0,
                client_data={0: {"start": 120.0, "title": "After end"}},
            )
            self.current_chapters = [{"start": 120.0, "title": "After end"}]
            self.duration = 90_000
            self.is_casting = False
            self._chapter_last_commit_idx = None
            self._chapter_last_commit_ts = 0.0
            self.seek_calls = []

        def _note_user_seek(self):
            pass

        def _apply_seek_time_ms(self, target_ms, force=False, reason=None):
            self.seek_calls.append((target_ms, force, reason))

        def _schedule_resume_save_after_seek(self, delay_ms=0):
            pass

        def _format_chapter_menu_label(self, chapter):
            return PlayerFrame._format_chapter_menu_label(self, chapter)

        def _update_chapter_accessibility_label(self, active_idx=None):
            return PlayerFrame._update_chapter_accessibility_label(self, active_idx)

    frame = _Frame()
    PlayerFrame._commit_chapter_selection(frame)

    assert frame.seek_calls == [(90_000, True, "chapter")]
    assert "current chapter 02:00  After end" in frame.chapter_choice.name


def test_commit_chapter_selection_seeks_cast_playback():
    class _Casting:
        def __init__(self):
            self.calls = []

        def seek(self, seconds):
            self.calls.append(seconds)

    class _Frame:
        def __init__(self):
            self.chapter_choice = _DummyChoice(
                selection=0,
                client_data={0: {"start": 42.5, "title": "Answer"}},
            )
            self.current_chapters = [{"start": 42.5, "title": "Answer"}]
            self.duration = 0
            self.is_casting = True
            self.casting_manager = _Casting()
            self._chapter_last_commit_idx = None
            self._chapter_last_commit_ts = 0.0

        def _format_chapter_menu_label(self, chapter):
            return PlayerFrame._format_chapter_menu_label(self, chapter)

        def _update_chapter_accessibility_label(self, active_idx=None):
            return PlayerFrame._update_chapter_accessibility_label(self, active_idx)

    frame = _Frame()
    PlayerFrame._commit_chapter_selection(frame)

    assert frame.casting_manager.calls == [42.5]
    assert frame._cast_last_pos_ms == 42_500


def test_previous_and_next_chapter_navigation_use_playback_position():
    class _Frame:
        def __init__(self, active_idx):
            self.active_idx = active_idx
            self.current_chapters = [
                {"start": 0.0},
                {"start": 30.0},
                {"start": 60.0},
            ]
            self.jumps = []

        def _active_chapter_index(self):
            return self.active_idx

        def _jump_to_chapter_index(self, idx):
            self.jumps.append(idx)

    middle = _Frame(active_idx=1)
    PlayerFrame.on_prev_chapter(middle, None)
    PlayerFrame.on_next_chapter(middle, None)
    assert middle.jumps == [0, 2]

    boundaries = _Frame(active_idx=0)
    PlayerFrame.on_prev_chapter(boundaries, None)
    boundaries.active_idx = 2
    PlayerFrame.on_next_chapter(boundaries, None)
    assert boundaries.jumps == []


def test_next_chapter_navigation_starts_first_chapter_before_chapter_timeline():
    class _Frame:
        current_chapters = [{"start": 10.0}, {"start": 30.0}]

        def __init__(self):
            self.jumps = []

        def _active_chapter_index(self):
            return -1

        def _jump_to_chapter_index(self, idx):
            self.jumps.append(idx)

    frame = _Frame()
    PlayerFrame.on_next_chapter(frame, None)
    assert frame.jumps == [0]


def test_on_char_hook_shortcuts_move_between_chapters():
    class _Frame:
        def __init__(self):
            self.calls = []

        def _is_focus_in_chapter_choice(self):
            return False

        def prev_chapter(self):
            self.calls.append("prev")

        def next_chapter(self):
            self.calls.append("next")

    frame = _Frame()

    left_evt = _DummyKeyEvent(wx.WXK_LEFT, ctrl=True, shift=True)
    PlayerFrame.on_char_hook(frame, left_evt)
    right_evt = _DummyKeyEvent(wx.WXK_RIGHT, ctrl=True, shift=True)
    PlayerFrame.on_char_hook(frame, right_evt)

    assert frame.calls == ["prev", "next"]
    assert left_evt.skipped is False
    assert right_evt.skipped is False


def test_on_char_hook_ctrl_shift_l_opens_selected_chapter_link():
    class _Frame:
        def __init__(self):
            self.calls = []

        def open_chapter_link(self):
            self.calls.append("open-link")

    frame = _Frame()
    event = _DummyKeyEvent(ord("L"), ctrl=True, shift=True)

    PlayerFrame.on_char_hook(frame, event)

    assert frame.calls == ["open-link"]
    assert event.skipped is False


def test_on_char_hook_ctrl_arrows_trigger_volume_and_seek_actions():
    class _Frame:
        def __init__(self):
            self.calls = []
            self.volume_step = 7
            self.seek_back_ms = 11000
            self.seek_forward_ms = 15000
            self._media_hotkeys = _HotkeysStub()

        def _is_focus_in_chapter_choice(self):
            return False

        def is_audio_playing(self):
            return True

        def adjust_volume(self, delta):
            self.calls.append(("volume", int(delta)))

        def seek_relative_ms(self, delta):
            self.calls.append(("seek", int(delta)))

    frame = _Frame()

    PlayerFrame.on_char_hook(frame, _DummyKeyEvent(wx.WXK_UP, ctrl=True))
    PlayerFrame.on_char_hook(frame, _DummyKeyEvent(wx.WXK_DOWN, ctrl=True))
    PlayerFrame.on_char_hook(frame, _DummyKeyEvent(wx.WXK_LEFT, ctrl=True))
    PlayerFrame.on_char_hook(frame, _DummyKeyEvent(wx.WXK_RIGHT, ctrl=True))

    assert frame.calls == [
        ("volume", 7),
        ("volume", -7),
        ("seek", -11000),
        ("seek", 15000),
    ]


def test_on_char_hook_enter_commits_chapter_when_choice_has_focus():
    class _Frame:
        def __init__(self):
            self.commits = 0

        def _is_focus_in_chapter_choice(self):
            return True

        def _commit_chapter_selection(self):
            self.commits += 1

    frame = _Frame()
    PlayerFrame.on_char_hook(frame, _DummyKeyEvent(wx.WXK_RETURN))
    PlayerFrame.on_char_hook(frame, _DummyKeyEvent(wx.WXK_NUMPAD_ENTER))
    assert frame.commits == 2


def test_on_char_hook_ctrl_up_down_fallback_runs_when_hotkeys_returns_false():
    class _Frame:
        def __init__(self):
            self.calls = []
            self.volume_step = 4
            self.seek_back_ms = 10000
            self.seek_forward_ms = 10000
            self._media_hotkeys = _HotkeysAlwaysFalse()

        def _is_focus_in_chapter_choice(self):
            return False

        def has_media_loaded(self):
            return True

        def adjust_volume(self, delta):
            self.calls.append(("volume", int(delta)))

        def seek_relative_ms(self, delta):
            self.calls.append(("seek", int(delta)))

    frame = _Frame()
    PlayerFrame.on_char_hook(frame, _DummyKeyEvent(wx.WXK_UP, ctrl=True))
    PlayerFrame.on_char_hook(frame, _DummyKeyEvent(wx.WXK_DOWN, ctrl=True))

    assert frame.calls == [("volume", 4), ("volume", -4)]
