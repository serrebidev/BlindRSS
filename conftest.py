import os
from pathlib import Path


def _can_use_temp_base(path: Path) -> bool:
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            return True
        except OSError:
            return False
    if not path.is_dir():
        return False
    try:
        with os.scandir(path):
            return True
    except OSError:
        return False


def pytest_configure(config):
    raw_basetemp = getattr(config.option, "basetemp", None)
    if not raw_basetemp:
        return

    base = Path(raw_basetemp)
    if not base.is_absolute():
        base = Path.cwd() / base

    if _can_use_temp_base(base):
        return

    # Some Windows runs leave this repo-local temp base owned by an elevated
    # context. Keep pytest repo-local by falling back to a sibling directory.
    parent = base.parent
    fallback = parent / f"{base.name}-fallback"
    if _can_use_temp_base(fallback):
        config.option.basetemp = str(fallback)
        return

    config.option.basetemp = str(parent / f"{base.name}-{os.getpid()}")
