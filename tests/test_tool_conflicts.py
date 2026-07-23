"""
Unit tests for cam_core/tool_conflicts.py.
Uses CAMFile.from_lines() so no real .nc files are needed.
"""
from cam_core.cam_file import CAMFile
from cam_core.tool_conflicts import find_active_tool_conflicts, format_tool_conflicts


def _file(name: str, tool_num: int, tool_desc: str) -> CAMFile:
    lines = [
        f"(  TOOL {tool_num} - {tool_desc} - DESC: 0.500 DIA )\n",
        "G90\n",
        "G0 X1.0000 Y2.0000\n",
    ]
    return CAMFile.from_lines(name, lines, is_root=True)


def test_same_tool_same_description_is_never_a_conflict():
    a = _file("01-a.nc", 20, "Downcut 2MM")
    b = _file("02-b.nc", 20, "Downcut 2MM")
    conflicts = find_active_tool_conflicts([a, b], is_enabled=lambda f: True)
    assert conflicts == {}


def test_unused_alternate_description_is_not_a_conflict():
    # Several roundover options can legitimately share a tool slot -- only one is
    # ever active/output at a time, so the machine never sees the other description.
    active = _file("01-roundover-a.nc", 14, "0.5in 7/16 roundover")
    inactive = _file("02-roundover-b.nc", 14, "0.375in roundover")
    enabled = {active.name: True, inactive.name: False}
    conflicts = find_active_tool_conflicts([active, inactive], is_enabled=lambda f: enabled[f.name])
    assert conflicts == {}


def test_two_active_descriptions_on_same_tool_is_a_conflict():
    a = _file("01-a.nc", 17, "Undercut PT75")
    b = _file("02-b.nc", 17, "Drawer slotting mill .25")
    conflicts = find_active_tool_conflicts([a, b], is_enabled=lambda f: True)
    assert conflicts == {17: {a.get_tool().get_desc(), b.get_tool().get_desc()}}


def test_disabled_files_are_ignored_even_with_multiple_descriptions():
    a = _file("01-a.nc", 17, "Undercut PT75")
    b = _file("02-b.nc", 17, "Drawer slotting mill .25")
    conflicts = find_active_tool_conflicts([a, b], is_enabled=lambda f: False)
    assert conflicts == {}


def test_format_tool_conflicts_lists_each_tool_and_its_descriptions():
    conflicts = {17: {"Undercut PT75", "Drawer slotting mill .25"}}
    text = format_tool_conflicts(conflicts)
    assert "T17" in text
    assert "Undercut PT75" in text
    assert "Drawer slotting mill .25" in text
