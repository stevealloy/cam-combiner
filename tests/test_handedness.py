"""
Unit tests for cam_core/handedness.py.
Uses CAMFile.from_lines() so no real .nc files are needed.
"""
from cam_core.cam_file import CAMFile
from cam_core.handedness import find_handedness_orphans, format_handedness_orphans

TOOL_LINE = "(  TOOL 3 - Test Bit - DESC: 0.125 DIA )\n"


def _file(name: str) -> CAMFile:
    return CAMFile.from_lines(name, [TOOL_LINE, "G90\n"], is_root=True)


def test_matched_pair_is_never_an_orphan_either_direction():
    lefty = _file("04-back-carve-01-lefty.nc")
    righty = _file("04-back-carve-01-righty.nc")
    by_step = {"04": [lefty, righty]}

    assert find_handedness_orphans(by_step, lefty=True) == []
    assert find_handedness_orphans(by_step, lefty=False) == []


def test_neutral_file_with_no_suffix_is_never_an_orphan():
    neutral = _file("05-neutral-op.nc")
    by_step = {"05": [neutral]}

    assert find_handedness_orphans(by_step, lefty=True) == []
    assert find_handedness_orphans(by_step, lefty=False) == []


def test_lefty_only_file_is_an_orphan_on_a_righty_run():
    lefty_only = _file("11-Full-body-StandardT-01-righty-pt01.nc".replace("righty", "lefty"))
    by_step = {"11": [lefty_only]}

    # Righty run (lefty=False) needs a -righty counterpart that doesn't exist.
    assert find_handedness_orphans(by_step, lefty=False) == [lefty_only]
    # Lefty run (lefty=True) already has the side it needs -- no orphan.
    assert find_handedness_orphans(by_step, lefty=True) == []


def test_righty_only_file_is_an_orphan_on_a_lefty_run():
    righty_only = _file("11-Full-body-StandardT-01-righty-pt01.nc")
    by_step = {"11": [righty_only]}

    assert find_handedness_orphans(by_step, lefty=True) == [righty_only]
    assert find_handedness_orphans(by_step, lefty=False) == []


def test_orphan_in_one_step_does_not_pair_with_counterpart_in_another_step():
    lefty_step1 = _file("01-thing-lefty.nc")
    righty_step2 = _file("02-thing-righty.nc")
    by_step = {"01": [lefty_step1], "02": [righty_step2]}

    # Same base name, but different steps -- not a real pair, so both are orphans
    # for the run that needs their missing counterpart.
    assert find_handedness_orphans(by_step, lefty=False) == [lefty_step1]
    assert find_handedness_orphans(by_step, lefty=True) == [righty_step2]


def test_format_handedness_orphans_names_the_missing_side_and_files():
    orphan = _file("04-back-carve-01-lefty.nc")
    text = format_handedness_orphans([orphan], lefty=False)
    assert "-righty" in text
    assert "04-back-carve-01-lefty.nc" in text
