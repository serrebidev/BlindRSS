import subprocess
import tarfile
from pathlib import Path

import pytest


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "--quiet", "-b", "main")
    (tmp_path / "core").mkdir()
    (tmp_path / "core/version.py").write_bytes(b"VERSION = '1.0.0'\n")
    (tmp_path / ".gitignore").write_text("config.json\n")
    git("-c", "core.autocrlf=false", "add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--quiet", "-m", "initial")
    (tmp_path / "core/version.py").write_bytes(b"VERSION = '1.0.1'\n")
    (tmp_path / "config.json").write_text('private account data')
    (tmp_path / "untracked.txt").write_text('not staged')
    return tmp_path


def test_working_snapshot_uses_tracked_edits_without_private_files(repo, tmp_path):
    from tools.build_linux_wsl import write_snapshot

    snapshot = tmp_path / "working.tar"
    write_snapshot(repo, snapshot)
    with tarfile.open(snapshot) as archive:
        assert "config.json" not in archive.getnames()
        assert "untracked.txt" not in archive.getnames()
        assert archive.extractfile("core/version.py").read().decode().splitlines() == ["VERSION = '1.0.1'"]


def test_release_snapshot_uses_exact_commit_without_working_edits(repo, tmp_path):
    from tools.build_linux_wsl import write_snapshot

    snapshot = tmp_path / "release.tar"
    write_snapshot(repo, snapshot, "HEAD")
    with tarfile.open(snapshot) as archive:
        assert archive.extractfile("core/version.py").read().decode().splitlines() == ["VERSION = '1.0.0'"]
        assert "config.json" not in archive.getnames()


def test_linux_docker_dependencies_persist_between_containers():
    script = (Path(__file__).resolve().parents[1] / "tools/build_linux_docker.sh").read_text(encoding="utf-8")
    assert '--volume "blindrss-linux-pip-cache:/root/.cache/pip"' in script


def test_cleanup_failure_prevents_success():
    from tools.build_linux_wsl import BUILD

    assert "trap 'cleanup || exit 1' EXIT" in BUILD


def test_windows_release_uses_wsl_and_has_a_nonpublishing_linux_mode():
    script = (Path(__file__).resolve().parents[1] / "build.bat").read_text(encoding="utf-8")
    assert '"%MODE%"=="linux"' in script
    assert 'tools\\build_linux_wsl.py --verify' in script
    assert 'tools\\build_linux_wsl.py --ref "%VERSION_TAG%"' in script
    assert 'ssh -o BatchMode' not in script
