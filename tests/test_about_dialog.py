"""About BlindRSS: every project link is a button Tab reaches."""
import wx

from gui import dialogs


def test_about_links_are_tab_stops():
    app = wx.GetApp() or wx.App(False)
    dlg = dialogs.AboutDialog(None, "9.9.9")
    try:
        urls = [url for _btn, url in dlg.link_buttons]
        for expected in (
            "https://github.com/serrebidev/BlindRSS",
            "https://git.serrebiradio.com/serrebi/BlindRSS",
            "https://projects.serrebiradio.com",
            "https://t.me/SerrebiProjects",
            "https://git.serrebiradio.com/serrebi/BlindRSS/src/branch/main/CREDITS.md",
        ):
            assert expected in urls, expected
        assert all(btn.AcceptsFocus() for btn, _url in dlg.link_buttons)
    finally:
        dlg.Destroy()
    assert app
