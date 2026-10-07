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
