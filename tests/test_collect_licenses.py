# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import collect_licenses


def test_requirement_names(tmp_path: Path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text(
        "# header\nbottle==0.13.4 \\\n    --hash=sha256:abc\npy-thing==1.0 ; sys_platform == 'win32'\n",
        encoding="utf-8",
    )
    assert collect_licenses.requirement_names(req) == ["bottle", "py-thing"]


def test_missing_package_is_reported() -> None:
    _, missing = collect_licenses.build_notice(["surely-not-installed-package-xyz"])
    assert any("surely-not-installed-package-xyz" in m for m in missing)


def test_notice_includes_installed_license(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collect_licenses, "python_license", lambda: "PSF LICENSE")
    text, missing = collect_licenses.build_notice(["pytest"])
    assert missing == []
    assert "pytest" in text
    assert "PSF LICENSE" in text


def test_main_fails_without_dist(tmp_path: Path) -> None:
    assert collect_licenses.main(["--dist", str(tmp_path / "missing")]) == 1


def test_vendored_license_fallback(tmp_path: Path) -> None:
    (tmp_path / "some-pkg.txt").write_text("BSD text", encoding="utf-8")
    assert collect_licenses.vendored_license("Some-Pkg", tmp_path) == [("some-pkg.txt", "BSD text")]
    assert collect_licenses.vendored_license("other", tmp_path) == []


def test_proxy_tools_license_is_vendored() -> None:
    assert collect_licenses.vendored_license("proxy-tools") != []
