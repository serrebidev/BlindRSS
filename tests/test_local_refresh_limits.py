import os
import sys


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from providers import local as local_provider


def test_adaptive_refresh_worker_cap_tiers():
    assert local_provider._adaptive_refresh_worker_cap(1) == 1
    assert local_provider._adaptive_refresh_worker_cap(2) == 1
    assert local_provider._adaptive_refresh_worker_cap(3) == 2
    assert local_provider._adaptive_refresh_worker_cap(4) == 2
    assert local_provider._adaptive_refresh_worker_cap(5) == 3
    assert local_provider._adaptive_refresh_worker_cap(16) == 3


def test_compute_refresh_limits_low_cpu_clamps_aggressively():
    workers, per_host, adaptive_cap = local_provider._compute_refresh_limits(
        configured_workers=10,
        configured_per_host=4,
        feed_count=50,
        cpu_count=2,
    )
    assert workers == 1
    assert per_host == 1
    assert adaptive_cap == 1


def test_compute_refresh_limits_mid_cpu_uses_two_workers_and_one_per_host():
    workers, per_host, adaptive_cap = local_provider._compute_refresh_limits(
        configured_workers=10,
        configured_per_host=4,
        feed_count=50,
        cpu_count=4,
    )
    assert workers == 2
    assert per_host == 1
    assert adaptive_cap == 2


def test_compute_refresh_limits_high_cpu_caps_at_three_workers_and_two_per_host():
    workers, per_host, adaptive_cap = local_provider._compute_refresh_limits(
        configured_workers=10,
        configured_per_host=4,
        feed_count=50,
        cpu_count=8,
    )
    assert workers == 3
    assert per_host == 2
    assert adaptive_cap == 3


def test_compute_refresh_limits_respects_configured_lower_values_and_feed_count():
    workers, per_host, adaptive_cap = local_provider._compute_refresh_limits(
        configured_workers=2,
        configured_per_host=1,
        feed_count=1,
        cpu_count=8,
    )
    assert workers == 1
    assert per_host == 1
    assert adaptive_cap == 3
