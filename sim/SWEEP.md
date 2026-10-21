# Compass parameter sweep — measured, not argued

BRIEF-SWEEP, executed 2026-10-21 with `python3 sweep.py --trials 24`
(48 cells x 24 seeded trials x 10 simulated minutes = 1152 trials,
~480 heading readings per cell; rerun is byte-identical — the CSV is
deterministic). Suite state at sweep time: 58 tests green.

## Method

Each cell is one (baseline, fix interval, rho) point; everything else at
design defaults (30 s fusion epochs, 600 s window, boat static at 42 deg,
fixes flow straight into the fusion — radio loss is measured elsewhere).

rho is the **correlated-error fraction** of a per-axis budget held at
sigma_fix = 1.5 m in every cell, split in the same proportions as the
`ErrorModel.correlated` preset (common : per-node bias : per-node
multipath = 4 : 4 : 1 in variance; taus 1800/1800/14400 s):

    sigma_white             = 1.5 * sqrt(1 - rho)
    common_sigma = bias_sigma = 1.5 * sqrt(rho) * 2/3
    mult_sigma              = 1.5 * sqrt(rho) / 3

The compass carries `const_bias_prior_m = mult_sigma` — the codebase's own
convention (run_trial's correlated preset carries 0.4 m against a 0.4 m
multipath): the install-time prior covers the multipath constant, and the
per-node bias OU is supposed to be caught by the measured-wander term.
Note that a 10-minute run never gives that term enough history to exist
(it needs four 600 s windows = 40 min), so every sigma below is of the
cold-start form `sqrt((1.6*white_floor)^2 + prior^2)`.

Per cell: median and p90 of |heading error| pooled over all readings,
median of the trials' final reported sigma, and coverage (fraction of
readings whose 95 % interval `±1.96*sigma` contained the true heading —
the README's calibration criterion, nominal 0.95). **honest = yes** when
pooled coverage >= 0.90 (with ~480 readings/cell the binomial se is
~1.4 %, so 0.90 is already charitable). Raw per-trial rows: `sweep.csv`.

## Table

| rho | baseline m | interval s | err med (deg) | err p90 (deg) | final sigma (deg) | cov95 | honest |
|---:|---:|---:|---:|---:|---:|---:|:--|
| 0.0 | 5 | 1 | 0.79 | 2.34 | 1.77 | 100% | yes |
| 0.0 | 5 | 5 | 1.84 | 4.47 | 2.27 | 99% | yes |
| 0.0 | 5 | 30 | 3.07 | 11.74 | 5.65 | 100% | yes |
| 0.0 | 10 | 1 | 0.46 | 1.29 | 0.89 | 100% | yes |
| 0.0 | 10 | 5 | 1.14 | 2.71 | 1.13 | 98% | yes |
| 0.0 | 10 | 30 | 1.60 | 5.82 | 2.82 | 100% | yes |
| 0.0 | 15 | 1 | 0.30 | 0.84 | 0.59 | 100% | yes |
| 0.0 | 15 | 5 | 0.76 | 1.86 | 0.76 | 98% | yes |
| 0.0 | 15 | 30 | 1.13 | 3.82 | 1.88 | 100% | yes |
| 0.0 | 25 | 1 | 0.18 | 0.53 | 0.35 | 100% | yes |
| 0.0 | 25 | 5 | 0.46 | 1.16 | 0.45 | 98% | yes |
| 0.0 | 25 | 30 | 0.70 | 2.38 | 1.13 | 100% | yes |
| 0.3 | 5 | 1 | 4.37 | 11.73 | 4.78 | 85% | NO |
| 0.3 | 5 | 5 | 5.03 | 11.87 | 4.98 | 91% | yes |
| 0.3 | 5 | 30 | 7.25 | 14.32 | 7.18 | 99% | yes |
| 0.3 | 10 | 1 | 2.83 | 5.99 | 2.39 | 77% | NO |
| 0.3 | 10 | 5 | 3.10 | 5.88 | 2.49 | 86% | NO |
| 0.3 | 10 | 30 | 3.79 | 8.02 | 3.59 | 98% | yes |
| 0.3 | 15 | 1 | 2.03 | 3.92 | 1.59 | 76% | NO |
| 0.3 | 15 | 5 | 2.26 | 4.10 | 1.66 | 85% | NO |
| 0.3 | 15 | 30 | 2.58 | 5.49 | 2.39 | 98% | yes |
| 0.3 | 25 | 1 | 1.29 | 2.45 | 0.96 | 77% | NO |
| 0.3 | 25 | 5 | 1.42 | 2.52 | 1.00 | 85% | NO |
| 0.3 | 25 | 30 | 1.58 | 3.34 | 1.44 | 97% | yes |
| 0.6 | 5 | 1 | 6.24 | 15.64 | 6.52 | 82% | NO |
| 0.6 | 5 | 5 | 6.63 | 16.81 | 6.67 | 88% | NO |
| 0.6 | 5 | 30 | 8.35 | 17.16 | 8.44 | 98% | yes |
| 0.6 | 10 | 1 | 3.93 | 8.42 | 3.26 | 72% | NO |
| 0.6 | 10 | 5 | 4.08 | 8.44 | 3.34 | 80% | NO |
| 0.6 | 10 | 30 | 5.01 | 9.54 | 4.22 | 92% | yes |
| 0.6 | 15 | 1 | 2.86 | 5.60 | 2.17 | 71% | NO |
| 0.6 | 15 | 5 | 2.90 | 5.50 | 2.22 | 79% | NO |
| 0.6 | 15 | 30 | 3.37 | 6.58 | 2.81 | 91% | yes |
| 0.6 | 25 | 1 | 1.79 | 3.41 | 1.30 | 71% | NO |
| 0.6 | 25 | 5 | 1.82 | 3.41 | 1.33 | 81% | NO |
| 0.6 | 25 | 30 | 2.07 | 4.02 | 1.69 | 91% | yes |
| 0.9 | 5 | 1 | 7.33 | 19.28 | 7.89 | 79% | NO |
| 0.9 | 5 | 5 | 7.38 | 20.26 | 8.01 | 86% | NO |
| 0.9 | 5 | 30 | 8.76 | 18.66 | 9.54 | 96% | yes |
| 0.9 | 10 | 1 | 4.59 | 10.41 | 3.94 | 71% | NO |
| 0.9 | 10 | 5 | 4.67 | 10.29 | 4.01 | 76% | NO |
| 0.9 | 10 | 30 | 5.67 | 11.00 | 4.77 | 87% | NO |
| 0.9 | 15 | 1 | 3.39 | 7.03 | 2.63 | 69% | NO |
| 0.9 | 15 | 5 | 3.46 | 6.84 | 2.67 | 75% | NO |
| 0.9 | 15 | 30 | 4.01 | 7.59 | 3.18 | 89% | NO |
| 0.9 | 25 | 1 | 2.19 | 4.10 | 1.58 | 70% | NO |
| 0.9 | 25 | 5 | 2.16 | 4.15 | 1.60 | 77% | NO |
| 0.9 | 25 | 30 | 2.44 | 4.63 | 1.91 | 88% | NO |

