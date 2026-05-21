import os
import sys


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gui.mainframe as mainframe


class _Config:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)


class _StopAfterTick:
    def __init__(self, wait_results=None):
        self.wait_results = list(wait_results or [True])
        self.wait_intervals = []

    def is_set(self):
        return False

    def wait(self, interval):
        self.wait_intervals.append(interval)
        if self.wait_results:
            return self.wait_results.pop(0)
        return True


class _RefreshLoopHost:
    refresh_loop = mainframe.MainFrame.refresh_loop

    def __init__(self, *, refresh_on_startup=True, interval=30, wait_results=None):
        self.config_manager = _Config(
            {
                "refresh_on_startup": refresh_on_startup,
                "refresh_interval": interval,
            }
        )
        self.stop_event = _StopAfterTick(wait_results)
        self.refresh_calls = []

    def _run_refresh(self, block, force=False):
        self.refresh_calls.append({"block": bool(block), "force": bool(force)})
        return True


def test_refresh_loop_runs_startup_refresh_without_force_when_enabled():
    host = _RefreshLoopHost(refresh_on_startup=True, interval=30, wait_results=[True])

    host.refresh_loop()

    assert host.refresh_calls == [{"block": False, "force": False}]


def test_refresh_loop_periodic_refresh_is_not_forced_after_startup():
    host = _RefreshLoopHost(refresh_on_startup=True, interval=30, wait_results=[False, True])

    host.refresh_loop()

    assert host.refresh_calls == [
        {"block": False, "force": False},
        {"block": False, "force": False},
    ]


def test_refresh_loop_startup_disabled_waits_then_uses_normal_refresh():
    host = _RefreshLoopHost(refresh_on_startup=False, interval=30, wait_results=[False, True])

    host.refresh_loop()

    assert host.stop_event.wait_intervals[0] == 30
    assert host.refresh_calls == [{"block": False, "force": False}]
