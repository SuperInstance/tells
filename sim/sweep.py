#!/usr/bin/env python3
"""tells compass parameter sweep (BRIEF-SWEEP).

The simulator is green; this measures, on the fast path (fixes flow
straight into the fusion -- radio loss is measured elsewhere):

  baseline      5, 10, 15, 25 m  (bow/stern pairs at +/-B/2, midships 0;
                                  the athwartships and vertical offsets of
                                  DEFAULT_LAYOUT are kept as-is)
  fix interval  1, 5, 30 s       (per-node hashed slots, as designed)
  rho           0.0, 0.3, 0.6, 0.9  (correlated-error fraction)

sigma_fix is held at 1.5 m per axis in every cell; rho only splits that
budget between white and time-correlated error, in the same proportions
as the ErrorModel.correlated preset (common : per-node bias : per-node
multipath = 4 : 4 : 1 in variance; taus 1800/1800/14400 s):

    sigma_white            = 1.5 * sqrt(1 - rho)
    common_sigma=bias_sigma= 1.5 * sqrt(rho) * 2/3
    mult_sigma             = 1.5 * sqrt(rho) / 3

The compass carries const_bias_prior_m = mult_sigma, the codebase's own
convention (run_trial's correlated preset carries 0.4 m against a 0.4 m
multipath): the install-time prior covers the multipath constant; the
per-node bias OU is supposed to be caught by the measured-wander term,
which needs four windows of history before it exists at all.

Each cell runs N seeded trials (default 24) of 10 simulated minutes,
boat static at 42 deg, compass at design defaults (30 s epochs, 600 s
window).  Per trial we keep every epoch's |heading error| and 95 %-interval
hit; per cell the table reports pooled median/p90 error, the median of
the trials' final reported sigma, and pooled coverage.  Honesty verdict:
coverage >= 0.90 (nominal 0.95; ~480 readings per cell put the binomial
se near 1.4 %).

Raw per-trial rows -> sweep.csv; aggregated table -> stdout (markdown).

Usage: python3 sweep.py [--trials 24] [--csv sweep.csv] [--smoke]
"""

import argparse
import csv
import math
import statistics
import sys
import time

from compass import (DEFAULT_LAYOUT, BoatTruth, Compass, ErrorModel,
                     GPSPayload, wrap180)
from world import World

SIGMA_FIX = 1.5
DURATION = 600.0
T95 = 1.959964
EPOCH_S = 30.0
BASELINES = (5.0, 10.0, 15.0, 25.0)
INTERVALS = (1.0, 5.0, 30.0)
RHOS = (0.0, 0.3, 0.6, 0.9)
HONEST_MIN = 0.90


def layout_for(baseline):
    """DEFAULT_LAYOUT (a 15 m baseline) rescaled fore-aft to `baseline`."""
    return {nid: (x * baseline / 15.0, y, z)
            for nid, (x, y, z) in DEFAULT_LAYOUT.items()}


def p90(xs):
    if not xs:
        return float("nan")
    if len(xs) < 2:
        return xs[0]
    return statistics.quantiles(xs, n=10, method="inclusive")[8]


def run_sweep_trial(seed, baseline, interval, rho, duration=DURATION):
    """One seeded 10-minute cell trial on the fast path (run_trial's
    skeleton, parameterized in layout, fix interval, and rho)."""
    world = World(seed)
    layout = layout_for(baseline)
    truth = BoatTruth(layout, heading_deg=42.0)
    sigma_white = SIGMA_FIX * math.sqrt(1.0 - rho)
    common = bias = SIGMA_FIX * math.sqrt(rho) * (2.0 / 3.0)
    mult = SIGMA_FIX * math.sqrt(rho) / 3.0
    errors = ErrorModel(world, sigma_white=sigma_white,
                        common_sigma=common, common_tau=1800.0,
                        bias_sigma=bias, bias_tau=1800.0,
                        mult_sigma=mult, mult_tau=14400.0)
    compass = Compass(layout, const_bias_prior_m=mult)
    for nid in layout:
        GPSPayload(nid, truth, errors, world, sink=compass.ingest,
                   interval=interval)
    readings = []
    truth_log = []

    def _epoch_tick():
        t = world.now
        compass.fuse(t)
        r = compass.report(t)
        if r is not None:
            readings.append(r)
            truth_log.append((t, truth.heading(t)))
        world.schedule(EPOCH_S, _epoch_tick)

    world.schedule(EPOCH_S, _epoch_tick)
    world.run(duration)
    errs = [abs(wrap180(r.heading - psi))
            for r, (_t, psi) in zip(readings, truth_log)]
    hits = [e <= T95 * r.sigma for e, r in zip(errs, readings)]
    return {
        "n_readings": len(readings),
        "err_median": statistics.median(errs) if errs else float("nan"),
        "err_p90": p90(errs),
        "err_final": errs[-1] if errs else float("nan"),
        "sigma_final": readings[-1].sigma if readings else float("nan"),
        "sigma_median": (statistics.median([r.sigma for r in readings])
                         if readings else float("nan")),
        "errs": errs,
        "hits": hits,
    }


