# Initially: only buttons to set input directory and output directory
#
#
# When either button is pressed, dialog box allow navigation to desired source tree
# populate base_dir and output_dir variables
#
# when output_dir is set, enable button for "generate final gcode"
#
# when base_dir is set,
#     read (json?) base_dir/fixture-config.txt to populate CLINE1 and CLINEDIFF
#     delete all existing dynamic boxes/widgets
#
# create check box/input box filled boxes as follows:

# 1. (automatic) Basic:
#     Num Units (1, 2 or 3)
#     Lamtop (check box)
#     Binding (check box)
#     Binding (check box)
#     Lefty (check box)
#
# 2- (dynamic) based on directory structure:
#     for each (base_dir/<SUB>) {
#         creates new high level box titled <SUB>
#         for each (base_dir/<SUB>/*.nc, but filter out base file names that
#         have matching -front / -back and - < SN >) {
#             create button
#         }
#     }
#
# when generate_final_gcode button is pressed {
#
# }from typing import Union

from pathlib import Path
import dearpygui.dearpygui as dpg
import os
import errno
import re
import json
import pyautogui
import shutil
import datetime
from datetime import datetime


def json_minify(string, strip_space=True):
    tokenizer = re.compile('"|(/\*)|(\*/)|(//)|\n|\r')
    end_slashes_re = re.compile(r'(\\)*$')

    in_string = False
    in_multi = False
    in_single = False

    new_str = []
    index = 0

    for match in re.finditer(tokenizer, string):

        if not (in_multi or in_single):
            tmp = string[index:match.start()]
            if not in_string and strip_space:
                # replace white space as defined in standard
                tmp = re.sub('[ \t\n\r]+', '', tmp)
            new_str.append(tmp)
        elif not strip_space:
            # Replace comments with white space so that the JSON parser reports
            # the correct column numbers on parsing errors.
            new_str.append(' ' * (match.start() - index))

        index = match.end()
        val = match.group()

        if val == '"' and not (in_multi or in_single):
            escaped = end_slashes_re.search(string, 0, match.start())

            # start of string or unescaped quote character to end string
            if not in_string or (escaped is None or len(escaped.group()) % 2 == 0):  # noqa
                in_string = not in_string
            index -= 1  # include " character in next catch
        elif not (in_string or in_multi or in_single):
            if val == '/*':
                in_multi = True
            elif val == '//':
                in_single = True
        elif val == '*/' and in_multi and not (in_string or in_single):
            in_multi = False
            if not strip_space:
                new_str.append(' ' * len(val))
        elif val in '\r\n' and not (in_multi or in_string) and in_single:
            in_single = False
        elif not ((in_multi or in_single) or (val in ' \r\n\t' and strip_space)):  # noqa
            new_str.append(val)

        if not strip_space:
            if val in '\r\n':
                new_str.append(val)
            elif in_multi or in_single:
                new_str.append(' ' * len(val))

    new_str.append(string[index:])
    return ''.join(new_str)


class Tool:
    def __init__(self, tnum, tdescr, fname):
        self.tnum = int(tnum)
        self.tdesc = tdescr
        self.fname = fname
        self.error = False
        self.warning = False

    def __repr__(self):
        rstr = ""
        if self.error:
            rstr = "ERROR:\t"
        elif self.warning:
            rstr = "WARNING:\t"
        rstr = rstr + "\t"

        dform = f"{self.tdesc:.20}"
        rstr = rstr + "T#" + f"{self.tnum:02d}\t" + dform + "\t" + os.path.basename(str(self.fname))
        return rstr

    def get_tnum(self):
        return self.tnum

    def get_desc(self):
        return self.tdesc

    def get_fname(self):
        return self.fname

    def set_error(self, val):
        self.error = val

    def set_warning(self, val):
        # if there is already an error pending, ignore the warning.
        if self.error:
            return
        self.warning = val

    def get_error(self):
        return self.error

    def get_warning(self):
        return self.warning

tools = []


class CAMFile:
    def __init__(self, name, directory, max_units, delta, direction, is_base_file_in):
        self._debug = False
        self.name = name
        self._dir = Path(directory)
        self._selected = False
        self._lines = []
        self._out_lines = []
        self._base = False
        self._toolnum = 0
        self.is_base_file = is_base_file_in

        self.max_x = -999.99
        self.min_x = 999.99
        self.max_y = -999.99
        self.min_y = 999.99
        self.max_z = -999.99
        self.min_z = 999.99
        self.min_s = 100000
        self.max_s = 0
        self.filename = Path(self._dir) / self.name

        if self._debug:
            print("New CAMFile: n:", self.name, "D:", self._dir, "Delta:", delta, "Direction:", direction )

        ##########################################################
        # read the contents of the file into an array
        f = open(self.filename)
        toolnum = 0
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
        for line in self._lines:
            match = re.search(r"\([ ]+TOOL ([0-9]+) - (.*)\)", line)
            if match is not None:
                if self._debug:
                    print("... tool found:", match[1], "++++", match[2])
                tools.append(Tool(match[1], match[2], self.name))
                if toolnum != 0:
                    print("**********************\nFATAL ERROR: multiple tools in " + str(self.filename) + ": T" + match[
                        1] + "\n****************")
                    dpg.destroy_context()

                if False and toolnum == 0:
                    print(fname.name + " T:" + match[1])

                toolnum = match[1]
        self._toolnum = toolnum

        ##########################################################
        # create gcode for each individual unit. Note that no mirroring
        # will happen here and no end codes will be suppressed
        self._indiv_unit_gcode = [] * max_units
        for i in range(0, max_units):
            self._indiv_unit_gcode.append([])

        for line in self._lines:
            newline = []
            for i in range(0, max_units):
                newline.append("")

            if direction == "HORIZONTAL":
                match = re.search(r"(.*)X(-*[0-9]+[.]*[0-9]*)(.*\n*)", line)
            else:
                match = re.search(r"(.*)Y(-*[0-9]+[.]*[0-9]*)(.*\n*)", line)

            if match is None:
                for i in range(0, max_units):
                    newline[i] = line
                # print(line)

            else:
                # print(line, " ==> ", match, "++++", match[1], "x", match[2], match[3], delta)
                old_val = float(match[2])
                new_val = old_val
                for i in range(0, max_units):
                    if direction == "HORIZONTAL":
                        newline[i] = f"{match[1]}X{new_val:.4f}{match[3]}"
                    else:
                        newline[i] = f"{match[1]}Y{new_val:.4f}{match[3]}"
                    new_val = round(new_val + delta, 4)

            for i in range(0, max_units):
                if newline[i] != "":
                    self._indiv_unit_gcode[i].append(newline[i])
                    # print(i + ": " + newline)


    def get_filename(self):
        return self.filename


    def get_name(self):
        return self.name


    def scan_for_debug_output(self):
        #print("scanning for debug output: " + self.name)
        #print("***************\n", self._out_lines, "***************\n")
        # walk through each line in out_lines to look for stuff we record about the file:
        # S, T#, min/max x/y/z. etc
        for line in self._out_lines:
            #print("LLL***************\n",line,"***************\n")
            match = re.search(r"(.*)X([-]*[0-9]+[.]*[0-9]*)(.*\n*)", line)
            if match:
                mval: float = float(match[2])
                # print("x match" + str(mval))

                if mval > self.max_x:
                    self.max_x = mval
                if mval < self.min_x:
                    self.min_x = mval

            match = re.search(r"(.*)Y([-]*[0-9]+[.]*[0-9]*)(.*\n*)", line)
            if match:
                mval = float(match[2])
                if mval > self.max_y:
                    self.max_y = mval
                if mval < self.min_y:
                    self.min_y = mval

            match = re.search(r"(.*)Z([-]*[0-9]+[.]*[0-9]*)(.*\n*)", line)
            if match:
                mval = float(match[2])
                if mval > self.max_z:
                    self.max_z = mval
                if mval < self.min_z:
                    self.min_z = mval

            match = re.search(r"(.*)S([-]*[0-9]+[.]*[0-9]*)(.*\n*)", line)
            if match:
                mval = float(match[2])
                if mval > self.max_s:
                    self.max_s = mval
                if mval < self.min_s:
                    self.min_s = mval

    def _int_mirror_line(self, line, cline: float, direction):
        debug_mirror = False
        if debug_mirror:
            print(str(cline)+" "+str(direction)+" "+str(line))

        # skip comment lines
        match = re.search(r"\(", line)
        if match is not None:
            return line

        if direction == "HORIZONTAL":
            match = re.search(r"(.*)X([-]*[0-9]+[.]*[0-9]*)(.*\n*)", line)
            # print("1: ", match)
            if match is not None:
                # replace Xnn.nnnn with the value of X mirrored around cline
                # print(line, " ==> ", match, "++++",  match[1], "x", match[2], match[3], cline)
                oldx = float(match[2])
                if debug_mirror:
                    print("oldx:", oldx)

                if oldx > cline:
                    newx = round(cline - (oldx - cline), 4)
                else:
                    newx = round(cline + (cline - oldx), 4)
                newline = f"{match[1]}X{newx:.4f}{match[3]}"
                if debug_mirror:
                    print("       ======> x", newx, "====", newline)
            else:
                newline = line

            match2 = re.search(r"(.*)I([-0-9]+[.]*[0-9]*)(.*\n*)", newline)
            # print("2: ", match2)

            if match2 is not None:
                # replace Inn.nnnn with the value of -I
                # print(line, " ==> ", match, "++++",  match[1], "x", match[2], match[3], cline)
                oldi = float(match2[2])
                newi = -1 * oldi
                newline = f"{match2[1]}I{newi}{match2[3]}"

                # we also need to change from G2 to G3 and vice versa
                match3 = re.search(r"(G[23])(.*\n*)", newline)
                # print("3: ", match3, "|", match3[1], "|", match3[2])
                if not match3:
                    print("ERROR!!!!!")
                if match3[1] == "G3":
                    newline = f"G2{match3[2]}"
                else:
                    newline = f"G3{match3[2]}"
                #  print("oldI:", oldi, " newI:", newi, "newline: ", newline)

        else:
            # vertical mirroring = serach for Y
            match = re.search(r"(.*)Y([-]*[0-9]+[.]*[0-9]*)(.*\n*)", line)
            if debug_mirror:
                print("1: ", match)
            if match is not None:
                # replace Xnn.nnnn with the value of X mirrored around cline
                # print(line, " ==> ", match, "++++",  match[1], "y", match[2], match[3], cline)
                oldy = float(match[2])
                if debug_mirror:
                    print("oldy:", oldy)

                if oldy > cline:
                    newy = round(cline - (oldy - cline), 4)
                else:
                    newy = round(cline + (cline - oldy), 4)
                newline = f"{match[1]}Y{newy:.4f}{match[3]}"
                if debug_mirror:
                    print("       ======> y", newy, "====", newline)
            else:
                newline = line

            match2 = re.search(r"(.*)J([-0-9]+[.]*[0-9]*)(.*\n*)", newline)

            if match2 is not None:
                #print("2: ", match2)
                # replace Jnn.nnnn with the value of -J
                # print(line, " ==> ", match, "++++",  match[1], "J", match[2], match[3], cline)
                oldj = float(match2[2])
                newj = -1 * oldj
                newline = f"{match2[1]}J{newj}{match2[3]}"

                # we also need to change from G2 to G3 and vice versa
                match3 = re.search(r"(G[23])(.*\n*)", newline)
                # print("3: ", match3, "|", match3[1], "|", match3[2])
                if not match3:
                    print("ERROR!!!!!")
                if match3[1] == "G3":
                    newline = f"G2{match3[2]}"
                else:
                    newline = f"G3{match3[2]}"
                #  print("oldJ:", oldj, " newJ:", newj, "newline: ", newline)

        return newline



    def get_output(self, lefty: bool, cline: float, clinedelta: float, start_unit: int, end_unit: int, direction, suppress_end_code):
        self._out_lines = []
        debug_get_output = False

        if debug_get_output:
            print(self.name, ": get output :", lefty, cline, clinedelta, "[", start_unit, ":", end_unit, "]", direction, suppress_end_code)

        for i in range(start_unit, end_unit+1):
            if debug_get_output:
                print(self.name, ": get output :", "dumping unit " + str(i))

            # duplicate and displace to ClineDelta
            for line in self._indiv_unit_gcode[i-1]:
                #print(line)
                if line == "HOME\n":
                    if i != end_unit:
                        if debug_get_output:
                            print(self.name, ": get output : skipping home in non-final unit #", i)
                        continue

                    if suppress_end_code:
                        # stuff in a home move
                        if debug_get_output:
                            print(self.name, ": get output : suppression on, final unit #", i, "; skipping home")
                        continue

                    # stuff in a home move
                    if debug_get_output:
                        print(self.name, ": get output : suppression on final unit #", i, "; inserting X2Y0")
                    self._out_lines.append("G0 X2Y0\n")
                else:
                    if lefty:
                        line = self._int_mirror_line(line, cline + clinedelta * (i-1), direction)
                    self._out_lines.append(line)

        self.scan_for_debug_output()

        return self._out_lines

    def __repr__(self):
        rstr = self.name
        # if self._selected:
        #     rstr = rstr + "SEL?: YES"
        # else:
        #     rstr = rstr + "SEL?: no"
        return str(rstr)

    def get_toolnum(self):
        return self._toolnum

    def set_toolnum(self, toolnum):
        self._toolnum = toolnum

    def set_selected(self, selected):
        if True:
            if selected:
                print("setting selected " + str(self._dir) + "\\" + self.name + " to " + str(selected))
            else:
                print("clearing selected " + self.name)
        self._selected = selected

    def set_base(self, isbase):
        self._base = isbase

    def get_base(self):
        return self._base

    def get_selected(self):
        # print("Feature:", self.name, self._selected)
        return self._selected

    def get_dir(self):
        return self._dir


