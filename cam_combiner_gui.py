import errno

from cam_core.version import GUI_BANNER, APP_BANNER, VERSION
from cam_core.jsonc_loader import load_config_file, normalize_legacy
from cam_core.planner import plan, scan_files
from cam_core.writer import write_output_file
from cam_core.session import save_session, load_session
from cam_core.debug import debug_dump_all, debug_print
from cam_core.cam_file import CAMFile
from cam_core.CAMFeature import CAMFeature
from cam_core.Tool import Tool
from cam_core.FeatureBlock import FeatureBlock

import dearpygui.dearpygui as dpg  # type: ignore
import os, re, shutil

print(GUI_BANNER)
print("="*40)
print(APP_BANNER)
print("="*40)

dpg.create_context()
dpg.create_viewport(title=f"CAM Combiner {VERSION}", width=2500, height=1250)

state = {
    "base": os.getcwd(),
    "output_base": None,
    "cfg_path": None,
    "cfg": None,                # static config file
    "params": {},               # dynamic value of config paramaters
    "param_values": {},         # dynamic value of string to use in gui for choices
    "shared_dir": None,
    "json_name": "",            # stem of the session JSON file (no extension)
}

param_based_color = (255, 0, 0, 255)  # red
feature_based_color = (0, 255, 0, 255)  # green
enabled_feature_color = (25, 255, 0, 255)  # green
root_non_param_color = (0, 0, 255, 255)  # blue
feat_color = (255, 255, 255, 255) # white
enabled_tool_color =  (255, 255, 0, 255) #
unmatched_color = (120, 120, 120, 255)  # gray: shades out root files with no Rule Match
mismatch_highlight_color = (255, 140, 0, 255)  # orange: the part of the name that diverged

CAMFiles: list[CAMFile] = []           # CAMFile objects
CAMFeatures: list[CAMFeature] = []      # CAMFeature objects
FeatureBlocks: list[FeatureBlock] = []     # FeatureBlock objects
CAMTools: list[Tool] = []

def _on_param_change(sender, app_data, user_data):
    """Combo callback: keep state['params'] in sync with GUI."""
    name = user_data
    state["params"][name] = app_data

    run_plan()
    _refresh_ui(False)


def _toggle_feature(cid: str, value: bool, feature: CAMFeature):
    if value:
        feature.set_enabled()
    else:
        feature.clear_enabled()

    run_plan()
    _refresh_ui(False)


def _is_file_enabled(file_target: CAMFile)->bool:

    if not "by_step" in state:
        return False

    if not "resolved" in state:
        return False

    for out in state["resolved"]:
        step = str(out.get("step", ""))
        step_files = state["by_step"].get(step, [])
        for s in step_files:
            #print("checking for "+file_target.name +" against: "+s.name)
            if s.name == file_target.name:
                #print("match!")
                return True

    return False


def _add_unmatched_name_text(name: str, spans):
    """Render name gray with only the given (start,end) char spans in orange."""
    if not spans:
        dpg.add_text(name, color=unmatched_color)
        return
    with dpg.group(horizontal=True, horizontal_spacing=0):
        pos = 0
        for start, end in sorted(spans):
            if start > pos:
                dpg.add_text(name[pos:start], color=unmatched_color)
            dpg.add_text(name[start:end], color=mismatch_highlight_color)
            pos = end
        if pos < len(name):
            dpg.add_text(name[pos:], color=unmatched_color)


