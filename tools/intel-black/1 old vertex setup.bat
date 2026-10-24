@echo off
rem Black picture test (Intel, issues #8 and #357): 1 old vertex setup
cd /d "%~dp0"
set LARECOMP_VK_DYN_VERTEX=0
start "" "%~dp0lasrecomp.exe"