class CAMFeature:
    def __init__(self, name):
        self.name = name
        self.files = []
        self.button = 0
        self.radiobtn = False
        self.btnitems = []
        self.default_value = False
        self.wildcard = ""

    def get_name(self):
        return self.name

    def set_default_val(self, val):
        self.default_value = val

    def set_radiobtn(self, btnitems_in):
        self.radiobtn = True
        self.btnitems = btnitems_in

    def add_file(self, newfile):
        self.files.append(newfile)

    def get_num_files(self):
        return len(self.files)

    def get_file(self, num):
        if num <= len(self.files):
            return self.files[num]
        else:
            return 0

    def set_button_on(self):
        print("setting button for " + self.name)
        if self.radiobtn:
            # nothing to do
            return

        if self.button == 0:
            # nothing to do
            return

        dpg.set_value(self.button, True)

    def add_button(self):
        if self.radiobtn:
            dpg.add_text(self.name)
            # print("creating button for:"+self.name)
            if len(self.btnitems) > 3:
                hval = False
            else:
                hval = False
            cid = dpg.add_radio_button(self.btnitems, label=self.name, tag=self.name,
                                       callback=box_clicked, horizontal=hval, default_value=self.default_value)
            self.button = cid
        else:
            # print("adding button %d", newbutton)
            # print("creating:"+self.name)
            cid = dpg.add_checkbox(label=self.name, callback=box_clicked)
            self.button = cid

    def get_button(self):
        return self.button

    def get_button_value(self):
        return dpg.get_value(self.button)

    def __repr__(self):
        ffiles = ""
        got_one = False
        for x in self.files:
            if got_one:
                ffiles += "||"
            got_one = True
            ffiles += x.name

        if not self.button:
            rstr = self.name + "\tB--\n"
        else:
            rstr = self.name + "\t" + str(self.get_button_value()) + str(self.button) + "files: " + str(self.get_num_files())
        rstr = rstr + "\t" + "[["+ffiles+"]]"
        #+ffiles
        return rstr


class FeatureBlock:
    def __init__(self, name, subdir):
        self.features = []
        self.name = name
        self.subdir = subdir
        self.fbwin = 0

    def contains_feature(self, queryfeature):
        for x in self.features:
            if x == queryfeature:
                return True
        return False

    def add_feature(self, newbfeature):
        self.features.append(newbfeature)

    def __repr__(self):
        # print("printing feature block")
        ffiles = ""
        got_one = False
        for x in self.features:
            if got_one:
                ffiles += " || "
            got_one = True
            ffiles += x.name
        return "<<" + self.name + ">> sd:'" \
               + self.subdir + "' ===>" + ffiles


class CAMConfig:
    def __init__(self):
        self.model = "UNKNOWN"
        self.base_files = []
        self.HasStartAndEnd = False
        self.Lefty = False
        self.MaxUnits = 3
        self.NumUnits = 1
        self.Cline = 0
        self.ClineDelta = 48
        self.Direction = "HORIZONTAL"

        self.NumSteps = 0
        self.FrontStep = "^07"
        self.BackStep = "^09"

        self.FileBased = True

        self.input_dir = ""
        self.output_dir = ""

        self.output_file_names = []
        self.output_file_prefix = []
        self.input_file_base_names = []
        self.input_file_base_required = []
        self.input_file_base_condition = []


CAMFiles = []
CAMFeatures = []
FeatureBlocks = []

config = CAMConfig()


def get_feature_block(name):
    for feat in FeatureBlocks:
        if feat.name == name:
            return feat

    return 0


def extract_feature_name(newfile):
    debug_extract = False
    if debug_extract:
        print("extracting feature from " + newfile.name)

    # check to confirm that this is a .nc file. If not, simply exit
    if not re.match('.nc', newfile.name) is None:
        return

    newline = newfile.name

    # remove step details to extract feature name
    newline = re.sub("-front", "", newline)
    newline = re.sub("-back", "", newline)
    newline = re.sub("-start", "", newline)
    newline = re.sub("-NOMIRROR", "", newline)
    newline = re.sub("-first", "", newline)
    newline = re.sub("-end", "", newline)
    newline = re.sub("-righty", "", newline)
    newline = re.sub("-lefty", "", newline)
    newline = re.sub('.nc', "", newline)
    newline = re.sub('-[0-9][0-9]', '', newline)

    if debug_extract:
        print("        newline: " + newline)

    # remove step number if present SMB
    stepnumsearch = re.match("^([A-Z])?([0-9][0-9]-)(.*)", newline)

    if stepnumsearch:
        if debug_extract:
            print("        searchresults: " + str(stepnumsearch.groups()))

        stepprefix = stepnumsearch[1]
        stepnum = stepnumsearch[2]
        newline = stepnumsearch[3]
        newline = re.sub('^([A-Z])?[0-9][0-9]-', '', newline)

        if debug_extract:
            print("       stepnum: prefix", stepprefix, " #", stepnum, " feature:", newline)
    else:
        if debug_extract:
            print("        searchresults: no match")

    # OK, newLine is the feature. See if we already have it.
    for x in CAMFeatures:
        if x.name == newline:
            # found a matching element. we have already seen this feature.
            # Add this new file to this feature
            # print("match found to %s", newline)
            if debug_extract:
                print("       adding to existing feature ", x.name, " file: ", newfile)
            x.add_file(newfile)
            return x

    # OK, didn't fine the newLine feature in our list of CAMFeatures.
    # Append a new entry on the list
    # print("no match, creating feature %s", newline)
    if debug_extract:
        print("       creating new feature", newline, " with file: ", newfile)
    nf = CAMFeature(newline)
    nf.add_file(newfile)
    CAMFeatures.append(nf)

    current_featureblock.add_feature(nf)






def capture_files(sdir):
    global current_featureblock
    skip_files = {"fixture_config.txt", "desktop.ini", "#*", ".*", ".DS_Store"}
    if not hasattr(capture_files, "base_featureblock"):
        capture_files.base_featureblock = True

    entries = sorted(os.scandir(sdir), key=lambda x: getattr(x, 'name'))

    # process all non-directory entries first
    for entry in entries:
        fname = sdir / entry.name
        if not entry.is_dir() and entry.name not in skip_files:
            newfile = CAMFile(entry.name, sdir, config.MaxUnits, config.ClineDelta, config.Direction, capture_files.base_featureblock)
            newfile.set_base(capture_files.base_featureblock)
            # print("new file " + entry.name + " T:" + str(toolnum))
            CAMFiles.append(newfile)
            if not capture_files.base_featureblock:
                extract_feature_name(newfile)
            else:
                config.base_files.append(newfile)

    # then process all directories (recursively)
    for entry in entries:
        fname = sdir / entry.name
        if entry.is_dir():
            print("DIR:" + entry.name)
            current_featureblock = FeatureBlock(entry.name, entry.name)
            FeatureBlocks.append(current_featureblock)
            # print("clearing base_featureblock:", fname)
            capture_files.base_featureblock = False
            capture_files(fname)


def box_clicked(sender, app_data):
    debug_click = False
    if debug_click:
        print(f"sender is: {sender}")
        print(f"app_data is: {app_data}")
        print("value:", dpg.get_value(sender))
        print("fb: ", FeatureBlocks)
    # find which button it was by iterating through the features array.
    for fb in FeatureBlocks:
        if debug_click:
            print("checking feature block ", fb)

        for f in fb.features:
            btn = f.get_button()
            if debug_click:
                print("    feature ", f, "button #", btn)
            if btn == sender:
                # got it!
                if debug_click:
                    print("    got matching feature with %d", f.get_num_files(), " files")
                # iterate through all files associated with X and mark them according to the value

                # OK, we have set the value selected for this item. Need to deselect the rest
                for y in range(f.get_num_files()):
                    xf = f.get_file(y)
                    if debug_click:
                        print("        iterating ", fb, "@@", f, "@@", y, "@@", xf, "@@", dpg.get_value(sender))
                    xf.set_selected(dpg.get_value(sender))
                break



