# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the camelot.barbican.rust.Rustup class."""

import subprocess
import sys

from pathlib import Path

import pytest

from camelot.barbican.rust import Rustup


_EXE = ".exe" if sys.platform == "win32" else ""

_VALID_CONFIG: dict = {
    "version": "1.85.0",
    "channel": "stable",
    "profile": "minimal",
    "targets": ["thumbv7em-none-eabihf"],
}


@pytest.fixture(scope="session")
def rustup_host_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Shared host_dir for all rustup tests in the session (created once)."""
    return tmp_path_factory.mktemp("sdk_host", numbered=False)


@pytest.fixture(scope="session")
def installed_rustup(
    rustup_host_dir: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> Rustup:
    """Install a real rustup environment once per session; reused by all tests."""
    dl_dir = tmp_path_factory.mktemp("sdk_dl", numbered=False)
    r = Rustup(_VALID_CONFIG, rustup_host_dir)
    r.install(dl_dir)
    return r


class TestRustupHostTarget:
    """Tests for platform-aware installer URL generation."""

    def test_host_target_tuple_nonempty(self) -> None:
        """Host target tuple must be a non-empty string."""
        assert Rustup._host_target_tuple()

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-specific check")
    def test_host_target_tuple_linux(self) -> None:
        """Host target tuple contains 'linux' on Linux."""
        assert "linux" in Rustup._host_target_tuple()

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific check")
    def test_host_target_tuple_macos(self) -> None:
        """Host target tuple contains 'apple-darwin' on macOS."""
        assert "apple-darwin" in Rustup._host_target_tuple()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific check")
    def test_host_target_tuple_windows(self) -> None:
        """Host target tuple contains 'windows' on Windows."""
        assert "windows" in Rustup._host_target_tuple()

    def test_installer_url_format(self) -> None:
        """Installer URL must point to the static.rust-lang.org distribution path."""
        url = Rustup._installer_url()
        assert url.startswith("https://static.rust-lang.org/rustup/dist/")
        assert "rustup-init" in url

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific check")
    def test_installer_url_windows_exe(self) -> None:
        """Installer URL must end with '.exe' on Windows."""
        assert Rustup._installer_url().endswith(".exe")

    @pytest.mark.skipif(sys.platform == "win32", reason="Non-Windows check")
    def test_installer_url_no_exe(self) -> None:
        """Installer URL must not end with '.exe' on non-Windows platforms."""
        assert not Rustup._installer_url().endswith(".exe")


class TestRustupPaths:
    """Tests for the ``cargo_home`` and ``rustup_home`` path properties."""

    def test_cargo_home(self, tmp_path: Path) -> None:
        """cargo_home must equal host_dir."""
        r = Rustup(_VALID_CONFIG, tmp_path)
        assert r.cargo_home == tmp_path

    def test_rustup_home(self, tmp_path: Path) -> None:
        """rustup_home must equal host_dir / 'share' / 'rustup'."""
        r = Rustup(_VALID_CONFIG, tmp_path)
        assert r.rustup_home == tmp_path / "share" / "rustup"


class TestRustupInstall:
    """Tests that verify a successfully installed rustup environment."""

    @pytest.mark.dependency(name="test_rustup_binary_exists")
    def test_rustup_binary_exists(self, installed_rustup: Rustup) -> None:
        """The rustup binary must exist and be executable after install."""
        rustup_bin = installed_rustup.cargo_home / "bin" / f"rustup{_EXE}"
        assert rustup_bin.exists(), f"rustup binary not found at {rustup_bin}"
        if sys.platform != "win32":
            assert rustup_bin.stat().st_mode & 0o111, "rustup binary is not executable"

    @pytest.mark.dependency(name="test_cargo_binary_exists")
    def test_cargo_binary_exists(self, installed_rustup: Rustup) -> None:
        """The cargo binary must exist after install."""
        cargo_bin = installed_rustup.cargo_home / "bin" / f"cargo{_EXE}"
        assert cargo_bin.exists(), f"cargo binary not found at {cargo_bin}"

    @pytest.mark.dependency(
        name="test_installed_version",
        depends=["test_rustup_binary_exists"],
    )
    def test_installed_version(self, installed_rustup: Rustup) -> None:
        """The configured toolchain version must appear in 'rustup toolchain list'."""
        result = subprocess.run(
            [str(installed_rustup.cargo_home / "bin" / f"rustup{_EXE}"), "toolchain", "list"],
            capture_output=True,
            text=True,
            check=True,
            env=installed_rustup._env(),
        )
        assert (
            "1.85.0" in result.stdout
        ), f"Version 1.85.0 not found in toolchain list:\n{result.stdout}"

    @pytest.mark.dependency(
        name="test_installed_target",
        depends=["test_rustup_binary_exists"],
    )
    def test_installed_target(self, installed_rustup: Rustup) -> None:
        """The configured cross-target must appear in 'rustup target list --installed'."""
        result = subprocess.run(
            [
                str(installed_rustup.cargo_home / "bin" / f"rustup{_EXE}"),
                "target",
                "list",
                "--installed",
            ],
            capture_output=True,
            text=True,
            check=True,
            env=installed_rustup._env(),
        )
        assert (
            "thumbv7em-none-eabihf" in result.stdout
        ), f"Target thumbv7em-none-eabihf not found in installed targets:\n{result.stdout}"


class TestRustupValidation:
    """Tests for eager validation and install failure handling."""

    def test_empty_targets_raises(self, tmp_path: Path) -> None:
        """Raise ValueError when the targets list is empty."""
        config = {"version": "1.85.0", "targets": []}
        with pytest.raises(ValueError, match="targets"):
            Rustup(config, tmp_path)

    def test_missing_version_raises(self, tmp_path: Path) -> None:
        """Raise ValueError when version key is absent."""
        config = {"targets": ["thumbv7em-none-eabihf"]}
        with pytest.raises(ValueError, match="version"):
            Rustup(config, tmp_path)

    def test_empty_version_raises(self, tmp_path: Path) -> None:
        """Raise ValueError when version is an empty string."""
        config = {"version": "", "targets": ["thumbv7em-none-eabihf"]}
        with pytest.raises(ValueError, match="version"):
            Rustup(config, tmp_path)

    def test_invalid_channel_raises(self, tmp_path: Path) -> None:
        """Raise ValueError when channel is not valid."""
        config = {
            "version": "1.85.0",
            "channel": "invalid_channel",
            "profile": "minimal",
            "targets": ["thumbv7em-none-eabihf"],
        }
        with pytest.raises(ValueError, match="RustupChannel"):
            Rustup(config, tmp_path)

    def test_invalid_profile_raises(self, tmp_path: Path) -> None:
        """Raise ValueError when profile is not valid."""
        config = {
            "version": "1.85.0",
            "channel": "stable",
            "profile": "invalid_profile",
            "targets": ["thumbv7em-none-eabihf"],
        }
        with pytest.raises(ValueError, match="RustupProfile"):
            Rustup(config, tmp_path)

    def test_invalid_version_install_raises(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        """Raise RuntimeError when the toolchain version does not exist on the server."""
        host_dir = tmp_path_factory.mktemp("invalid_ver_host")
        dl_dir = tmp_path_factory.mktemp("invalid_ver_dl")
        config = {
            "version": "0.0.0",
            "channel": "stable",
            "profile": "minimal",
            "targets": ["thumbv7em-none-eabihf"],
        }
        r = Rustup(config, host_dir)
        with pytest.raises(RuntimeError):
            r.install(dl_dir)

    def test_invalid_target_install_raises(
        self,
        installed_rustup: Rustup,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """Raise RuntimeError when an invalid target triple is requested."""
        # Reuse an already-installed host_dir to skip full re-install; only target add fails.
        host_dir = installed_rustup.cargo_home
        dl_dir = tmp_path_factory.mktemp("invalid_tgt_dl")
        config = {
            "version": "1.85.0",
            "channel": "stable",
            "profile": "minimal",
            "targets": ["invalid-not-a-real-target-triple"],
        }
        r = Rustup(config, host_dir)
        with pytest.raises(RuntimeError):
            r.install(dl_dir)
