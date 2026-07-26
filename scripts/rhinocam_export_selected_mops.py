"""
Export each selected RhinoCAM machining operation (MOp) to its own individual
.nc file, instead of RhinoCAM's default of posting a whole setup as one
combined program.

Run this from Rhino's CLASSIC Python editor (the EditPythonScript command) --
NOT Rhino 8's newer "Tools > Script > Edit" ScriptEditor, which defaults to
CPython 3 and can't import mecsoftcamapi (that module only exists for
IronPython 2, in a completely separate folder under the RhinoCAM SDK install).
Have the part open and RhinoCAM's MILL module active.

The RhinoCAM API has no documented call to read which rows are highlighted in
the Operations Manager tree, so "selected" here means picked from a checklist
this script shows you (every MOp across every setup, pre-checked) -- tick the
ones you want, uncheck the rest. Folders (MopSets) each get one extra
"select all in this folder" checkbox alongside their individual per-MOp rows
-- but see MOPSET LIMITATION below: their contents don't actually show up.

Configure POSTPROCESSOR / POSTPROCESSOR_PATH below to match the post your
shop actually uses, and USE_ACTIVE_POSTPROCESSOR to match which RhinoCAM SDK
you're running against (2021 vs 2026 -- see the comment on that flag).

Does NOT call Regenerate() before posting -- regenerating depends on the
operation's correct geometry actually being displayed/current in the Rhino
viewport, which a script has no way to guarantee or verify. Operations you
choose to export are assumed to already be clean (regenerated, not dirty)
via your own workflow; posting just reads whichever toolpath the operation
already has. Suppressed or dirty operations are detected automatically
(RhinoCAM 2026's IsSuppressed()/IsDirty()) and excluded from the checklist,
with one more check right before posting in case something changed since.

MOPSET LIMITATION: MOpManager has no documented -- or, it turns out,
reflectable-and-callable -- function to enumerate a MopSet folder's
contents. MOpManager.GetMOpCount()/GetMOpByIndex() only work on a real
MOpSetup; calling them on a MopSet (type name MOpSetMOp) reliably raises
rather than returning children (confirmed across ~50 folders in a real
production file). Operations organized into folders are entirely invisible
to this script -- keep anything you want individually exported at the root
level of the Operations Manager. Filed as an open question with MecSoft;
see mecsoft_support_question.md if you have it, or ask again for it.
"""
import datetime
import os
import re

import rhinoscriptsyntax as rs
from mecsoftcamapi import *
import MecSoftCAM.Types.ModuleType as ModuleType
import MecSoftCAM.Managers.MOpManager as MOpManager
import MecSoftCAM.Managers.ToolManager as ToolManager

# EDIT ME: the post-processor name as RhinoCAM lists it (see RhinoCAM's own
# Post dialog for the exact string -- it's the .spm file's name). Used
# directly when USE_ACTIVE_POSTPROCESSOR is False (RhinoCAM 2021 SDK).
POSTPROCESSOR = "AlloyShopsabre(WinCNC)ATC.spm"

# EDIT ME: full path to that same postprocessor's .spm file. Used when
# USE_ACTIVE_POSTPROCESSOR is True (RhinoCAM 2026 SDK).
POSTPROCESSOR_PATH = (
    r"C:\ProgramData\MecSoft Corporation\RhinoCAM 2026 for Rhino 8.0"
    r"\Posts\MILL\SPM\AlloyShopsabre(WinCNC)ATC.spm"
)

# RhinoCAM 2026 adds MOpManager.SetPostProcessor(path)/GetPostProcessor(),
# plus argument-less Post-family overloads that use whatever was last set
# active -- none of this exists in the RhinoCAM 2021 SDK, which needs the
# postprocessor name passed explicitly on every call instead. True for 2026,
# False for 2021.
USE_ACTIVE_POSTPROCESSOR = True

# EDIT ME: folder for the debug log. Defaults to next to this script file.
try:
    LOG_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    LOG_DIR = os.environ.get("TEMP", "C:\\")

_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')

# The 9 documented creatable operation types share the common GetName()/
# Post()/Regenerate()/etc. interface. WorkZeroMOp and MOpSetMOp (folders) are
# different object types without that interface -- calling a common-
# interface method on one of those is unsupported, so unknown types are
# filtered out by name before anything else touches them.
_EXPORTABLE_MOP_TYPES = {
    "Cut3AxPFinishingMOp",
    "Cut3AxProjPocketingMOp",
    "Cut3AxHRoughingMOp",
    "Cut2AxFaceTopMOp",
    "Cut2AxPocketingMOp",
    "Cut2AxProfilingMOp",
    "Cut2AxEngravingMOp",
    "DrillMOp",
    "Cut2AxFacingMOp",
}


_log_file = None  # set by _open_log(); _log() writes here as well as to Output


def _open_log():
    global _log_file
    path = os.path.join(LOG_DIR, "rhinocam_export_log_{}.txt".format(
        datetime.datetime.now().strftime("%Y%m%d_%H%M%S")))
    _log_file = open(path, "w")
    return path


