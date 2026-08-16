from __future__ import annotations
from cam_core.Tool import Tool
from cam_core.debug import debug_print

import os
import re
import shutil
import tempfile

_MOP_RE = re.compile(r"\(\s*MOP:\s*(.*?)\s*\)")
# A bare "( <name>)" comment with no other content -- used as an operation-boundary
# marker. A file that only has one is a normal single-op file (its marker usually
# repeats the MOP: name). A file with more than one is several operations concatenated
# back-to-back sharing one TOOL declaration (only the first gets an ( MOP: ... ) line;
# later ones just get their own bare marker), which is worth knowing about separately
# from a genuinely stale ( MOP: ... ) header.
_OP_MARKER_RE = re.compile(r"^\(\s([A-Za-z0-9][A-Za-z0-9_.]*(?:-[A-Za-z0-9_.]+)*)\)\s*$")
_X_RE = re.compile(r"X(-?[0-9]+\.?[0-9]*)")
_Y_RE = re.compile(r"Y(-?[0-9]+\.?[0-9]*)")
_Z_RE = re.compile(r"Z(-?[0-9]+\.?[0-9]*)")
_F_RE = re.compile(r"F([0-9]+\.?[0-9]*)")
_S_RE = re.compile(r"(?:^|\s)S([0-9]+)")

# units numbered across X first, then step Y
class Unit:
    def __init__(self, unit_number:int, clineX:float, deltaX:float, clineY:float, deltaY:float):
        self._unit_number = unit_number
        self.clineX = clineX
        self.deltaX = deltaX
        self.clineY = clineY
        self.deltaY = deltaY