def aggregate(trials):
    errs = [e for tr in trials for e in tr["errs"]]
    hits = [h for tr in trials for h in tr["hits"]]
    return {
        "n": len(trials),
        "readings": len(errs),
        "err_median": statistics.median(errs),
        "err_p90": p90(errs),
        "sigma_final": statistics.median([tr["sigma_final"] for tr in trials]),
        "coverage": sum(hits) / len(hits) if hits else 0.0,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trials", type=int, default=24,
                    help="seeded trials per cell (brief demands >= 20)")
    ap.add_argument("--csv", default="sweep.csv", help="raw per-trial CSV")
    ap.add_argument("--smoke", action="store_true",
                    help="tiny grid (2 baselines x 2 intervals x 2 rhos, "
                         "2 trials) for a quick pace check")
    args = ap.parse_args()

    baselines = (5.0, 25.0) if args.smoke else BASELINES
    intervals = (1.0, 30.0) if args.smoke else INTERVALS
    rhos = (0.0, 0.9) if args.smoke else RHOS
    n_trials = 2 if args.smoke else args.trials
    seeds = [1000 + i for i in range(n_trials)]

    rows = []
    cells = []
    t0 = time.time()
    n_cells = len(baselines) * len(intervals) * len(rhos)
    k = 0
    for rho in rhos:
        for baseline in baselines:
            for interval in intervals:
                k += 1
                tc0 = time.time()
                trials = [run_sweep_trial(seed, baseline, interval, rho)
                          for seed in seeds]
                for seed, tr in zip(seeds, trials):
                    rows.append({"baseline_m": baseline, "interval_s": interval,
                                 "rho": rho, "seed": seed,
                                 "n_readings": tr["n_readings"],
                                 "err_median_deg": tr["err_median"],
                                 "err_p90_deg": tr["err_p90"],
                                 "err_final_deg": tr["err_final"],
                                 "sigma_final_deg": tr["sigma_final"],
                                 "sigma_median_deg": tr["sigma_median"],
                                 "coverage95": sum(tr["hits"]) / len(tr["hits"])
                                 if tr["hits"] else 0.0})
                cell = {"baseline": baseline, "interval": interval, "rho": rho}
                cell.update(aggregate(trials))
                cells.append(cell)
                print(f"cell {k:2d}/{n_cells}  B={baseline:4.0f}  int={interval:4.0f}s"
                      f"  rho={rho:.1f}  med {cell['err_median']:5.2f}  "
                      f"p90 {cell['err_p90']:5.2f}  sigma {cell['sigma_final']:5.2f}"
                      f"  cov {cell['coverage'] * 100:5.1f}%  "
                      f"[{time.time() - tc0:5.1f}s]", flush=True)

    with open(args.csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\n=== aggregated (rho | baseline m | interval s | err med deg | "
          f"err p90 deg | final sigma deg | coverage | honest) ===")
    print("| rho | baseline m | interval s | err med (deg) | err p90 (deg) "
          "| final sigma (deg) | cov95 | honest |")
    print("|---:|---:|---:|---:|---:|---:|---:|:--|")
    for c in cells:
        honest = "yes" if c["coverage"] >= HONEST_MIN else "NO"
        print(f"| {c['rho']:.1f} | {c['baseline']:.0f} | {c['interval']:.0f} "
              f"| {c['err_median']:.2f} | {c['err_p90']:.2f} "
              f"| {c['sigma_final']:.2f} | {c['coverage'] * 100:.0f}% "
              f"| {honest} |")
    print(f"\n{len(rows)} trials in {time.time() - t0:.0f} s -> {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
