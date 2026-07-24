# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

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
    _translation_provider_key_from_ui = dialogs.SettingsDialog._translation_provider_key_from_ui

    def __init__(self, provider):
        self.translation_provider_ctrl = _ChoiceStub(provider)
        self._translation_layout_sizer = _SizerStub()
        self._translation_layout_panel = _PanelStub()
        self._translation_provider_display_to_key = {}
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


# ---------------------------------------------------------------------------
# Announcements tab (issue #67): dropdown -> {event_id: mode} collection
# ---------------------------------------------------------------------------

from core import announcements as _ann


class _ModeChoiceStub:
    def __init__(self, index):
        self._index = int(index)

    def GetSelection(self):
        return self._index


class _AnnouncementHost:
    _collect_announcement_modes = dialogs.SettingsDialog._collect_announcement_modes

    def __init__(self, selections):
        # selections: {event_id: mode_index}
        self._announcement_mode_values = list(_ann.MODE_ORDER)
        self._announcement_choice_ctrls = {
            eid: _ModeChoiceStub(idx) for eid, idx in selections.items()
        }


def test_collect_announcement_modes_reads_dropdowns():
    idx = {m: i for i, m in enumerate(_ann.MODE_ORDER)}
    host = _AnnouncementHost(
        {
            "filter_change": idx["none"],
            "status_toggle": idx["speech"],
            "playback_speed": idx["braille"],
            "media_navigation": idx["both"],
        }
    )
    out = host._collect_announcement_modes()
    # Explicit selections are honored...
    assert out["filter_change"] == "none"
    assert out["status_toggle"] == "speech"
    assert out["playback_speed"] == "braille"
    assert out["media_navigation"] == "both"
    # ...and unlisted events are filled with the default (both).
    assert out["start_update"] == _ann.MODE_BOTH
    assert set(out) == {e.id for e in _ann.iter_events()}
