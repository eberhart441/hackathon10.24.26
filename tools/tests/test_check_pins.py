"""Tests for tools/check_pins.py (Requirement 23.1). Uses tmp files only."""

import json

import pytest

from tools.check_pins import main, version_problem


def write_pkg(tmp_path, deps=None, dev=None):
    p = tmp_path / "package.json"
    p.write_text(
        json.dumps({"name": "x", "dependencies": deps or {}, "devDependencies": dev or {}}),
        encoding="utf-8",
    )
    return p


def write_req(tmp_path, text):
    p = tmp_path / "requirements.txt"
    p.write_text(text, encoding="utf-8")
    return p


GOOD_REQ = "# pinned\n\nfastapi==0.115.0\nuvicorn==0.30.6  # server\n"


@pytest.mark.parametrize(
    "version",
    ["1.2.3", "0.0.1", "10.4.0-beta.1", "1.0.0-rc.x1", "5.6.2+build.x"],
)
def test_exact_versions_pass(version):
    assert version_problem(version) is None


@pytest.mark.parametrize(
    "version",
    ["^1.2.3", "~1.2.3", ">1.0.0", ">=1.0.0", "<2", "<=2.0.0", "*", "x", "X",
     "1.x", "1.2.x", "1.X.0", "latest", "LATEST", "", "1.0.0 || 2.0.0", "1.0.0 - 2.0.0"],
)
def test_range_versions_fail(version):
    assert version_problem(version) is not None


def test_all_pinned_files_exit_zero(tmp_path):
    pkg = write_pkg(tmp_path, {"preact": "10.24.3"}, {"vite": "5.4.10"})
    req = write_req(tmp_path, GOOD_REQ)
    assert main([str(pkg), str(req)]) == 0


@pytest.mark.parametrize("section", ["deps", "dev"])
def test_caret_in_either_section_fails(tmp_path, section):
    bad = {"three": "^0.170.0"}
    pkg = write_pkg(tmp_path, **{section: bad})
    req = write_req(tmp_path, GOOD_REQ)
    assert main([str(pkg), str(req)]) == 1


@pytest.mark.parametrize("line", ["httpx", "httpx>=0.27", "httpx~=0.27.0", "httpx==0.27.*"])
def test_unpinned_requirement_fails(tmp_path, line):
    pkg = write_pkg(tmp_path, {"preact": "10.24.3"})
    req = write_req(tmp_path, GOOD_REQ + line + "\n")
    assert main([str(pkg), str(req)]) == 1


def test_comments_and_blanks_ignored(tmp_path):
    pkg = write_pkg(tmp_path)
    req = write_req(tmp_path, "\n   \n# httpx>=1\n  # another comment\npytest==8.3.3\n")
    assert main([str(pkg), str(req)]) == 0


def test_missing_file_fails(tmp_path):
    req = write_req(tmp_path, GOOD_REQ)
    assert main([str(tmp_path / "nope.json"), str(req)]) == 1
