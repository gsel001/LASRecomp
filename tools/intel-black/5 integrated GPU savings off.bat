@echo off
rem Black picture test (Intel, issues #8 and #357): 5 integrated GPU savings off
cd /d "%~dp0"
set LARECOMP_VK_LEAN_USAGE=0
set LARECOMP_VK_SMAA_STENCIL=0
set LARECOMP_NO_FRAME_CLEAR=0
start "" "%~dp0lasrecomp.exe"
