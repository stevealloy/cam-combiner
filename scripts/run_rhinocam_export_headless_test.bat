@echo off
REM HEADLESS TESTING ONLY. Sets RHINOCAM_EXPORT_HEADLESS=1 (inherited by the
REM Rhino.exe child process below) so rhinocam_export_selected_mops.py skips
REM CheckListBox/BrowseForFolder and runs fully unattended, for reproducing
REM the non-deterministic RhinoCAM API crash across repeated automated runs.
REM Writes to a disposable scratch folder, never a real export destination.
REM Do NOT use this for a real production export -- use run_rhinocam_export.bat
REM (no headless env var) for that; it keeps the human review dialogs.

set RHINOCAM_EXPORT_HEADLESS=1
"C:\Program Files\Rhino 7\System\Rhino.exe" "G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy Standard Builds\Fingerboard\Fingerboards-2026-v102.3dm" /nosplash /runscript="-_RunPythonScript ""G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\PycharmProjects\CC2\scripts\rhinocam_export_selected_mops.py"""
