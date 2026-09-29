@echo off
chcp 65001 >nul
title MuseFolders
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1"
if errorlevel 1 (
  echo.
  echo MuseFolders could not start. Please read the message above.
  pause
)
