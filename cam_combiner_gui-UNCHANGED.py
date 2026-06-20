# cam_combiner_gui.py — minimal changes to add Feature checkboxes (unique per tag)

from cam_core.version import GUI_BANNER, APP_BANNER, VERSION
from cam_core.jsonc_loader import load_config_file, normalize_legacy
from cam_core.planner import plan, scan_files
from cam_core.debug import debug_dump_params_and_dir
import sys, os, re

print(GUI_BANNER)
print("="*40)
print(APP_BANNER)
print("="*40)

try:
    import dearpygui.dearpygui as dpg  # type: ignore
except Exception:
    print("[error] GUI requires dearpygui. Install with: pip install dearpygui")
    sys.exit(1)

dpg.create_context()
dpg.create_viewport(title=f"CAM Combiner {VERSION}", width=1550, height=1050)

state = {
    "base": os.getcwd(),
    "cfg_path": None,
    "cfg": None,                # static config file
    "params": {},               # dynamic value of config paramaters

    "features": {},             # {feature_tag: [relative file paths]}
    "enabled_features": set(),  # {feature_tag, ...}
    "feature_checks": {},       # tag -> checkbox item id

    "feature_blocks": {},       # { feature_tag: block name
}

CAMFiles = []           # CAMFile objects
CAMFeatures = [],       # CAMFeature objects
FeatureBlocks = [],     # FeatureBlock objects

# --- helpers -------------------------------------------------------------

_TAG_STRIP_RE = re.compile(r"-(lefty|righty|NODUP|NOMIRROR)(?=\.|$)", re.IGNORECASE)
_NUM_MID_RE   = re.compile(r"(?<!^)-?\d+(?=[^-]*$)")  # numbers not at start; conservative

def _on_param_change(sender, app_data, user_data):
    """Combo callback: keep state['params'] in sync with GUI."""
    name = user_data
    state["params"][name] = app_data
    # Keep a quick, readable dump in the Options box for reference
    try:
        lines = [f"{k}={v}" for k, v in sorted(state["params"].items())]
        dpg.set_value("Options", "\n".join(lines))
    except Exception:
        pass

def _rel(root: str, path: str) -> str:
    try:
        return os.path.relpath(path, root).replace("\\", "/")
    except Exception:
        return path.replace("\\", "/")

def _feature_tag_from_rel(rel_path: str) -> str:
    """
    Given a relative path like 'TRWheelSlots/05-wheel-slot-s25PT5-01-end.nc'
    → '05-wheel-slot-s25PT5'
    For single files like 'Options/new12radius.nc' → 'new12radius'.
    """
    part = rel_path.split("/", 1)[-1] if "/" in rel_path else rel_path
    stem = os.path.splitext(os.path.basename(part))[0]
    # strip known tags
    stem = re.sub(r"-front", "", stem)
    stem = re.sub(r"-back", "", stem)
    stem = re.sub(r"-end", "", stem)
    stem = re.sub(r"-start", "", stem)
    stem = re.sub(r"^([A-Za-z]?\d{2})-", "", stem)

    # drop trailing run-like numbers that are not at start (e.g., '-01', '-02')
    stem = re.sub(r"-\d+$", "", stem)
    # drop any remaining mid-number run (conservative)
    #stem = _NUM_MID_RE.sub("", stem)
    #stem = stem.strip("-_")
    # if there is a directory prefix, keep only the file-derived tag for UI label
    return stem

