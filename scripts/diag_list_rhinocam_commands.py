"""
Diagnostic: list every Rhino command whose name mentions "post" or "cam",
to find out what actual Rhino command name backs RhinoCAM's interactive
"Post" action (right-click a MOp > Post). If a real Rhino command exists
for this, it can be driven via rs.Command("_-CommandName ...") from script --
a completely different code path from the mecsoftcamapi Python bindings
(mop.Post()), which has proven unable to produce real output via the API
despite the same operations posting fine through the UI.

Run via the same launch mechanism as rhinocam_export_selected_mops.py.
Writes results to diag_rhinocam_commands_log.txt next to this script.
"""
import os
import datetime

import Rhino

LOG_DIR = os.path.dirname(os.path.abspath(__file__))
log_path = os.path.join(LOG_DIR, "diag_rhinocam_commands_log_{}.txt".format(
    datetime.datetime.now().strftime("%Y%m%d_%H%M%S")))

with open(log_path, "w") as f:
    def log(msg):
        print(msg)
        f.write(msg + "\n")
        f.flush()

    log("=== Diagnostic run {} ===".format(datetime.datetime.now().isoformat()))

    try:
        all_commands = Rhino.Commands.Command.GetCommands()
    except Exception as e:
        log("ERROR calling Rhino.Commands.Command.GetCommands(): {}".format(e))
        all_commands = []

    log("Total registered commands: {}".format(len(all_commands)))

    keywords = ("post", "cam", "mop", "toolpath", "regen")
    matches = []
    for cmd in all_commands:
        try:
            english = cmd.EnglishName or ""
            local = cmd.LocalName or ""
            plugin_name = ""
            try:
                plugin = Rhino.PlugIns.PlugIn.Find(cmd.PlugInId)
                if plugin is not None:
                    plugin_name = plugin.Name
            except Exception:
                pass
            combined = (english + " " + local + " " + plugin_name).lower()
            if any(k in combined for k in keywords):
                matches.append("EnglishName={!r}  LocalName={!r}  Plugin={!r}  Id={}".format(
                    english, local, plugin_name, cmd.Id))
        except Exception as e:
            log("  (error reading a command entry: {})".format(e))

    log("Matches ({} of {} total):".format(len(matches), len(all_commands)))
    for m in matches:
        log("  " + m)

    log("=== Done ===")

print("Log written to: {}".format(log_path))
