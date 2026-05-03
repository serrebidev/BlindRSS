"""Shared libVLC option helpers."""


def build_vlc_instance_args(*args: str) -> tuple[str, ...]:
    """Return libVLC instance args with BlindRSS-safe defaults.

    On Windows, system VLC installs can leave an outdated plugins.dat cache after
    upgrades. libVLC logs one "stale plugins cache" line for every changed plugin
    when that cache is used. Disabling the plugin cache avoids that noisy startup
    path without requiring admin rights to regenerate Program Files metadata.
    """
    out: list[str] = []
    seen = set()
    for arg in ("--no-plugins-cache", *args):
        value = str(arg or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return tuple(out)