def build_checkboxes():
    winnum = 0

    winy = 390
    winwidth = 225
    winheight = 750
    winyinc = winheight + 10
    winxinc = winwidth + 10

    for fb in FeatureBlocks:
        if (fb.fbwin):
            continue

        print("creating block for " + fb.name)
        winx = winnum * winxinc
        fb.fbwin = dpg.window(label=fb.name,
                              width=winwidth, height=winheight, pos=(winx, winy),
                              no_close=True, no_collapse=True)
        winnum += 1
        if winnum == 10:
            winnum = 0
            winy = winy + winyinc

        with fb.fbwin:
            for ft in fb.features:
                ft.add_button()


def write_output_file(cfile, fname, output_file, start_unit, num_units, mirror, tnum, suppress_end_code):
    #print("Writing Output File ", fname, "==>", output_file)
    output_file.write("( BEGIN FILE " + fname + "TNUM: " + str(tnum) + " )\n")
    status = "( Lefty:" + str(mirror) + " Nunits:" + str(num_units) + " )\n"
    output_file.write(status)
    status = "( cline: " + str(config.Cline) + " delta:" + str(config.ClineDelta) + " )\n"
    output_file.write(status)
    status = "( start_unit: "+ str(start_unit) + " num_units: " + str(num_units) + ")\n"
    output_file.write(status)

    outlist = cfile.get_output(mirror, config.Cline, config.ClineDelta,
                               start_unit, num_units,
                               config.Direction, suppress_end_code)
    for line in outlist:
        output_file.write(line)
    output_file.write("( END FILE " + fname + " )\n")


featuredict = {}


def is_condition_true(condition):
    debug_condition = False
    rval = True

    if condition == "None":
        return True;

    # OK. Condition is not "None" so we have to actually do the evaluation.
    # simple case: condition equals one of the parameters or the negation. Search through the parameters for this condition string.
    if debug_condition:
        print("Evaluating condition: " + condition)

    # break condition into an array of elements
    equal = False
    notequal = False
    op = ""

    split_conditions    = condition.split("==")
    if (len(split_conditions) == 2):
        equal = True
        op = "equal"

    else:
        split_conditions = condition.split("!=")
        if (len(split_conditions) == 2):
            notequal = True
            op="notequal"
        else:
            split_conditions = condition.split("&&")
            op="boolean"

    r1 = ""
    r2 = ""
    c1 = split_conditions[0]
    c2 = ""
    if c1 in featuredict:
        r1 = featuredict[c1]

    if ((len(split_conditions) == 2)):
        c2 = split_conditions[1]
        r2 = c2

        if debug_condition:
            print(c1 + "...feature dict value: " + str(featuredict[c1]))

    if debug_condition:
        print("...split into array: " + str(split_conditions) + " =====> " + str(c1) + "==" + str(r1) + "    " + str(c2) + "     operation: " + op)

    if (equal):
        if r1 == r2:
            if debug_condition:
                print(".....equal condition met return true")
            return True
        else:
            if debug_condition:
                print(".....equal condition not met return false")
            return False
    if (notequal):
        if r1 != r2:
            if debug_condition:
                print(".....notequal condition met return true")
            return True
        else:
            if debug_condition:
                print(".....notequal condition not met return false")
            return False

    # no == or !=
    for c in split_conditions:
        # now for each sub-condition see if it is True

        if (c[:1] == "!"):
            reverse = True
            c = c[1:]
            if debug_condition:
                print("...negative condition: !" + c)
        else:
            reverse = False

        if c in featuredict:
            if debug_condition:
                print("...feature dict value: " + str(featuredict[c]))

            if featuredict[c]:
                rval2 = True
            else:
                rval2 = False

            if reverse:
                rval2 = not rval2

            rval = rval and rval2

        else:
            print("FATAL ERROR: can't evaluate this condition: " + c)
            dpg.destroy_context()
            return True

    if debug_condition:
        print("...returning " + str(rval))

    return rval




