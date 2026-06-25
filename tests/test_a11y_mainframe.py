"""Main-window accessibility behavior.

Covers the platform-gated "Add Shortcuts..." File-menu item. Desktop/Start
Menu/Taskbar shortcuts are Windows-only concepts (the dialog is disabled off
Windows; the macOS equivalent, start at login, lives in Settings), so the item
must be hidden on macOS while staying available on Windows/Linux.

The accessible names given to the tree/list/search/content controls are verified
live with VoiceOver during integration; constructing the full ``MainFrame`` here
is avoided because it starts background threads/refresh.
"""

import gui.mainframe as mainframe


def test_add_shortcuts_hidden_on_macos():
    assert mainframe.should_show_add_shortcuts("darwin") is False


def test_add_shortcuts_shown_on_windows_and_linux():
    assert mainframe.should_show_add_shortcuts("win32") is True
    assert mainframe.should_show_add_shortcuts("linux") is True


def test_add_shortcuts_uses_current_platform_by_default(monkeypatch):
    monkeypatch.setattr(mainframe.sys, "platform", "darwin")
    assert mainframe.should_show_add_shortcuts() is False
    monkeypatch.setattr(mainframe.sys, "platform", "win32")
    assert mainframe.should_show_add_shortcuts() is True