def _refresh_ui(recreate_params: bool):
    global CAMFiles, CAMFeatures, FeatureBlocks, CAMTools
    global feat_color, enabled_feature_color, root_non_param_color, param_based_color
    verbose = False

    # clear all previously created dynamic elements
    if recreate_params and dpg.does_item_exist("Parameters"):
        # delete all children
        for child in list(dpg.get_item_children("Parameters", 1) or []):
            dpg.delete_item(child)
    if recreate_params and dpg.does_item_exist("features_box"):
        # delete all children
        for child in list(dpg.get_item_children("features_box", 1) or []):
            dpg.delete_item(child)
    if dpg.does_item_exist("Options"):
        # delete all children
        for child in list(dpg.get_item_children("Options", 1) or []):
            dpg.delete_item(child)
    if dpg.does_item_exist("model_params"):
        # delete all children
        for child in list(dpg.get_item_children("model_params", 1) or []):
            dpg.delete_item(child)
    if dpg.does_item_exist("files"):
        # delete all children
        for child in list(dpg.get_item_children("files", 1) or []):
            dpg.delete_item(child)
    if dpg.does_item_exist("tools"):
        # delete all children
        for child in list(dpg.get_item_children("tools", 1) or []):
            dpg.delete_item(child)

    # Only recreate the Parameters and Features sections on request (they are "stateful")
    if recreate_params:
        with dpg.group(horizontal=False, parent="Parameters"):
            for p in state["params"]:
                if p == "zip_subdirs":
                    continue  # rendered alongside unit_1_only below
                with dpg.group(horizontal=True, parent="Parameters"):
                     # Label + combo per parameter
                    if state["param_values"][p] == "":
                        dpg.add_checkbox(label=p,
                                         default_value=bool(state["params"].get(p, False)),
                                         callback=_on_param_change,
                                         user_data=p)
                    else:
                        dpg.add_text(p, color=param_based_color)
                        dpg.add_combo(
                            tag=f"param_{p}",
                            items=state["param_values"][p],
                            default_value=state["params"][p],
                            width=200,
                            callback=_on_param_change,
                            user_data=p
                        )

                    if p == "unit_1_only" and "zip_subdirs" in state["params"]:
                        dpg.add_checkbox(label="Zip Subdirs",
                                         default_value=bool(state["params"].get("zip_subdirs", False)),
                                         callback=_on_param_change,
                                         user_data="zip_subdirs")

        with dpg.group(parent="features_box"):
            for fb in FeatureBlocks:
                if fb.get_CAM_features() == []:
                    continue

                dpg.add_separator(label=fb.get_name())

                for f in fb.get_CAM_features():
                    if verbose:
                        debug_print("trying to build button for feature:", f.name)

                    cid = dpg.add_checkbox(label=f.name,
                                           default_value=False, # default OFF
                                           callback=_toggle_feature,
                                           user_data=f)
                    f.set_radiobtn(cid)

    # Mirror a readable dump of params in the Options text box (handy for copy/paste)
    with dpg.group(parent="Options"):
        dpg.add_text("Chosen Parameters:\n")
        for k, v in sorted(state["params"].items()):
            line = f"{k:20s} = {v}"
            dpg.add_text(line)

    # update_model_params:
    with dpg.group(parent="model_params"):
        dpg.add_text("Model And Fixture Parameters:")
        dpg.add_text("   Model       = " + str(state["cfg"]["MODEL"]))
        dpg.add_text("   Center Line = " + str(state["cfg"]["CLINE"]))
        dpg.add_text("   CL-to-CL    = " + str(state["cfg"]["CLINE_DELTA"]))
        dpg.add_text("   Max Units   = " + str(state["cfg"]["MAXUNITS"]))
        dpg.add_text("   Direction   = " + str(state["cfg"]["DIRECTION"]))

    with (dpg.group(parent="tools")):
        # Only available if scrollX/scrollY are disabled and stretch columns are not used
        with dpg.table(header_row=True,
                       policy=dpg.mvTable_SizingStretchProp,
                       resizable=True,
                       no_host_extendX=True,
                       borders_innerV=True,
                       borders_outerV=True,
                       borders_outerH=True):

            dpg.add_table_column(label="Num", width=30)
            dpg.add_table_column(label="Desc", width=150)
            dpg.add_table_column(label="Files", width=250)

            for t in sorted(CAMTools, key=lambda x: int(x.tnum) if x is not None else 0):
                tnum = t.get_tool_num()
                tdesc = t.get_desc()
                tfiles = ""
                with dpg.table_row():
                    dpg.add_text(str(tnum))
                    dpg.add_text(tdesc, wrap=150)
                    with dpg.group():
                        for f in t.get_files():
                            if _is_file_enabled(f):
                                #print("got one!"+f.name)
                                dpg.add_text(f.name, color=enabled_tool_color)
                            else:
                                dpg.add_text(f.name)



    with (dpg.group(parent="files")):
        # Only available if scrollX/scrollY are disabled and stretch columns are not used
        with dpg.table(header_row=True,
                       policy=dpg.mvTable_SizingStretchProp,
                       resizable=True,
                       no_host_extendX=True,
                       borders_innerV=True,
                       borders_outerV=True,
                       borders_outerH=True):

            dpg.add_table_column(label="File Name")
            dpg.add_table_column(label="Tool")
            dpg.add_table_column(label="Step")
            dpg.add_table_column(label="Rule Match")


            txt_color = param_based_color
            for f in CAMFiles:
                tnum = str(f.get_toolnum())
                step = str(f.get_step())
                rule_match = ""
                unmatched = False
                diff_spans = []
                if f.is_root():
                    # Root directory files (project root or shared root). if params are active: param color else root color
                    if "INPUT-FILE-NAME-BASES" in state["cfg"]:
                        # param based
                        rule_match = f.get_matching_search_string()
                        if rule_match:
                            txt_color = param_based_color
                        else:
                            # No base pattern matched this file: shade it out and
                            # highlight only the token(s) that diverge from the
                            # closest candidate pattern, so it's easy to spot why.
                            unmatched = True
                            txt_color = unmatched_color
                            diff_spans = f.get_match_diff_spans()
                    else:
                        txt_color = root_non_param_color

                else:
                    txt_color = feature_based_color

                with dpg.table_row():
                    if unmatched:
                        _add_unmatched_name_text(f.name, diff_spans)
                    else:
                        dpg.add_text(f.name, color=txt_color)
                    if unmatched:
                        dpg.add_text(tnum, color=unmatched_color)
                        dpg.add_text(step, color=unmatched_color)
                    else:
                        dpg.add_text(tnum)
                        dpg.add_text(step)
                    dpg.add_text(rule_match)
                    #print("RM: "+f.name+" "+rule_match+"<====>"+f.get_matching_search_string())


def _get_enabled_features() -> list[CAMFeatures]:
    global CAMFiles, CAMFeatures, FeatureBlocks, CAMTools
    outlist: list[CAMFeature] = []
    for f in CAMFeatures:
        if f.get_enabled():
            outlist.append(f)

    return outlist


