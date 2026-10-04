import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize(("feed", "override", "expected"), [
    ("3.0.25", "", "3.0.25"),
    ("../../unsafe", "", "3.0.24"),
    ("", "", "3.0.24"),
    ("3.0.25", "3.0.26", "3.0.26"),
])
def test_macos_vlc_stable_discovery(feed, override, expected):
    bash = shutil.which("bash")
    if os.name == "nt":
        git_bash = Path("C:/Program Files/Git/bin/bash.exe")
        bash = str(git_bash) if git_bash.exists() else bash
    if not bash:
        pytest.skip("Bash is required for the macOS build-script check")
    script = (Path(__file__).resolve().parents[1] / "build.sh").read_text(encoding="utf-8")
    start = script.index('  local vlc_version="${BLINDRSS_VLC_VERSION:-}"')
    end = script.index("  local vlc_arch", start)
    curl = f"curl() {{ printf '%s\\n' '{feed}'; }}" if feed else "curl() { return 22; }"
    check = curl + "\ncheck() {\n" + script[start:end] + '\nprintf "%s" "$vlc_version"\n}\ncheck\n'
    env = dict(os.environ, BLINDRSS_VLC_VERSION=override)
    result = subprocess.run([bash, "-s"], input=check, text=True, capture_output=True, env=env, check=True)
    assert result.stdout == expected
