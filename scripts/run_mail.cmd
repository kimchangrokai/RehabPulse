@echo off
rem RehabPulse 프로젝트 메일·점검 (Windows 작업 스케줄러용)
chcp 65001 >nul
cd /d "%~dp0.."
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m rehabpulse mail %* >> "logs\scheduler.log" 2>&1
