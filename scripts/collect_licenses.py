# SPDX-License-Identifier: Apache-2.0
"""Collect the license texts of the bundled dependencies into the PyInstaller output folder.

Fails if any runtime dependency listed in requirements.txt has no license text, so a
release never goes out with incomplete third-party notices. Packages whose distribution
ships no license file can provide one in licenses/<name>.txt.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from importlib import metadata
from pathlib import Path

LICENSE_NAME = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.IGNORECASE)
VENDORED = Path(__file__).resolve().parent.parent / "licenses"
REQUIREMENT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==")
SOURCE_NOTES = {
    "pystray": "Licensed under the LGPL-3.0. Source code: https://github.com/moses-palmer/pystray",
}


def requirement_names(path: Path) -> list[str]:
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = REQUIREMENT.match(line.strip())
        if m:
            names.append(m.group(1))
    return names


def license_files(dist: metadata.Distribution) -> list[tuple[str, str]]:
    found = []
    for file in dist.files or []:
        if LICENSE_NAME.search(file.name) and ".dist-info" in str(file.parent):
            path = Path(file.locate())
            text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
            if text.strip():
                found.append((str(file), text))
    return found


def python_license() -> str | None:
    for candidate in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")
    return None


def vendored_license(name: str, folder: Path = VENDORED) -> list[tuple[str, str]]:
    path = folder / f"{name.lower()}.txt"
    if path.is_file():
        return [(path.name, path.read_text(encoding="utf-8"))]
    return []


def build_notice(names: list[str]) -> tuple[str, list[str]]:
    sections: list[str] = []
    missing: list[str] = []
    for name in names:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.append(f"{name} (not installed)")
            continue
        files = license_files(dist) or vendored_license(name)
        if not files:
            missing.append(name)
            continue
        header = f"{dist.metadata['Name']} {dist.version}"
        body = [header, "=" * len(header)]
        if name.lower() in SOURCE_NOTES:
            body.append(SOURCE_NOTES[name.lower()])
        for file_name, text in files:
            body += ["", f"--- {Path(file_name).name} ---", text.rstrip()]
        sections.append("\n".join(body))
    py = python_license()
    if py is None:
        missing.append("Python (LICENSE.txt not found)")
    else:
        version = ".".join(map(str, sys.version_info[:3]))
        sections.append(f"Python {version}\n{'=' * (7 + len(version))}\n\n{py.rstrip()}")
    text = "Third-party software bundled with topomask\n\n" + "\n\n\n".join(sections) + "\n"
    return text, missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", type=Path, default=Path("requirements.txt"))
    parser.add_argument("--dist", type=Path, default=Path("dist/topomask"))
    parser.add_argument("--license", type=Path, default=Path("LICENSE"))
    args = parser.parse_args(argv)

    if not args.dist.is_dir():
        print(f"error: {args.dist} does not exist; run PyInstaller first", file=sys.stderr)
        return 1
    text, missing = build_notice(requirement_names(args.requirements))
    if missing:
        print("error: no license file found for: " + ", ".join(missing), file=sys.stderr)
        return 1
    (args.dist / "THIRD_PARTY_LICENSES.txt").write_text(text, encoding="utf-8")
    shutil.copyfile(args.license, args.dist / "LICENSE")
    print(f"wrote {args.dist / 'THIRD_PARTY_LICENSES.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
