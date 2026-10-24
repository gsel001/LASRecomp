@echo off
rem Black picture test (Intel, issues #8 and #357): 4 full constant blocks
cd /d "%~dp0"
set LARECOMP_VK_NO_CBUF_LEAN=1
start "" "%~dp0lasrecomp.exe"
