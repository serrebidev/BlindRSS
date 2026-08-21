# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Low-overhead updates for very large accessible reader text controls."""

from __future__ import annotations

import json


LARGE_READER_TEXT_CHARS = 16_384


def notify_reader_content_changed(control, *, tree_changed: bool = False) -> bool:
    """Tell assistive technology that an asynchronous reader update finished.

    wx normally emits accessibility events for direct user edits, but the
    article readers are read-only controls updated after a worker completes.
    VoiceOver can otherwise keep its earlier accessibility snapshot even
    though the native control or WebView now contains the full article.
    """
    try:
        import wx

        if tree_changed:
            parent = control.GetParent()
            wx.Accessible.NotifyEvent(
                wx.ACC_EVENT_OBJECT_REORDER,
                parent or control,
                wx.OBJID_CLIENT,
                wx.ACC_SELF,
            )
        wx.Accessible.NotifyEvent(
            wx.ACC_EVENT_OBJECT_VALUECHANGE,
            control,
            wx.OBJID_CLIENT,
            wx.ACC_SELF,
        )
        return True
    except Exception:
        return False


def replace_text_control_value(control, value: str) -> bool:
    """Replace a text control without copying or repainting huge values twice.

    ``TextCtrl.GetValue`` allocates a second Python string and walks the entire
    native RichEdit buffer. For transcripts and complete discussions that can
    be the most expensive UI-thread operation before ``SetValue`` even starts.
    Large values are known to be a completed asynchronous replacement, so use
    ``ChangeValue`` (no EVT_TEXT round trip) inside Freeze/Thaw and never read
    the old multi-megabyte buffer back. No content is shortened or omitted.
    """
    text = str(value or "")
    if len(text) < LARGE_READER_TEXT_CHARS:
        try:
            if control.GetValue() == text:
                return False
        except Exception:
            pass
        control.SetValue(text)
        return True

    frozen = False
    try:
        control.Freeze()
        frozen = True
    except Exception:
        pass
    try:
        changer = getattr(control, "ChangeValue", None)
        if callable(changer):
            changer(text)
        else:
            control.SetValue(text)
    finally:
        if frozen:
            try:
                control.Thaw()
            except Exception:
                pass
    return True


def set_accessible_webview_content(webview, html_body: str) -> bool:
    """Replace large WebView content without blocking wx's event loop.

    ``wx_accessible_webview`` 0.2 uses synchronous ``RunScript`` for content
    replacement.  WebView2 then parses the complete article and updates its
    accessibility tree before returning, which can stall both wx and NVDA.
    Keep the library's stable document, but queue large subtree replacements
    asynchronously and mark the subtree busy so assistive technology handles
    the mutation as one coherent update.  The HTML is passed in full.
    """
    body = str(html_body or "")
    view = getattr(webview, "view", None)
    ready = bool(getattr(webview, "_ready", False))
    runner = getattr(view, "RunScriptAsync", None) if view is not None else None
    if len(body) < LARGE_READER_TEXT_CHARS or not ready or not callable(runner):
        webview.set_content(body)
        return False

    payload = json.dumps(body)
    script = (
        "(function(h){"
        "var c=document.getElementById('content');"
        "if(!c){return false;}"
        "c.setAttribute('aria-busy','true');"
        "try{"
        "var t=document.createElement('template');"
        "t.innerHTML=h;"
        "c.replaceChildren(t.content.cloneNode(true));"
        "return true;"
        "}finally{c.setAttribute('aria-busy','false');}"
        f"}})({payload});"
    )
    runner(script)
    return True