## The 5 lines that matter

1. **Where heading is good to <3 deg (median)**: at rho = 0, everywhere
   except the 5 m + 30 s corner (3.1 deg). At rho = 0.3 it takes >= 15 m
   at any interval (or 10 m at 1 s). At rho = 0.6 it takes 25 m, or 15 m
   at <= 5 s. At rho = 0.9 only 25 m clears it (2.2-2.4 deg). p90 < 3 deg
   exists only at rho <= 0.3 (six cells at rho = 0, one at rho = 0.3:
   25 m + 1 s).
2. **What dominates**: baseline. 5 -> 25 m cuts median error 3.4-5.5x at
   every rho and interval. Fix interval is a white-noise knob: 1 -> 30 s
   costs 3.5-3.9x at rho = 0 but only 1.1-1.2x at rho = 0.9 — once error
   is correlated, more fixes stop buying accuracy (REVIEW SS4.3's floor,
   now measured, not asserted). Cross-check: at rho = 0.9, B = 25 m the
   measured median 2.19 deg sits within 6 % of the quasi-constant
   differential model `0.674 * sqrt(2)*sigma_c/B` with
   `sigma_c = sqrt(bias^2+mult^2) = 1.06 m`.
3. **Where honesty breaks**: everywhere rho > 0 at 1 s and 5 s intervals —
   pooled coverage 71-91 % against nominal 95 %, and stricter
   final-epoch coverage 0.67-0.88. At rho = 0 the report is conservative
   everywhere (coverage 98-100 %, final-epoch 100 %).
4. **The 30 s "passes" are accidental**: at 30 s the white floor is fat
   (few fixes -> little averaging claimed) and masks the unmodeled term
   (coverage 87-99 %). At rho = 0.9 even that fails at >= 10 m. Nowhere
   that the correlated term dominates is the report actually calibrated.
5. **Root cause and fix**: over 10 minutes the bias OU (tau = 30 min) is
   quasi-constant, and the wander term meant to catch it never wakes
   (needs 40 min of history), so sigma = sqrt((1.6*white)^2 + prior^2)
   with the prior covering multipath only — half the story. Reported
   sigma lands at 49-58 % of the true error scale in every rho >= 0.3
   cell at 1-5 s. Fix: carry the prior at the full quasi-constant scale
   sqrt(bias^2 + mult^2) (~2.2x today's at the 4:4:1 split), or hold the
   cold-start inflation until 40 min of window history exists.

## Reproduce

```sh
cd sim && python3 sweep.py --trials 24   # -> sweep.csv + this table (~40 s)
```
