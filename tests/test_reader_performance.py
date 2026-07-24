# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from gui.reader_performance import (
    LARGE_READER_TEXT_CHARS,
    replace_text_control_value,
    set_accessible_webview_content,
)


class _Control:
    def __init__(self, value=""):
        self.value = value
        self.get_calls = 0
        self.set_calls = 0
        self.change_calls = 0
        self.freeze_calls = 0
        self.thaw_calls = 0

    def GetValue(self):
        self.get_calls += 1
        return self.value

    def SetValue(self, value):
        self.set_calls += 1
        self.value = value

    def ChangeValue(self, value):
        self.change_calls += 1
        self.value = value

    def Freeze(self):
        self.freeze_calls += 1

    def Thaw(self):
        self.thaw_calls += 1


def test_small_reader_update_avoids_replacing_identical_text():
    control = _Control("same")
    assert replace_text_control_value(control, "same") is False
    assert control.get_calls == 1
    assert control.set_calls == 0


def test_large_reader_update_never_reads_or_truncates_existing_value():
    complete = "all text\n" * (LARGE_READER_TEXT_CHARS // 5)
    control = _Control("old")

    assert replace_text_control_value(control, complete) is True
    assert control.value == complete
    assert control.get_calls == 0
    assert control.set_calls == 0
    assert control.change_calls == 1
    assert control.freeze_calls == control.thaw_calls == 1


def test_typical_youtube_length_uses_large_update_path():
    complete = "subtitle line\n" * 1500
    control = _Control("old")

    replace_text_control_value(control, complete)

    assert len(complete) > LARGE_READER_TEXT_CHARS
    assert control.value == complete
    assert control.get_calls == 0
    assert control.change_calls == 1


def test_large_webview_update_is_async_complete_and_atomic():
    class _View:
        def __init__(self):
            self.scripts = []

        def RunScriptAsync(self, script):
            self.scripts.append(script)

    class _WebView:
        def __init__(self):
            self.view = _View()
            self._ready = True
            self.sync_calls = []

        def set_content(self, body):
            self.sync_calls.append(body)

    body = "<p>complete</p>" + ("x" * LARGE_READER_TEXT_CHARS) + "UNIQUE TAIL"
    webview = _WebView()

    assert set_accessible_webview_content(webview, body) is True
    assert not webview.sync_calls
    script = webview.view.scripts[0]
    assert "aria-busy" in script
    assert "replaceChildren" in script
    assert "UNIQUE TAIL" in script