def write_output_files(file_list):
    debug_wof = False
    output_file_ind_unit = []

    if debug_wof:
        print("*************** creating output directories")
    for i in range(1, config.MaxUnits + 1):
        # create output directories
        if debug_wof:
            print("making " + config.output_dir + "/" + str(i))
        try:
            os.makedirs(config.output_dir + "/" + str(i) + "/IndFiles", True)
        except OSError as error:
            if error.errno != errno.EEXIST:
                print("FATAL ERROR: can't create directory: ", config.output_dir + "/" + str(i) + " ERROR: " + str(error) )
                dpg.destroy_context()

        if debug_wof:
            print("making " + config.output_dir + "/" + str(i) + "/Features")
        try:
            os.makedirs(config.output_dir + "/" + str(i) + "/Features", True)
        except OSError as error:
            if error.errno != errno.EEXIST:
                print("FATAL ERROR: can't create directory: ", config.output_dir + "/" + str(i) + "/Features ERROR: " + str(error) )
                dpg.destroy_context()


    for i in range(2, config.MaxUnits + 1):
        # create output directories
        try:
            os.makedirs(config.output_dir + "/1to" + str(i), True)
        except OSError as error:
            if error.errno != errno.EEXIST:
                print("FATAL ERROR: can't create directory: ", config.output_dir + "/1to" + str(i) + "ERROR: " + str(error) )
                dpg.destroy_context()


    # *************************************************************************************************
    # grab a screenshot to document the settings and save it in the output directory
    # do this before generating files since that takes time and the screen will probably change before then...
    if debug_wof:
        print("********** Dumping screenshot")
    im = pyautogui.screenshot()
    im.save(config.output_dir + "/" + "Screenshot.jpg")
    # *************************************************************************************************

    for i in range(0, config.NumSteps):
        if debug_wof:
            print("*************** write_output_files: step #", i, "/", config.NumSteps, config.output_file_names[i])
        if not len(file_list[i]):
            # no files for output file #i
            if debug_wof:
                print("*************** No files for this step.")
            continue

        output_file = open(config.output_dir + "/" + config.output_file_names[i], "w")
        if not output_file:
            print("FATAL ERROR CAN NOT OPEN OUTPUT FILE: ", config.output_file_names[i])
            dpg.destroy_context()

        output_file_ind_unit = []
        for unit in range(0, config.MaxUnits):
            unit_fn = config.output_dir + "/" + str(unit+1) + "/" + config.output_file_names[i]
            newfile = open(unit_fn, "w")
            if debug_wof:
                print("...opening unit output file: ", unit_fn, "result: ", newfile)
            if not newfile:
                print("FATAL ERROR CAN NOT OPEN OUTPUT FILE: ", config.output_file_names[i], " for unit " + str(unit))
                dpg.destroy_context()
            output_file_ind_unit.append(newfile)

        num_files = len(file_list[i])
        for j in range(0, num_files):
            if debug_wof:
                print("*************** write_output_files outputting " + file_list[i][j].name + " to " + config.output_dir + "/" + config.output_file_names[i])
            current_tool_num = file_list[i][j].get_toolnum()
            if j < num_files - 1:
                next_tool_num = file_list[i][j + 1].get_toolnum()
            else:
                next_tool_num = -1

            if next_tool_num == current_tool_num:
                suppress_end_code = True
            else:
                suppress_end_code = False

            if re.search("-NODUP", file_list[i][j].name):
                # NODUP IMPLIES NOMIRROR
                # no duplication/displacement and no mirroring for this file
                numUnits = 1
                mirror_active = False
            else:
                numUnits = config.NumUnits
                mirror_active = config.Lefty

            if re.search("-NOMIRROR", file_list[i][j].name):
                mirror_active = False

            write_output_file(file_list[i][j], file_list[i][j].name, output_file,
                              1, numUnits,
                              mirror_active,
                              current_tool_num,
                              suppress_end_code)
            if numUnits == 1:
                # output this file only in the unit 1 output
                if debug_wof:
                    print("*************** write_output_files ind units " + file_list[i][j].name + " to " + config.output_dir + "/1/" + config.output_file_names[i])
                write_output_file(file_list[i][j], file_list[i][j].name, output_file_ind_unit[0],
                              1, 1,
                              mirror_active,
                              current_tool_num,
                              suppress_end_code)
            else:
                for unit in range (0, config.MaxUnits):
                    # output this file for each unit
                    if debug_wof:
                        print("*************** write_output_files ind units " + file_list[i][j].name + " to " + config.output_dir + "/" + str(unit) + "/" + config.output_file_names[i])
                    write_output_file(file_list[i][j], file_list[i][j].name, output_file_ind_unit[unit],
                                      unit+1, unit+1,
                                      mirror_active,
                                      current_tool_num,
                                      suppress_end_code)

        for unit in range(0, config.MaxUnits):
            output_file_ind_unit[unit].close()


    if debug_wof:
        print("*************** outputing individual files")
    for cfile in CAMFiles:
        # output individual files for each unit, appropriately mirrored if lefty
        fname = cfile.name
        for i in range(1, config.MaxUnits + 1):
            ofname = config.output_dir + "/" + str(i) + "/IndFiles/" + fname
            if re.search("-NODUP", fname):
                if i == 1:
                    if debug_wof:
                        print("     NoDUP. Outputing for unit 1 only")
                    # no duplication, displacement, do not output to the individual units except for first unit.
                    # do not suppress end codes
                    output_file = open(ofname, "w")
                    write_output_file(cfile, fname, output_file, 1, 1, False,        -1, False)
                    output_file.close()
                else:
                    if debug_wof:
                        print("     NoDUP. Not outputing for unit ", i)
            else:
                if debug_wof:
                    print("     Normal file, outputting for unit ", i, "only.")
                output_file = open(ofname, "w")
                write_output_file(cfile, fname, output_file, i, i, config.Lefty, -1, False)
                output_file.close()

        # this is not necessary for determining suppression of end codes (since we won't)
        # but is still necessary since it is output in comments into the file
        current_tool_num = cfile.get_toolnum()

        # do not suppress end code since files are intended to be run independently
        suppress_end_code = False

        if debug_wof:
            print("*************** outputing composite files")
            # for each possible number of units from 1-config.numUnits, build individual files for multiple units
        for i in range(2, config.MaxUnits + 1):
            fname = cfile.name

            ofname = config.output_dir + "/1to" + str(i) + "/" + fname
            output_file = open(ofname, "w")
            if re.search("-NODUP", fname):
                # no duplication, displacement, mirroring for this one.
                if debug_wof:
                    print("     NODUP case. This was already written above")
                continue

            else:
                if debug_wof:
                    print("     Normal file, outputting for units [1:", i, "] to ", ofname)
                write_output_file(cfile, fname, output_file, 1, i, config.Lefty, -1, True)

    # Output files for each feature (including any/all files for that feature) for each individual unit
    if False:
        for i in range(1, config.MaxUnits + 1):
            # output combined gcode files for any set of files that are the same other than _nn sequence numbers
            for cf in sorted(CAMFiles, key=lambda cfile: cfile.name):
                config.input_dir = str(cf.get_dir())
                if debug_wof:
                    print("CAM file: " + config.input_dir + "\\" + cf.name)

                newline = cf.name
                # newline = re.sub("-front", "", newline)
                # newline = re.sub("-back", "", newline)
                newline = re.sub("-start", "", newline)
                newline = re.sub("-first", "", newline)
                newline = re.sub("-end", "", newline)
                newline = re.sub('-[0-9][0-9]', '', newline)
                newline = re.sub('-NOMIRROR', '', newline)
                newline = re.sub('-NODUP', '', newline)

                ofname = config.output_dir + "/" + str(i) + "/Features/" + newline
                if debug_wof:
                    print("Creating feature output file " + str(ofname))
                output_file = open(ofname, "a")
                write_output_file(cf, cf.name, output_file, i, i, config.Lefty, -1, False)

    # *************************************************************************************************
    if debug_wof:
        print("********** Dumping summary.txt file")
    # dump out a list of input files, etc. and the output mapping
    output_file = open(config.output_dir + "/" + "summary.txt", "w")
    output_file.write("Model:" + str(config.model) + "\n")
    output_file.write("\nLefty:" + str(config.Lefty) + "\nNunits:" + str(config.NumUnits) + "\n")
    output_file.write(
        "\nCline: " + str(config.Cline) + "\nClineDelta:" + str(config.ClineDelta) + " \nDirection:" + str(
            config.Direction) + "\n")
    output_file.write("\nInput Dir:" + str(config.input_dir) + "\nOutput Dir:" + str(config.output_dir) + "\nCommon Dir:" + str(config.common_dir) + "\n")
    output_file.write("\nNotes:\n" + str(dpg.get_value(note_txt)) + "\nEndNotes\n\n")

    output_file.write("**************************************************************\n")
    output_file.write("**********OutputFileNames*************************************\n")

    for step_num in range(0, config.NumSteps):
        output_file.write(config.output_file_names[step_num] + "\n")

    output_file.write("**************************************************************\n\n")

    output_file.write("**************************************************************\n")
    output_file.write("**********OutputFileContents**********************************\n")
    for i in range(0, config.NumSteps):
        output_file.write(config.output_file_names[i] + ":\n")
        for j in file_list[i]:
            output_file.write("\t" + j.name + "\tT" + str(j.get_toolnum()) + "\n")

    output_file.write("**************************************************************\n\n")

    output_file.write("**************************************************************\n")
    output_file.write("**********CAMFiles********************************************\n")
    for x in range(len(CAMFiles)):
        config.input_dir = str(CAMFiles[x].get_dir())
        output_file.write("CAM file: " + config.input_dir + "\\" + str(CAMFiles[x]))
        output_file.write("\n")

    output_file.write("**************************************************************\n\n")

    output_file.write("**************************************************************\n")
    output_file.write("**********CAMFiles: stats**************************************\n")
    output_file.write("XMin\tXMax\tYMin\tYMax\tZMin\tZMax")
    output_file.write("\tTNUM")
    output_file.write("\tSMin\tSMax")
    output_file.write("\tFileName\n")

    for x in range(len(CAMFiles)):
        output_file.write(str(CAMFiles[x].min_x))
        output_file.write("\t" + str(CAMFiles[x].max_x))
        output_file.write("\t" + str(CAMFiles[x].min_y))
        output_file.write("\t" + str(CAMFiles[x].max_y))
        output_file.write("\t" + str(CAMFiles[x].min_z))
        output_file.write("\t" + str(CAMFiles[x].max_z))
        output_file.write("\t" + str(CAMFiles[x].get_toolnum()))
        output_file.write("\t" + str(CAMFiles[x].min_s))
        output_file.write("\t" + str(CAMFiles[x].max_s))
        output_file.write("\t" + str(CAMFiles[x]))
        output_file.write("\n")

    output_file.write("**************************************************************\n\n")

    output_file.write("**************************************************************\n")
    output_file.write("**********BaseFiles*******************************************\n")
    # get base files from root directory
    for x in config.base_files:
        output_file.write("BASE file: " + config.input_dir + "\\" + str(x) + "\n")
    output_file.write("**************************************************************\n")

    output_file.write("**************************************************************\n")
    output_file.write("**********ScriptCalculatedFeatureTree*************************\n")
    for ft in FeatureBlocks:
        output_file.write(str(ft) + "\n")
    output_file.write("**************************************************************\n")

    output_file.write("**************************************************************\n")
    output_file.write("**********ScriptCalculatedFeatures****************************\n")
    for fnum in range(len(CAMFeatures)):
        output_file.write(str(CAMFeatures[fnum]) + "\n")
    output_file.write("**************************************************************\n")

    # *************************************************************************************************
    # And close the summary file.
    # *************************************************************************************************
    output_file.close()
    # *************************************************************************************************
    # *************************************************************************************************

    # *************************************************************************************************
    # generate a tool list to be output to the output directory, and check to see if there are any potential conflicts
    # in tool number assignments - if the tool descriptions for two tools with the same number do not match.
    # *************************************************************************************************
    have_error = False
    have_warning = False
    tools_filename = config.output_dir + f"/tools.txt"
    tfile = open(tools_filename, "w")
    tfile.write("Model:" + str(config.model) + "\n")
    tfile.write("\nLefty:" + str(config.Lefty) + "\nNunits:" + str(config.NumUnits) + "\n")
    tfile.write(
        "\nCline: " + str(config.Cline) + "\nClineDelta:" + str(config.ClineDelta) + " \nDirection:" + str(
            config.Direction) + "\n")
    tfile.write("\nInput Dir:" + str(config.input_dir) + "\nOutput Dir:" + str(config.output_dir) + "\n")
    tfile.write("\nNotes:\n" + str(dpg.get_value(note_txt)) + "\nEndNotes\n\n")

    for t in sorted(tools, key=lambda x: x.tnum):
        mytoolnum = t.get_tnum()
        mydesc = t.get_desc()

        # Determine if the file in question is actually used in this run, as determined by the user-chosen options.
        # If not, then note the potential error as a warning
        myfilename = t.get_fname()

        if False and debug_wof:
            print("********** Tool check: ", mytoolnum, myfilename, mydesc)

        myfilenum = -1
        # get the CAMFile object for this file name
        for fnum in range(len(CAMFiles)):
            if False and debug_wof:
                print("checking: ", CAMFiles[fnum].get_filename(), myfilename)
            if (CAMFiles[fnum].get_name() == myfilename):
                if False and debug_wof:
                    print("match! num=", fnum)
                myfilenum = fnum
                break

        if myfilenum == -1:
            # huh? didn't find the CAM file for this. WTF?
            print("WTF. can't find my own CAM File structure! Aborting." + myfilename)
            print(CAMFiles)
            dpg.destroy_context()

        for t2 in sorted(tools, key=lambda x: x.tnum):
            if (t2.fname == myfilename):
                # this is just us! move on!
                continue

            if (t2.get_tnum() == mytoolnum):
                # OK, this is our toolnumber before! (or this is the same tool... but no matter)
                if t2.get_desc() != mydesc:
                    # print("error! inside ", mytoolnum, mydesc, myfilename)
                    # this is the problem case: mark it as such
                    t2filenum = -1
                    # get the CAMFile object for this file name
                    for fnum in range(len(CAMFiles)):
                        if (CAMFiles[fnum].get_name() == t2.fname):
                            t2filenum = fnum
                            break

                    if t2filenum == -1:
                        # huh? didn't find the CAM file for this. WTF?
                        print("WTF. can't find T2 CAM File structure! Aborting.")
                        dpg.destroy_context()

                    if (CAMFiles[myfilenum].get_selected() or CAMFiles[t2filenum].get_selected()):
                        have_error = True
                        t.set_error(True)
                        t2.set_error(True)
                    else:
                        have_warning = True
                        t.set_warning(True)
                        t2.set_warning(True)

    if have_warning:
        # put some error text out the GUI to let the user know
        dpg.set_value(error_txt, "WARNING: conflicting tool numbers. See tools.txt in the output directory.")
    if have_error:
        # put some error text out the GUI to let the user know
        dpg.set_value(error_txt, "ERROR: conflicting tool numbers. See tools.txt in the output directory.")

    # write the tool list out to the file but filter out repeats but not error cases
    last_tnum = -1
    tfile.write("Error\tTnum\tDesc\tFirstOccuranceFile\n")
    for t in sorted(tools, key=lambda x: x.tnum):
        if not t.get_error() and not t.get_warning() and t.get_tnum() == last_tnum:
            # print("skipping tool")
            continue
        last_tnum = t.get_tnum()
        # print("writing tool")
        tfile.write(f"{t}\n")
    tfile.close()

    # create archive files (in, out)
    model = config.model
    dtime: datetime = datetime.now()
    base_name = model + "--" + str(
        dtime.year) + "-" + "%02d" % dtime.month + "-" + "%02d" % dtime.day + "--" + "%02d" % dtime.hour + "-" + "%02d" % dtime.minute + "-" + "%02d" % dtime.second
    root_dir = "G:\\Shared drives\\AlloyProjectFiles\\Customer CAD files\\Alloy-Standard-Builds-CAM\\Archive"
    archive_name = str(Path(root_dir + "\\" + base_name + "-in"))
    adir = config.input_dir
    shutil.make_archive(archive_name, "gztar", adir)

    archive_name = str(Path(root_dir + "\\" + base_name + "-out"))
    adir = config.output_dir
    shutil.make_archive(archive_name, "gztar", adir)

    print("********** Done Dumping Files! ******************")



