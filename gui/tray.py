import wx
import wx.adv

class BlindRSSTrayIcon(wx.adv.TaskBarIcon):
    def __init__(self, frame):
        super().__init__()
        self.frame = frame
        
        # Set Icon
        self.set_default_icon()
        
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DOWN, self.on_left_down)
        
    def set_default_icon(self):
        # Create a simple colored block icon
        icon_size = wx.SystemSettings.GetMetric(wx.SYS_ICON_X)
        if icon_size <= 0:
            icon_size = 32
        bmp = wx.Bitmap(icon_size, icon_size)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush("ORANGE"))
        dc.Clear()
        dc.SetTextForeground("WHITE")
        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        dc.SetFont(font)
        dc.DrawText("R", 2, 2)
        dc.SelectObject(wx.NullBitmap)
        
        icon = wx.Icon()
        icon.CopyFromBitmap(bmp)
        self.SetIcon(icon, "BlindRSS")

    def CreatePopupMenu(self):
        menu = wx.Menu()
        
        restore_item = menu.Append(wx.ID_ANY, "Restore")
        toggle_player_item = menu.Append(wx.ID_ANY, "Show/Hide Player")
        menu.AppendSeparator()
        
        refresh_item = menu.Append(wx.ID_ANY, "Refresh Feeds")
        menu.AppendSeparator()
        
        # Media Controls
        play_pause_item = menu.Append(wx.ID_ANY, "Play/Pause")
        stop_item = menu.Append(wx.ID_ANY, "Stop")
        rewind_item = menu.Append(wx.ID_ANY, "Rewind")
        forward_item = menu.Append(wx.ID_ANY, "Fast Forward")

        vol_up_item = menu.Append(wx.ID_ANY, "Volume Up")
        vol_down_item = menu.Append(wx.ID_ANY, "Volume Down")
        
        # Volume Submenu
        vol_menu = wx.Menu()
        for vol in [100, 80, 60, 40, 20, 5]:
            item = vol_menu.Append(wx.ID_ANY, f"{vol}%")
            self.Bind(wx.EVT_MENU, lambda e, v=vol: self.on_volume(v), item)
        menu.AppendSubMenu(vol_menu, "Volume")
        
        menu.AppendSeparator()
        exit_item = menu.Append(wx.ID_EXIT, "Exit")
        
        self.Bind(wx.EVT_MENU, self.on_restore, restore_item)
        self.Bind(wx.EVT_MENU, self.on_toggle_player, toggle_player_item)
        self.Bind(wx.EVT_MENU, self.on_refresh, refresh_item)
        self.Bind(wx.EVT_MENU, self.on_play_pause, play_pause_item)
        self.Bind(wx.EVT_MENU, self.on_stop, stop_item)
        self.Bind(wx.EVT_MENU, self.on_rewind, rewind_item)
        self.Bind(wx.EVT_MENU, self.on_forward, forward_item)
        self.Bind(wx.EVT_MENU, self.on_volume_up, vol_up_item)
        self.Bind(wx.EVT_MENU, self.on_volume_down, vol_down_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        
        return menu

    def on_left_down(self, event):
        self.on_restore(event)

    def on_restore(self, event):
        handler = getattr(self.frame, 'show_and_focus_main', None)
        if callable(handler):
            handler()
            return
        if self.frame.IsIconized():
            self.frame.Iconize(False)
        if not self.frame.IsShown():
            self.frame.Show()
        self.frame.Raise()

    def on_refresh(self, event):
        self.frame.on_refresh_feeds(None)

    def on_toggle_player(self, event):
        try:
            self.frame.toggle_player_visibility()
        except Exception:
            pass

    def on_play_pause(self, event):
        pw = getattr(self.frame, "player_window", None)
        if pw:
            try:
                pw.toggle_play_pause()
            except Exception:
                pass

    def on_stop(self, event):
        pw = getattr(self.frame, "player_window", None)
        if pw:
            pw.stop()

    def on_rewind(self, event):
        pw = getattr(self.frame, "player_window", None)
        if pw:
            try:
                pw.seek_relative_ms(-int(getattr(pw, "seek_back_ms", 10000)))
            except Exception:
                pass

    def on_forward(self, event):
        pw = getattr(self.frame, "player_window", None)
        if pw:
            try:
                pw.seek_relative_ms(int(getattr(pw, "seek_forward_ms", 10000)))
            except Exception:
                pass

    def on_volume_up(self, event):
        pw = getattr(self.frame, "player_window", None)
        if pw:
            try:
                pw.adjust_volume(int(getattr(pw, "volume_step", 5)))
            except Exception:
                pass

    def on_volume_down(self, event):
        pw = getattr(self.frame, "player_window", None)
        if pw:
            try:
                pw.adjust_volume(-int(getattr(pw, "volume_step", 5)))
            except Exception:
                pass

    def on_volume(self, vol):
        pw = getattr(self.frame, "player_window", None)
        if pw:
            pw.set_volume_percent(vol, persist=True)

    def on_exit(self, event):
        self.RemoveIcon()
        self.frame.real_close()

    def show_notification(self, title: str, message: str, timeout_ms: int = 10000) -> bool:
        """Best-effort native tray notification on Windows."""
        try:
            if hasattr(self, "ShowBalloon"):
                return bool(self.ShowBalloon(str(title or "BlindRSS"), str(message or ""), int(timeout_ms), wx.ICON_INFORMATION))
        except Exception:
            return False
        return False
