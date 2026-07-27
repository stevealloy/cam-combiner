"""
Unit tests for cam_core/file_order.py.
Uses CAMFile.from_lines() so no real .nc files are needed.
"""
from cam_core.cam_file import CAMFile
from cam_core.file_order import apply_order_override

TOOL_LINE = "(  TOOL 3 - Test Bit - DESC: 0.125 DIA )\n"


def _file(name: str) -> CAMFile:
    return CAMFile.from_lines(name, [TOOL_LINE, "G90\n"], is_root=True)


def test_no_override_leaves_by_step_untouched():
    a, b = _file("01-a.nc"), _file("01-b.nc")
    by_step = {"01": [a, b]}
    assert apply_order_override(by_step, {}) == by_step


def test_step_with_no_matching_override_entry_untouched():
    a, b = _file("01-a.nc"), _file("01-b.nc")
    by_step = {"01": [a, b]}
    assert apply_order_override(by_step, {"02": ["x.nc"]}) == by_step


def test_override_reverses_order():
    a, b, c = _file("01-a.nc"), _file("01-b.nc"), _file("01-c.nc")
    by_step = {"01": [a, b, c]}
    result = apply_order_override(by_step, {"01": ["01-c.nc", "01-b.nc", "01-a.nc"]})
    assert result["01"] == [c, b, a]


def test_files_not_in_override_are_appended_in_default_order():
    # Only "b" has an explicit position -- "a" and "c" aren't in the override
    # (e.g. they're new since the override was saved) and should land after
    # every overridden file, keeping their original relative order.
    a, b, c = _file("01-a.nc"), _file("01-b.nc"), _file("01-c.nc")
    by_step = {"01": [a, b, c]}
    result = apply_order_override(by_step, {"01": ["01-b.nc"]})
    assert result["01"] == [b, a, c]


def test_override_entry_for_a_file_no_longer_present_is_ignored():
    a = _file("01-a.nc")
    by_step = {"01": [a]}
    result = apply_order_override(by_step, {"01": ["01-gone.nc", "01-a.nc"]})
    assert result["01"] == [a]


def test_multiple_steps_ordered_independently():
    a1, b1 = _file("01-a.nc"), _file("01-b.nc")
    a2, b2 = _file("02-a.nc"), _file("02-b.nc")
    by_step = {"01": [a1, b1], "02": [a2, b2]}
    result = apply_order_override(by_step, {"01": ["01-b.nc", "01-a.nc"]})
    assert result["01"] == [b1, a1]
    assert result["02"] == [a2, b2]