def run_plan(sender=None, app_data=None, user_data=None):
    global CAMFiles, CAMFeatures, FeatureBlocks, CAMTools

    verbose=False

    if not state["cfg"] or not state["base"]:
        debug_print("[warn] Choose a base directory and config file first.")
        return
    cfg = state["cfg"]

    # Verbose dump (unchanged)
    if (verbose):
        debug_print(debug_dump_all(state["base"], state["params"], CAMFiles, CAMFeatures, FeatureBlocks))

    enabled_features = _get_enabled_features()
    if (verbose):
        for f in enabled_features:
            debug_print(f.name())

    resolved, by_step = plan(cfg,
                             state["params"],
                             CAMFiles,
                             state["base"],
                             FeatureBlocks,
                             enabled_features,
                             verbose=False)


    # List the planned file outputs to the "Outputs" window
    dpg.delete_item("Outputs_table", children_only=True, slot=1)
    parts = ""
    for out in resolved:
        step = str(out.get("step", ""))
        name = out.get("name", "")
        step_files = by_step.get(step, [])
        files_str = "\n".join(f.name for f in step_files)
        files_height = max(26, len(step_files) * 19 + 6)
        with dpg.table_row(parent="Outputs_table"):
            dpg.add_text(f"{step:02}")
            dpg.add_input_text(default_value=name, readonly=True, width=-1)
            dpg.add_input_text(default_value=files_str, readonly=True, multiline=True,
                               width=-1, height=files_height)
        parts += f"{step:02}   {name:35s}{files_str}\n"
    debug_print(parts)

    state["resolved"] = resolved
    state["by_step"] = by_step


def generate_output(sender=None, app_data=None, user_data=None):
    global CAMFiles, CAMFeatures, FeatureBlocks, CAMTools

    debug_print("=================================================")
    debug_print("=================================================")
    debug_print("=================================================")
    outputs = state["resolved"]
    by_step = state["by_step"]
    cfg = state["cfg"]

    #debug_print(outputs)
    #debug_print(by_step)

    model = state["cfg"]["MODEL"]
    cline = state["cfg"]["CLINE"]
    cline_delta = float(state["cfg"]["CLINE_DELTA"])
    max_units = state["cfg"]["MAXUNITS"]
    direction = state["cfg"]["DIRECTION"]
    lefty = state["params"]["Lefty"]

    #debug_print(model+str(cline)+str(cline_delta)+str(max_units)+direction+str(lefty))

    # for each file, ask the CAMFile object to produce the code for all individual units.
    for f in CAMFiles:
        f.create_unit_code(max_units, cline_delta, direction)

    write_output_files()

    json_name = dpg.get_value("json_name_val").strip()
    state["json_name"] = json_name
    model_name = str(state["cfg"].get("MODEL", ""))
    output_basename = os.path.basename(state.get("output_base", ""))
    if json_name and json_name != model_name and state.get("output_base") and output_basename != json_name:
        _copy_root_outputs_to_subdir(json_name)

    _save_session_named(json_name)




def _zip_and_remove_unit_subdirs(base_output_dir, units_to_produce):
    """Zip each per-unit/1toN output subdir into <name>.zip, then remove it."""
    names = [str(u) for u in range(1, units_to_produce + 1)]
    names += ["1to" + str(n) for n in range(2, units_to_produce + 1)]

    for name in names:
        subdir = os.path.join(base_output_dir, name)
        if not os.path.isdir(subdir):
            continue
        zip_base = os.path.join(base_output_dir, name)
        if os.path.exists(zip_base + ".zip"):
            os.remove(zip_base + ".zip")
        shutil.make_archive(zip_base, "zip", subdir)
        shutil.rmtree(subdir)


