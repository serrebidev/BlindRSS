from core.shortcuts import global_hotkey_spec


def test_default_ctrl_alt_b():
    assert global_hotkey_spec("Ctrl+Alt+B") == (0x1 | 0x2, ord("B"))


def test_function_key_and_win_modifier():
    assert global_hotkey_spec("F9") == (0, 0x78)
    assert global_hotkey_spec("Win+Shift+R") == (0x8 | 0x4, ord("R"))


def test_rejects_blank_typing_keys_and_garbage():
    assert global_hotkey_spec("") is None
    assert global_hotkey_spec("B") is None
    assert global_hotkey_spec("Shift+B") is None
    assert global_hotkey_spec("Ctrl+Alt+Left") is None
    assert global_hotkey_spec("Hyper+B") is None


def test_rejects_f12_and_non_ascii_keys():
    assert global_hotkey_spec("Ctrl+F12") is None
    assert global_hotkey_spec("Ctrl+\u00e9") is None
    assert global_hotkey_spec("Ctrl+\uff11") is None
    assert global_hotkey_spec("Ctrl+F11") == (0x2, 0x7A)


def test_settings_ok_blocks_unusable_hotkey(monkeypatch):
    import types

    from gui import dialogs

    shown = []
    monkeypatch.setattr(dialogs.wx, "MessageBox", lambda *a, **k: shown.append(a))

    class Ctrl:
        def __init__(self, value):
            self.value = value

        def GetValue(self):
            return self.value

        def GetParent(self):
            return None

        def SetFocus(self):
            pass

        def SelectAll(self):
            pass

    class Event:
        skipped = False

        def Skip(self):
            self.skipped = True

    for value, ok in (("Ctrl+F12", False), ("Ctrl+Alt+B", True), ("", True)):
        host = types.SimpleNamespace(global_hotkey_ctrl=Ctrl(value), notebook=None)
        ev = Event()
        shown.clear()
        dialogs.SettingsDialog._on_settings_ok(host, ev)
        assert ev.skipped is ok, value
        assert bool(shown) is not ok, value
