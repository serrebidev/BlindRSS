import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe
from core.config import DEFAULT_CONFIG


class _DummyConfig:
    def __init__(self, prompt_enabled=True):
        self._prompt_enabled = bool(prompt_enabled)

    def get(self, key, default=None):
        if key == "prompt_missing_dependencies_on_startup":
            return self._prompt_enabled
        return default


class _DummyMainFrame:
    _check_media_dependencies = mainframe.MainFrame._check_media_dependencies

    def __init__(self, prompt_enabled=True):
        self.config_manager = _DummyConfig(prompt_enabled=prompt_enabled)
        self.status_calls = []

    def SetStatusText(self, text):
        self.status_calls.append(str(text))

    def _install_dependencies_thread(self, *args, **kwargs):
        return None


def test_default_config_prompts_for_missing_dependencies_on_startup():
    assert bool(DEFAULT_CONFIG.get("prompt_missing_dependencies_on_startup", False)) is True


def test_media_dependency_prompt_can_be_disabled(monkeypatch):
    host = _DummyMainFrame(prompt_enabled=False)

    def _unexpected_check():
        raise AssertionError("media dependency status check should be skipped when prompt is disabled")

    def _unexpected_message_box(*args, **kwargs):
        raise AssertionError("message box should not be shown when prompt is disabled")

    monkeypatch.setattr(mainframe.dependency_check, "check_media_tools_status", _unexpected_check)
    monkeypatch.setattr(mainframe.wx, "MessageBox", _unexpected_message_box)

    host._check_media_dependencies()


def test_media_dependency_prompt_still_shows_when_enabled(monkeypatch):
    host = _DummyMainFrame(prompt_enabled=True)
    captured = {}
    monkeypatch.setattr(mainframe.sys, "platform", "win32")

    monkeypatch.setattr(
        mainframe.dependency_check,
        "check_media_tools_status",
        lambda: (True, True, False),
    )

    def _fake_message_box(msg, title, flags):
        captured["msg"] = str(msg)
        captured["title"] = str(title)
        captured["flags"] = flags
        return mainframe.wx.NO

    monkeypatch.setattr(mainframe.wx, "MessageBox", _fake_message_box)

    host._check_media_dependencies()

    assert captured["title"] == "Install Dependencies"
    assert "VLC Media Player" in captured["msg"]
    assert "FFmpeg" in captured["msg"]
    assert "disable this prompt" in captured["msg"]
