# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import logging
import os
import sys
import time

import wx

log = logging.getLogger(__name__)


def _open_clipboard(clipboard=None, *, attempts: int = 3, delay_s: float = 0.05) -> bool:
    clipboard = clipboard or wx.TheClipboard
    attempts = max(1, int(attempts or 1))
    for attempt in range(attempts):
        try:
            if clipboard.Open():
                return True
        except Exception:
            log.debug("Failed to open clipboard", exc_info=True)
        if attempt + 1 < attempts:
            time.sleep(max(0.0, float(delay_s or 0.0)))
    return False


def copy_text_to_clipboard(text: str, *, flush: bool = True) -> bool:
    """Copy text and flush it so it survives abrupt process shutdown on Windows."""
    if text is None:
        return False

    clipboard = wx.TheClipboard
    if not _open_clipboard(clipboard):
        return False

    try:
        if clipboard.SetData(wx.TextDataObject(str(text))) is False:
            return False
        if flush:
            try:
                flushed = clipboard.Flush()
            except Exception:
                log.debug("Failed to flush clipboard", exc_info=True)
                return False
            return flushed is not False
        return True
    finally:
        try:
            clipboard.Close()
        except Exception:
            log.debug("Failed to close clipboard", exc_info=True)


def get_textctrl_selection_text(ctrl) -> str:
    try:
        text = ctrl.GetStringSelection()
        if text:
            return str(text)
    except Exception:
        pass

    try:
        start, end = ctrl.GetSelection()
        if start == end:
            return ""
        return str(ctrl.GetRange(start, end) or "")
    except Exception:
        return ""


def copy_textctrl_selection_to_clipboard(ctrl) -> bool:
    text = get_textctrl_selection_text(ctrl)
    if not text:
        return False
    return copy_text_to_clipboard(text, flush=True)


def _windows_clipboard_owner_belongs_to_current_process() -> bool:
    if not sys.platform.startswith("win"):
        return False

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.GetClipboardOwner.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        owner = user32.GetClipboardOwner()
        if not owner:
            return False

        pid = wintypes.DWORD()
        if not user32.GetWindowThreadProcessId(owner, ctypes.byref(pid)):
            return False
        return int(pid.value) == os.getpid()
    except Exception:
        log.debug("Could not identify Windows clipboard owner", exc_info=True)
        return False


def persist_owned_text_clipboard() -> bool:
    """Materialize app-owned text clipboard data before tearing down wx controls."""
    if not _windows_clipboard_owner_belongs_to_current_process():
        return False

    clipboard = wx.TheClipboard
    if not _open_clipboard(clipboard):
        return False

    try:
        data = wx.TextDataObject()
        if not clipboard.GetData(data):
            return False
        text = data.GetText()
        if text is None:
            return False
        if clipboard.SetData(wx.TextDataObject(str(text))) is False:
            return False
        flushed = clipboard.Flush()
        return flushed is not False
    except Exception:
        log.debug("Failed to persist owned text clipboard", exc_info=True)
        return False
    finally:
        try:
            clipboard.Close()
        except Exception:
            log.debug("Failed to close clipboard", exc_info=True)
