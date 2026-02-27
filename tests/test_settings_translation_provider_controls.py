import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import gui.dialogs as dialogs


class _ChoiceStub:
    def __init__(self, selection):
        self._selection = str(selection)

    def GetStringSelection(self):
        return str(self._selection)


class _SizerStub:
    def __init__(self):
        self.calls = []

    def Show(self, row, show, recursive=True):
        self.calls.append((row, bool(show), bool(recursive)))


class _PanelStub:
    def __init__(self):
        self.layout_calls = 0
        self.refresh_calls = 0

    def Layout(self):
        self.layout_calls += 1

    def Refresh(self):
        self.refresh_calls += 1


class _Host:
    _update_translation_provider_controls = dialogs.SettingsDialog._update_translation_provider_controls

    def __init__(self, provider):
        self.translation_provider_ctrl = _ChoiceStub(provider)
        self._translation_layout_sizer = _SizerStub()
        self._translation_layout_panel = _PanelStub()
        self._translation_provider_rows = {
            "grok": ["grok_model", "grok_api"],
            "groq": ["groq_model", "groq_api"],
            "openai": ["openai_model", "openai_api"],
            "openrouter": ["openrouter_model", "openrouter_api"],
            "gemini": ["gemini_model", "gemini_api"],
            "qwen": ["qwen_model", "qwen_api"],
        }


def _shown_rows(calls):
    return {row for row, show, _recursive in calls if show}


def _hidden_rows(calls):
    return {row for row, show, _recursive in calls if not show}


def test_update_translation_provider_controls_shows_only_openai_rows():
    host = _Host("openai")
    host._update_translation_provider_controls()

    assert _shown_rows(host._translation_layout_sizer.calls) == {"openai_model", "openai_api"}
    assert _hidden_rows(host._translation_layout_sizer.calls) == {
        "grok_model",
        "grok_api",
        "groq_model",
        "groq_api",
        "openrouter_model",
        "openrouter_api",
        "gemini_model",
        "gemini_api",
        "qwen_model",
        "qwen_api",
    }
    assert host._translation_layout_panel.layout_calls == 1
    assert host._translation_layout_panel.refresh_calls == 1


def test_update_translation_provider_controls_falls_back_to_grok_for_unknown_provider():
    host = _Host("unknown-provider")
    host._update_translation_provider_controls()

    assert _shown_rows(host._translation_layout_sizer.calls) == {"grok_model", "grok_api"}


def test_update_translation_provider_controls_shows_only_qwen_rows():
    host = _Host("qwen")
    host._update_translation_provider_controls()

    assert _shown_rows(host._translation_layout_sizer.calls) == {"qwen_model", "qwen_api"}


def test_update_translation_provider_controls_shows_only_openrouter_rows():
    host = _Host("openrouter")
    host._update_translation_provider_controls()

    assert _shown_rows(host._translation_layout_sizer.calls) == {"openrouter_model", "openrouter_api"}


def test_update_translation_provider_controls_shows_only_groq_rows():
    host = _Host("groq")
    host._update_translation_provider_controls()

    assert _shown_rows(host._translation_layout_sizer.calls) == {"groq_model", "groq_api"}
