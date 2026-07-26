<#
Automated outer retry-and-resume driver for rhinocam_export_selected_mops.py.

WHY THIS EXISTS: the RhinoCAM 2021 API SDK has proven, through extensive
manual testing, to crash the entire Rhino.exe process non-deterministically
on essentially any live GetName()/Post() call -- not tied to any specific
operation, timing, or call ordering (see the script's own docstring/inline
DIAGNOSTIC comments for the full history). A crash can never be caught or
retried from *inside* the crashing process, so the only retry loop that can
actually work lives out here: relaunch Rhino, let the script resume from its
own checkpoint, repeat until the checkpoint shows everything accounted for.

This runs the script in HEADLESS mode (RHINOCAM_EXPORT_HEADLESS=1), which
auto-selects every collected operation and skips the CheckListBox/
BrowseForFolder dialogs -- required for unattended looping, since a human
would otherwise have to click through two dialogs on every single retry.
Output lands in HEADLESS_OUTPUT_DIR (scripts/headless_test_output), same as
all the interactive/manual runs so far -- NOT a real production export
destination. Do not point this at real output without reviewing the script's
HEADLESS section first.

Usage:
    powershell -ExecutionPolicy Bypass -File run_rhinocam_export_auto_retry.ps1 `
        -DocPath "G:\...\Fingerboards-2026-v102.3dm" `
        -MaxAttempts 20 -WaitTimeoutSeconds 180
#>

param(
    [Parameter(Mandatory=$true)][string]$DocPath,
    [int]$MaxAttempts = 20,
    [int]$WaitTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RhinoExe = "C:\Program Files\Rhino 7\System\Rhino.exe"
$ScriptPath = Join-Path $ScriptDir "rhinocam_export_selected_mops.py"
$CheckpointPath = Join-Path $ScriptDir "rhinocam_export_checkpoint.json"

function Get-CheckpointCounts {
    if (-not (Test-Path $CheckpointPath)) {
        return @{ CollectedOk = 0; Exported = 0; Total = 0 }
    }
    try {
        $ckpt = Get-Content $CheckpointPath -Raw | ConvertFrom-Json
    } catch {
        Write-Output "  (checkpoint unreadable this check: $_)"
        return @{ CollectedOk = 0; Exported = 0; Total = 0 }
    }
    $collectedOk = 0
    foreach ($prop in $ckpt.collected.PSObject.Properties) {
        if ($prop.Value.ok -eq $true) { $collectedOk++ }
    }
    $exported = ($ckpt.exported.PSObject.Properties | Measure-Object).Count
    return @{ CollectedOk = $collectedOk; Exported = $exported; Total = ($ckpt.collected.PSObject.Properties | Measure-Object).Count }
}

$env:RHINOCAM_EXPORT_HEADLESS = "1"
$docArg = '"' + $DocPath + '"'
$runscriptArg = '/runscript="-_RunPythonScript ""' + $ScriptPath + '"""'

for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    $counts = Get-CheckpointCounts
    if ($counts.Total -gt 0 -and $counts.Exported -ge $counts.CollectedOk) {
        Write-Output "All $($counts.CollectedOk) collected operation(s) already have export results recorded -- done."
        break
    }

    Write-Output "=== Attempt $attempt/$MaxAttempts -- collected_ok=$($counts.CollectedOk) exported=$($counts.Exported) ==="

    $before = @(Get-CimInstance Win32_Process -Filter "Name='Rhino.exe'" | Select-Object -ExpandProperty ProcessId)
    Start-Process -FilePath $RhinoExe -ArgumentList @($docArg, "/nosplash", $runscriptArg)

    $newProcPid = $null
    $waited = 0
    while ($waited -lt 15 -and -not $newProcPid) {
        Start-Sleep -Seconds 1
        $waited++
        $candidates = @(Get-CimInstance Win32_Process -Filter "Name='Rhino.exe'" | Where-Object { $before -notcontains $_.ProcessId })
        if ($candidates.Count -gt 0) { $newProcPid = $candidates[0].ProcessId }
    }

    if (-not $newProcPid) {
        Write-Output "  WARNING: no new Rhino process detected -- skipping this attempt."
        continue
    }

    $proc = Get-Process -Id $newProcPid -ErrorAction SilentlyContinue
    if ($proc) {
        $exited = $proc.WaitForExit($WaitTimeoutSeconds * 1000)
        if (-not $exited) {
            Write-Output "  Rhino (PID $newProcPid) did not exit within ${WaitTimeoutSeconds}s -- forcing close."
            Stop-Process -Id $newProcPid -Force -ErrorAction SilentlyContinue
        } else {
            Write-Output "  Rhino (PID $newProcPid) exited on its own (crash or clean finish)."
        }
    }

    Start-Sleep -Seconds 2
    $counts = Get-CheckpointCounts
    Write-Output "  after attempt: collected_ok=$($counts.CollectedOk) exported=$($counts.Exported)"
}

$final = Get-CheckpointCounts
Write-Output ""
Write-Output "=== Final: collected_ok=$($final.CollectedOk) exported=$($final.Exported) ==="
if ($final.Total -gt 0 -and $final.Exported -ge $final.CollectedOk) {
    Write-Output "COMPLETE."
} else {
    Write-Output "NOT complete after $MaxAttempts attempt(s) -- re-run this script to keep going (it resumes from the same checkpoint)."
}
