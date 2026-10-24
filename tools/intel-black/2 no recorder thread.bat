@echo off
rem Black picture test (Intel, issues #8 and #357): 2 no recorder thread
cd /d "%~dp0"
set LARECOMP_VK_RECORDER=0
start "" "%~dp0lasrecomp.exe"