def write_output_files():
    global CAMFiles, CAMFeatures, FeatureBlocks, CAMTools
    debug_wof = False

    outputs = state["resolved"]
    by_step = state["by_step"]

    model = state["cfg"]["MODEL"]
    cline = state["cfg"]["CLINE"]
    cline_delta = float(state["cfg"]["CLINE_DELTA"])
    max_units = state["cfg"]["MAXUNITS"]
    if state["params"]["unit_1_only"]:
        units_to_produce = 1
    else:
        units_to_produce = max_units
    direction = state["cfg"]["DIRECTION"]
    lefty = state["params"]["Lefty"]
    base_input_dir = state["base"]
    base_output_dir = state["output_base"]
    num_steps = state["cfg"]["NUM-STEPS"]
    output_file_names = state["cfg"]["OUTPUT-FILE-NAMES"]

    # create output directories
    if debug_wof:
        debug_print("*************** creating output directories")
    for unitnum in range(1, units_to_produce + 1):
        # create output directories
        if debug_wof:
            debug_print("making " + base_output_dir + "/" + str(unitnum))
        try:
            os.makedirs(base_output_dir + "/" + str(unitnum) + "/IndFiles", True)
        except OSError as error:
            if error.errno != errno.EEXIST:
                debug_print("FATAL ERROR: can't create directory: ", base_output_dir + "/" + str(unitnum) + " ERROR: " + str(error) )
                dpg.destroy_context()

    for unitnum in range(2, units_to_produce + 1):
        # create output directories
        try:
            os.makedirs(base_output_dir + "/1to" + str(unitnum) + "/IndFiles", True)
        except OSError as error:
            if error.errno != errno.EEXIST:
                debug_print("FATAL ERROR: can't create directory: ", base_output_dir + "/1to" + str(unitnum) + "/IndFiles ==> ERROR: " + str(error) )
                dpg.destroy_context()

    # *************************************************************************************************
    if debug_wof:
        print("********** Dumping summary.txt file")
    # dump out a list of input files, etc. and the output mapping
    output_file = open(base_output_dir + "/" + "summary.txt", "w")
    output_file.write("Model:" + str(model) + "\n")
    output_file.write("\nLefty:" + str(lefty) + "\nNunits:" + str(units_to_produce) + "\n")
    output_file.write(
        "\nCline: " + str(cline) + "\nClineDelta:" + str(cline_delta) + " \nDirection:" + str(
            direction) + "\n")
    output_file.write("\nInput Dir:" + str(base_input_dir) + "\nOutput Dir:" + str(base_output_dir) + "\n")

    output_file.write("**************************************************************\n")
    output_file.write("**********OutputFileNames*************************************\n")

    for stepnum in range(0, num_steps):
        output_file.write(output_file_names[stepnum] + "\n")
        stepstr = str(stepnum).zfill(2)
        if stepstr in by_step:
            for f in by_step[stepstr]:
                output_file.write("\t" + f.name + "\tT" + str(f.get_toolnum()) + "\n")

    output_file.write("**************************************************************\n\n")


    if (0):
        output_file.write("**************************************************************\n")
        output_file.write("**********OutputFileContents**********************************\n")
        for stepnum in range(0, config.NumSteps):
            output_file.write(config.output_file_names[stepnum] + ":\n")
            for j in file_list[i]:
                output_file.write("\t" + j.name + "\tT" + str(j.get_toolnum()) + "\n")

        output_file.write("**************************************************************\n\n")

        output_file.write("**************************************************************\n")
        output_file.write("**********CAMFiles********************************************\n")
        for f in CAMFiles:
            config.input_dir = str(f.get_dir())
            output_file.write("CAM file: " + config.input_dir + "\\" + f.name())
            output_file.write("\n")

        output_file.write("**************************************************************\n\n")

    if (0):
        output_file.write("**************************************************************\n")
        output_file.write("**********CAMFiles: stats**************************************\n")
        output_file.write("XMin\tXMax\tYMin\tYMax\tZMin\tZMax")
        output_file.write("\tTNUM")
        output_file.write("\tSMin\tSMax")
        output_file.write("\tFileName\n")

        for f in CAMFiles:
            output_file.write(str(f.min_x))
            output_file.write("\t" + str(f.max_x))
            output_file.write("\t" + str(f.min_y))
            output_file.write("\t" + str(f.max_y))
            output_file.write("\t" + str(fmin_z))
            output_file.write("\t" + str(f.max_z))
            output_file.write("\t" + str(f.get_toolnum()))
            output_file.write("\t" + str(f.min_s))
            output_file.write("\t" + str(f.max_s))
            output_file.write("\t" + str(f))
            output_file.write("\n")

        output_file.write("**************************************************************\n\n")


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
    tools_filename = base_output_dir + f"/tools.txt"
    tfile = open(tools_filename, "w")
    tfile.write("Model:" + str(model) + "\n")
    tfile.write("\nLefty:" + str(lefty) + "\nNunits:" + str(units_to_produce) + "\n")

    tfile.write(
        "\nCline: " + str(cline) + "\nClineDelta:" + str(cline_delta) + " \nDirection:" + str(
            direction) + "\n")
    tfile.write("\nInput Dir:" + str(base_input_dir) + "\nOutput Dir:" + str(base_output_dir) + "\n")

    tfile.close()
    tfile = open(tools_filename, "a")

    for t in sorted(CAMTools, key=lambda x: int(x.tnum) if x is not None else 0):
        mytoolnum = t.get_tool_num()
        mydesc = t.get_desc()

        # Determine if the file in question is actually used in this run, as determined by the user-chosen options.
        # If not, then note the potential error as a warning
        for f in t.get_files():
            myfilename = f.name

            if False and debug_wof:
                debug_print("********** Tool check: ", mytoolnum, myfilename, mydesc)

            myfile = None
            # get the CAMFile object for this file name
            for cfile in CAMFiles:
                if False and debug_wof:
                    debug_print("checking: ", cfile.get_name(), myfilename)
                if (cfile.get_name() == myfilename):
                    myfile = cfile
                    break

            if myfile == None:
                # huh? didn't find the CAM file for this. WTF?
                debug_print("WTF. can't find my own CAM File structure! Aborting." + myfilename)
                debug_print(CAMFiles)
                dpg.destroy_context()

        for t2 in sorted(CAMTools, key=lambda x: int(x.tnum)):

            if (t2.get_tool_num() == mytoolnum):
                # OK, this is our toolnumber before! (or this is the same tool... but no matter)
                if t2.get_desc() != mydesc:
                    # debug_print("error! inside ", mytoolnum, mydesc, myfilename)
                    # this is the problem case: mark it as such
                    t2file = None
                    # get the CAMFile object for this file name
                    for f2 in CAMFiles:
                        if f2 in t2.get_files():
                            t2file = f2
                            break

                    if t2file == None:
                        # huh? didn't find the CAM file for this. WTF?
                        debug_print("WTF. can't find T2 CAM File structure! Aborting.")
                        dpg.destroy_context()

                    if _is_file_enabled(t2file):
                        have_error = True
                        t.set_error("conflict")
                        t2.set_error("conflict")
                    else:
                        have_warning = True
                        t.set_warning("conflict")
                        t2.set_warning("conflict")

    if 0:
        if have_warning:
            # put some error text out the GUI to let the user know
            dpg.set_value(error_txt, "WARNING: conflicting tool numbers. See tools.txt in the output directory.")
        if have_error:
            # put some error text out the GUI to let the user know
            dpg.set_value(error_txt, "ERROR: conflicting tool numbers. See tools.txt in the output directory.")

    # Build one entry per unique (tnum, desc) pair across all CAM files
    tool_entries = {}
    for cfile in CAMFiles:
        t = cfile.get_tool()
        if t is None:
            continue
        key = (t.get_tool_num(), t.get_desc())
        tool_entries.setdefault(key, []).append(cfile)

    tnum_descs = {}
    for (tnum, desc) in tool_entries:
        tnum_descs.setdefault(tnum, set()).add(desc)

    tfile.write("Used\tConflict\tTnum\tDesc\n")
    for (tnum, desc) in sorted(tool_entries.keys()):
        is_used = any(_is_file_enabled(f) for f in tool_entries[(tnum, desc)])
        conflict = len(tnum_descs.get(tnum, set())) > 1
        tfile.write(f"{'YES' if is_used else 'no'}\t{'CONFLICT' if conflict else ''}\tT#{tnum:02d}\t{desc}\n")
    tfile.close()

    # create output files by step
    for out in outputs:
        stepnum = out["step"]
        if debug_wof:
            print("*************** write_output_files: step #", stepnum, ": ", out["name"])
        if (not stepnum in by_step) or (len(by_step[stepnum]) == 0):
            # no files for output file #i
            if debug_wof:
                debug_print("*************** No files for this step.")
            continue

        output_file = open(base_output_dir + "/" + out["name"], "w")

        output_file_ind_unit = []
        for unit in range(0, units_to_produce):
            unit_fn = base_output_dir + "/" + str(unit+1) + "/" + out["name"]
            newfile = open(unit_fn, "w")
            if debug_wof:
                print("...opening unit output file: ", unit_fn, "result: ", newfile)
            output_file_ind_unit.append(newfile)

        output_file_1toN = []
        for n in range(2, units_to_produce + 1):
            fn = base_output_dir + "/1to" + str(n) + "/" + out["name"]
            output_file_1toN.append(open(fn, "w"))

        lastf = None
        for f in by_step[stepnum]:
            lastf = f

        for f in by_step[stepnum]:
            if debug_wof:
                print("*************** write_output_files outputting " + f.name + " to " + base_output_dir + "/" + out["name"])

            current_tool_num = f.get_toolnum()
            if f == lastf:
                next_tool_num = -1
            else:
                found_me = False
                nextfile: CAMFiles = None
                for q in by_step[stepnum]:
                    if found_me:
                        nextfile = q
                        break
                    if q == f:
                        found_me = True
                if nextfile:
                    next_tool_num = nextfile.get_toolnum()
                else:
                    next_tool_num = -1

            if next_tool_num == current_tool_num:
                suppress_end_code = True
            else:
                suppress_end_code = False

            if re.search("-NODUP", f.name):
                # NODUP IMPLIES NOMIRROR
                # no duplication/displacement and no mirroring for this file
                numUnits = 1
                mirror_active = False
            else:
                numUnits = units_to_produce
                mirror_active = lefty

            if re.search("-NOMIRROR", f.name):
                mirror_active = False

            write_output_file(f,
                              f.name,
                              output_file,
                              1, numUnits,
                              mirror_active,
                              current_tool_num,
                              suppress_end_code,
                              cline, cline_delta, direction)
            if numUnits == 1:
                # output this file only in the unit 1 output
                if debug_wof:
                    print("*************** write_output_files ind units " + f.name + " to " + base_output_dir + "/1/" + out["name"])
                write_output_file(f, f.name, output_file_ind_unit[0],
                            1, 1,
                            mirror_active,
                            current_tool_num,
                            suppress_end_code,
                            cline, cline_delta, direction)
            else:
                for unit in range (0, units_to_produce):
                    # output this file for each unit
                    if debug_wof:
                        print("*************** write_output_files ind units " + f.name + " to " + base_output_dir + "/" + str(unit) + "/" + out["name"])
                    write_output_file(f,
                                      f.name,
                                      output_file_ind_unit[unit],
                                      unit+1,
                                      1,
                                      mirror_active,
                                      current_tool_num,
                                      suppress_end_code,
                                      cline, cline_delta, direction)

            for idx, n in enumerate(range(2, units_to_produce + 1)):
                n_units = 1 if numUnits == 1 else n
                write_output_file(f, f.name, output_file_1toN[idx],
                                  1, n_units,
                                  mirror_active,
                                  current_tool_num,
                                  suppress_end_code,
                                  cline, cline_delta, direction)

        step_files = by_step[stepnum]
        if len(step_files) > 1:
            first_tnum = next((f.get_toolnum() for f in step_files if f.get_toolnum() and f.get_toolnum() != 0), None)
            if first_tnum:
                tool_reload = f"T{int(first_tnum):02d}\n"
                output_file.write(tool_reload)
                for uf in output_file_ind_unit:
                    uf.write(tool_reload)
                for nf in output_file_1toN:
                    nf.write(tool_reload)

        output_file.close()
        for unit in range(0, units_to_produce):
            output_file_ind_unit[unit].close()
        for n_file in output_file_1toN:
            n_file.close()


    if debug_wof:
        print("*************** outputing individual files")
    for cfile in CAMFiles:
        # output individual files for each unit, appropriately mirrored if lefty
        fname = cfile.name
        for i in range(1, units_to_produce + 1):
            ofname = base_output_dir + "/" + str(i) + "/IndFiles/" + fname
            if re.search("-NODUP", fname):
                if i == 1:
                    if debug_wof:
                        print("     NoDUP. Outputing for unit 1 only")
                    # no duplication, displacement, do not output to the individual units except for first unit.
                    # do not suppress end codes
                    output_file = open(ofname, "w")
                    write_output_file(cfile, fname, output_file, 1, 1, False,  -1, False, cline, cline_delta, direction)
                    output_file.close()
                else:
                    if debug_wof:
                        print("     NoDUP. Not outputing for unit ", i)
            else:
                if debug_wof:
                    print("     Normal file, outputting for unit ", i, "only.")
                output_file = open(ofname, "w")
                write_output_file(cfile, fname, output_file, i, 1, lefty, -1, False, cline, cline_delta, direction)
                output_file.close()

        # this is not necessary for determining suppression of end codes (since we won't)
        # but is still necessary since it is output in comments into the file
        current_tool_num = cfile.get_toolnum()

        # do not suppress end code since files are intended to   be run independently
        suppress_end_code = False

        if debug_wof:
            print("*************** outputing composite files")
            # for each possible number of units from 1-config.numUnits, build individual files for multiple units
        for i in range(2, units_to_produce + 1):
            fname = cfile.name

            ofname = base_output_dir + "/1to" + str(i) + "/IndFiles/" + fname
            if re.search("-NODUP", fname):
                # no duplication, displacement, mirroring for this one.
                if debug_wof:
                    print("     NODUP case. This was already written above")
                continue
            if debug_wof:
                print("     Normal file, outputting for units [1:", i, "] to ", ofname)
            with open(ofname, "w") as output_file:
                write_output_file(cfile, fname, output_file, 1, i, lefty, -1, True, cline, cline_delta, direction)

    if state["params"].get("zip_subdirs"):
        _zip_and_remove_unit_subdirs(base_output_dir, units_to_produce)

    if 0:
        # create archive files (in, out)
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

    debug_print("********** Done Dumping Files! ******************")


