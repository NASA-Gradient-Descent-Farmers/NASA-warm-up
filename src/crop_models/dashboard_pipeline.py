"""Regenerate everything the dashboard reads, in the right order, with one command.

    python -m src.crop_models.dashboard_pipeline              # WOFOST runs + SIAP + planner + export (~35 min)
    python -m src.crop_models.dashboard_pipeline --export     # only re-export from the outputs already in data/
    python -m src.crop_models.dashboard_pipeline --check      # only check the committed JSON against data/

Order (each step needs the ones before it):
1. Default-parameter scenario suite -> data/rotations/ (its baseline weather feeds step 2).
2. SIAP Texcoco yields and prices -> data/observations/ (downloaded once, then cached).
3. In parallel, both needing SIAP prices:
   a. NSGA grid and fronts -> data/nsga/ (calibrated, then default).
   b. Calibrated scenario suite -> data/rotations_calibrated/.
4. Export -> dashboard/public/data/ and the dashboard's test fixtures, then check them.

Needs `pip install -r requirements.txt` and internet (NASA POWER weather, SIAP). No Earthdata login is needed once
data/igbp/ and data/gldas/ hold the soil grids. Run from the repo root.
"""

import argparse
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .rotation_experiments import SCENARIOS

ROOT = Path(__file__).resolve().parents[2]


def module(name, *args):
    return [sys.executable, "-m", f"src.crop_models.{name}", *args]


DEFAULT_SCENARIOS = module("rotation_experiments", "--out-dir", "data/rotations")
SIAP = module("observed_maize")
PLANNER = [module("nsga_planner", "--build-grid", "--model", "calibrated", "--out-dir", "data/nsga/calibrated"),
           module("nsga_planner", "--model", "default", "--out-dir", "data/nsga/default")]
CALIBRATED_SCENARIOS = module("calibration", "--simulate", "--scenarios", *SCENARIOS)
EXPORT = module("dashboard_export")
CHECK = module("dashboard_export", "--check")


def run(command, label):
    """Run one step from the repo root, its output prefixed with the label; raise if it fails."""
    started = time.monotonic()
    print(f"[{label}] {' '.join(command[2:])}", flush=True)
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        if "warning" not in line.lower():
            print(f"[{label}] {line.rstrip()}", flush=True)
    if process.wait() != 0:
        raise SystemExit(f"[{label}] failed (exit {process.returncode}); later steps were not run")
    print(f"[{label}] done in {time.monotonic() - started:.0f} s", flush=True)


def run_all(commands, label):
    for command in commands:
        run(command, label)


def regenerate():
    run(DEFAULT_SCENARIOS, "1 default scenarios")
    run(SIAP, "2 SIAP")
    with ThreadPoolExecutor(2) as pool:  # independent; wait for both, surfacing the first failure
        jobs = [pool.submit(run_all, PLANNER, "3a planner"), pool.submit(run, CALIBRATED_SCENARIOS, "3b calibrated")]
        for job in jobs:
            job.result()
    run(EXPORT, "4 export")
    run(CHECK, "4 check")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--export", action="store_true", help="Only re-export from the outputs already in data/")
    mode.add_argument("--check", action="store_true", help="Only check the committed JSON against data/")
    args = parser.parse_args()
    if args.check:
        run(CHECK, "check")
    elif args.export:
        run(EXPORT, "export")
        run(CHECK, "check")
    else:
        regenerate()
    print("Dashboard data is up to date. Next: python -m unittest discover -s tests; cd dashboard && npm test")


if __name__ == "__main__":
    main()
