# register_task.ps1 — Windows 작업 스케줄러에 RehabPulse 평일 09:00 동기화 등록
# 실행: powershell -ExecutionPolicy Bypass -File scripts/register_task.ps1
# 해제: schtasks /Delete /F /TN "RehabPulse Daily Sync"

param(
    [string]$TaskTime = "09:00"
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ScriptPath = Join-Path $ProjectRoot "scripts\run_sync.cmd"
$TaskName = "RehabPulse Daily Sync"

schtasks /Create /F /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST $TaskTime /TN $TaskName /TR "`"$ScriptPath`""

$task = Get-ScheduledTask -TaskName $TaskName
$task.Settings.StartWhenAvailable = $true
$task.Settings.DisallowStartIfOnBatteries = $false
$task.Settings.StopIfGoingOnBatteries = $false
Set-ScheduledTask -TaskName $TaskName -TaskPath $task.TaskPath -Settings $task.Settings | Out-Null

Write-Host "등록: $TaskName (평일 $TaskTime, 놓친 실행 보충 켜짐)"
Write-Host "  스크립트: $ScriptPath"
Write-Host "해제: schtasks /Delete /F /TN `"$TaskName`""
