# register_task.ps1 — 프로젝트별 평일 조회(기본 04:00)와 메일(기본 07:00)
# 실행: powershell -ExecutionPolicy Bypass -File scripts/register_task.ps1

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SyncScript = Join-Path $ProjectRoot "scripts\run_sync.cmd"
$MailScript = Join-Path $ProjectRoot "scripts\run_mail.cmd"
$DataRoot = Join-Path $ProjectRoot "data"

function Register-WeeklyTask($TaskName, $TaskTime, $Command) {
    schtasks /Create /F /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST $TaskTime /TN $TaskName /TR $Command | Out-Null
    $task = Get-ScheduledTask -TaskName $TaskName
    $task.Settings.StartWhenAvailable = $true
    $task.Settings.DisallowStartIfOnBatteries = $false
    $task.Settings.StopIfGoingOnBatteries = $false
    Set-ScheduledTask -TaskName $TaskName -TaskPath $task.TaskPath -Settings $task.Settings | Out-Null
    Write-Host "등록: $TaskName (평일 $TaskTime)"
}

if (Test-Path $DataRoot) {
    Get-ChildItem -Path $DataRoot -Recurse -Filter *.yaml | ForEach-Object {
        $company = $_.Directory.Name
        $project = $_.BaseName
        $lookup = "04:00"
        $mail = "07:00"
        foreach ($line in Get-Content $_.FullName -Encoding UTF8) {
            if ($line -match 'lookup_time:\s*"?([0-9]{2}:[0-9]{2})') { $lookup = $Matches[1] }
            if ($line -match 'mail_time:\s*"?([0-9]{2}:[0-9]{2})') { $mail = $Matches[1] }
        }
        $syncCmd = "`"$SyncScript`" --company $company --project $project"
        $mailCmd = "`"$MailScript`" --company $company --project $project"
        Register-WeeklyTask "RehabPulse Lookup $company $project" $lookup $syncCmd
        Register-WeeklyTask "RehabPulse Mail $company $project" $mail $mailCmd
    }
} else {
    Write-Host "data/ 없음. python -m rehabpulse init 후 다시 실행하세요."
}
