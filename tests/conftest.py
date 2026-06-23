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


def _collect_in_dirs(config) -> list[Path]:
    """Return all *-in subdirectories that contain a fixture_config.txt."""
    raw = config.getoption("--base-dir")
    if raw:
        base = Path(raw)
    else:
        base = Path(__file__).parent.parent / "Testing"

    if not base.is_dir():
        return []

    return sorted(
        d for d in base.iterdir()
        if d.is_dir()
        and d.name.endswith("-in")
        and (d / "fixture_config.txt").exists()
    )


def pytest_generate_tests(metafunc):
    """Parametrize any test that declares an `in_dir` fixture."""
    if "in_dir" not in metafunc.fixturenames:
        return

    dirs = _collect_in_dirs(metafunc.config)
    metafunc.parametrize("in_dir", dirs, ids=[d.name for d in dirs])
