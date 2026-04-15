import os

from core import runtime_env


def test_configure_runtime_environment_adds_frozen_bin_dir(monkeypatch, tmp_path):
    app_dir = tmp_path / "BlindRSS.app" / "Contents" / "MacOS"
    frameworks_bin_dir = tmp_path / "BlindRSS.app" / "Contents" / "Frameworks" / "bin"
    frameworks_bin_dir.mkdir(parents=True)

    monkeypatch.setattr(runtime_env.sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(runtime_env.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_env.sys, "executable", str(app_dir / "BlindRSS"), raising=False)
    monkeypatch.setenv("PATH", "/usr/bin")

    runtime_env.configure_runtime_environment()

    assert os.environ["PATH"].split(os.pathsep)[0] == str(frameworks_bin_dir)


def test_configure_runtime_environment_sets_macos_vlc_vars(monkeypatch, tmp_path):
    app_dir = tmp_path / "BlindRSS.app" / "Contents" / "MacOS"
    frameworks_dir = tmp_path / "BlindRSS.app" / "Contents" / "Frameworks"
    lib_dir = frameworks_dir / "vlc" / "lib"
    plugin_dir = frameworks_dir / "vlc" / "plugins"
    lib_dir.mkdir(parents=True)
    plugin_dir.mkdir(parents=True)
    (lib_dir / "libvlc.dylib").write_text("", encoding="utf-8")

    monkeypatch.setattr(runtime_env.sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(runtime_env.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_env.sys, "executable", str(app_dir / "BlindRSS"), raising=False)
    monkeypatch.delenv("PYTHON_VLC_LIB_PATH", raising=False)
    monkeypatch.delenv("PYTHON_VLC_MODULE_PATH", raising=False)
    monkeypatch.delenv("DYLD_LIBRARY_PATH", raising=False)

    runtime_env.configure_runtime_environment()

    assert os.environ["PYTHON_VLC_LIB_PATH"] == str(lib_dir / "libvlc.dylib")
    assert os.environ["PYTHON_VLC_MODULE_PATH"] == str(plugin_dir)
    assert os.environ["DYLD_LIBRARY_PATH"].split(os.pathsep)[0] == str(lib_dir)


def test_configure_runtime_environment_sets_linux_vlc_vars_for_versioned_lib(monkeypatch, tmp_path):
    app_dir = tmp_path / "BlindRSS"
    lib_dir = app_dir / "vlc" / "lib"
    plugin_dir = app_dir / "vlc" / "plugins"
    lib_dir.mkdir(parents=True)
    plugin_dir.mkdir(parents=True)
    (lib_dir / "libvlc.so.12").write_text("", encoding="utf-8")

    monkeypatch.setattr(runtime_env.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(runtime_env.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_env.sys, "executable", str(app_dir / "BlindRSS"), raising=False)
    monkeypatch.delenv("PYTHON_VLC_LIB_PATH", raising=False)
    monkeypatch.delenv("PYTHON_VLC_MODULE_PATH", raising=False)
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)

    runtime_env.configure_runtime_environment()

    assert os.environ["PYTHON_VLC_LIB_PATH"] == str(lib_dir / "libvlc.so.12")
    assert os.environ["PYTHON_VLC_MODULE_PATH"] == str(plugin_dir)
    assert os.environ["LD_LIBRARY_PATH"].split(os.pathsep)[0] == str(lib_dir)