class CAMFile:
    def __init__(self, name: str, directory: str, is_root: bool, cached: dict = None):
        if directory == ".":
            directory = os.getcwd()
        # directory = directory.replace("\\","/")

        self._debug = False
        self.name = name
        self._dir = directory
        self._is_root = is_root
        # True for a root file whose is_root came from ROOT-PASSTHROUGH-DIRS
        # rather than sitting loose in the actual base/shared root -- lets the
        # GUI identify bulk-generated files (thousands, from e.g. ParamBuilder)
        # to hide by default without changing base-file matching semantics.
        # Set by planner.py::_scan_files_int after construction, not here.
        self._is_passthrough_dir = False
        # self._dir = Path(directory)

        self.max_x = -999.99
        self.min_x = 999.99
        self.max_y = -999.99
        self.min_y = 999.99
        self.max_z = -999.99
        self.min_z = 999.99
        self.min_s = 100000
        self.max_s = 0
        self.filename = self._dir + "\\" + self.name

        # extracted from self.name
        self._step = "00"

        self._run_suffix = None

        # determine the appropriate step for this file.
        # Root/base files: the leading step prefix always wins -- any letter is
        # accepted here, matching jsonc_loader.normalize_legacy()'s OUTPUT-FILE-NAMES
        # step regex, both sides must agree on what counts as a step prefix, or a
        # file can match an output entry's pattern but still get bucketed under the
        # wrong step (e.g. ThroughNeck-in's W00/W01/W02 series).
        # Feature (subfolder) files: -front/-back wins INSTEAD, checked before the
        # leading-prefix regex -- a feature file's leading token is sometimes a
        # descriptive prefix that only coincidentally looks like a step (e.g. the
        # "P90" pickup style in PUPS/P90-PUP-Bridge-front-01.nc, indistinguishable
        # in shape from a real step like "B00"). Every such file across the actual
        # build tree already carries an explicit -front/-back marker, so checking
        # that first resolves the ambiguity without touching root-file step parsing
        # (which has no such marker to prefer and must keep the prefix-first order).
        prefix_match = re.search(r"^([A-Za-z]?\d{2})-", self.name)
        # [-\.]|$ -- ParamBuilder-generated files (ROOT-PASSTHROUGH-DIRS trees
        # like GeneratedGCode/) are written with no extension at all, so
        # "...-front"/"...-back" is sometimes the literal end of the name, not
        # followed by a "-" or ".". Without the end-of-string alternative here,
        # e.g. "BackRoundover-T-PT125-01-back" (no ".nc") matches neither
        # marker, falls through to the "00" bucket below, and silently never
        # reaches its configured FRONT-STEP/BACK-STEP output.
        front_match = re.search(r"(-front)(?:[-\.]|$)", self.name)
        back_match = re.search(r"(-back)(?:[-\.]|$)", self.name)
        if is_root and prefix_match is not None:
            self._step = prefix_match[1]
        elif not is_root and front_match is not None:
            self._step = "FRONT"
        elif not is_root and back_match is not None:
            self._step = "BACK"
        elif prefix_match is not None:
            self._step = prefix_match[1]
        elif front_match is not None:
            self._step = "FRONT"
        elif back_match is not None:
            self._step = "BACK"
        else:
            self._step = "00"
        if self._debug:
            debug_print("     step: " + str(self._step))

        # _family_tag is always computed, even for root/base files -- unlike
        # get_feature_name() (used by the CAMFeature toggle system, which deliberately
        # treats root files as having no feature), this is a general-purpose "what
        # operation is this, independent of which file it is" tag used by the
        # consistency checks to group root-level files (profile, frets, radius, ...) too.
        # Computed after self._step (above) so it can reuse that same root-vs-feature
        # prefix/front-back precedence when deciding whether the leading token is a
        # step to discard or part of the feature's identity to keep (e.g. "P90-").
        self._family_tag = self._feature_tag_from_rel()
        self._feature_name = "" if is_root else self._family_tag

        # extracted during file read
        self._toolnum = 0
        self._tool: Tool = None
        self._lines = []  # raw lines from file
        self._out_lines = []
        self._output = []  # dynamic 2 dim array [unit_num][lines]

        self._matching_search_string = ""
        self._match_diff_spans = []  # [(start,end), ...] char ranges in self.name that diverge from the closest base pattern, if unmatched

        if self._debug:
            debug_print("New CAMFile: n:" + self.name + "D:" + directory + "====" + self._dir + " is base?")

        if cached is not None:
            # scan_cache hit (see cam_core/scan_cache.py): this exact file's
            # (size, mtime_ns) matched the last scan, so reuse its previously
            # -derived content fields instead of re-opening/re-parsing it.
            # Raw _lines/_output stay empty until create_unit_code() actually
            # needs them (see _ensure_content_loaded) -- Load-time work never
            # needs the actual G-code text, only these derived scalars.
            self._content_loaded = False
            self._restore_cached_fields(cached)
            return

        self._content_loaded = True
        ##########################################################
        # read the contents of the file into an array
        f = open(self.filename, encoding='utf-8', errors='replace')
        for line in f:
            # change all home entries to "HOME"
            if line == "X0Y0\n" or line == "G0 X0Y0\n" or line == "X2Y0\n" or line == "G0 X2Y0\n":
                self._lines.append("HOME\n")
            else:
                self._lines.append(line)
        f.close()

        ##########################################################
        # determine the tool number for this file.
        #       If there are more than one tool represented, this is a fatal error
        toolnum = 0
        self._tool = None
        for line in self._lines:
            match = re.search(r"\(\s+TOOL\s+([0-9]+)\s+-\s+(.*)\)", line)
            if match is not None:
                if 0 and self._debug:
                    debug_print("... tool found:" + match[1] + "++++" + match[2])
                self._tool = Tool(match[1], match[2])
                self._tool.add_file(self)
                if toolnum != 0:
                    raise ValueError(f"Multiple tools in {self.filename}: T{match[1]}")

                toolnum = match[1]

        self._toolnum = toolnum
        if self._debug:
            debug_print("     tool: " + str(self._toolnum))

        ##########################################################
        # capture the MOP: header name (used to detect a stale header that no longer
        # matches the file's own name) and this file's coordinate/feed/speed envelope
        # (used for cross-file consistency checks -- clearance plane, feed/speed, etc).
        # Comment lines are skipped for coordinates/feed/speed since they're not real
        # toolpath motion (e.g. the FILE: header can contain path text that isn't G-code).
        self._mop_name = None
        self._op_markers = []
        self._feed_rates = set()
        for line in self._lines:
            if self._mop_name is None:
                mop_match = _MOP_RE.search(line)
                if mop_match:
                    self._mop_name = mop_match.group(1).strip()
            marker_match = _OP_MARKER_RE.match(line.rstrip("\n"))
            if marker_match:
                self._op_markers.append(marker_match.group(1))
            if "(" in line:
                continue
            for xm in _X_RE.finditer(line):
                v = float(xm.group(1))
                self.min_x = min(self.min_x, v)
                self.max_x = max(self.max_x, v)
            for ym in _Y_RE.finditer(line):
                v = float(ym.group(1))
                self.min_y = min(self.min_y, v)
                self.max_y = max(self.max_y, v)
            for zm in _Z_RE.finditer(line):
                v = float(zm.group(1))
                self.min_z = min(self.min_z, v)
                self.max_z = max(self.max_z, v)
            for fm in _F_RE.finditer(line):
                self._feed_rates.add(float(fm.group(1)))
            for sm in _S_RE.finditer(line):
                v = int(sm.group(1))
                self.min_s = min(self.min_s, v)
                self.max_s = max(self.max_s, v)

    @classmethod
    def from_lines(cls, name: str, lines: list, is_root: bool = True) -> "CAMFile":
        """Construct a CAMFile from in-memory lines without reading from disk."""
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, name)
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            return cls(name, tmpdir, is_root)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def to_cache_fields(self) -> dict:
        """JSON-serializable snapshot of every content-derived scalar field
        (everything __init__ computes from disk except raw _lines, which
        stays lazy -- see _ensure_content_loaded). Only meaningful right
        after a fresh, non-cached parse; used by scan_cache.record()."""
        return {
            "toolnum": self._toolnum,
            "tool_num": self._tool.get_tool_num() if self._tool else None,
            "tool_desc": self._tool.get_desc() if self._tool else None,
            "min_x": self.min_x, "max_x": self.max_x,
            "min_y": self.min_y, "max_y": self.max_y,
            "min_z": self.min_z, "max_z": self.max_z,
            "min_s": self.min_s, "max_s": self.max_s,
            "mop_name": self._mop_name,
            "op_markers": list(self._op_markers),
            "feed_rates": sorted(self._feed_rates),
        }

    def _restore_cached_fields(self, cached: dict) -> None:
        self._toolnum = cached["toolnum"]
        self._tool = None
        if cached.get("tool_num") is not None:
            self._tool = Tool(cached["tool_num"], cached["tool_desc"])
            self._tool.add_file(self)
        self.min_x = cached["min_x"]; self.max_x = cached["max_x"]
        self.min_y = cached["min_y"]; self.max_y = cached["max_y"]
        self.min_z = cached["min_z"]; self.max_z = cached["max_z"]
        self.min_s = cached["min_s"]; self.max_s = cached["max_s"]
        self._mop_name = cached["mop_name"]
        self._op_markers = list(cached["op_markers"])
        self._feed_rates = set(cached["feed_rates"])

    def _ensure_content_loaded(self) -> None:
        """Lazily read this file's raw lines from disk if construction came
        from a scan_cache hit (see __init__) and nothing has needed the
        actual G-code text yet. A no-op otherwise. Must run before anything
        reads self._lines (currently only create_unit_code())."""
        if self._content_loaded:
            return
        self._lines = []
        f = open(self.filename, encoding='utf-8', errors='replace')
        for line in f:
            if line == "X0Y0\n" or line == "G0 X0Y0\n" or line == "X2Y0\n" or line == "G0 X2Y0\n":
                self._lines.append("HOME\n")
            else:
                self._lines.append(line)
        f.close()
        self._content_loaded = True

    def set_matching_search_string(self, match: str):
        # print(self.name + " setting search string: "+match)
        self._matching_search_string = match

    def get_matching_search_string(self) -> str:
        return self._matching_search_string

    def set_match_diff_spans(self, spans):
        self._match_diff_spans = spans

    def get_match_diff_spans(self):
        return self._match_diff_spans

    def get_tool(self):
        return self._tool

    def _feature_tag_from_rel(self) -> str:
        part = self.name.split("/", 1)[-1] if "/" in self.name else self.filename
        stem = os.path.splitext(os.path.basename(part))[0]
        # strip known tags (see get_step() above for why any letter is accepted here).
        # Only strip the leading token if it was actually treated as this file's step
        # (self._step, set just above) -- on a feature file where -front/-back took
        # precedence instead (e.g. "P90-PUP-Bridge-front-01.nc"), the leading token is
        # part of the feature's own identity, not a step to discard.
        if self._is_root or self._step not in ("FRONT", "BACK"):
            stem = re.sub(r"^([A-Za-z]?\d{2})-", "", stem)
        stem = re.sub(r"-NODUP", "", stem)
        stem = re.sub(r"-NOMIRROR", "", stem)
        stem = re.sub(r"-front-", "-", stem)
        stem = re.sub(r"-front", "", stem)
        stem = re.sub(r"-back-", "-", stem)
        stem = re.sub(r"-back", "", stem)
        stem = re.sub(r"-end-", "-", stem)
        stem = re.sub(r"-end", "", stem)
        stem = re.sub(r"-start-", "-", stem)
        stem = re.sub(r"-start", "", stem)

        # capture the run/pass number (e.g. '-01', '-02') before dropping it, so callers
        # can tell same-feature files apart by which pass they represent (rough vs finish,
        # etc) instead of treating e.g. a rough pass and a finish pass as directly
        # comparable. Done after the -end/-start strip above so a number buried before one
        # of those (e.g. '...-01-end') is still found.
        run_match = re.search(r"-(\d\d)", stem)
        self._run_suffix = run_match.group(1) if run_match else None

        # drop trailing run-like numbers that are not at start (e.g., '-01', '-02')
        stem = re.sub(r"-\d\d", "", stem)
        return stem

    def get_feature_name(self):
        return self._feature_name

    def get_family_tag(self):
        return self._family_tag

    def get_run_suffix(self):
        return self._run_suffix

    def is_root(self) -> bool:
        return self._is_root

    def is_passthrough_dir(self) -> bool:
        return self._is_passthrough_dir

    def get_step(self) -> str:
        return self._step

    def get_toolnum(self):
        return self._toolnum

    def get_name(self):
        return self.name

    def has_coordinates(self) -> bool:
        """False for placeholder/no-op files where no X/Y/Z motion was ever found."""
        return self.min_x <= self.max_x

    def get_min_x(self):
        return self.min_x if self.has_coordinates() else None

    def get_max_x(self):
        return self.max_x if self.has_coordinates() else None

    def get_min_y(self):
        return self.min_y if self.has_coordinates() else None

    def get_max_y(self):
        return self.max_y if self.has_coordinates() else None

    def get_min_z(self):
        return self.min_z if self.has_coordinates() else None

    def get_max_z(self):
        return self.max_z if self.has_coordinates() else None

    def get_min_s(self):
        return self.min_s if self.min_s <= self.max_s else None

    def get_max_s(self):
        return self.max_s if self.min_s <= self.max_s else None

    def get_feed_rates(self):
        return frozenset(self._feed_rates)

    def get_mop_name(self):
        return self._mop_name

    def get_op_markers(self):
        """Bare '( <name>)' operation-boundary comments found in the file, in order.
        A normal single-op file has exactly one (matching the MOP: header). More than
        one means several operations are concatenated into this file sharing one tool."""
        return list(self._op_markers)

    def create_unit_code(self,
                         numUnits: int,
                         clinedelta: float,
                         direction):

        self._ensure_content_loaded()
        self._output = []
        for i in range(0, numUnits):
            self._output.append([])

        ##########################################################
        # create gcode for each individual unit. Note that no mirroring
        # will happen here and no end codes will be suppressed
        for line in self._lines:
            newline = []
            for i in range(0, numUnits):
                newline.append("")

            if re.search(r"\(", line):
                for i in range(0, numUnits):
                    newline[i] = line
                for i in range(0, numUnits):
                    self._output[i].append(newline[i])
                continue

            if direction == "HORIZONTAL":
                match = re.search(r"(.*)X(-*[0-9]+[.]*[0-9]*)(.*\n*)", line)
            else:
                match = re.search(r"(.*)Y(-*[0-9]+[.]*[0-9]*)(.*\n*)", line)

            if match is None:
                for i in range(0, numUnits):
                    newline[i] = line
                # debug_print(line)

            else:
                # debug_print(line + " ==> " + match + "++++" + match[1] + "x" + match[2] + match[3] + clinedelta)
                old_val = float(match[2])
                new_val = old_val
                for i in range(0, numUnits):
                    if direction == "HORIZONTAL":
                        newline[i] = f"{match[1]}X{new_val:.4f}{match[3]}"
                    else:
                        newline[i] = f"{match[1]}Y{new_val:.4f}{match[3]}"
                    new_val = round(new_val + clinedelta, 4)

            for i in range(0, numUnits):
                if newline[i] != "":
                    self._output[i].append(newline[i])
                    # debug_print(i + ": " + newline)

    def get_output(self,
                   lefty: bool,
                   cline: float,
                   clinedelta: float,
                   start_unit: int,
                   num_units: int,
                   direction,
                   suppress_end_code):
        end_unit = start_unit + num_units - 1
        self._out_lines = []
        debug_get_output = False

        if debug_get_output:
            debug_print(self.name + ": get output :" + str(lefty) + str(cline) + str(clinedelta) +
                        "[" + str(start_unit) + ":" + str(end_unit) + "]" + direction +
                        suppress_end_code)

        for i in range(start_unit, end_unit + 1):
            if debug_get_output:
                debug_print(self.name  + ": get output :" + "dumping unit " + str(i))

            # duplicate and displace to ClineDelta
            for line in self._output[i - 1]:
                # debug_print(line)
                if line == "HOME\n":
                    if i != end_unit:
                        if debug_get_output:
                            debug_print(self.name + ": get output : skipping home in non-final unit #" + str(i))
                        continue

                    if suppress_end_code:
                        # stuff in a home move
                        if debug_get_output:
                            debug_print(self.name + ": get output : suppression on, final unit #" + str(i) + "; skipping home")
                        continue

                    # stuff in a home move
                    if debug_get_output:
                        debug_print(self.name + ": get output : suppression on final unit #" + str(i) + "; inserting X2Y0")
                    self._out_lines.append("G0 X2Y0\n")
                else:
                    if lefty:
                        line = self._int_mirror_line(line, cline + clinedelta * (i - 1), direction)
                    self._out_lines.append(line)

        # self.scan_for_debug_output()

        return self._out_lines

    def _int_mirror_line(self, line, cline: float, direction):
        debug_mirror = False
        if debug_mirror:
            debug_print(str(cline)+" "+str(direction)+" "+str(line))

        # skip comment lines
        match = re.search(r"\(", line)
        if match is not None:
            return line

        if direction == "HORIZONTAL":
            match = re.search(r"(.*)X([-]*[0-9]+[.]*[0-9]*)(.*\n*)", line)
            # debug_print("1: "  + match)
            if match is not None:
                # replace Xnn.nnnn with the value of X mirrored around cline
                # debug_print(line + " ==> " + match + "++++" +  match[1] + "x" + match[2] + match[3] + cline)
                oldx = float(match[2])
                if debug_mirror:
                    debug_print("oldx:" + str(oldx))

                if oldx > cline:
                    newx = round(cline - (oldx - cline), 4)
                else:
                    newx = round(cline + (cline - oldx), 4)
                newline = f"{match[1]}X{newx:.4f}{match[3]}"
                if debug_mirror:
                    debug_print("       ======> x" + str(newx) + "====" + newline)
            else:
                newline = line

            match2 = re.search(r"(.*)I([-0-9]+[.]*[0-9]*)(.*\n*)", newline)
            # debug_print("2: " + match2)

            if match2 is not None:
                # replace Inn.nnnn with the value of -I
                # debug_print(line + " ==> " + match + "++++" +  match[1] + "x" + match[2] + match[3] + cline)
                oldi = float(match2[2])
                newi = -1 * oldi
                newline = f"{match2[1]}I{newi:.4f}{match2[3]}"

                # we also need to change from G2 to G3 and vice versa
                match3 = re.search(r"(G[23])(.*\n*)", newline)
                if match3:
                    if match3[1] == "G3":
                        newline = f"G2{match3[2]}"
                    else:
                        newline = f"G3{match3[2]}"
                else:
                    raise ValueError(f"Arc has I but no G2/G3 on same line in {self.name}: {newline!r}")
                #  debug_print("oldI:"  + str(oldi)  + " newI:"  + str(newi)  + " newline: "  + newline)
        else:
            # vertical mirroring = serach for Y
            match = re.search(r"(.*)Y([-]*[0-9]+[.]*[0-9]*)(.*\n*)", line)
            if debug_mirror:
                debug_print("1: " + str(match))
            if match is not None:
                # replace Xnn.nnnn with the value of X mirrored around cline
                # debug_print(line + " ==> " + match + "++++" +  match[1] + "y" + match[2] + match[3] + cline)
                oldy = float(match[2])
                if debug_mirror:
                    debug_print("oldy:" + str(oldy))

                if oldy > cline:
                    newy = round(cline - (oldy - cline), 4)
                else:
                    newy = round(cline + (cline - oldy), 4)
                newline = f"{match[1]}Y{newy:.4f}{match[3]}"
                if debug_mirror:
                    debug_print("       ======> y" + str(newy) + "====" + newline)
            else:
                newline = line

            match2 = re.search(r"(.*)J([-0-9]+[.]*[0-9]*)(.*\n*)", newline)

            if match2 is not None:
                # debug_print("2: "  + match2)
                # replace Jnn.nnnn with the value of -J
                # debug_print(line + " ==> " + match + "++++" + match[1] + "J" + match[2] + match[3] + cline)
                oldj = float(match2[2])
                newj = -1 * oldj
                newline = f"{match2[1]}J{newj:.4f}{match2[3]}"

                # we also need to change from G2 to G3 and vice versa
                match3 = re.search(r"(G[23])(.*\n*)", newline)
                if not match3:
                    raise ValueError(f"Arc has J but no G2/G3 on same line in {self.name}: {newline!r}")
                if match3[1] == "G3":
                    newline = f"G2{match3[2]}"
                else:
                    newline = f"G3{match3[2]}"
                #  debug_print("oldJ:" + oldj + " newJ:" + newj + "newline: " + newline)

        return newline
