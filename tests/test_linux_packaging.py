import pytest

from tools import linux_packaging


def test_package_architectures_for_x86_64():
    assert linux_packaging.package_architectures("x86_64") == ("amd64", "x86_64")


def test_package_architectures_for_arm64():
    assert linux_packaging.package_architectures("arm64") == ("arm64", "aarch64")


def test_package_architectures_rejects_unknown_arch():
    with pytest.raises(ValueError):
        linux_packaging.package_architectures("ppc64")


def test_artifact_paths_include_deb_and_rpm(tmp_path):
    artifacts = linux_packaging.artifact_paths(tmp_path, "1.2.3", "x86_64")
    assert artifacts.deb.name == "BlindRSS-linux-x86_64-v1.2.3.deb"
    assert artifacts.rpm.name == "BlindRSS-linux-x86_64-v1.2.3.rpm"


def test_launcher_uses_bundled_linux_runtime_paths():
    launcher = linux_packaging.render_launcher()
    assert 'APP_ROOT="/opt/BlindRSS"' in launcher
    assert 'export PATH="$APP_ROOT/bin:$PATH"' in launcher
    assert 'export PYTHON_VLC_MODULE_PATH="$VLC_PLUGIN_DIR"' in launcher
    assert 'exec "$APP_ROOT/BlindRSS" "$@"' in launcher


def test_debian_control_contains_expected_metadata():
    control = linux_packaging.render_debian_control("1.2.3", "amd64")
    assert "Package: blindrss" in control
    assert "Version: 1.2.3" in control
    assert "Architecture: amd64" in control
    assert "Maintainer: Brandon <serrebi101@gmail.com>" in control
    assert "Homepage: https://github.com/serrebi/BlindRSS" in control


def test_rpm_spec_contains_expected_paths():
    spec = linux_packaging.render_rpm_spec("1.2.3", "x86_64")
    assert "BuildArch:      x86_64" in spec
    assert "/opt/BlindRSS" in spec
    assert "/usr/bin/blindrss" in spec
    assert "/usr/share/applications/blindrss.desktop" in spec
