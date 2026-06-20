from __future__ import annotations
from cam_core.Tool import Tool
from cam_core.debug import debug_print

import os
import re

# units numbered across X first, then step Y
class Unit:
    def __init__(self, unit_number:int, clineX:float, deltaX:float, clineY:float, deltaY:float):
        self._unit_number = unit_number
        self.clineX = clineX
        self.deltaX = deltaX
        self.clineY = clineY
        self.deltaY = deltaY




class CAMFile:
    def __init__(self, name: str, directory: str, is_root: bool):
        if directory == ".":
            directory = os.getcwd()
        # directory = directory.replace("\\","/")

        self._debug = False
        self.name = name
        self._dir = directory
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

        if is_root:
            self._feature_name = ""
        else:
            self._feature_name = self._feature_tag_from_rel()

        # extracted during file read
        self._toolnum = 0
        self._tool: Tool = None
        self._lines = []  # raw lines from file
        self._out_lines = []
        self._output = []  # dynamic 2 dim array [unit_num][lines]

        self._matching_search_string = ""

        if self._debug:
            debug_print("New CAMFile: n:" + self.name + "D:" + directory + "====" + self._dir + " is base?")

        # determine the appropriate step for this file
        match = re.search(r"^([A-Ga-g]?\d{2})-", self.name)
        if match is not None:
            self._step = match[1]
        else:
            match = re.search(r"(-front)[-\.]", self.name)
            if match is not None:
                self._step = "FRONT"
            else:
                match = re.search(r"(-back)[-\.]", self.name)
                if match is not None:
                    self._step = "BACK"
                else:
                    self._step = "00"
        if self._debug:
            debug_print("     step: " + str(self._step))

        ##########################################################
        # read the contents of the file into an array
        f = open(self.filename)
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

    def set_matching_search_string(self, match: str):
        # print(self.name + " setting search string: "+match)
        self._matching_search_string = match

    def get_matching_search_string(self) -> str:
        return self._matching_search_string

    def get_tool(self):
        return self._tool

    def _feature_tag_from_rel(self) -> str:
        part = self.name.split("/", 1)[-1] if "/" in self.name else self.filename
        stem = os.path.splitext(os.path.basename(part))[0]
        # strip known tags
        stem = re.sub(r"^([A-Ga-g]?\d{2})-", "", stem)
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

        # drop trailing run-like numbers that are not at start (e.g., '-01', '-02')
        stem = re.sub(r"-\d\d", "", stem)
        return stem

    def get_feature_name(self):
        return self._feature_name

    def get_step(self) -> str:
        return self._step

    def get_toolnum(self):
        return self._toolnum

    def get_name(self):
        return self.name

    def create_unit_code(self,
                         numUnits: int,
                         clinedelta: float,
                         direction):

        for i in range(0, numUnits):
            self._output.append([])

        ##########################################################
        # create gcode for each individual unit. Note that no mirroring
        # will happen here and no end codes will be suppressed
        for line in self._lines:
            newline = []
            for i in range(0, numUnits):
                newline.append("")

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
                newline = f"{match2[1]}I{newi}{match2[3]}"

                # we also need to change from G2 to G3 and vice versa
                match3 = re.search(r"(G[23])(.*\n*)", newline)
                # debug_print("3: "  match3  + "|"  + match3[1]  + "|"  + match3[2])
                if not match3:
                    debug_print("ERROR!!!!!")
                if match3[1] == "G3":
                    newline = f"G2{match3[2]}"
                else:
                    newline = f"G3{match3[2]}"
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
                newline = f"{match2[1]}J{newj}{match2[3]}"

                # we also need to change from G2 to G3 and vice versa
                match3 = re.search(r"(G[23])(.*\n*)", newline)
                # debug_print("3: " + match3 + "|" + match3[1] + "|" + match3[2])
                if not match3:
                    debug_print("ERROR!!!!!")
                if match3[1] == "G3":
                    newline = f"G2{match3[2]}"
                else:
                    newline = f"G3{match3[2]}"
                #  debug_print("oldJ:" + oldj + " newJ:" + newj + "newline: " + newline)

        return newline
