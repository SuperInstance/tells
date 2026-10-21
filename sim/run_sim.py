#!/usr/bin/env python3
"""tells compass demo (BRIEF-BUILD + REVIEW SS4.8 addendum).

6 GPS tells on a 15 m baseline (bow/midships/stern pairs, DESIGN SS5),
sigma_fix = 1.5 m, one trial per noise regime, printing heading error
and reported sigma over simulated time:

  independent -- white noise only.  The naive model: averaging keeps
    buying ~1/sqrt(N).  Shown because the addendum demands the
    falsehood it proves be measurable, not asserted.
  correlated  -- white + common-mode OU (cancels in the differential)
    + per-node bias OU (does not cancel, does not average away) +
    per-node multipath.  The physically honest model; the compass
    floors at a few degrees and its report says so.
  lossy radio -- the correlated regime again, but the fixes cross a
    claimed fleet on a 25%-loss, 80 ms-latency bus: gaps in the fix
    stream, never garbage in the heading.

Usage: python3 run_sim.py [--seed N] [--duration S]
"""

import argparse
import math
import statistics
import sys

from compass import DEFAULT_LAYOUT, coverage95, run_trial, wrap180

T95 = 1.959964


def run_leg(title, seed, note="", **kw):
    print(f"\n=== {title} ===")
    if note:
        print(f"    {note}")
    readings, truth_log, _ = run_trial(seed, **kw)
    if not readings:
        print("    no readings produced")
        return
    print("   t(min)   err(deg)  sigma(deg)  95% interval  nodes")
    step = max(1, len(readings) // 18)
    for r, (t, psi) in zip(readings[::step], truth_log[::step]):
        err = wrap180(r.heading - psi)
        hit = "inside" if abs(err) <= T95 * r.sigma else "OUTSIDE"
        print(f"  {r.t / 60.0:7.1f}  {err:+9.3f}  {r.sigma:10.3f}  "
              f"{hit:>11s}  {r.n_nodes:d}")
    cut = readings[-1].t * 0.6
    tail = [(r, t, psi) for r, (t, psi) in zip(readings, truth_log) if t >= cut]
    errs = [wrap180(r.heading - psi) for r, _t, psi in tail]
    rms = math.sqrt(sum(e * e for e in errs) / len(errs))
    sig = statistics.mean(r.sigma for r, _, _ in tail)
    cov = coverage95(readings, truth_log, after_s=cut)
    gaps = sum(1 for r, _, _ in tail if r.n_nodes < len(DEFAULT_LAYOUT))
    print(f"  steady-state (last 40%): rms error {rms:.2f} deg, "
          f"mean reported sigma {sig:.2f} deg, "
          f"95% interval covered truth {cov * 100.0:.0f}% of readings")
    if gaps:
        full = len(tail)
        print(f"  fleet thinned by loss: {gaps}/{full} readings fused on a "
              f"shorter baseline (gaps, not garbage)")
    return rms, sig, cov


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--duration", type=float, default=5400.0)
    args = ap.parse_args()

    print("tells compass-line simulator -- 6 GPS nodes, 15 m baseline, "
          "sigma_fix = 1.5 m")
    print(f"seed {args.seed}, duration {args.duration / 3600.0:.1f} h, "
          f"true heading 42.0 deg (static, at anchor)")

    results = {}
    results["independent"] = run_leg(
        "regime 1/3: independent (white noise only -- the naive model)",
        args.seed, regime="independent", duration=args.duration,
        note="what an iid-only sim wants to see: 1/sqrt(N) keeps paying")
    results["correlated"] = run_leg(
        "regime 2/3: correlated (white + common OU + per-node bias OU + multipath)",
        args.seed, regime="correlated", duration=args.duration,
        note="the honest model: common-mode cancels, per-node bias floors")
    results["lossy radio"] = run_leg(
        "regime 3/3: correlated over a lossy radio (25% loss, 80 ms latency)",
        args.seed, regime="correlated", duration=args.duration,
        radioed=True, loss=0.25, latency=0.080,
        note="claim ceremony + MAC'd telemetry on the ESP-NOW-shaped bus")

    print("\n=== accuracy by regime (steady-state, last 40% of run) ===")
    for name, res in results.items():
        if res:
            rms, sig, cov = res
            print(f"  {name:14s} rms error {rms:5.2f} deg   reported sigma "
                  f"{sig:5.2f} deg   coverage {cov * 100:5.1f}%")
    print("\nthe point: the independent regime is a fiction -- under "
          "correlated error the compass floors at a few degrees and the "
          "reported sigma carries that floor instead of following the "
          "white-noise fantasy toward zero.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
