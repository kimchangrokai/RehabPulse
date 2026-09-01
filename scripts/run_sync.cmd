@echo off
rem RehabPulse 프로젝트 조회 (Windows 작업 스케줄러용)
chcp 65001 >nul
cd /d "%~dp0.."
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m rehabpulse sync %* >> "logs\scheduler.log" 2>&1
