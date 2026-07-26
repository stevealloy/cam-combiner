"""
Minimal repro: can a MopSet's contents be read back via the API?

Expects a document with one MOpSetup containing:
  - one real machining operation directly at the setup's root, AND
  - one MopSet (folder) containing at least one machining operation inside it.

Run via Rhino's Python editor (EditPythonScript > open > Run), MILL module
active, with mopset-repo.3dm open. Prints (and logs to a file next to this
script) what it finds at the setup's root level, and, for anything that
turns out to be a MopSet, what (if anything) can be read out of it.
"""
import datetime
import os

from mecsoftcamapi import *
import MecSoftCAM.Types.ModuleType as ModuleType
import MecSoftCAM.Managers.MOpManager as MOpManager

LOG_DIR = r"G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\PycharmProjects\CC2\scripts"
log_path = os.path.join(LOG_DIR, "mopset_repro_log_{}.txt".format(
    datetime.datetime.now().strftime("%Y%m%d_%H%M%S")))
_log_file = open(log_path, "w")


def log(msg):
    print(msg)
    _log_file.write(msg + "\n")
    _log_file.flush()


log("=== mopset_repro run {} ===".format(datetime.datetime.now().isoformat()))

MecSoftCAM.API.Initialize()
MecSoftCAM.API.SetActiveModule(ModuleType.MILL)

setup = MOpManager.GetMOpSetupByIndex(0)
mop_count = MOpManager.GetMOpCount(setup)
log("Setup root slot count: {}".format(mop_count))

for i in range(mop_count):
    mop = MOpManager.GetMOpByIndex(setup, i)
    if mop is None:
        continue
    type_name = type(mop).__name__
    log("Root slot #{}: type={}".format(i, type_name))

    if type_name == "MOpSetMOp":
        log("  -> this is a MopSet folder. Attempting to read its contents:")
        try:
            child_count = MOpManager.GetMOpCount(mop)
            log("     MOpManager.GetMOpCount(mop) succeeded: {} children".format(child_count))
            for j in range(child_count):
                child = MOpManager.GetMOpByIndex(mop, j)
                log("       child #{}: {}".format(
                    j, type(child).__name__ if child is not None else "None"))
        except Exception as e:
            log("     MOpManager.GetMOpCount(mop) raised: {}".format(e))
        # dir() dump, for reference -- pure reflection, calls nothing.
        members = [m for m in dir(mop) if not m.startswith("_")]
        log("     dir(mop) members: {}".format(", ".join(members)))
    else:
        try:
            log("     GetName(): {}".format(mop.GetName()))
        except Exception as e:
            log("     GetName() raised: {}".format(e))

MecSoftCAM.API.Uninitialize()
log("=== Done ===")
_log_file.close()
print("Log written to: {}".format(log_path))
