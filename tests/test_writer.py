"""
Unit tests for cam_core/writer.py.
"""
import io
from cam_core.cam_file import CAMFile
from cam_core.writer import write_output_file

TOOL_LINE = "(  TOOL 7 - Engraver - DESC: 0.060 DIA )\n"


def _make_file(name: str = "01-prep-01.nc", num_units: int = 1) -> CAMFile:
    f = CAMFile.from_lines(name, [TOOL_LINE, "G90\n", "G0 X1.0000 Y2.0000\n", "X0Y0\n"])
    f.create_unit_code(num_units, 4.0, "VERTICAL")
    return f


class TestWriteOutputFile:
    def test_begin_end_markers_present(self):
        buf = io.StringIO()
        f = _make_file("01-prep-01.nc")
        write_output_file(f, "01-prep-01.nc", buf, 1, 1, False, 7, False, 0.0, 4.0, "VERTICAL")
        out = buf.getvalue()
        assert "( BEGIN FILE 01-prep-01.nc" in out
        assert "( END FILE 01-prep-01.nc )" in out

    def test_metadata_lines_present(self):
        buf = io.StringIO()
        f = _make_file(num_units=2)
        write_output_file(f, "01-prep-01.nc", buf, 1, 2, True, 7, False, -22.8, 4.0, "VERTICAL")
        out = buf.getvalue()
        assert "Lefty:True" in out
        assert "Nunits:2" in out
        assert "cline: -22.8" in out
        assert "delta:4.0" in out

    def test_gcode_content_written(self):
        buf = io.StringIO()
        f = _make_file()
        write_output_file(f, "01-prep-01.nc", buf, 1, 1, False, 7, False, 0.0, 4.0, "VERTICAL")
        out = buf.getvalue()
        assert "G90" in out

    def test_home_suppressed_when_suppress_end_code(self):
        buf = io.StringIO()
        f = _make_file()
        write_output_file(f, "01-prep-01.nc", buf, 1, 1, False, 7, True, 0.0, 4.0, "VERTICAL")
        out = buf.getvalue()
        assert "G0 X2Y0" not in out

    def test_home_emitted_when_not_suppressed(self):
        buf = io.StringIO()
        f = _make_file()
        write_output_file(f, "01-prep-01.nc", buf, 1, 1, False, 7, False, 0.0, 4.0, "VERTICAL")
        out = buf.getvalue()
        assert "G0 X2Y0" in out