def _scan_features(base_dir: str) -> dict:
    verbose = True
    """
    Group subdirectory files by feature tag.
    Only considers files that are NOT at the base root (i.e., in subfolders).
    """
    CAMFiles, FeatureBlocks, CAMFeatures = scan_files(base_dir)
    found_dirs = set()

    if (verbose):
        print("=====================scanning for Features==========================")
    for p in files:
        rel = p.replace("\\", "/")
        if "/" not in rel:
            continue  # root-level file -> base, not a feature
        topdir = rel.split("/", 1)[0]
        found_dirs.add(topdir)
        tag = _feature_tag_from_rel(rel)
        if not tag:
            continue
        features.setdefault(tag, []).append(rel)
        if (tag in feature_blocks):
            if (verbose):
                print("appending to existing feature block: tag"+topdir+"value:"+tag+" rel:"+rel)
            feature_blocks[topdir].append(tag)
        else:
            if (verbose):
                print("creating new feature block: tag:"+tag+" dir:"+topdir)
            feature_blocks.setdefault(tag, []).append(tag)

    if verbose:
        print(f"[features] discovered subfolders: {', '.join(sorted(found_dirs))}" if found_dirs else "[features] no subfolders")
        for k, v in sorted(features.items()):
            print(f"[features] {k}: {len(v)} files: {v}")

        print("featureblocks: "+str(feature_blocks))
        print("================Done scanning for Features==========================")

    return features, feature_blocks

def _refresh_features_ui():
    """Create one checkbox per unique feature tag."""
    # clear previous
    parent = "features_box"
    if dpg.does_item_exist(parent):
        # delete all children
        for child in list(dpg.get_item_children(parent, 1) or []):
            dpg.delete_item(child)

    state["feature_checks"].clear()

    if not state["features"]:
        with dpg.group(parent=parent):
            dpg.add_text("(no features found)")
        return

    with dpg.group(parent=parent):
        dpg.add_text("Enable Features:")
        for fbtag in state["feature_blocks"]:
            dpg.add_separator(label=fbtag)
            ftag = state["feature_blocks"][fbtag]
            print("fb: fbtag", str(fbtag), "ftag:", ftag)

            for f in ftag:
                print("trying to build button for ", f)
                # default OFF
                checked = False
                try:
                    if dpg.get_value(fbtag):
                        checked = dpg.get_value(fbtag)
                except Exception:
                    pass
                cid = dpg.add_checkbox(label=f, default_value=checked,
                                       callback=lambda s, a, u=ftag: _toggle_feature(u, a))
                state["feature_checks"][fbtag] = cid

def _toggle_feature(tag: str, value: bool):
    if value:
        state["enabled_features"].add(tag)
    else:
        state["enabled_features"].discard(tag)
    # Re-plan on toggle (non-invasive; same button layout)
    run_plan()

# --- main actions --------------------------------------------------------

def _get_enabled_features() -> dict:
    enabled = set()
    for tag, item_id in state.get("feature_checks", {}).items():
        try:
            if dpg.get_value(tag):
                print("gef: "+str(tag))
                enabled.add(tag)
        except Exception:
            pass
    return enabled

def run_plan(sender=None, app_data=None, user_data=None):
    if not state["cfg"] or not state["base"]:
        dpg.set_value("log", "[warn] Choose a base directory and config file first.")
        return
    cfg = state["cfg"]

    # Build params from cfg defaults (unchanged)
    params = {p["name"]: p.get("default") for p in cfg.get("parameters", []) if isinstance(p, dict) and p.get("name")}

    files = scan_files(state["base"])
    # Verbose dump (unchanged)
    if (1):
        debug_dump_params_and_dir(state["base"], params, files)

    enabled_features = _get_enabled_features()
    print("====GUI============Enabled Features========================")
    for f in enabled_features:
        print(f)
        ft = state["features"].get(f)
        print(ft)
    print("====GUI====================================================")

    # Plan (pass-through; core may ignore features for now—UI only toggle)
    # If/when core supports it, wire via cfg/user_data.
    from io import StringIO
    import contextlib
    buf = StringIO()
    with contextlib.redirect_stdout(buf):
        resolved, by_step = plan(state["base"],
                                 cfg,
                                 params,
                                 files,
                                 enabled_features,
                                 verbose=True)
    print(buf.getvalue())
    dpg.set_value("Log", buf.getvalue())

    # Pretty Outputs box (unchanged logic)
    parts = ""
    for out in resolved:
        step = str(out.get("step", ""))
        name = out.get("name", "")
        step_files = by_step.get(step, [])
        if not step_files:
            continue
        parts += name + ":"
        parts += ",".join(step_files)
        parts += "\n"

    dpg.set_value("Outputs", parts)
    print(parts)