def choose_out(sender, app_data):
    global CAMFiles, CAMFeatures, FeatureBlocks, CAMTools

    state["output_base"] = app_data["file_path_name"]
    dpg.set_value("out_val", state["output_base"])

    json_name = os.path.basename(state["output_base"])
    state["json_name"] = json_name
    if dpg.does_item_exist("json_name_val"):
        dpg.set_value("json_name_val", json_name)

    # Auto-select config in base (unchanged behavior)
    cfg_path = os.path.join(state["output_base"], "fixture_config.txt")
    set_cfg(cfg_path)
    _refresh_session_combo()


def choose_base(sender, app_data):
    global CAMFiles, CAMFeatures, FeatureBlocks, CAMTools

    state["base"] = app_data["file_path_name"]
    dpg.set_value("base_val", state["base"])

    # Auto-select output directory *-in ==> *-out
    if re.search("-in$", state["base"]):
        out_path = re.sub("-in$", "-out", state["base"])
        state["output_base"] = out_path
        dpg.set_value("out_val", state["output_base"])

    cfg_path = os.path.join(state["base"], "fixture_config.txt")
    set_cfg(cfg_path)

    # Auto-select shared GCode directory: Base/../SharedGCode
    shared_default = os.path.normpath(os.path.join(state["base"], "..", "SharedGCode"))
    if os.path.isdir(shared_default):
        state["shared_dir"] = shared_default
        dpg.set_value("shared_val", state["shared_dir"])
    else:
        state["shared_dir"] = None
        dpg.set_value("shared_val", "")

    # Scan & refresh Features
    CAMFiles, FeatureBlocks, CAMFeatures, CAMTools = scan_files(state["base"], shared_dir=state["shared_dir"])

    run_plan()
    _refresh_ui(True)
    _refresh_session_combo()