def generate_file_based(sender, app_data):
    wildcard = {}

    print("**************generating based on parameters ****************************************")

    # get BASE featureblock so that we can get LEFTY, and NumUnits
    for b in FeatureBlocks:
        blockname = b.name
        # print("scanning featureblock ", blockname)
        if blockname == "BASE":
            # walk through all features in this block
            for x in b.features:
                featurename = x.name
                bval = x.get_button_value()
                # print("adding feature ", featurename, bval)
                featuredict[featurename] = bval
                if featurename == "Lefty":
                    if bval:
                        config.Lefty = True
                    else:
                        config.Lefty = False
                elif featurename == "NumUnits":
                    # print(" bval:", bval)
                    config.NumUnits = int(bval)
                else:
                    # not a match, do nothing
                    print("POTENTIAL ERROR NO MATCH IN BASE: " + featurename)
            continue

        # non-BASE block. Walk through all features and get values, building a dictionary mapping name->value
        for x in b.features:
            featurename = x.name
            bvalue = x.get_button_value()
            wvalue = x.wildcard
            # print("adding feature ", featurename, bvalue)
            featuredict[featurename] = bvalue
            if wvalue:
                wildcard[wvalue] = featurename
                #print("new wc: ", wvalue, featurename)

    # OK, we have all features in the featuredict structure.
    # for item in featuredict.items():
    #     print(item)

    # now for each base name, fill in the features
    input_expanded_base_names = []
    for fname in config.input_file_base_names:
        # print("filling in: ", fname)
        for item in featuredict:
            # OK, search for <feature_name> and replace with <feature_value>
            # print("  item:", item, featuredict[item])
            restr = re.sub(r"\<" + item + r"\>", str(featuredict[item]), fname)
            fname = restr

        # print(" final: ", fname)
        input_expanded_base_names.append(fname)

    #print("Base file forms selected:")
    for i in range(0, len(input_expanded_base_names)):
        fname = input_expanded_base_names[i]
        #print("     " + fname + " required? " + str(config.input_file_base_required[i]))

    if True:
        print("TOOLS:")
        for t in sorted(tools, key=lambda x: x.tnum):
            print(t)

        print("FEATURES:")
        for fnum in range(len(CAMFeatures)):
            print("     " + str(CAMFeatures[fnum]))

        print("FILES")
        for fnum in range(len(CAMFiles)):
            print("     " + str(CAMFiles[fnum]))

        print("BLOCKS:")
        for fb in range(len(FeatureBlocks)):
            print("     " + str(FeatureBlocks[fb]))

    build_checkboxes()

    for f in CAMFiles:
        print("file: ", f, f.is_base_file)
        if f.is_base_file:
            f.set_selected(False)

    file_search_debug = True
    file_search_results_debug = True
    for i in range(0, len(input_expanded_base_names)):
        # skip this file if the condition associated with it is not True
        if config.input_file_base_condition[i] != "None":
            if not is_condition_true(config.input_file_base_condition[i]):
                if file_search_debug or file_search_results_debug:
                    print("base name: " + input_expanded_base_names[i] + " condition: " + config.input_file_base_condition[i] + " FALSE! skipping this file base.")
                continue

        if file_search_debug or file_search_results_debug:
            print("Looking for matches for " + input_expanded_base_names[i])
        got_one = False
        got_exact = False

        newline = ""
        for f in CAMFiles:

            # remove step details to extract feature name
            if file_search_debug:
                print("***checking ", f.name)

            newline = f.name
            #newline = re.sub("-front", "", newline)
            #newline = re.sub("-back", "", newline)
            newline = re.sub("-start", "", newline)
            newline = re.sub("-first", "", newline)
            newline = re.sub("-end", "", newline)
            newline = re.sub('.nc', "", newline)
            newline = re.sub('-[0-9][0-9]', '', newline)
            newline = re.sub('-NOMIRROR', '', newline)
            if re.search("-lefty", newline):
                if config.Lefty:
                    # this file is for lefty... and we are in lefty mode Remove the -lefty.
                    newline = re.sub('-lefty', '', newline)
                # ELSE this file is for lefty... but we are not in lefty mode. We want to skip this... so just leave the -lefty in place.

            if re.search("-righty", newline):
                if not config.Lefty:
                    # this file is for right... and we are in righty mode Remove the -righty.
                    newline = re.sub('-righty', '', newline)
                # ELSE this file is for righty... but we are in lefty mode. We want to skip this... so just leave the -righty in place.

            if file_search_debug or file_search_results_debug:
                print("      " + f.name + "==>" + newline + " no match to " + input_expanded_base_names[i])

            if newline == input_expanded_base_names[i]:
                # match!
                if file_search_debug or file_search_results_debug:
                    print("     base name: " + input_expanded_base_names[i] + " condition: " + config.input_file_base_condition[i] + " True! ==> match: " + f.name + "==>" + newline)
                f.set_selected(True)
                got_one = True
                got_exact = True

                if file_search_debug or file_search_results_debug:
                    print("have exact match skipping wildcard analysis for " + f.name + "==>" + newline)

        if not got_exact:
            # OK, now we search all files using wild card
            newline = ""
            for f in CAMFiles:

                # remove step details to extract feature name
                if file_search_debug:
                    print("***checking ", f.name)

                newline = f.name
                # newline = re.sub("-front", "", newline)
                # newline = re.sub("-back", "", newline)
                newline = re.sub("-start", "", newline)
                newline = re.sub("-first", "", newline)
                newline = re.sub("-end", "", newline)
                newline = re.sub('.nc', "", newline)
                newline = re.sub('-[0-9][0-9]', '', newline)
                newline = re.sub('-NOMIRROR', '', newline)

                if re.search("-lefty", newline):
                    if config.Lefty:
                        # this file is for lefty... and we are in lefty mode Remove the -lefty.
                        newline = re.sub('-lefty', '', newline)
                    # ELSE this file is for lefty... but we are not in lefty mode. We want to skip this... so just leave the -lefty in place.

                if re.search("-righty", newline):
                    if not config.Lefty:
                        # this file is for right... and we are in righty mode Remove the -righty.
                        newline = re.sub('-righty', '', newline)
                    # ELSE this file is for righty... but we are in lefty mode. We want to skip this... so just leave the -righty in place.

                if file_search_debug or file_search_results_debug:
                    print("      " + f.name + "==>" + newline + " no match to " + input_expanded_base_names[i])

                #************************************************************************
                # OK, no exact matches. Let's check to see if a wildcard creates a match
                #************************************************************************
                # search through newline and replace occurrences of wildcards with the selected value
                if False and file_search_debug:
                    print("***", wildcard, "***")
                wcitems = wildcard.items()

                newline_orig = newline
                for j in range(0, len(wcitems)):
                    feat = list(wcitems)[j][1]
                    wcstring = list(wcitems)[j][0]
                    fval = featuredict[feat]
                    if False and file_search_debug:
                        print("WC: ", wcstring, feat, "==>", fval)
                    if wcstring == "":
                        if file_search_debug:
                                print("... skipping since WC is empty string")
                        continue

                    # OK, search for <wcstring> and replace with <fval>
                    restr = re.sub(r"" + wcstring + r"", str(fval), newline)
                    if restr != newline:
                        newline = restr
                    else:
                        continue

                if file_search_debug:
                    print("WCs applied. " + f.name, "==>", newline)
                if newline == newline_orig:
                    # there was no wildcard replacement for this file. We are done here.
                    if file_search_debug or file_search_results_debug:
                        print("      " + f.name + "==>" + newline + " no wildcards replaced",
                              input_expanded_base_names[i])

                elif newline == input_expanded_base_names[i]:
                    # match!
                    if file_search_debug or file_search_results_debug:
                        print("     base name: " + input_expanded_base_names[i] + " condition: " + config.input_file_base_condition[i] + " True! ==> Wildcard match: " + f.name + "==>" + newline)
                    f.set_selected(True)
                    got_one = True
                else:
                    if file_search_debug or file_search_results_debug:
                        print("      " + f.name + "==>" + newline + " no match with wildcards to ", input_expanded_base_names[i])

        if not got_one:

            if config.input_file_base_required[i]:
                print("FATAL ERROR: no matching file for REQUIRED " + input_expanded_base_names[i])
                dpg.destroy_context()
            else:
                print("       no matching file for OPTIONAL " + input_expanded_base_names[i])

    input_base_names = []
    file_list = []

    for step_num in range(0, config.NumSteps):
        file_list.append([])
        input_base_names.append([])

    for step_num in range(0, config.NumSteps):

        snstr = "^%02d-" % step_num # SMB
        stepnumsearch = re.search("^([A-Z])?([0-9][0-9]-)(.*)", config.output_file_names[step_num])
        if stepnumsearch:
            stepprefix = stepnumsearch[1]
            stepnum = stepnumsearch[2]
            snstr = str(stepprefix) + str(stepnum)
        else:
            stepnumsearch = re.search("^([0-9][0-9]-)(.*)", config.output_file_names[step_num])
            if stepnumsearch:
                snstr = stepnumsearch[1]

        input_base_names[step_num] = []
        for i in range(0, len(input_expanded_base_names)):
            if re.search(snstr, input_expanded_base_names[i]):
                input_base_names[step_num].append(input_expanded_base_names[i])


    # ***************************************************************************
    # ***************************************************************************
    # ***************************************************************************
    # generic
    debug_files = True
    for step_num in range(0, config.NumSteps):
        snstr = "^" + config.output_file_prefix[step_num]
        #snstr = "^%02d-" % step_num
        if debug_files:
            print("STEP: " + str(snstr) + " c.ofp=" + config.output_file_prefix[step_num] + " FS:" + config.FrontStep + " BS:" + config.BackStep)

        for f in CAMFiles:
            if not f.get_selected():
                continue
            if f.get_base():
                continue
            if re.search("-lefty", f.name):
                if not config.Lefty:
                    continue
            if re.search("-righty", f.name):
                if config.Lefty:
                    continue

            if re.search(snstr, f.name) and re.search("-first", f.name):
                if debug_files:
                    print(step_num+"(features): ", f.name)
                    print("8", f.name)

                file_list[step_num].append(f)

        # "-start" files
        for bf in config.base_files:
            # unlike the file-based case, we only use base files if they are marked as selected
            if not bf.get_selected():
                continue
            if re.search("-lefty", bf.name):
                if not config.Lefty:
                    continue
            if re.search("-righty", bf.name):
                if config.Lefty:
                    continue
            if re.search(snstr, bf.name):
                if config.HasStartAndEnd is False:
                    # print("6", f.name)
                    if debug_files:
                        print("      (noSE): " + bf.name + "==>" + re.sub('-[0-9][0-9]', '', bf.name))
                    file_list[step_num].append(bf)
                elif re.search("-start", bf.name):
                    # print("7", bf.name)
                    # print(step_num+"start): ", bf.name)
                    if debug_files:
                        print("      -start: " + bf.name + "==>" + re.sub('-[0-9][0-9]', '', bf.name))
                    file_list[step_num].append(bf)

        # features
        for f in CAMFiles:
            if not f.get_selected():
                continue
            if f.get_base():
                continue
            if re.search("-lefty", f.name):
                if not config.Lefty:
                    continue
            if re.search("-righty", f.name):
                if config.Lefty:
                    continue

            if re.search(snstr, f.name) and not re.search("-end", f.name) and not re.search("-first", f.name):
                if debug_files:
                    print(str(step_num) + "(features): ", f.name)
                    print("5", f.name)
                file_list[step_num].append(f)
                continue
            if re.search("^[0-9][0-9]", f.name):
                continue

            if re.search("-first", f.name):
                continue

            if re.search("-end", f.name):
                continue

            if config.output_file_prefix[step_num] != config.FrontStep and config.output_file_prefix[step_num] != config.BackStep:
                continue

            if config.output_file_prefix[step_num] == config.FrontStep:
                if re.search("-front", f.name) or not re.search("-back", f.name):
                    if debug_files:
                        print("9", f.name)
                    file_list[step_num].append(f)
                    continue
            elif config.output_file_prefix[step_num] == config.BackStep:
                if re.search("-back", f.name):
                    # "unlabeled" file. put it here as the default place for such files
                    if debug_files:
                        print("10", f.name)
                    file_list[step_num].append(f)
                    continue

        # not "-end" or "-start" files
        for bf in config.base_files:
            # unlike the file-based case, we only use base files if they are marked as selected
            if not bf.get_selected():
                continue
            if re.search("-lefty", bf.name):
                if not config.Lefty:
                    continue
            if re.search("-righty", bf.name):
                if config.Lefty:
                    continue
            if re.search(snstr, bf.name):
                if config.HasStartAndEnd is False:
                    # this was output above
                    continue
                elif re.search("-start", bf.name):
                    # this was output above
                    continue
                elif re.search("-end", bf.name):
                    # this will be outputbelow
                    continue
                else:
                    # print("4", bf.name)
                    # this needs to go out here (has our number, does not have start, and wasn't output above because start/end are not in use
                    # print(step_num+"(end): ", bf.name)
                    if debug_files:
                        print("      not start/end: " + bf.name + "==>" + re.sub('-[0-9][0-9]', '', bf.name))
                    file_list[step_num].append(bf)


        # "-end" files from features
        for f in CAMFiles:
            if not f.get_selected():
                continue
            if f.get_base():
                continue
            if re.search("-lefty", f.name):
                if not config.Lefty:
                    continue
            if re.search("-righty", f.name):
                if config.Lefty:
                    continue

            if re.search(snstr, f.name) and re.search("-end", f.name):
                if debug_files:
                    print(str(step_num)+"(features-end): ", f.name)
                #print("1", f.name)
                file_list[step_num].append(f)

            if not re.search("-end", f.name):
                continue

            if re.search("^[0-9][0-9]", f.name):
                continue

            if re.search("-first", f.name):
                continue

            if config.output_file_prefix[step_num] == config.FrontStep:
                if re.search("-front", f.name):
                    if debug_files:
                        print("2", f.name)
                    file_list[step_num].append(f)
                    continue
            elif config.output_file_prefix[step_num] == config.BackStep:
                if re.search("-back", f.name):
                    if debug_files:
                        print("3", f.name)
                    # "unlabeled" file. put it here as the default place for such files
                    file_list[step_num].append(f)
                    continue

        # "-end" files
        for bf in config.base_files:
            # unlike the file-based case, we only use base files if they are marked as selected
            if not bf.get_selected():
                continue
            if re.search("-lefty", bf.name):
                if not config.Lefty:
                    continue
            if re.search("-righty", bf.name):
                if config.Lefty:
                    continue
            if re.search(snstr, bf.name):
                if config.HasStartAndEnd is False:
                    # this was output above
                    continue
                elif re.search("-start", bf.name):
                    # this was output above
                    continue
                elif not re.search("-end", bf.name):
                    # this was output above
                    continue
                else:
                    # print("4", bf.name)
                    # this needs to go out here (has our number, does not have start, and wasn't output above because start/end are not in use
                    # print(step_num+"(end): ", bf.name)
                    if debug_files:
                        print("      -end: " + bf.name + "==>" + re.sub('-[0-9][0-9]', '', bf.name))
                    file_list[step_num].append(bf)

    # ***************************************************************************
    # ***************************************************************************
    # ***************************************************************************

    # *************************************************************************************************
    # for debug purposes, output the file lists
    for step_num in range(0, config.NumSteps): #SMB
        print(config.output_file_prefix[step_num], ": ", file_list[step_num])
    # *************************************************************************************************

    write_output_files(file_list)

    print("**************DONE generating based on parameters ****************************************")


