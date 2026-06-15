# Windows Task Scheduler setup for boot-durable watchdog
# Run this script as Administrator to register the watchdog as a startup task

$ErrorActionPreference = "Stop"

$ProjectRoot = "d:\diigoo\ai calls"
$TaskName = "DiigooVoiceAgentWatchdog"
$PythonExe = "python"
$WatchdogScript = Join-Path $ProjectRoot "scripts\watchdog.py"
$WorkingDir = $ProjectRoot

# Verify paths exist
if (-not (Test-Path $WatchdogScript)) {
    Write-Error "Watchdog script not found: $WatchdogScript"
    exit 1
}

if (-not (Test-Path $WorkingDir)) {
    Write-Error "Project root not found: $WorkingDir"
    exit 1
}

# Remove existing task if present
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed existing task (if any)"
} catch {
    # Ignore if task doesn't exist
}

# Create the task action
$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument $WatchdogScript `
    -WorkingDirectory $WorkingDir

# Create the trigger - run at startup and if the task fails
$Trigger = New-ScheduledTaskTrigger -AtStartup

# Settings: run with highest privileges, don't stop on idle, restart if fails
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -Priority 0

# Principal: run as SYSTEM with highest privileges
$Principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

# Register the task
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Diigoo AI Voice Agent Watchdog - keeps the LiveKit worker registered and running" `
    -Force

Write-Host "Task '$TaskName' registered successfully"
Write-Host "The watchdog will start automatically on system boot"
Write-Host ""
Write-Host "To test immediately:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "To view logs:"
Write-Host "  Get-Content '$ProjectRoot\watchdog.log' -Wait"
Write-Host "  Get-Content '$ProjectRoot\worker.log' -Wait"
Write-Host "  Get-Content '$ProjectRoot\worker.err.log' -Wait"
Write-Host ""
Write-Host "To stop the watchdog:"
Write-Host "  Stop-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
