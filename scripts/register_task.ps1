# register_task.ps1 — Windows 작업 스케줄러에 RehabPulse Daily Sync 등록
# 실행: powershell -ExecutionPolicy Bypass -File scripts/register_task.ps1

param(
    [string]$TaskTime = "09:00"
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ScriptPath = Join-Path $ProjectRoot "scripts\run_sync.cmd"

# 기존 작업 제거 (있으면)
Unregister-ScheduledTask -TaskName "RehabPulse Daily Sync" -Confirm:$false -ErrorAction SilentlyContinue

# 새 작업 등록
$Action = New-ScheduledTaskAction -Execute $ScriptPath -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Daily -At $TaskTime
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName "RehabPulse Daily Sync" `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "RehabPulse 개인회생 인가 감시기 - 평일 조회"

Write-Host "✅ 'RehabPulse Daily Sync' 등록 완료 (매일 $TaskTime)"
Write-Host "   스크립트: $ScriptPath"
