"""
Unit tests for CAMFile's coordinate/feed/speed/MOP extraction and cam_core/consistency_checks.py.
Uses CAMFile.from_lines() so no real .nc files are needed.
"""
from cam_core.cam_file import CAMFile
from cam_core.consistency_checks import (
    check_stale_headers,
    check_multi_op_files,
    check_below_zero,
    check_missing_tool,
    check_tool_consistency_within_feature,
    check_feed_speed_consistency_within_feature,
    check_clearance_plane_consistency_within_feature,
)


def _file(name, tool_num=7, tool_desc="Downcut PT125", min_z=0.15, max_z=4.0,
          feed=25.0, speed=11000, is_root=True, mop_name=None):
    mop = mop_name if mop_name is not None else name.rsplit(".", 1)[0]
    lines = [
        f"( MOP:  {mop} )\n",
        "G90\n",
        "(  BEGIN TOOL LIST )\n",
        f"(  TOOL {tool_num} - {tool_desc} - DESC: 0.500 DIA )\n",
        "(  ENDOF TOOL LIST )\n",
        f"T{tool_num:02d}\n",
        f"S{speed}\n",
        "M3\n",
        f"G0 Z{max_z:.4f}\n",
        "G0 X1.0000 Y1.0000\n",
        f"G1 X1.0000 Y1.0000 Z{min_z:.4f} F{feed}.\n",
    ]
    return CAMFile.from_lines(name, lines, is_root=is_root)


def _multi_op_file(name, segments, tool_num=17, tool_desc="Downcut 1.0mm PT0394"):
    """A file with several operations concatenated back-to-back sharing one TOOL
    declaration -- mirrors the real 02-inlay-Fangs-idPT09-s25PT5-02.nc pattern: an
    ( MOP: <first segment> ) header, one tool list, then a bare '( <segment>)' marker
    before each segment's G-code (including the first)."""
    stem = name.rsplit(".", 1)[0]
    lines = [
        f"( MOP:  {stem}{segments[0]} )\n",
        "G90\n",
        "(  BEGIN TOOL LIST )\n",
        f"(  TOOL {tool_num} - {tool_desc} - DESC: 0.500 DIA )\n",
        "(  ENDOF TOOL LIST )\n",
        f"T{tool_num:02d}\n",
        "S12000\n",
        "M3\n",
    ]
    for seg in segments:
        lines.append(f"( {stem}{seg})\n")
        lines.append("G0 X1.0000 Y1.0000\n")
        lines.append("G1 X1.0000 Y1.0000 Z0.1300 F25.\n")
    return CAMFile.from_lines(name, lines, is_root=True)


def _placeholder(name):
    return CAMFile.from_lines(name, ["( placeholder, no actions )\n"], is_root=True)


# ---------------------------------------------------------------------------
# CAMFile extraction
# ---------------------------------------------------------------------------

def test_placeholder_has_no_coordinates():
    f = _placeholder("00-unused.nc")
    assert f.has_coordinates() is False
    assert f.get_min_z() is None
    assert f.get_max_z() is None
    assert f.get_min_s() is None
    assert f.get_feed_rates() == frozenset()


def test_family_tag_computed_for_root_files_too():
    # get_feature_name() is "" for root files by design (CAMFeature toggle system only
    # applies to non-root feature files) -- get_family_tag() is the general-purpose one
    # the consistency checks use, and must work for root/base-step files too.
    f = _file("05-profile-s24PT75-nw43-Fender-T-NFrets21-01.nc", is_root=True)
    assert f.get_feature_name() == ""
    assert f.get_family_tag() != ""
    assert f.get_run_suffix() == "01"


# ---------------------------------------------------------------------------
# check_stale_headers
# ---------------------------------------------------------------------------

def test_stale_header_detected():
    f = _file("02-inlay-Dot6mm-idPT09-s24PT75.nc", mop_name="02-inlay-Dot6mm-idPT04-s24PT75")
    warnings = check_stale_headers([f])
    assert len(warnings) == 1
    assert "idPT04" in warnings[0]


def test_matching_header_is_silent():
    f = _file("02-inlay-Dot6mm-idPT09-s24PT75.nc")
    assert check_stale_headers([f]) == []


# ---------------------------------------------------------------------------
# check_below_zero
# ---------------------------------------------------------------------------

def test_below_zero_detected():
    f = _file("01-facing.nc", min_z=-0.05)
    warnings = check_below_zero([f])
    assert len(warnings) == 1
    assert "-0.05" in warnings[0]


def test_at_or_above_zero_is_silent():
    f = _file("01-facing.nc", min_z=0.0)
    assert check_below_zero([f]) == []


# ---------------------------------------------------------------------------
# check_missing_tool
# ---------------------------------------------------------------------------

def test_missing_tool_on_real_geometry_flagged():
    lines = ["( MOP:  broken )\n", "G90\n", "G0 X1.0000 Y1.0000\n", "G1 X2.0000 Y2.0000 Z0.1000 F25.\n"]
    f = CAMFile.from_lines("broken.nc", lines)
    warnings = check_missing_tool([f])
    assert len(warnings) == 1


