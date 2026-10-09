import pytest
import wx
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui.dialogs import YouTubeAccountDialog


class Config(dict):
    def set(self, key, value):
        self[key] = value


@pytest.mark.parametrize("route", ["button", "escape", "window"])
def test_account_dialog_closes_and_saves_options(route):
    # A fresh wx process avoids modal-loop interference from other GUI tests.
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), route],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def check_close(route):
    app = wx.GetApp() or wx.App(False)
    parent = wx.Frame(None)
    config = Config(youtube_account_refresh_token="test")
    dialog = YouTubeAccountDialog(parent, config, lambda *a: None, lambda *a: None)
    dialog.auto_add_chk.SetValue(False)
    timed_out = []

    def close():
        if route == "window":
            dialog.Close()  # EVT_CLOSE, including the title-bar and Alt+F4 paths
        else:
            button_id = dialog.GetEscapeId() if route == "escape" else next(
                c.GetId() for c in dialog.GetChildren()
                if isinstance(c, wx.Button) and c.GetLabel() == "Close"
            )
            event = wx.CommandEvent(wx.EVT_BUTTON.typeId, button_id)
            dialog.FindWindowById(button_id).GetEventHandler().ProcessEvent(event)

    def watchdog():
        timed_out.append(True)
        dialog.EndModal(wx.ID_ABORT)

    timer = wx.CallLater(100, close)
    guard = wx.CallLater(600, watchdog)
    try:
        dialog.ShowModal()
        assert not timed_out, "Close did not end the modal dialog"
        assert config["youtube_account_auto_add"] is False
        assert config["youtube_account_category"] == "YouTube"
        assert dialog._sign_in_token == 1
    finally:
        timer.Stop()
        guard.Stop()
        dialog.Destroy()
        parent.Destroy()
        wx.Yield()


if __name__ == "__main__":
    check_close(sys.argv[1])
