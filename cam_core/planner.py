import os, re
import itertools
from typing import Dict, Any, List, Tuple
from cam_core.jsonc_loader import normalize_legacy
from cam_core.conditions import eval_condition
from cam_core.debug import debug_print
from cam_core.cam_file import CAMFile
from cam_core.CAMFeature import CAMFeature
from cam_core.Tool import Tool
from cam_core.FeatureBlock import FeatureBlock

def _param_lookup(parameters: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for p in parameters:
        name = p.get("name")
        if not name:
            continue
        out[name] = p
    return out


def _render_pattern(name: str, params: Dict[str, Any], pmap: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str]]:
    tokens = re.findall(r"<([A-Za-z_]\w*)(?::(lower|upper))?>", name)

    # build the "exact" version
    exact = name
    token_values = {}
    for t, case in tokens:
        v = params.get(t, "")
        if isinstance(v, bool):
            v = "True" if v else "False"
        v = str(v)
        if case == "lower":
            v = v.lower()
        elif case == "upper":
            v = v.upper()
        token_values[t] = v
        exact = exact.replace(f"<{t}" + (f":{case}>" if case else ">"), v)

    attempts = [(exact, "exact")]

    # generate wildcard substitutions for all combinations
    n = len(tokens)
    for r in range(1, n+1):  # 1 token → all tokens
        for combo in itertools.combinations([t for t, _ in tokens], r):
            candidate = exact
            labels = []
            for t in combo:
                wc = pmap.get(t, {}).get("wildcard")
                if wc:
                    candidate = candidate.replace(token_values[t], wc)
                    labels.append(t)
            if labels:  # only add if at least one token had a wildcard
                attempts.append((candidate, f"wildcard({','.join(labels)})"))

    return attempts


def _match_files(files: List[CAMFile], attempt: str) -> List[CAMFile]:
    esc = re.escape(attempt)
    rx = re.compile(rf"^{esc}(?:[-.].*)?$", re.IGNORECASE)
    return [f for f in files if rx.match(f.name)]


def _scan_features():
    verbose = False
    """
    Group subdirectory files by feature tag.
    Only considers files that are NOT at the base root (i.e., in subfolders).
    """
    if (verbose):
        debug_print("=====================scanning for Features==========================")
    for fb in scan_files.fblocks:
        if verbose:
            debug_print("Block: ", fb.get_name())
        if (fb.get_name() == "Base"):
            # base / root directory. No features here to add
            continue

        last_feature = ""
        last_feature_name = ""
        unsortedfiles = fb.get_CAM_files()
        sortedfiles = sorted(unsortedfiles, key=lambda f: f.get_feature_name())
        if verbose:
            v("unsorted: " + str(unsortedfiles))
            debug_print("sorted: " + str(sortedfiles))
        for cf in sortedfiles:
            if verbose:
                print("     File: ", cf.name, " ==> ", cf.get_feature_name())
            file_feature_name = cf.get_feature_name()
            if file_feature_name != last_feature_name:
                if (verbose):
                    debug_print("new Feature: ", cf.get_feature_name())
                newFeature = CAMFeature(cf.get_feature_name())
                scan_files.cfeatures.append(newFeature)
                last_feature = newFeature
                last_feature_name = cf.get_feature_name()

                # add the new feature to the feature block
                fb.add_CAM_feature(newFeature)

            last_feature.add_CAM_file(cf)
            if verbose:
                debug_print("   adding to: ", cf.get_feature_name(), " file: ", cf.name)

    if verbose:
        debug_print("================Done scanning for Features==========================")

    return