def check_all(sender, app_data):
    # print("setting all buttons")
    for feat in CAMFeatures:
        feat.set_button_on()

        for y in range(feat.get_num_files()):
            xf = feat.get_file(y)
            # print("   iterating ", y, xf)
            xf.set_selected(True)


def generate(sender, app_data):
    if config.FileBased == False:
        generate_file_based(sender, app_data)
        return

    print("**************generating****************************************")

    dpg.set_value(error_txt, "")

    # get BASE featureblock so that we can get LEFTY, and NumUnits
    for b in FeatureBlocks:
        blockname = b.name
        if not blockname == "BASE":
            continue

        # walk through all features in this block
        for x in b.features:
            featurename = x.name
            bval = x.get_button_value()
            if featurename == "Lefty":
                if bval:
                    config.Lefty = True
                else:
                    config.Lefty = False
            elif featurename == "NumUnits":
                # print("btn:", btn, " bval:", bval)
                config.NumUnits = int(bval)
            else:
                # not a match, do nothing
                print("POTENTIAL ERROR NO MATCH IN BASE: " + featurename)

    print("Lefty:", config.Lefty, " Nunits:", config.NumUnits)

    # if enabled, print to debug a list of all files
    if True:
        for x in range(len(CAMFiles)):
            print("CAM file: ", CAMFiles[x])

        # get base files from root directory
        for x in config.base_files:
            print("BASE file: ", x)

    # file list is 11 elements. We will ignore element 0 simply so that file numbers match the index used
    file_list = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    # ***************************************************************************
    # ***************************************************************************
    # ***************************************************************************
    # generic
    debug_fs = True
    for step_num in range(0, config.NumSteps):
        snstr = "^" + config.output_file_prefix[step_num]
        #snstr = "^%02d-" % step_num
        if debug_fs:
            print(snstr)
        for f in CAMFiles:
            if False and debug_fs:
                print(f.name)
            if not f.get_selected():
                if debug_fs:
                    print(f.name + " not selected")
                continue
            if f.get_base():
                if debug_fs:
                    print(f.name + " in base")
                continue
            if re.search("-lefty", f.name):
                if not config.Lefty:
                    continue
            if re.search("-righty", f.name):
                if config.Lefty:
                    continue

            if re.search(snstr, f.name) and re.search("-first", f.name):
                if debug_fs:
                    print(str(step_num)+"(features): ", f.name)
                    print("8", f.name)

                file_list[step_num].append(f)
            if False and config.output_file_prefix[step_num] == config.FrontStep:
                if re.search("-front", f.name) or not re.search("-back", f.name):
                    if debug_fs:
                        print("9a", f.name)
                    file_list[step_num].append(f)
                    continue
            elif False and config.output_file_prefix[step_num] == config.BackStep:
                if re.search("-back", f.name):
                    # "unlabeled" file. put it here as the default place for such files
                    if debug_fs:
                        print("10a", f.name)
                    file_list[step_num].append(f)
                    continue

        # "-start" files
        for bf in config.base_files:
            if re.search("-lefty", bf.name):
                if not config.Lefty:
                    continue
            if re.search("-righty", bf.name):
                if config.Lefty:
                    continue
            if re.search(snstr, bf.name):
                if config.HasStartAndEnd is False:
                    # print("6", f.name)

                    file_list[step_num].append(bf)
                elif re.search("-start", bf.name):
                    if debug_fs:
                        print("7", bf.name)
                        print(str(step_num) + "start): ", bf.name)
                    file_list[step_num].append(bf)

        # features
        for f in CAMFiles:
            if not f.get_selected():
                continue
            if f.get_base():
                continue
            if re.search("-lefty", f.name):
                if not config.Lefty:
                    continue
            if re.search("-righty", f.name):
                if config.Lefty:
                    continue

            if re.search(snstr, f.name) and not re.search("-end", f.name) and not re.search("-first", f.name):
                if debug_fs:
                    print(str(step_num)+"(features): ", f.name)
                    print("5", f.name)
                file_list[step_num].append(f)
                continue
            if re.search("^[0-9][0-9]", f.name):
                continue

            if re.search("-first", f.name):
                continue

            if re.search("-end", f.name):
                continue

            if config.output_file_prefix[step_num] != config.FrontStep and config.output_file_prefix[step_num] != config.BackStep:
                continue

            if config.output_file_prefix[step_num] == config.FrontStep:
                if re.search("-front", f.name) or not re.search("-back", f.name):
                    if debug_fs:
                        print("9", f.name)
                    file_list[step_num].append(f)
                    continue
            elif config.output_file_prefix[step_num] == config.BackStep:
                if re.search("-back", f.name):
                    # "unlabeled" file. put it here as the default place for such files
                    if debug_fs:
                        print("10", f.name)
                    file_list[step_num].append(f)
                    continue

        # "-end" files
        for bf in config.base_files:
            if re.search("-lefty", bf.name):
                if not config.Lefty:
                    continue
            if re.search("-righty", bf.name):
                if config.Lefty:
                    continue
            if re.search(snstr, bf.name):
                if config.HasStartAndEnd is False:
                    # this was output above
                    continue
                elif re.search("-start", bf.name):
                    # this was output above
                    continue
                else:
                    if debug_fs:
                        print("4", bf.name)
                    # this needs to go out here (has our number, does not have start, and wasn't output above because start/end are not in use
                    # print(step_num+"(end): ", bf.name)
                    file_list[step_num].append(bf)

        # "-end" files from features
        for f in CAMFiles:
            if not f.get_selected():
                continue
            if f.get_base():
                continue
            if re.search("-lefty", f.name):
                if not config.Lefty:
                    continue
            if re.search("-righty", f.name):
                if config.Lefty:
                    continue

            if re.search(snstr, f.name) and re.search("-end", f.name):
                if debug_fs:
                    print(str(step_num)+"(features-end): ", f.name)
                    print("1", f.name)
                file_list[step_num].append(f)

            if not re.search("-end", f.name):
                continue

            if re.search("^[0-9][0-9]", f.name):
                continue

            if re.search("-first", f.name):
                continue

            if config.output_file_prefix[step_num] == config.FrontStep:
                if re.search("-front", f.name):
                    if debug_fs:
                        print("2", f.name)
                    file_list[step_num].append(f)
                    continue
            elif config.output_file_prefix[step_num] == config.BackStep:
                if re.search("-back", f.name):
                    if debug_fs:
                        print("3", f.name)
                    # "unlabeled" file. put it here as the default place for such files
                    file_list[step_num].append(f)
                    continue

    # ***************************************************************************
    # ***************************************************************************
    # ***************************************************************************

    # *************************************************************************************************
    # for debug purposes, output the file lists
    for step_num in range(0, config.NumSteps):
        print(step_num, ": ", file_list[step_num])
    # *************************************************************************************************

    # *************************************************************************************************
    # *************************************************************************************************
    # *************************************************************************************************
    # OK, now build the actual output files
    # *************************************************************************************************
    # *************************************************************************************************
    # *************************************************************************************************
    # *************************************************************************************************
    # write the actual output files
    # *************************************************************************************************
    write_output_files(file_list)