def test_missing_tool_on_placeholder_is_silent():
    f = _placeholder("00-unused.nc")
    assert check_missing_tool([f]) == []


# ---------------------------------------------------------------------------
# family/run-suffix grouped checks -- filenames mirror the real Fingerboards-in
# naming convention (scale/radius/depth-code tokens that _family_key() strips out)
# ---------------------------------------------------------------------------

def test_tool_consistency_flags_mismatch_within_same_family_and_run():
    a = _file("05-profile-s24PT75-nw43-Fender-T-NFrets21-01.nc", tool_num=11, tool_desc="Downcut PT750 ROUGH")
    b = _file("05-profile-s25PT5-nw43-Fender-T-NFrets22-01.nc", tool_num=15, tool_desc="Fretkerf PT025")
    warnings = check_tool_consistency_within_feature([a, b])
    assert len(warnings) == 1
    assert "inconsistent tool" in warnings[0]


def test_tool_consistency_silent_when_matching():
    a = _file("05-profile-s24PT75-nw43-Fender-T-NFrets21-01.nc", tool_num=11, tool_desc="Downcut PT750 ROUGH")
    b = _file("05-profile-s25PT5-nw43-Fender-T-NFrets22-01.nc", tool_num=11, tool_desc="Downcut PT750 ROUGH")
    assert check_tool_consistency_within_feature([a, b]) == []


def test_tool_consistency_ignores_different_run_suffix():
    # -01 (rough) and -02 (finish) are expected to differ -- only files sharing the
    # same run-suffix should be compared against each other.
    a = _file("05-profile-s24PT75-nw43-Fender-T-NFrets21-01.nc", tool_num=11, tool_desc="Downcut PT750 ROUGH")
    b = _file("05-profile-s24PT75-nw43-Fender-T-NFrets21-02.nc", tool_num=5, tool_desc="Downcut PT375")
    assert check_tool_consistency_within_feature([a, b]) == []


def test_feed_speed_consistency_flags_mismatch():
    a = _file("01-backprep-Pins-s23-ftPT30-AnyCustomer-NOMIRROR.nc", feed=40.0, speed=11000)
    b = _file("01-backprep-Pins-s27-ftPT30-AnyCustomer-NOMIRROR.nc", feed=60.0, speed=11000)
    warnings = check_feed_speed_consistency_within_feature([a, b])
    assert len(warnings) == 1
    assert "inconsistent feed/speed" in warnings[0]


def test_clearance_plane_consistency_flags_mismatch():
    a = _file("01-backprep-AnyScale-ftPT30-01.nc", max_z=6.0)
    b = _file("01-backprep-s34-ftPT30-01.nc", max_z=4.0)
    warnings = check_clearance_plane_consistency_within_feature([a, b])
    assert len(warnings) == 1
    assert "inconsistent clearance plane" in warnings[0]


def test_no_warnings_on_a_fully_consistent_group():
    a = _file("01-backprep-face-pt19.nc", tool_num=1, tool_desc="Surface 2PT500", feed=50.0, speed=12000, max_z=2.0)
    b = _file("01-backprep-face-pt20.nc", tool_num=1, tool_desc="Surface 2PT500", feed=50.0, speed=12000, max_z=2.0)
    assert check_tool_consistency_within_feature([a, b]) == []
    assert check_clearance_plane_consistency_within_feature([a, b]) == []


# ---------------------------------------------------------------------------
# check_multi_op_files / multi-op-aware check_stale_headers
# ---------------------------------------------------------------------------

def test_multi_op_file_detected():
    f = _multi_op_file("02-inlay-Fangs-idPT09-s25PT5-02.nc", ["a", "b"])
    assert f.get_op_markers() == [
        "02-inlay-Fangs-idPT09-s25PT5-02a",
        "02-inlay-Fangs-idPT09-s25PT5-02b",
    ]
    warnings = check_multi_op_files([f])
    assert len(warnings) == 1
    assert "2 concatenated operations" in warnings[0]


def test_single_op_file_not_flagged_as_multi_op():
    f = _file("01-facing.nc")
    assert check_multi_op_files([f]) == []


def test_multi_op_normal_segment_naming_is_not_a_stale_header():
    # The MOP: header naturally says "<stem>a" for the first segment of a multi-op
    # file -- that's the expected pattern, not a stale/wrong header.
    f = _multi_op_file("02-inlay-Fangs-idPT09-s25PT5-02.nc", ["a", "b"])
    assert check_stale_headers([f]) == []


def test_multi_op_file_with_genuinely_wrong_header_is_still_flagged():
    # If the segment names don't even match the file's own name (beyond the trailing
    # letter), it's a real stale header, multi-op or not.
    f = _multi_op_file("02-inlay-Fangs-idPT09-s25PT5-02.nc", ["a", "b"])
    f._mop_name = "02-inlay-Fangs-idPT09-s24PT625-02a"  # wrong scale entirely
    warnings = check_stale_headers([f])
    assert len(warnings) == 1