def _log(msg):
    print(msg)
    if _log_file is None:
        return
    _log_file.write(msg + "\n")
    _log_file.flush()


def _safe_filename(name, fallback):
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", (name or "").strip())
    return cleaned or fallback


def _check_suppressed_dirty(mop):
    """Return (is_suppressed, is_dirty) via RhinoCAM 2026's documented,
    direct IsSuppressed()/IsDirty() instance methods."""
    return bool(mop.IsSuppressed()), bool(mop.IsDirty())


def _get_mopset_children(container):
    """Try to enumerate `container`'s children via MOpManager.GetMOpCount().
    See the module docstring's MOPSET LIMITATION note -- this always returns
    None for a real MopSet today (GetMOpCount()/GetMOpByIndex() reject the
    wrong type), kept here in case a future SDK build adds real support."""
    try:
        return MOpManager.GetMOpCount(container)
    except Exception:
        return None


def _resolve_mop(setup, mop_path):
    """Re-fetch the actual MOp object for `mop_path` (a tuple of indices),
    descending through nested MopSet containers as needed. mop_path[0] is
    always an index into `setup` itself; any further indices descend into
    successive MopSet children."""
    container = setup
    mop = None
    for idx in mop_path:
        mop = MOpManager.GetMOpByIndex(container, idx)
        container = mop
    return mop


def _visit_container(container, child_count, setup_idx, path_prefix, tag_prefix, entries, folder_groups):
    """Visit every child of `container` (a MOpSetup, or -- experimentally --
    a MopSet folder), appending real exportable MOps to `entries`. Recurses
    into any MopSet child whose contents turn out to be enumerable, treating
    it as an opaque leaf otherwise (see MOPSET LIMITATION in the docstring).

    Whenever a MopSet's children are successfully collected, their entries'
    positions get recorded into `folder_groups` as (folder_tag,
    [entries-indices]), so the checklist dialog can offer one "select all in
    this folder" checkbox alongside the individual per-MOp ones."""
    for i in range(child_count):
        path = path_prefix + (i,)
        tag = "{} #{}".format(tag_prefix, i + 1)

        mop = MOpManager.GetMOpByIndex(container, i)
        if mop is None:
            continue
        type_name = type(mop).__name__

        if type_name == "MOpSetMOp":
            sub_count = _get_mopset_children(mop)
            if sub_count is not None:
                start = len(entries)
                _visit_container(mop, sub_count, setup_idx, path, tag, entries, folder_groups)
                if len(entries) > start:
                    folder_groups.append((tag, list(range(start, len(entries)))))
            else:
                _log("Skipping {} -- folder, contents not enumerable".format(tag))
            continue

        if type_name not in _EXPORTABLE_MOP_TYPES:
            _log("Skipping {} -- {}".format(tag, type_name))
            continue

        is_suppressed, is_dirty = _check_suppressed_dirty(mop)
        if is_suppressed:
            _log("Skipping {} -- suppressed".format(tag))
            continue
        if is_dirty:
            _log("Skipping {} -- dirty (needs regenerate)".format(tag))
            continue

        label = "{}: {}".format(tag, mop.GetName())
        entries.append((setup_idx, path, label))


def _collect_all_mops():
    """Return (entries, folder_groups) -- see _visit_container()."""
    entries = []
    folder_groups = []
    setup_count = MOpManager.GetMOpSetupCount()
    for setup_idx in range(setup_count):
        setup = MOpManager.GetMOpSetupByIndex(setup_idx)
        if setup is None:
            continue
        mop_count = MOpManager.GetMOpCount(setup)
        _visit_container(setup, mop_count, setup_idx, (), "Setup {}".format(setup_idx + 1),
                          entries, folder_groups)
    return entries, folder_groups


