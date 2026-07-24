# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from providers import local as local_provider


def test_adaptive_refresh_worker_cap_tiers():
    assert local_provider._adaptive_refresh_worker_cap(1) == 8
    assert local_provider._adaptive_refresh_worker_cap(2) == 8
    assert local_provider._adaptive_refresh_worker_cap(3) == 16
    assert local_provider._adaptive_refresh_worker_cap(4) == 16
    assert local_provider._adaptive_refresh_worker_cap(5) == 24
    assert local_provider._adaptive_refresh_worker_cap(8) == 24
    assert local_provider._adaptive_refresh_worker_cap(16) == 32


def test_compute_refresh_limits_low_cpu_clamps_aggressively():
    workers, per_host, adaptive_cap = local_provider._compute_refresh_limits(
        configured_workers=10,
        configured_per_host=4,
        feed_count=50,
        cpu_count=2,
    )
    assert workers == 8
    assert per_host == 2
    assert adaptive_cap == 8


def test_compute_refresh_limits_mid_cpu_passes_through_configured_workers():
    workers, per_host, adaptive_cap = local_provider._compute_refresh_limits(
        configured_workers=10,
        configured_per_host=4,
        feed_count=50,
        cpu_count=4,
    )
    assert workers == 10
    assert per_host == 4
    assert adaptive_cap == 16


def test_compute_refresh_limits_high_cpu_passes_through_configured_workers():
    workers, per_host, adaptive_cap = local_provider._compute_refresh_limits(
        configured_workers=10,
        configured_per_host=4,
        feed_count=50,
        cpu_count=8,
    )
    assert workers == 10
    assert per_host == 4
    assert adaptive_cap == 24


def test_compute_refresh_limits_respects_configured_lower_values_and_feed_count():
    workers, per_host, adaptive_cap = local_provider._compute_refresh_limits(
        configured_workers=2,
        configured_per_host=1,
        feed_count=1,
        cpu_count=8,
    )
    assert workers == 1
    assert per_host == 1
    assert adaptive_cap == 24