def callback_out(sender, app_data):
    # print("(out)Sender: ", sender)
    # print("(out)App Data: ", app_data)
    directory = app_data['file_path_name']
    dpg.set_value(od_txt, directory)
    config.output_dir = directory
    dpg.configure_item(dpgGenBtn, enabled=True, )
    dpg.configure_item(dpgCheckAllBtn, enabled=True)


current_featureblock = FeatureBlock("BASE", "")
base_featureblock = True

lefty_feature = CAMFeature('Lefty')
current_featureblock.add_feature(lefty_feature)
numunits_feature = CAMFeature('NumUnits')
current_featureblock.add_feature(numunits_feature)

FeatureBlocks.append(current_featureblock)


def parse_parameters(obj):
    # print(json.dumps(obj, indent=4, sort_keys=True))
    for param in obj['PARAMETERS']:
        print(json.dumps(param))
        newfeature = CAMFeature(param['name'])

        if param['wildcard']:
            newfeature.wildcard = param['wildcard']
        else:
            newfeature.wildcard = ""

        btnitems = []
        for option in param['values']:
            btnitems.append(option)

        #if not param['required']:
         #   btnitems.append('None')

        if len(btnitems) > 2:
            # create a radio button for this feature
            newfeature.set_radiobtn(btnitems)
            newfeature.set_default_val(param['default'])

        elif len(btnitems) == 2:
            if (((btnitems[0] == "True" or btnitems[0] == "False") and
                 (btnitems[1] == "True" or btnitems[1] == "False")) or
                    ((btnitems[0] == "Yes" or btnitems[0] == "No") and
                     (btnitems[1] == "Yes" or btnitems[1] == "No"))):
                # it is a simple button. Nothing to do
                #btnitems = []
                newfeature.set_default_val(param['default'])

            else:
                # this is a non T/F 2 element option. create a radio button
                newfeature.set_radiobtn(btnitems)
                newfeature.set_default_val(param['default'])

        # print(param['block'])
        if param['block'] == "Base":
            current_featureblock.add_feature(newfeature)
        else:
            # get or create the appropriate feature block
            feat = get_feature_block(param['block'])
            if feat == 0:
                # create block
                feat = FeatureBlock(param['block'], "")
                FeatureBlocks.append(feat)
                # print("created: ", feat)

            feat.add_feature(newfeature)

    # get input file name templates
    if not obj['INPUT-FILE-NAME-BASES']:
        print("error: FILE BASED but no input file name templates")
        return

    config.input_file_base_names = []
    for fname in obj['INPUT-FILE-NAME-BASES']:
        config.input_file_base_names.append(fname['name'])
        config.input_file_base_required.append(fname['required'] == 'True')
        config.input_file_base_condition.append(fname['condition'])


def callback_in(sender, app_data):
    # print("(in)Sender: ", sender)
    # print("(in)App Data: ", app_data)
    sdir = Path(app_data['file_path_name'])
    dpg.set_value(id_txt, sdir)
    config.input_dir = sdir
    config.common_dir = Path(common_in_folder)

    #     read json base_dir/fixture-config.txt
    cfgfile = sdir / "fixture_config.txt"
    with open(cfgfile, 'r') as myfile:
        data = myfile.read()
    print(data)
    obj = json.loads(json_minify(data))

    # print("DIR: ", obj['DIRECTION'], "CLINE: ", obj['CLINE'], " DELTA:", obj['CLINE_DELTA'])

    # ******* REQUIRED ELEMENTS ********
    if not 'MODEL' in obj:
        # FAIL! required element
        print("FAIL!")
    else:
        dpg.set_value(model_txt, obj['MODEL'])
    config.model = obj['MODEL']

    dpg.set_value(cl_txt, obj['CLINE'])
    config.Cline = float(obj['CLINE'])

    dpg.set_value(cld_txt, obj['CLINE_DELTA'])
    config.ClineDelta = float(obj['CLINE_DELTA'])

    dpg.set_value(dir_txt, obj['DIRECTION'])
    config.Direction = obj['DIRECTION']
    # print("dir: ", config.Direction)

    if 'PARAMETERS' in obj:
        # print("HasStartAndEnd!" + obj['FILE-BASED'])
        parse_parameters(obj)
        config.FileBased = False
    else:
        config.FileBased = True

    if 'HasStartAndEnd' in obj:
        # print("HasStartAndEnd!" + obj['HasStartAndEnd'])
        config.HasStartAndEnd = (obj['HasStartAndEnd'] == "True")
    else:
        config.HasStartAndEnd = True

    if 'LEFTY' in obj:
        # print("lefty!")
        config.Lefty = (obj['LEFTY'] == "True")
    else:
        config.Lefty = False

    if 'NUMUNITS' in obj:
        # print("NUMUNITS")
        config.NumUnits = obj['NUMUNITS']
    else:
        config.NumUnits = 1

    if 'MAXUNITS' in obj:
        # print("MAXUNITS")
        config.MaxUnits = int(obj['MAXUNITS'])
    else:
        config.MaxUnits = 1

    if 'FRONT-STEP' in obj:
        # print("FRONT-STEP")
        config.FrontStep = "%02s-" % str(obj['FRONT-STEP'])
    else:
        config.FrontStep = "07-"
    print("FRONT-STEP: ==" + config.FrontStep + "==")

    if 'BACK-STEP' in obj:
        # print("BACK-STEP")
        config.BackStep = "%02s-" % str(obj['BACK-STEP'])
    else:
        config.BackStep = "09-"
    print("Back-STEP: ==" + config.BackStep + "==")

    debug_output_file_prefix = False
    if 'OUTPUT-FILE-NAMES' in obj:
        print(obj['OUTPUT-FILE-NAMES']) #SMB
        config.NumSteps = len(obj['OUTPUT-FILE-NAMES'])
        for i in range(0, config.NumSteps):
            config.output_file_names.append(obj['OUTPUT-FILE-NAMES'][i])
            stepnumsearch = re.match("^([A-Z])?([0-9][0-9]-)(.*)", obj['OUTPUT-FILE-NAMES'][i])
            if stepnumsearch:
                if (stepnumsearch[1]):
                    prefix = str(stepnumsearch[1])+stepnumsearch[2]
                else:
                    prefix = str(stepnumsearch[2])
                config.output_file_prefix.append(prefix)
            else:
                stepnumsearch = re.match("^([0-9][0-9]-)(.*)", obj['OUTPUT-FILE-NAMES'][i])
                if stepnumsearch:
                    prefix = stepnumsearch[1]
                else:
                    prefix = "b%02d" % i
                config.output_file_prefix.append(prefix)
    else:
        config.output_file_names = []
        config.output_file_prefix = []

    if debug_output_file_prefix:
        for i in range(0, config.NumSteps):
            print("ofp[", str(i), "] ==> ", config.output_file_prefix[i])

    btnitems = []
    for i in range(0, int(config.MaxUnits)):
        btnitems.append(i + 1)
    numunits_feature.set_radiobtn(btnitems)

    capture_files(sdir)
    if config.common_dir and str(config.common_dir) != "None":
        capture_files(config.common_dir)

    # if enabled, output lists of all discovered tools, features, files and block(directories)
    if True:
        print("TOOLS:")
        for t in sorted(tools, key=lambda x: x.tnum):
            print(t)

        print("FEATURES:")
        for fnum in range(len(CAMFeatures)):
            print(CAMFeatures[fnum])

        print("FILES:")
        for fnum in range(len(CAMFiles)):
            print(CAMFiles[fnum])

        print("BLOCKS:")
        for fb in range(len(FeatureBlocks)):
            print(FeatureBlocks[fb])

    build_checkboxes()

    # update the UI to reflect the preferred defaults
    dpg.set_value(lefty_feature.get_button(), config.Lefty)
    dpg.set_value(numunits_feature.get_button(), config.NumUnits)

    # since changing input directories is broken... disable the button so that user can't hit a second time
    dpg.configure_item(dpgInBtn, enabled=False, )



#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\ADHD\CAM\ADHD"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\ADHDFlat"

#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\T"
#base_folder =    r"g:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\S"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\JM"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\PB"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\LP"

#base_folder =    r'g:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\neck'
#base_folder =    r'g:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\bass-neck'
#base_folder =    r'G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\ThroughNeck'
#base_folder =    r'g:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\tiltback-necks'

base_folder =    r"g:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\Fingerboards"

#base_folder =    r"g:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\Test"

#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Soulfire\CAM\SF1"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Black 35 guitars\CAM\Body"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Songhurst\CAM\lap"

#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Inglewood\CAM\Fixture"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Inglewood\CAM\Body"

#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Kala\CAM\kala"

#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Moser\CAM\Moser"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Moser\CAM\Stick"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Moser\CAM\Stick-fixture"

#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\CIARI\CAM\Mid-cost-CAM-2022-05"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\CIARI\CAM\RevJ"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\CIARI\CAM\Neck"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\CIARI\CAM\Neck-fixture"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\CIARI\CAM\fingerboard"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\CIARI\CAM\Fingerboard-fixture"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\CIARI\CAM\Headstock-fixture"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\CIARI\CAM\Headstock"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\CIARI\CAM\RevJFixture"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\CIARI\CAM\Mid-Cost-2022-06-fix"

#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Pinter\Pinter"

#base_folder =    r"g:\Shared drives\AlloyProjectFiles\Customer CAD files\Belltone\CAM\Belltone-carve"
#base_folder =    r"g:\Shared drives\AlloyProjectFiles\Customer CAD files\Belltone\CAM\Belltone"

#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\BA Ferguson\CAM\body"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\KXB\CAM\body"

#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Wolnick\CAM\body"