def scan_files(base_dir: str, include_ext: Tuple[str,...]=(".nc",), shared_dir: str=None) ->Tuple[List[CAMFile], List[FeatureBlock], List[CAMFeature], List[Tool]]:
    scan_files.cfiles: [CAMFile] = []
    scan_files.cfeatures: [CAMFeature] = []
    scan_files.fblocks: [FeatureBlock] = []
    scan_files.tools: [Tool] = []

    scan_files.current_featureblock = FeatureBlock("Base", "Base")
    scan_files.fblocks.append(scan_files.current_featureblock)

    _scan_files_int(base_dir, include_ext)

    if shared_dir:
        base_block = next(fb for fb in scan_files.fblocks if fb.name == "Base")
        scan_files.current_featureblock = base_block
        _scan_files_int(shared_dir, include_ext, block_prefix="Shared")

    _scan_features()

    #*********************************************************************************
    # note that this sorting gives different ordering of CAM objects in output files:
    # we are now alphebetizing by feature name. In the original script, final ordering
    # was based on Feature Block (i.e., by directory -- which was sorted alphabetically),
    # then by feature name within each block (i.e., by the file names in alphabetic order)
    #*********************************************************************************
    new_fblocks = sorted(scan_files.fblocks, key=lambda fbl: fbl.name)
    scan_files.fblocks = new_fblocks
    new_cfeatures = sorted(scan_files.cfeatures, key=lambda cft: cft.name)
    scan_files.cfeatures = new_cfeatures

    return scan_files.cfiles, scan_files.fblocks, scan_files.cfeatures, scan_files.tools


def _scan_files_int(base_dir: str, include_ext: Tuple[str,...]=(".nc",), block_prefix: str=""):
    verbose = False
    skip_files = {"fixture_config.txt", "desktop.ini", "#*", ".*", ".DS_Store"}

    entries = sorted(os.scandir(base_dir), key=lambda x: getattr(x, 'name'))

    # scan ALL to create CAMFile objects, but skip dirs
    for entry in entries:
        fname = base_dir + "/" + entry.name
        # process all non-directory entries first
        if not entry.is_dir() and entry.name not in skip_files:
            newfile = CAMFile(entry.name, base_dir, scan_files.current_featureblock.name == "Base")
            scan_files.cfiles.append(newfile)
            scan_files.current_featureblock.add_CAM_file(newfile)
            tool = newfile.get_tool()
            if not tool is None:
                got_one = False
                for t in scan_files.tools:
                    if t.get_tool_num() == tool.get_tool_num():
                        got_one = True
                        if t.get_desc() == tool.get_desc():
                            # same #, same description. add new file to old tool
                            t.add_file(newfile)
                        else:
                            # t # match, but descp fail. ERROR!
                            t.set_error("file " + entry.name + " reused tool #" + str(t.get_tool_num()) + " new descr: "+tool.get_desc())
                            t.add_file(newfile)
                        break
                if not got_one:
                    # add new tool to our array of tools
                    scan_files.tools.append(tool)

    # now scan all directories and call ourselves recursively
    for entry in entries:
        fname = base_dir + "/" + entry.name
        if entry.is_dir():
            if verbose:
                debug_print("DIR:" + entry.name)
            block_name = (block_prefix + "/" + entry.name) if block_prefix else entry.name
            scan_files.current_featureblock = FeatureBlock(block_name, entry.name)
            scan_files.fblocks.append(scan_files.current_featureblock)
            _scan_files_int(fname, include_ext, block_name)

    return

def normalize_step(stepin: str)->str:
    return stepin.format("")


