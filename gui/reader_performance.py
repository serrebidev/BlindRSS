"""Low-overhead updates for very large accessible reader text controls."""

from __future__ import annotations


LARGE_READER_TEXT_CHARS = 100_000


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
