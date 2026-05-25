from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIALOGS = ROOT / "gui" / "dialogs.py"


def test_settings_dialog_exposes_article_delete_confirmation_toggle():
    text = DIALOGS.read_text(encoding="utf-8")

    assert "confirm_article_delete" in text
    assert "Confirm before deleting articles" in text