def export_selected_mops():
    log_path = _open_log()
    print("Logging to: {}".format(log_path))  # plain print: shown even if _log_file somehow fails to open
    _log("=== Run started {} ===".format(datetime.datetime.now().isoformat()))

    try:
        # --- Phase 1: collect, with the RhinoCAM API initialized ---
        MecSoftCAM.API.Initialize()
        try:
            try:
                _log("RhinoCAM API version: {}".format(MecSoftCAM.Version.GetVersion()))
            except Exception:
                _log("RhinoCAM API version: (MecSoftCAM.Version not available -- pre-2026 SDK)")
            MecSoftCAM.API.SetActiveModule(ModuleType.MILL)
            entries, folder_groups = _collect_all_mops()
        finally:
            MecSoftCAM.API.Uninitialize()

        _log("Found {} exportable operation(s).".format(len(entries)))
        if not entries:
            _log("No machining operations found -- nothing to export.")
            return

        # --- Phase 2: dialogs, with the RhinoCAM API uninitialized ---
        # Build the flat checklist with one synthetic "select all in this
        # folder" row inserted right before each folder's first child
        # (rs.CheckListBox has no hierarchical/parent-child concept, so this
        # is the closest approximation: a master row that, if checked, pulls
        # in every item in that folder -- including nested sub-folders,
        # since folder_groups' index lists already include descendants
        # transparently -- alongside the individual per-MOp rows, which
        # still work independently when the master is left unchecked).
        groups_by_start = {}
        for gi, (_folder_tag, child_indices) in enumerate(folder_groups):
            if child_indices:
                groups_by_start.setdefault(child_indices[0], []).append(gi)
        for start in groups_by_start:
            groups_by_start[start].sort(key=lambda group_idx: -len(folder_groups[group_idx][1]))

        dialog_labels = []
        dialog_map = []  # parallel list: ("folder", gi) or ("entry", entries-index)
        for idx, (_setup_idx, _mop_path, label) in enumerate(entries):
            for gi in groups_by_start.get(idx, []):
                folder_tag, child_indices = folder_groups[gi]
                dialog_labels.append(("[FOLDER] {} -- ALL {} item(s)".format(
                    folder_tag, len(child_indices)), True))
                dialog_map.append(("folder", gi))
            dialog_labels.append((label, True))
            dialog_map.append(("entry", idx))

        picked = rs.CheckListBox(dialog_labels, "Choose operations to export individually "
                                  "(FOLDER rows select everything in that folder)", "Export CAM Ops")
        if picked is None:
            _log("Cancelled.")
            return

        checked_entries = set()
        checked_folders = set()
        for (kind, ref), (_name, checked) in zip(dialog_map, picked):
            if not checked:
                continue
            if kind == "entry":
                checked_entries.add(ref)
            else:
                checked_folders.add(ref)
        for gi in checked_folders:
            _, child_indices = folder_groups[gi]
            checked_entries.update(child_indices)

        chosen = [entries[i] for i in sorted(checked_entries)]
        _log("{} operation(s) checked.".format(len(chosen)))
        if not chosen:
            _log("Nothing checked -- nothing to export.")
            return

        out_dir = rs.BrowseForFolder(message="Choose the export folder")
        if not out_dir:
            _log("Cancelled -- no export folder chosen.")
            return

        # --- Phase 3: re-Initialize and export, re-fetching fresh objects by
        # index rather than reusing anything obtained in Phase 1. ---
        MecSoftCAM.API.Initialize()
        try:
            MecSoftCAM.API.SetActiveModule(ModuleType.MILL)

            if USE_ACTIVE_POSTPROCESSOR:
                pp_ok = MOpManager.SetPostProcessor(POSTPROCESSOR_PATH)
                _log("MOpManager.SetPostProcessor({!r}) returned {}".format(POSTPROCESSOR_PATH, pp_ok))

            exported, failed = [], []
            active_setup_idx = None  # tracks which setup_idx SetActiveSetup() was last called for
            for setup_idx, mop_path, label in chosen:
                setup = MOpManager.GetMOpSetupByIndex(setup_idx)
                mop = _resolve_mop(setup, mop_path)

                # Safety re-check right before posting: state could have
                # changed since collection (e.g. the part was edited between
                # building the checklist and this export running).
                is_suppressed, is_dirty = _check_suppressed_dirty(mop)
                if is_suppressed or is_dirty:
                    reason = "suppressed" if is_suppressed else "dirty"
                    _log("Skipping {} -- now {} (was clean at collection time)".format(label, reason))
                    failed.append((label, "(skipped: {})".format(reason)))
                    continue

                # Individual export: post THIS MOp alone, not its whole
                # setup, so each operation lands in its own file.
                filename = _safe_filename(mop.GetName(), "mop_{}".format(len(exported) + len(failed) + 1)) + ".nc"
                out_path = os.path.join(out_dir, filename)

                # Make this MOp's parent setup, and its own tool, the API's
                # active context before posting (only call SetActiveSetup()
                # when the setup actually changes -- it's session-level
                # state, not per-MOp).
                if setup_idx != active_setup_idx:
                    MOpManager.SetActiveSetup(setup)
                    active_setup_idx = setup_idx
                mop_tool = mop.GetMOpTool()
                if mop_tool is not None:
                    ToolManager.SetActiveTool(mop_tool)

                _log("Posting {} -> {} ...".format(label, out_path))
                if USE_ACTIVE_POSTPROCESSOR:
                    ok = MOpManager.PostProcessMOp(out_path, mop)
                else:
                    ok = MOpManager.PostProcessMOp(out_path, POSTPROCESSOR, mop)

                (exported if ok else failed).append((label, out_path))

            _log("Exported {} operation(s):".format(len(exported)))
            for label, path in exported:
                _log("  OK   {} -> {}".format(label, path))
            if failed:
                _log("Failed {} operation(s):".format(len(failed)))
                for label, path in failed:
                    _log("  FAIL {} -> {}".format(label, path))
        finally:
            MecSoftCAM.API.Uninitialize()

        _log("=== Run finished {} ===".format(datetime.datetime.now().isoformat()))
    finally:
        if _log_file is not None:
            _log_file.close()


if __name__ == "__main__":
    export_selected_mops()
