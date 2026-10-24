@echo off
rem Black picture test (Intel, issues #8 and #357): 3 simple descriptor sets
cd /d "%~dp0"
set LARECOMP_VK_NO_SET_REUSE=1
set LARECOMP_VK_NO_SET_BATCH=1
set LARECOMP_VK_NO_SET_RECYCLE=1
start "" "%~dp0lasrecomp.exe"
