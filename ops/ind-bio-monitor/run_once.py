#!/usr/bin/env python3
from ind_monitor.config import load_settings
from ind_monitor.monitor import run_check

if __name__ == "__main__":
    raise SystemExit(run_check(load_settings()))