def choose_cfg(sender, app_data):
    path = app_data["file_path_name"]
    set_cfg(path)


def choose_shared(sender, app_data):
    global CAMFiles, CAMFeatures, FeatureBlocks, CAMTools

    state["shared_dir"] = app_data["file_path_name"]
    dpg.set_value("shared_val", state["shared_dir"])

    CAMFiles, FeatureBlocks, CAMFeatures, CAMTools = scan_files(state["base"], shared_dir=state["shared_dir"])
    run_plan()
    _refresh_ui(True)


def _apply_session(path: str) -> bool:
    """Load session JSON and restore all state. Returns True on success."""
    global CAMFiles, CAMFeatures, FeatureBlocks, CAMTools

    try:
        data = load_session(path)
    except Exception as e:
        debug_print(f"[error] Failed to load session: {e}")
        return False

    # Restore directory paths
    if data.get("base"):
        state["base"] = data["base"]
        dpg.set_value("base_val", state["base"])
    if data.get("output_base"):
        state["output_base"] = data["output_base"]
        dpg.set_value("out_val", state["output_base"])
    state["shared_dir"] = data.get("shared_dir")
    dpg.set_value("shared_val", state["shared_dir"] or "")

    # Load config — sets param choice lists and defaults, calls _refresh_ui(True)
    if data.get("cfg_path"):
        set_cfg(data["cfg_path"])

    # Override params with saved values
    state["params"].update(data.get("params", {}))

    # Scan files with restored directories
    CAMFiles, FeatureBlocks, CAMFeatures, CAMTools = scan_files(
        state["base"], shared_dir=state["shared_dir"]
    )

    # Re-enable saved features (scan created fresh CAMFeature objects)
    saved_features = set(data.get("enabled_features", []))
    for feat in CAMFeatures:
        if feat.name in saved_features:
            feat.set_enabled()

    run_plan()
    _refresh_ui(True)

    # Tick feature checkboxes that were enabled
    for feat in CAMFeatures:
        if feat.get_enabled():
            dpg.set_value(feat.get_radiobtn(), True)

    # Set json_name to match the file we just loaded (so Save writes back to same file)
    json_name = os.path.splitext(os.path.basename(path))[0]
    state["json_name"] = json_name
    if dpg.does_item_exist("json_name_val"):
        dpg.set_value("json_name_val", json_name)

    _refresh_session_combo()
    debug_print(f"[info] Session loaded from {path}")
    return True


