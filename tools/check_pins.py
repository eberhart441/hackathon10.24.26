"""Dependency pin checker (pwa-dashboard Requirement 23.1).

Fails (exit 1) if any version in dashboard/package.json (dependencies and
devDependencies) uses a range (^, ~, >, <, *, x-range, latest), or if any
non-blank, non-comment line in hub/requirements.txt is not an exact `==` pin.

Usage:
    python tools/check_pins.py [PACKAGE_JSON] [REQUIREMENTS_TXT]

Paths default to the repo-root files, resolved relative to this script.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACKAGE_JSON = REPO_ROOT / "dashboard" / "package.json"
DEFAULT_REQUIREMENTS = REPO_ROOT / "hub" / "requirements.txt"

# An "x" counts only as a whole version component (x, 1.x, 1.2.X), not any letter x.
_X_RANGE = re.compile(r"(?:^|[.\s=v])[xX](?=$|[.\s])")
_RANGE_CHARS = ("^", "~", ">", "<", "*")
_PIP_BAD_OPERATORS = ("~=", "!=", ">", "<", "*")


def version_problem(version: str) -> str | None:
    """Return a reason string if an npm version spec is not exact, else None."""
    v = version.strip()
    if not v:
        return "empty version"
    if v.lower() == "latest":
        return "uses 'latest'"
    for ch in _RANGE_CHARS:
        if ch in v:
            return f"uses range operator '{ch}'"
    if "||" in v or " - " in v:
        return "uses a range expression"
    # Only the major.minor.patch core can be an x-range; prerelease/build tags may contain x.
    core = v.split("+", 1)[0].split("-", 1)[0]
    if _X_RANGE.search(core):
        return "uses x-range"
    return None


def check_package_json(path: Path) -> list[str]:
    """Return a list of error messages for non-exact versions in package.json."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    errors: list[str] = []
    for section in ("dependencies", "devDependencies"):
        deps = data.get(section) or {}
        for name, version in deps.items():
            if not isinstance(version, str):
                errors.append(f"{path}: {section}.{name}: version is not a string")
                continue
            reason = version_problem(version)
            if reason:
                errors.append(f"{path}: {section}.{name} = {version!r} {reason}")
    return errors


def check_requirements(path: Path) -> list[str]:
    """Return a list of error messages for requirements lines lacking an exact == pin."""
    errors: list[str] = []
    for lineno, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            errors.append(f"{path}:{lineno}: {raw.strip()!r} lacks '=='")
            continue
        for op in _PIP_BAD_OPERATORS:
            if op in line:
                errors.append(f"{path}:{lineno}: {raw.strip()!r} uses '{op}'")
                break
    return errors


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    package_json = Path(args[0]) if len(args) > 0 else DEFAULT_PACKAGE_JSON
    requirements = Path(args[1]) if len(args) > 1 else DEFAULT_REQUIREMENTS

    errors: list[str] = []
    for path, checker in ((package_json, check_package_json), (requirements, check_requirements)):
        if not path.is_file():
            errors.append(f"{path}: file not found")
            continue
        try:
            errors.extend(checker(path))
        except (OSError, ValueError) as exc:  # json.JSONDecodeError is a ValueError
            errors.append(f"{path}: could not read: {exc}")

    if errors:
        for err in errors:
            print(f"FAIL {err}", file=sys.stderr)
        return 1
    print("OK: all dependencies are exact-pinned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
