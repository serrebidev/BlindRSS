"""Help > Report an issue on GitHub: the prefilled new-issue link."""
from gui import dialogs


def test_issue_url_carries_title_body_and_version():
    url = dialogs.issue_url("Photo & video", "Line 1\nПривет", "9.9.9")
    assert url.startswith(
        "https://github.com/serrebidev/BlindRSS/issues/new?title=Photo%20%26%20video&body=Line%201%0A%D0%9F"
    )
    assert "%0A---%0ABlindRSS%209.9.9%20on%20" in url
    assert not any(c in url for c in " \n#")


def test_report_issue_opens_prefilled_page_and_cancel_opens_nothing(monkeypatch):
    opened = []
    monkeypatch.setattr(dialogs.webbrowser, "open", opened.append)
    answers = iter([None])
    monkeypatch.setattr(dialogs, "_ask_issue_text", lambda *a: next(answers))
    dialogs.report_issue(None, "1.0")
    assert opened == []
    answers = iter(["Crash", "Steps"])
    dialogs.report_issue(None, "1.0")
    assert opened[0].startswith("https://github.com/serrebidev/BlindRSS/issues/new?title=Crash&body=Steps")
