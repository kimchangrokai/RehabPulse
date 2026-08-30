@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist logs mkdir logs
.venv\Scripts\python.exe -m rehabpulse sync >> logs\scheduler.log 2>&1
