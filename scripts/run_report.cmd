@echo off
rem RehabPulse 현황 보고서 메일
chcp 65001 >nul
cd /d "%~dp0.."
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m rehabpulse report --email %* >> "logs\scheduler.log" 2>&1
