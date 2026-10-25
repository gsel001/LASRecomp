#!/bin/zsh
# This launcher only requests diagnostics from an existing verified profiling session.
cd "$HOME/Developer/LASRecomp-Metal-Research/profiling" || exit 1
/usr/bin/env python3 -B hang_watch.py emergency
capture_result=$?
if (( capture_result != 0 )); then
  print "Diagnostics did not fully complete. Read the message above; existing evidence is preserved."
  read "?Press Return to close this window."
fi
exit $capture_result