def plan(cfg: Dict[str, Any],
        runtime_params: Dict[str, Any],
        files: List[CAMFile],
        base_dir: str,
        feature_blocks: list[FeatureBlock],
        features_enabled: list[CAMFeature],
        verbose: bool=False):
    if verbose:
        debug_print("==========================================PLANNER==============================")

    cfg = normalize_legacy(cfg or {})
    outputs = cfg.get("outputs", [])
    base_entries = cfg.get("base_selection", {}).get("input_file_base_names", [])
    if verbose:
        debug_print("base: ", base_entries)
    parameters = cfg.get("parameters", [])
    pmap = _param_lookup(parameters)

    if verbose:
        debug_print("================ PLANNER: DIRECTORY LISTING ================")
        for f in files:
            print(" -", f)

    # clear the search string matches in all files
    for m in files:
        m.set_matching_search_string("")

    selected_by_step: Dict[str, List[CAMFile]] = {}
    sorted_selected_by_step: Dict[str, List[CAMFile]] = {}
    featbool: Dict[CAMFile, List[bool]] = {}
    firstbool: Dict[CAMFile, List[bool]] = {}
    endbool: Dict[CAMFile, List[bool]] = {}
    req_missing = []

    params = {}
    for p in parameters:
        name = p.get("name")
        if not name: continue
        params[name] = runtime_params.get(name, p.get("default"))
    for k, v in runtime_params.items():
        params.setdefault(k, v)

    for entry in base_entries:
        patt = entry.get("name") if isinstance(entry, dict) else str(entry)
        required = str(entry.get("required", "False")).lower() in ("true","yes","1") if isinstance(entry, dict) else False
        cond = (entry.get("condition") if isinstance(entry, dict) else None) or ""
        ok = eval_condition(cond, params)
        if verbose:
            debug_print(f"[cond] {patt}: {cond or 'None'} => {ok}")
        if not ok:
            continue
        attempts = _render_pattern(patt, params, pmap)
        matches = []
        level = "none"
        for concrete, lvl in attempts:
            if verbose:
                debug_print(f"[debug] pattern concrete='{concrete}'")
            matches = _match_files(files, concrete)
            if matches:
                level = lvl
                break
        if verbose:
            debug_print(f"[base] {patt}: matches={len(matches)} level={level}")
        if required and not matches:
            req_missing.append(patt)
        for m in matches:
            step = m.get_step()
            if verbose:
                debug_print(os.path.basename(m.filename) + "==>" + str(step))
            selected_by_step.setdefault(step, []).append(m)
            m.set_matching_search_string(patt)
            #print("match: " + patt + str(m.name))

    if not base_entries:
        if verbose:
            debug_print("checking for base step file")

        # output files from the base directory
        for ft in feature_blocks:
            if ft.name == "Base":
                for f in ft.get_CAM_files():
                    fstep = f.get_step()

                    if fstep == "FRONT":
                        fstep = cfg.get("FRONT-STEP") or "00"
                    if fstep == "BACK":
                        fstep = cfg.get("BACK-STEP") or "00"
                    selected_by_step.setdefault(fstep, []).append(f)

    unsortedfeatures = features_enabled
    sortedfeatures = sorted(unsortedfeatures, key=lambda f: f.name)
    for v in sortedfeatures:
        if verbose:
            debug_print("feature enabled: " + str(v))
        unsortedfiles = v.get_CAM_files()
        sortedfiles = sorted(unsortedfiles, key=lambda f: f.name)
        if verbose:
            debug_print("unsorted: " + str(unsortedfiles))
            debug_print("sorted: " + str(sortedfiles))

        for f in sortedfiles:
            raw_step = str(f.get_step())
            if raw_step == "FRONT":
                raw_step = cfg.get("FRONT-STEP") or "00"
            if raw_step == "BACK":
                raw_step = cfg.get("BACK-STEP") or "00"
            fstep = str(f'{raw_step:0>2}')
            selected_by_step.setdefault(fstep, []).append(f)

    if req_missing:
        debug_print("[warn] required base patterns missing:" + ", ".join(req_missing))

    featbool = {}
    firstbool = {}
    endbool = {}

    #OK, sort the output files for each step
    for out in outputs:
        step2 = str(out.get("step",""))
        if step2 in selected_by_step:
            for f in selected_by_step.get(step2, []):
                featbool.setdefault(f, []).append(not f._is_root)
                if re.search("-first", f.name) or re.search("-start", f.name):
                    firstbool.setdefault(f, []).append(True)
                else:
                    firstbool.setdefault(f, []).append(False)
                if re.search("-end", f.name):
                    endbool.setdefault(f, []).append(True)
                else:
                    endbool.setdefault(f, []).append(False)

    for out2 in outputs:
        step = out2.get("step", "")
        if step in selected_by_step:
            #***** FEAT ****** FIRST ******* !END
            for f in selected_by_step.get(step, []):
                fet = (featbool.get(f) or [False])[0]
                fst = (firstbool.get(f) or [False])[0]
                eb = (endbool.get(f) or [False])[0]
                #print("step:"+step+" file:"+f.name+" feat?"+str(fet)+" fst?"+str(fst)+" end?"+str(eb))
                if fet and fst and not eb:
                    # output it
                    sorted_selected_by_step.setdefault(step, []).append(f)

            # ***** BASE ****** FIRST ******* !END
            for f in selected_by_step.get(step, []):
                fet = (featbool.get(f) or [False])[0]
                fst = (firstbool.get(f) or [False])[0]
                eb = (endbool.get(f) or [False])[0]
                if not fet and fst and not eb:
                    #output it
                    sorted_selected_by_step.setdefault(step, []).append(f)
                    continue

            #***** FEAT ****** !FIRST ******* !END (Normal feature files)
            for f in selected_by_step.get(step, []):
                fet = (featbool.get(f) or [False])[0]
                fst = (firstbool.get(f) or [False])[0]
                eb = (endbool.get(f) or [False])[0]
                if fet and not fst and not eb:
                    #output it
                    sorted_selected_by_step.setdefault(step, []).append(f)
                    continue

            #***** BASE ****** !FIRST ******* !END (Normal base files)
            for f in selected_by_step.get(step, []):
                fet = (featbool.get(f) or [False])[0]
                fst = (firstbool.get(f) or [False])[0]
                eb = (endbool.get(f) or [False])[0]
                if not fet and not fst and not eb:
                    #output it
                    sorted_selected_by_step.setdefault(step, []).append(f)
                    continue

            #***** FEAT ****** !FIRST ******* END (-end feature files)
            for f in selected_by_step.get(step, []):
                fet = (featbool.get(f) or [False])[0]
                fst = (firstbool.get(f) or [False])[0]
                eb = (endbool.get(f) or [False])[0]
                if fet and not fst and eb:
                    #output it
                    sorted_selected_by_step.setdefault(step, []).append(f)
                    continue

            #***** BASE ****** !FIRST ******* END (-end base files)
            for f in selected_by_step.get(step, []):
                fet = (featbool.get(f) or [False])[0]
                fst = (firstbool.get(f) or [False])[0]
                eb = (endbool.get(f) or [False])[0]
                if not fet and not fst and eb:
                    #output it
                    sorted_selected_by_step.setdefault(step, []).append(f)
                    continue

    debug_print("================ PLANNER OUTPUT SELECTION ================")
    resolved_outputs = outputs
    for out in resolved_outputs:
        step = str(out.get("step",""))
        name = out.get("name","")
        files = selected_by_step.get(step, [])
        debug_print(f"     {name} step={step} count={len(files)}")
        for f in files:
            fet = featbool.get(f)[0]
            fst = firstbool.get(f)[0]
            eb = endbool.get(f)[0]
            #debug_print(f"         - FT{fet} FST{fst} END{eb} {f.name}")
            debug_print(f"         - {f.name}")
    debug_print("================ PLANNER SORTED OUTPUT  =====================")
    for out in resolved_outputs:
        step = str(out.get("step",""))
        name = out.get("name","")
        files = sorted_selected_by_step.get(step, [])
        debug_print(f"     {name}] step={step} count={len(files)}")
        for f in files:
            fet = featbool.get(f)[0]
            fst = firstbool.get(f)[0]
            eb = endbool.get(f)[0]
            #debug_print(f"         - FT{fet} FST{fst} END{eb} {f.name}")
            debug_print(f"         - {f.name}")
    debug_print("=========================================================")

    return resolved_outputs, sorted_selected_by_step