def _refresh_session_combo():
    """Scan output dir for *.json files and update the Sessions dropdown."""
    if not state.get("output_base") or not os.path.isdir(state["output_base"]):
        return
    files = sorted(f for f in os.listdir(state["output_base"]) if f.endswith(".json"))
    if dpg.does_item_exist("session_combo"):
        dpg.configure_item("session_combo", items=files)
        current = dpg.get_value("session_combo")
        if files and current not in files:
            dpg.set_value("session_combo", files[0])


def _write_session_file(name: str):
    """Write state to <name>.json in output dir and refresh the dropdown."""
    enabled_names = [f.name for f in CAMFeatures if f.get_enabled()]
    filename = name + ".json"
    save_session(state["output_base"], state, enabled_names, filename=filename)
    _refresh_session_combo()
    if dpg.does_item_exist("session_combo"):
        dpg.set_value("session_combo", filename)
    debug_print(f"[info] Session saved as {filename}")


def _save_session_named(name: str):
    """Save current state as <name>.json, always overwriting any existing file."""
    if not name:
        debug_print("[warn] Json Name is empty, skipping session save")
        return
    if not state.get("output_base"):
        debug_print("[error] No output directory set, cannot save session")
        return
    _write_session_file(name)


def _load_selected_session(sender=None, app_data=None):
    name = dpg.get_value("session_combo")
    if not name or not state.get("output_base"):
        return
    path = os.path.join(state["output_base"], name)
    if os.path.isfile(path):
        _apply_session(path)


def _save_current_session_manual(sender=None, app_data=None):
    name = dpg.get_value("json_name_val").strip()
    state["json_name"] = name
    _save_session_named(name)


def _on_json_name_change(sender, app_data, user_data=None):
    state["json_name"] = app_data


def _copy_root_outputs_to_subdir(name: str):
    """Copy root-level output files to output_base/<name>/."""
    base = state["output_base"]
    dest = os.path.join(base, name)
    os.makedirs(dest, exist_ok=True)
    for fname in ("summary.txt", "tools.txt"):
        src = os.path.join(base, fname)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dest, fname))
    by_step = state.get("by_step", {})
    for out in state.get("resolved", []):
        step = str(out.get("step", ""))
        if step and (step not in by_step or not by_step[step]):
            continue  # not produced in current run; don't copy stale file
        src = os.path.join(base, out["name"])
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dest, out["name"]))
    debug_print(f"[info] Root outputs copied to {dest}")


def set_cfg(path):
    try:
        cfg = normalize_legacy(load_config_file(path))
        if cfg=={}:
            state["cfg"] = {}
            state["cfg_path"] = ""
            dpg.set_value("cfg_val", "None")
            return

        state["cfg"] = cfg
        state["cfg_path"] = path

        if "MODEL" not in cfg:
            debug_print("***********************error: config file doesn't set MODEL")
            state["cfg"]["MODEL"] = "UNKNOWN"
        if "CLINE" not in cfg:
            debug_print("***********************error: config file doesn't set CLINE")
            state["cfg"]["CLINE"] = 0
        if "CLINE_DELTA" not in cfg:
            debug_print("***********************error: config file doesn't set CLINE_DELTA")
            state["cfg"]["CLINE_DELTA"] = 15.5
        if "MAXUNITS" not in cfg:
            debug_print("***********************error: config file doesn't set MAXUNITS")
            state["cfg"]["MAXUNITS"] = 1
        if "DIRECTION" not in cfg:
            debug_print("***********************error: config file doesn't set DIRECTION")
            state["cfg"]["DIRECTION"] = "HORIZONTAL"
        if "NUM-STEPS" not in cfg:
            debug_print("***********************error: config file doesn't set NUM-STEPS")
            state["cfg"]["NUM-STEPS"] = len(cfg.get("OUTPUT-FILE-NAMES", []))

        dpg.set_value("cfg_val", path)
        model = cfg.get("MODEL", "")
        if model:
            state["json_name"] = model
            if dpg.does_item_exist("json_name_val"):
                dpg.set_value("json_name_val", model)
        debug_print("[info] Config loaded.")
    except Exception as e:
        debug_print( f"[error] Failed to load config: {e}")
        return

    # Build defaults & GUI pulldowns from cfg parameters
    state["params"] = {}
    state["params"]["Lefty"] = False
    state["param_values"]["Lefty"] = ""
    state["params"]["unit_1_only"] = False
    state["param_values"]["unit_1_only"] = ""
    state["params"]["zip_subdirs"] = False
    state["param_values"]["zip_subdirs"] = ""

    params_list = cfg.get("parameters", [])
    if not isinstance(params_list, list):
        params_list = []


    for p in params_list:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if not name:
            continue
        if name in ("Lefty", "unit_1_only", "zip_subdirs"):
            continue
        items = p.get("values", [])
        # normalize: dearpygui expects strings
        items_str = ["" if v is None else str(v) for v in items] if isinstance(items, list) else []
        default = p.get("default")
        default_str = "" if default is None else str(default)

        # Seed state with defaults
        state["params"][name] = default_str
        state["param_values"][name] = items_str

    run_plan()
    _refresh_ui(True)


