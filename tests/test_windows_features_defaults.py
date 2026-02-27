from core.config import DEFAULT_CONFIG
from core import windows_integration


def test_default_sort_and_notification_settings():
    assert DEFAULT_CONFIG.get("article_sort_by") == "date"
    assert bool(DEFAULT_CONFIG.get("article_sort_ascending", True)) is False
    assert bool(DEFAULT_CONFIG.get("windows_notifications_enabled", True)) is False
    assert int(DEFAULT_CONFIG.get("windows_notifications_max_per_refresh", -1)) == 0
    assert DEFAULT_CONFIG.get("windows_notifications_excluded_feeds", None) == []
    assert bool(DEFAULT_CONFIG.get("start_on_windows_login", True)) is False
    assert bool(DEFAULT_CONFIG.get("translation_enabled", True)) is False
    assert str(DEFAULT_CONFIG.get("translation_provider", "")) == "grok"
    assert str(DEFAULT_CONFIG.get("translation_target_language", "")) == "en"
    assert str(DEFAULT_CONFIG.get("translation_grok_model", "x")) == ""
    assert str(DEFAULT_CONFIG.get("translation_grok_api_key", "x")) == ""
    assert str(DEFAULT_CONFIG.get("translation_groq_model", "x")) == ""
    assert str(DEFAULT_CONFIG.get("translation_groq_api_key", "x")) == ""
    assert str(DEFAULT_CONFIG.get("translation_openai_model", "x")) == ""
    assert str(DEFAULT_CONFIG.get("translation_openai_api_key", "x")) == ""
    assert str(DEFAULT_CONFIG.get("translation_openrouter_model", "x")) == ""
    assert str(DEFAULT_CONFIG.get("translation_openrouter_api_key", "x")) == ""
    assert str(DEFAULT_CONFIG.get("translation_gemini_model", "x")) == ""
    assert str(DEFAULT_CONFIG.get("translation_gemini_api_key", "x")) == ""
    assert str(DEFAULT_CONFIG.get("translation_qwen_model", "x")) == ""
    assert str(DEFAULT_CONFIG.get("translation_qwen_api_key", "x")) == ""


def test_windows_integration_launch_parts_script_mode(monkeypatch, tmp_path):
    fake_script = tmp_path / "main.py"
    fake_script.write_text("print('ok')", encoding="utf-8")

    monkeypatch.setattr(windows_integration.sys, "argv", [str(fake_script)], raising=False)
    monkeypatch.setattr(windows_integration.sys, "executable", r"C:\Python313\python.exe", raising=False)
    if hasattr(windows_integration.sys, "frozen"):
        monkeypatch.delattr(windows_integration.sys, "frozen", raising=False)

    target, args, working_dir, _icon = windows_integration.get_launch_parts()
    assert target.lower().endswith("python.exe") or target.lower().endswith("pythonw.exe")
    assert str(fake_script) in args
    assert working_dir == str(tmp_path)


def test_set_startup_enabled_returns_error_off_windows(monkeypatch):
    monkeypatch.setattr(windows_integration, "is_windows", lambda: False)
    ok, msg = windows_integration.set_startup_enabled(True)
    assert ok is False
    assert "windows" in (msg or "").lower()
