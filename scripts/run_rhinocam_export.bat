@echo off
REM Launches Rhino with the Fingerboards document open and immediately runs
REM rhinocam_export_selected_mops.py via Rhino's scripted (dash-prefixed)
REM RunPythonScript command -- the dash is what avoids Rhino popping up its
REM own "choose a script file" dialog instead of running the path directly.
REM
REM Written as a .bat (not .ps1) on purpose: Rhino's documented /runscript=
REM quoting convention (doubled quotes around the embedded path) is a
REM cmd.exe convention. PowerShell re-quotes native-exe arguments in its own
REM way when you use "&" or Start-Process, which can silently break this
REM exact doubled-quote pattern. A .bat file's contents are plain text that
REM cmd.exe reads and runs with no re-quoting layer in between, so it's the
REM most reliable way to reproduce McNeel's documented syntax exactly.
REM Still fine to launch from PowerShell: & .\scripts\run_rhinocam_export.bat

"C:\Program Files\Rhino 7\System\Rhino.exe" "G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy Standard Builds\Fingerboard\Fingerboards-2026-v102.3dm" /nosplash /runscript="-_RunPythonScript ""G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\PycharmProjects\CC2\scripts\rhinocam_export_selected_mops.py"""