with dpg.window(label="CAM Combiner", width=2500, height=1250):
    with dpg.group(horizontal=True):
        with dpg.group(horizontal=False):
            with dpg.group(horizontal=True):
                dpg.add_text("Base Directory:")
                dpg.add_input_text(tag="base_val", readonly=True, width=500)
                dpg.add_button(label="Choose Base", callback=lambda: dpg.show_item("base_dialog"))

            with dpg.group(horizontal=True):
                dpg.add_text("Config File:")
                dpg.add_input_text(tag="cfg_val", readonly=True, width=500)
                dpg.add_button(label="Choose Config", callback=lambda: dpg.show_item("cfg_dialog"))

            with dpg.group(horizontal=True):
                dpg.add_text("Shared GCode Dir:")
                dpg.add_input_text(tag="shared_val", readonly=True, width=500)
                dpg.add_button(label="Choose Shared Dir", callback=lambda: dpg.show_item("shared_dialog"))

            with dpg.group(horizontal=True):
                dpg.add_text("Output Director:")
                dpg.add_input_text(tag="out_val", readonly=True, width=500)
                dpg.add_button(label="Choose Output Dir", callback=lambda: dpg.show_item("out_dialog"))

            with dpg.group(horizontal=True):
                dpg.add_text("Json Name:  ")
                dpg.add_input_text(tag="json_name_val", default_value="", width=300,
                                   callback=_on_json_name_change)

            with dpg.group(horizontal=True):
                dpg.add_text("Sessions:   ")
                dpg.add_combo(tag="session_combo", items=[], width=350)
                dpg.add_button(label="Load", callback=_load_selected_session)
                dpg.add_button(label="Save", callback=_save_current_session_manual)

    dpg.add_separator()
    with dpg.group(horizontal=True, parent="Parameters"):
        dpg.add_button(label="Generate Output", callback=generate_output)

    dpg.add_separator()

    with dpg.group(horizontal=True, height=700):
        with dpg.child_window(width=350, border=True):
            dpg.add_text("Features", color=feature_based_color)
            dpg.add_group(tag="features_box")  # populated dynamically

        with dpg.child_window(width=350, border=True):
            dpg.add_text("Parameters", color=param_based_color)
            dpg.add_group(tag="Parameters")  # populated dynamically

        with dpg.group(horizontal=False, width=350):
            dpg.add_group(tag="model_params", width=350, height=325)  # populated dynamically
            dpg.add_group(tag="Options", width=350, height=325)  # populated dynamically

        with dpg.child_window(width=1000, border=True):
            dpg.add_group(tag="files")  # populated dynamically

        with dpg.child_window(width=500, border=True):
            dpg.add_group(tag="tools")  # populated dynamically

    dpg.add_separator()
    with dpg.child_window(tag="Outputs_window", border=True, height=225, width=2450):
        with dpg.table(tag="Outputs_table", header_row=True,
                       borders_innerH=True, borders_innerV=True, borders_outerV=True, borders_outerH=True):
            dpg.add_table_column(label="Step", width_fixed=True, init_width_or_weight=45)
            dpg.add_table_column(label="Out Name", width_fixed=True, init_width_or_weight=270)
            dpg.add_table_column(label="CAM Files Included", width_stretch=True)
    dpg.add_separator()
    with dpg.child_window(tag="Log_window", border=True, height=100, width=2450, horizontal_scrollbar=True):
        dpg.add_input_text(tag="Log", multiline=True, width=2400)

with dpg.file_dialog(directory_selector=True, show=False, callback=choose_base, tag="base_dialog", width=1000, height=500):
    dpg.add_file_extension(".*")

with dpg.file_dialog(directory_selector=False, show=False, callback=choose_cfg, tag="cfg_dialog", width=1000, height=500):
    dpg.add_file_extension(".*")

with dpg.file_dialog(directory_selector=True, show=False, callback=choose_shared, tag="shared_dialog", width=1000, height=500):
    dpg.add_file_extension(".*")

with dpg.file_dialog(directory_selector=True, show=False, callback=choose_out, tag="out_dialog", width=1000, height=500):
    dpg.add_file_extension(".*")

dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()