#base_folder =    r"g:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\Fixtures\Fingerboard-fix"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\Fixtures\BAFurguson-fix"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\Fixtures\t-fix"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Kala\CAM\kala-fix"
#base_folder =    r'G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\Fixtures\neck-fix'
#base_folder =    r"g:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\Fixtures\s-fix"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\Fixtures\JM-fix"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\Fixtures\PB-fixture"

#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Claflin\Cubcasterbody\cubcaster"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\Fretboard-Pinter"
#base_folder =    r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Belltone\CAM\belltoneneck"


in_folder = base_folder + "-in"
out_folder = base_folder + "-out"

common_in_folder = "None"
#common_in_folder = r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\CommonCAM"

# if the out folders do not exist, create it
if not(os.path.exists(out_folder) and os.path.isdir(out_folder)):
    os.mkdir(out_folder)

dpg.create_context()

dpgBaseWin = dpg.window(label="Controls", width=2500, height=380, no_collapse=True)

dpg.add_file_dialog(directory_selector=True,
                    show=False,
                    callback=callback_in,
                    tag="file_in_dialog_id",
                    default_path=in_folder,
                    height=500,
                    width=1000)
dpg.add_file_dialog(directory_selector=True,
                    show=False,
                    callback=callback_out,
                    tag="file_out_dialog_id",
                    default_path=out_folder,
                    height=500,
                    width=1000)

with dpgBaseWin:
    with dpg.group(horizontal=True):
        dpgInBtn = dpg.add_button(label="Select Input Base Directory",
                                  callback=lambda: dpg.show_item("file_in_dialog_id"))
        id_txt = dpg.add_text("--")

    with dpg.group(horizontal=True):
        model_txt = dpg.add_text("UNKNOWN")

    with dpg.group(horizontal=True):
        dpgOutBtn = dpg.add_button(label="Select Output Base Directory",
                                   callback=lambda: dpg.show_item("file_out_dialog_id"))
        od_txt = dpg.add_text("--")

    with dpg.group(horizontal=True):
        clh_txt = dpg.add_text('DIR, CLINE, CLINEDELTA: ')
        dir_txt = dpg.add_text("--")
        cl_txt = dpg.add_text("--")
        cld_txt = dpg.add_text("--")
        error_txt = dpg.add_text("", color=[255, 0, 0, 255])

    with dpg.group(horizontal=True):
        note_txt = dpg.add_input_text(label="Notes: ", show=True, enabled=True, multiline=True)

    dpgGenBtn = dpg.add_button(label="Generate GCODE!", callback=generate, enabled=False)

    dpgCheckAllBtn = dpg.add_button(label="Check All Options", callback=check_all, enabled=False)

dpg.create_viewport(title='Alloy CAM Combiner', width=2500, height=2000)
dpg.set_global_font_scale(1.5)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()

if False:

    # *************************** 01 LAM-PREP ************************************
    for x in config.base_files:
        if re.search("^01-", x.name):
            # print("01: ", x.name)
            file_list[1].append(x)

    for f in CAMFiles:
        if not f.get_selected():
            continue
        if f.get_base():
            continue
        if re.search("^01-", f.name):
            # print("01(features): ", f.name)
            file_list[1].append(f)

    # *************************** 02 BACK-PREP ************************************
    for x in config.base_files:
        if re.search("^02-", x.name):
            # print("02: ", x.name)
            file_list[2].append(x)

    for f in CAMFiles:
        if not f.get_selected():
            continue
        if f.get_base():
            continue
        if re.search("^02-", f.name):
            # print("02(features): ", f.name)
            file_list[2].append(f)

    # *************************** 03 FRONT-PREP ************************************
    # never output. Unused

    # *************************** 04 BLANK-PREP-LAM ************************************
    for x in config.base_files:
        if re.search("^04-", x.name):
            # print("04:", x.name)
            file_list[4].append(x)
            continue

    # now scan through all files. If a file is selected (by the user in the UI choosing the associated feature)
    # check to see if the file is named "^04-". If so, include it in the 04 output
    for f in CAMFiles:
        if not f.get_selected():
            continue
        if f.get_base():
            continue
        if re.search("^04-", f.name):
            # print("04(features): ", f.name)
            file_list[4].append(f)

    # *************************** 05 FRONT-FACE ************************************
    # Output in cases where back i carved first (e.g., LP-style). This allows for facing the
    # lam/carve top before flipping to carve the back
    for x in config.base_files:
        if re.search("^05-", x.name):
            # print("02: ", x.name)
            file_list[5].append(x)

    for f in CAMFiles:
        if not f.get_selected():
            continue
        if f.get_base():
            continue
        if re.search("^05-", f.name):
            # print("08(features): ", f.name)
            file_list[5].append(f)

    # *************************** 06 BINDING-PREP ************************************
    for f in CAMFiles:
        if not f.get_selected():
            continue
        if f.get_base():
            continue
        if re.search("^06-", f.name):
            # print("06(features): ", f.name)
            file_list[6].append(f)

    # *************************** 07 FRONT/BACK ************************************
    # "-first" files
    for f in CAMFiles:
        if not f.get_selected():
            continue
        if f.get_base():
            continue
        if re.search("^07-", f.name) and re.search("-first", f.name):
            # print("07(features): ", f.name)
            file_list[7].append(f)

    # "-start" files
    for bf in config.base_files:
        if re.search("^07-", bf.name):
            if config.HasStartAndEnd is False:
                file_list[7].append(bf)
            elif re.search("-start", bf.name):
                # print("07(start): ", bf.name)
                file_list[7].append(bf)

    # features
    for f in CAMFiles:
        if not f.get_selected():
            continue
        if f.get_base():
            continue
        if re.search("^07-", f.name) and not re.search("-end", f.name) and not re.search("-first", f.name):
            # print("07(features): ", f.name)
            file_list[7].append(f)
            continue
        if re.search("^[0-9][0-9]", f.name):
            continue

        if not re.search("-end", f.name) and not re.search("-first", f.name):
            # "unlabeled" file. put it here as the default place for such files
            file_list[7].append(f)
            continue

        print("ERROR: unclaimed file: " + f.name)

    # "-end" files
    for bf in config.base_files:
        if re.search("^07-", bf.name) and re.search("-end", bf.name):
            # print("07(end): ", bf.name)
            file_list[7].append(bf)

    # "-end" files from features
    for f in CAMFiles:
        if not f.get_selected():
            continue
        if f.get_base():
            continue
        if re.search("^07-", f.name) and re.search("-end", f.name):
            # print("07(features-end): ", f.name)
            file_list[7].append(f)

    # *************************** 08 Binding Prep ************************************
    for f in CAMFiles:
        if not f.get_selected():
            continue
        if f.get_base():
            continue
        if re.search("^08-", f.name):
            # print("08(features): ", f.name)
            file_list[8].append(f)

    # *************************** 09 BACK/FRONT ************************************
    # "-first" operations from features
    for f in CAMFiles:
        if not f.get_selected():
            continue
        if f.get_base():
            continue
        if re.search("^09-", f.name) and re.search("-first", f.name):
            # print("09(features): ", f.name)
            file_list[9].append(f)

    # "-start" CAM operations
    for bf in config.base_files:
        if re.search("^09-", bf.name):
            if config.HasStartAndEnd is False:
                file_list[9].append(bf)
            elif re.search("-start", bf.name):
                # print("09(start): ", bf.name)
                file_list[9].append(bf)

    # features
    for f in CAMFiles:
        if not f.get_selected():
            continue
        if f.get_base():
            continue
        if re.search("^09-", f.name) and not re.search("-end", f.name) and not re.search("-first", f.name):
            # print("09(features): ", f.name)
            file_list[9].append(f)

    # "end" cam operations
    if config.HasStartAndEnd is True:
        for bf in config.base_files:
            if re.search("^09-", bf.name):
                if re.search("-end", bf.name):
                    # print("09(end): ", bf.name)
                    file_list[9].append(bf)

    for f in CAMFiles:
        if not f.get_selected():
            continue
        if f.get_base():
            continue
        if re.search("^09-", f.name) and re.search("-end", f.name):
            # print("09(features-end): ", f.name)
            file_list[9].append(f)

    # *************************** 10 FINAL ************************************
    for bf in config.base_files:
        if re.search("^10-", bf.name):
            # print("10: ", bf.name)
            file_list[10].append(bf)

    for f in CAMFiles:
        if not f.get_selected():
            continue
        if f.get_base():
            continue
        if re.search("^10-", f.name):
            # print("10(features): ", f.name)
            file_list[10].append(f)

    def _duplicate_and_displace_file(self, delta, numunits, direction, suppress_end_code):
        self._out_lines = []

        # print("dup/displace dir:", str(direction), str(config.Direction))

        # print("dup and disp: ", delta, numunits, direction)
        if numunits == 0:
            self._out_lines = []
            # print("numunits == 0; clearing output lines")
            return

        # if we are mirroring, use the mirrored lines for input to the duplicate/displace
        if not len(self._mirror_lines):
            # print("using input lines")
            inlist = self._lines.copy()
        else:
            # print("using mirror lines")
            inlist = self._mirror_lines.copy()

        # our output is minimally one unit = not displaced. If there is a mirror version, use it

        if numunits == 1:
            # we are done
            self._out_lines = inlist.copy()
            return

        for line in inlist:
            newline = []
            for i in range(0, numunits):
                newline.append("")

            if line == "HOME\n":
                # do nothing to this homing action except for the last instance
                # unless suppress is True
                # print("home: ", line)
                for i in range(0, numunits - 1):
                    newline[i] = ""
                if suppress_end_code == False:
                    newline[numunits - 1] = line
                else:
                    newline[numunits - 1] = ""
            else:
                if direction == "HORIZONTAL":
                    match = re.search(r"(.*)X(-*[0-9]+[.]*[0-9]*)(.*\n*)", line)
                else:
                    match = re.search(r"(.*)Y(-*[0-9]+[.]*[0-9]*)(.*\n*)", line)

                if match is None:
                    for i in range(0, numunits):
                        newline[i] = line
                    # print(line)

                else:
                    # print(line, " ==> ", match, "++++", match[1], "x", match[2], match[3], delta)
                    old_val = float(match[2])
                    new_val = old_val
                    for i in range(0, numunits):
                        if direction == "HORIZONTAL":
                            newline[i] = f"{match[1]}X{new_val:.4f}{match[3]}"
                        else:
                            newline[i] = f"{match[1]}Y{new_val:.4f}{match[3]}"
                        new_val = round(new_val + delta, 4)

            for i in range(0, numunits):
                if newline[i] != "":
                    self._ret_list[i].append(newline[i])
                    # print(i + ": " + newline)

        # now for each potential position append the lines to the output array
        for i in range(0, numunits):
            for line in self._ret_list[i]:
                self._out_lines.append(line)