def choose_base(sender, app_data):
    state["base"] = app_data["file_path_name"]
    dpg.set_value("base_val", state["base"])

    # Auto-select config in base (unchanged behavior)
    cfg_path = os.path.join(state["base"], "fixture_config.txt")
    set_cfg(cfg_path)

    # Scan & refresh Features
    CAMFiles, FeatureBlocks, CAMFeatures = scan_files(base_dir)

    #state["files"], state["feature_blocks"], state["features"] = _scan_features(state["base"])
    _refresh_features_ui()

def choose_cfg(sender, app_data):
    path = app_data["file_path_name"]
    set_cfg(path)

def set_cfg(path):
    try:
        cfg = normalize_legacy(load_config_file(path))
        state["cfg"] = cfg
        state["cfg_path"] = path
        dpg.set_value("cfg_val", path)
        dpg.set_value("Log", "[info] Config loaded.")
    except Exception as e:
        dpg.set_value("Log", f"[error] Failed to load config: {e}")
    # Build defaults & GUI pulldowns from cfg parameters
    state["params"] = {}
    params_list = cfg.get("parameters", [])
    if not isinstance(params_list, list):
        params_list = []

    with dpg.group(horizontal=True, parent="Parameters"):
        dpg.add_checkbox(
            label="Lefty",
            tag="lefty_cb",
            default_value=False,
            callback=lambda s, a: state.__setitem__("lefty", bool(a))
        )

    for p in params_list:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if not name:
            continue
        items = p.get("values", [])
        # normalize: dearpygui expects strings
        items_str = ["" if v is None else str(v) for v in items] if isinstance(items, list) else []
        default = p.get("default")
        default_str = "" if default is None else str(default)

        # Seed state with defaults
        state["params"][name] = default_str

        # Label + combo per parameter
        with dpg.group(horizontal=True, parent="Parameters"):
            dpg.add_text(name)
            dpg.add_combo(
                tag=f"param_{name}",
                items=items_str,
                default_value=default_str,
                width=200,
                callback=_on_param_change,
                user_data=name
            )

    # Also mirror a readable dump of params in the Options text box (handy for copy/paste)
    try:
        lines = [f"{k}={v}" for k, v in sorted(state["params"].items())]
        dpg.set_value("Options", "\n".join(lines))
        #FIXME: add Lefty to the output here
    except Exception:
        pass

# --- UI ------------------------------------------------------------------

with dpg.window(label="CAM Combiner", width=1500, height=1000):
    with dpg.group(horizontal=True):
        dpg.add_text("Base Directory:")
        dpg.add_input_text(tag="base_val", readonly=True, width=600)
        dpg.add_button(label="Choose Base", callback=lambda: dpg.show_item("base_dialog"))

    with dpg.group(horizontal=True):
        dpg.add_text("Config File:")
        dpg.add_input_text(tag="cfg_val", readonly=True, width=600)
        dpg.add_button(label="Choose Config", callback=lambda: dpg.show_item("cfg_dialog"))

    dpg.add_separator()
    dpg.add_button(label="Plan Outputs", callback=run_plan)

    dpg.add_separator()
    with dpg.group(horizontal=True, width=1000, height=500):
        with dpg.child_window(width=350, height=500, border=True):
            dpg.add_text("Features")
            dpg.add_group(tag="features_box")  # populated dynamically

        with dpg.child_window(width=350, height=500, border=True):
            dpg.add_text("Parameters")
            dpg.add_group(tag="Parameters")

        with dpg.group():
            dpg.add_input_text(tag="Options", multiline=True, width=5350, height=500)

    dpg.add_separator()
    dpg.add_input_text(tag="Outputs", multiline=True, width=1000, height=200)
    dpg.add_separator()
    dpg.add_input_text(tag="Log", multiline=True, width=1000, height=200)

with dpg.file_dialog(directory_selector=True, show=False, callback=choose_base, tag="base_dialog", width=500, height=500):
    dpg.add_file_extension(".*")

with dpg.file_dialog(directory_selector=False, show=False, callback=choose_cfg, tag="cfg_dialog", width=500, height=500):
    dpg.add_file_extension(".*")

dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()
