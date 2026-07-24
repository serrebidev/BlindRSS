# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import wx
import time
import threading

class TestFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Scroll Position Test", size=(400, 600))
        self.panel = wx.Panel(self)
        self.list_ctrl = wx.ListCtrl(self.panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list_ctrl.InsertColumn(0, "Item", width=300)
        
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        
        self.btn_load_more = wx.Button(self.panel, label="Load More / Append")
        self.btn_load_more.Bind(wx.EVT_BUTTON, self.on_load_more)
        self.sizer.Add(self.btn_load_more, 0, wx.ALL, 5)
        
        self.panel.SetSizer(self.sizer)
        
        # Populate initial list
        self.items = [f"Item {i}" for i in range(20)]
        self._populate()
        
        wx.CallLater(100, self.run_test)

    def run_test(self):
        print("Running test...")
        self.on_load_more(None)
        wx.CallLater(500, self.Close)
        
    def _populate(self):
        self.list_ctrl.DeleteAllItems()
        for i, item in enumerate(self.items):
            self.list_ctrl.InsertItem(i, item)

    def on_load_more(self, event):
        # Simulate loading more items
        # Current logic (Broken): Freeze -> DeleteAll -> Append -> Restore Focus -> Thaw
        
        # Capture "state" (Top item is better than focused item for visual stability)
        top_idx = self.list_ctrl.GetTopItem()
        top_text = self.list_ctrl.GetItemText(top_idx) if top_idx != -1 else None
        
        print(f"Top item before refresh: {top_idx} ({top_text})")
        
        new_items = [f"Item {i}" for i in range(len(self.items), len(self.items) + 20)]
        self.items.extend(new_items)
        
        self.list_ctrl.Freeze()
        self.list_ctrl.DeleteAllItems()
        
        for i, item in enumerate(self.items):
            self.list_ctrl.InsertItem(i, item)
            
        # Attempt restoration (Naive/Broken way simulates current code)
        # In current code: Focus restoration happens here, inside Freeze/Thaw
        
        self.list_ctrl.Thaw()
        
        # Fix Proposal:
        # Restore scroll position AFTER Thaw, via CallAfter/EnsureVisible
        if top_text:
             wx.CallAfter(self._restore_scroll, top_text)

    def _restore_scroll(self, target_text):
        # Find index of target_text
        count = self.list_ctrl.GetItemCount()
        target_idx = -1
        for i in range(count):
            if self.list_ctrl.GetItemText(i) == target_text:
                target_idx = i
                break
        
        if target_idx != -1:
            print(f"Restoring scroll to item: {target_idx} ({target_text})")
            # EnsureVisible brings it into view, but not necessarily to the TOP.
            # But it's better than jumping to top (index 0).
            self.list_ctrl.EnsureVisible(target_idx)
            
            # To force it to top is harder in wx.ListCtrl without native calls, 
            # but EnsureVisible usually puts it at bottom if scrolling down, or top if scrolling up.
            # Since we cleared list (pos 0), EnsureVisible(N) usually puts N at bottom of view.
            
            # Try to scroll a bit further down then up? No.
            # The most reliable standard wx way is EnsureVisible.

if __name__ == "__main__":
    app = wx.App()
    frame = TestFrame()
    frame.Show()
    app.MainLoop()
