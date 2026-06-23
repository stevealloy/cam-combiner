"""
pytest configuration and dynamic parametrization for multi-directory tests.

Usage
-----
Default (searches Testing/ inside the project):
    python -m pytest tests/ -v

Point at a real CAM job folder containing *-in directories:
    python -m pytest tests/ -v --base-dir "G:/Shared drives/.../MyJob"
"""
from pathlib import Path
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--base-dir",
        default=None,
        metavar="DIR",
        help=(
            "Root directory to search for *-in input directories. "
            "Defaults to the project's Testing/ folder."
        ),
    )


def _collect_pairs(config) -> list[tuple]:
    """Return (in_dir, session_json_or_None) pairs.

    For each *-in directory that has *.json files in the matching *-out
    directory, one pair is produced per JSON.  If no JSON files exist the
    directory is still covered with a single (in_dir, None) pair so tests
    run with default params.
    """
    raw = config.getoption("--base-dir")
    base = Path(raw) if raw else Path(__file__).parent.parent / "Testing"

    if not base.is_dir():
        return []

    in_dirs = sorted(
        d for d in base.iterdir()
        if d.is_dir()
        and d.name.endswith("-in")
        and (d / "fixture_config.txt").exists()
    )

    pairs: list[tuple] = []
    for d in in_dirs:
        out_dir = d.parent / (d.name[:-3] + "-out")   # *-in → *-out
        jsons = sorted(out_dir.glob("*.json")) if out_dir.is_dir() else []
        if jsons:
            pairs.extend((d, j) for j in jsons)
        else:
            pairs.append((d, None))
    return pairs


def pytest_generate_tests(metafunc):
    """Parametrize tests that declare in_dir (and optionally session_json)."""
    if "in_dir" not in metafunc.fixturenames:
        return

    pairs = _collect_pairs(metafunc.config)

    if "session_json" in metafunc.fixturenames:
        ids = [
            f"{d.name}/{j.stem}" if j else d.name
            for d, j in pairs
        ]
        metafunc.parametrize(["in_dir", "session_json"], pairs, ids=ids)
    else:
        # Tests that only declare in_dir get one run per unique directory.
        seen: dict = {}
        for d, _ in pairs:
            seen.setdefault(d, None)
        dirs = list(seen)
        metafunc.parametrize("in_dir", dirs, ids=[d.name for d in dirs])
