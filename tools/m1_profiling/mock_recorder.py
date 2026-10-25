#!/usr/bin/env python3
"""Synthetic test process only; never calls Instruments or the game."""
import argparse,signal,time
p=argparse.ArgumentParser();p.add_argument('--ignore-signals',action='store_true');p.add_argument('--seconds',type=float,default=30);p.add_argument('--exit',type=int,default=0);a=p.parse_args()
if a.ignore_signals:
 signal.signal(signal.SIGINT,signal.SIG_IGN);signal.signal(signal.SIGTERM,signal.SIG_IGN)
print('ready',flush=True);time.sleep(a.seconds);raise SystemExit(a.exit)
