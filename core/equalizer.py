# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Pure helpers for the media-player equalizer config.

The libVLC calls live in the GUI/player layer; this module only normalizes and
clamps the persisted config so it stays testable without vlc.

Config shape (stored in config.json under "equalizer"):

    {
        "enabled": bool,
        "preamp": float,          # dB, clamped to [AMP_MIN, AMP_MAX]
        "bands": [float, ...],    # BAND_COUNT gains in dB, each clamped
        "preset": str | None,     # name of the last applied preset, for the UI
    }
"""
from __future__ import annotations

from typing import Dict, List, Optional

# libVLC's equalizer exposes a fixed 10-band graphic EQ. Amps clamp to VLC's
# documented [-20, +20] dB range.
BAND_COUNT = 10
AMP_MIN = -20.0
AMP_MAX = 20.0

# The center frequencies libVLC actually uses for its 10 bands (Hz). These are
# the values libvlc_audio_equalizer_get_band_frequency() reports; the GUI queries
# libVLC at runtime and falls back to these. (The old display list — 60/170/310…
# — did not match what the engine filters, so the sliders were mislabeled.)
BAND_FREQUENCIES = [31.25, 62.5, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


def format_band_label(freq) -> str:
    """Human label for a band center frequency, e.g. '500 Hz' or '16 kHz'."""
    try:
        f = float(freq)
    except Exception:
        return ""
    if f >= 1000:
        return "%g kHz" % (f / 1000.0)
    return "%g Hz" % f


def clamp_amp(value) -> float:
    try:
        v = float(value)
    except Exception:
        return 0.0
    if v != v:  # NaN
        return 0.0
    return max(AMP_MIN, min(AMP_MAX, round(v, 1)))


def flat_config() -> Dict:
    return {
        "enabled": False,
        "preamp": 0.0,
        "bands": [0.0] * BAND_COUNT,
        "preset": None,
    }


def normalize_config(cfg: Optional[Dict]) -> Dict:
    """Coerce arbitrary input into a well-formed, clamped equalizer config."""
    if not isinstance(cfg, dict):
        return flat_config()

    bands_in = cfg.get("bands")
    bands: List[float] = []
    if isinstance(bands_in, (list, tuple)):
        for v in bands_in[:BAND_COUNT]:
            bands.append(clamp_amp(v))
    while len(bands) < BAND_COUNT:
        bands.append(0.0)

    preset = cfg.get("preset")
    preset = str(preset) if isinstance(preset, str) and preset.strip() else None

    return {
        "enabled": bool(cfg.get("enabled", False)),
        "preamp": clamp_amp(cfg.get("preamp", 0.0)),
        "bands": bands,
        "preset": preset,
    }


def is_flat(cfg: Optional[Dict]) -> bool:
    c = normalize_config(cfg)
    return c["preamp"] == 0.0 and all(b == 0.0 for b in c["bands"])


# --------------------------------------------------------------------------
# User-defined presets (stored in config under "equalizer_user_presets")
#
# Each preset is {"name": str, "preamp": float, "bands": [float, ...]}. These
# helpers are pure so the save/rename/delete rules stay testable without a
# player. Names are matched case-insensitively; upsert overwrites in place.
# --------------------------------------------------------------------------

def normalize_user_presets(raw) -> List[Dict]:
    """Coerce stored user presets into a clean, de-duplicated list."""
    out: List[Dict] = []
    if not isinstance(raw, (list, tuple)):
        return out
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        c = normalize_config({"preamp": item.get("preamp", 0.0), "bands": item.get("bands", [])})
        out.append({"name": name, "preamp": c["preamp"], "bands": list(c["bands"])})
    return out


def upsert_user_preset(raw, name: str, preamp, bands) -> List[Dict]:
    """Return the preset list with `name` added or overwritten (clamped)."""
    presets = normalize_user_presets(raw)
    name = str(name or "").strip()
    if not name:
        return presets
    presets = [p for p in presets if p["name"].lower() != name.lower()]
    c = normalize_config({"preamp": preamp, "bands": bands})
    presets.append({"name": name, "preamp": c["preamp"], "bands": list(c["bands"])})
    return presets


def remove_user_preset(raw, name: str) -> List[Dict]:
    """Return the preset list with `name` removed (case-insensitive)."""
    presets = normalize_user_presets(raw)
    name = str(name or "").strip()
    if not name:
        return presets
    return [p for p in presets if p["name"].lower() != name.lower()]
