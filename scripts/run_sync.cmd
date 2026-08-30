@echo off
rem RehabPulse 무인 동기화 (Windows 작업 스케줄러용, FR-8.2)
chcp 65001 >nul
cd /d "%~dp0.."
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m rehabpulse sync >> "logs\scheduler.log" 2>&1
