# Compass parameter sweep — measured, not argued

BRIEF-SWEEP, executed 2026-10-21 with `python3 sweep.py --trials 24`
(48 cells x 24 seeded trials x 10 simulated minutes = 1152 trials,
~480 heading readings per cell; rerun is byte-identical — the CSV is
deterministic). Suite state at sweep time: 58 tests green.

The grid below is the PRE-FIX measurement (prior covering multipath
only); the post-fix re-run with the fix BRIEF-COMPASS-FIX prescribed is
in [Post-fix](#post-fix-brief-compass-fix) below.

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

---

## Post-fix (BRIEF-COMPASS-FIX)

Executed 2026-10-21, same protocol and same seeds (1000-1023, 24 trials
per cell, deterministic). Suite state: 60 tests green (the two new
regression tests pin the coverage property at rho = 0.6, 15 m, 5 s).

### What changed in sim/compass.py

1. **Prior at the full quasi-constant scale** (the brief's prescription,
   ~2.24x the old value at the 4:4:1 split): `const_bias_prior_m` now
   covers the per-node bias OU and the multipath OU together — over any
   window shorter than their taus they are one unidentifiable per-node
   offset.  The sweep passes `sqrt(bias^2 + mult^2)`; `run_trial`'s
   correlated preset carries `sqrt(0.8^2 + 0.4^2) ~ 0.89 m` (was 0.4).
2. **Const floor from the estimator's own sensitivity** instead of the
   `sqrt(2)/sqrt(sum lever^2)` hand factor: the 2-D weighted-Procrustes
   linearization gives `d(yaw)/d(offset_i) = w_i r_i / sum_j(w_j r_j^2)`
   with `r_i = sqrt(x_i^2+y_i^2)`, accumulated (unsigned coefficients
   add) across the window's epochs.  Measured honest scale factor
   0.80-0.97 across baselines (the athwartships spread dilutes yaw
   sensitivity at short baselines); the old hand factor was 1.414
   everywhere.
3. **White floor from per-fix coefficient accounting**: each epoch
   contributes `(fix -> yaw)` coefficients through the prediction
   weights (`_predict`'s effective fix weights, signed — extrapolation
   gives old fixes negative weight), and a fix shared by several
   epochs' tracks accumulates its coefficients across those epochs
   BEFORE squaring.  The old distinct-fix sum treated shared fixes as
   independent information and understated the white term by
   1.1-1.7x depending on fix interval (worst at 5 s).  Per-epoch the
   accounting is exact (measured/predicted epoch sd = 1.006).
4. **cold_infl 1.6 -> 1.1**: with the quasi-const term carried by the
   prior, the inflation is only a guard band for the white model's
   second-order gaps (measured residual ~1.0-1.1x), never a substitute
   for the missing prior — 1.6 had been accidentally covering part of
   the bias wherever the white floor was fat (the pre-fix "accidental
   passes" at 30 s).  Cold start still ends only when the wander
   estimate wakes (4 windows = 40 min of history), as before.

### Post-fix table

| rho | baseline m | interval s | err med (deg) | err p90 (deg) | final sigma (deg) | cov95 | honest |
|---:|---:|---:|---:|---:|---:|---:|:--|
| 0.0 | 5 | 1 | 0.79 | 2.34 | 0.81 | 98% | yes |
| 0.0 | 5 | 5 | 1.84 | 4.47 | 1.65 | 96% | yes |
| 0.0 | 5 | 30 | 3.07 | 11.74 | 3.74 | 94% | yes |
| 0.0 | 10 | 1 | 0.46 | 1.29 | 0.45 | 98% | yes |
| 0.0 | 10 | 5 | 1.14 | 2.71 | 0.92 | 95% | yes |
| 0.0 | 10 | 30 | 1.60 | 5.82 | 2.09 | 98% | yes |
| 0.0 | 15 | 1 | 0.30 | 0.84 | 0.31 | 98% | yes |
| 0.0 | 15 | 5 | 0.76 | 1.86 | 0.63 | 95% | yes |
| 0.0 | 15 | 30 | 1.13 | 3.82 | 1.42 | 99% | yes |
| 0.0 | 25 | 1 | 0.18 | 0.53 | 0.19 | 99% | yes |
| 0.0 | 25 | 5 | 0.46 | 1.16 | 0.38 | 94% | yes |
| 0.0 | 25 | 30 | 0.70 | 2.38 | 0.87 | 98% | yes |
| 0.3 | 5 | 1 | 4.37 | 11.73 | 6.08 | 91% | yes |
| 0.3 | 5 | 5 | 5.03 | 11.87 | 6.24 | 93% | yes |
| 0.3 | 5 | 30 | 7.25 | 14.32 | 7.10 | 98% | yes |
| 0.3 | 10 | 1 | 2.83 | 5.99 | 3.40 | 94% | yes |
| 0.3 | 10 | 5 | 3.10 | 5.88 | 3.49 | 96% | yes |
| 0.3 | 10 | 30 | 3.79 | 8.02 | 3.96 | 97% | yes |
| 0.3 | 15 | 1 | 2.03 | 3.92 | 2.32 | 95% | yes |
| 0.3 | 15 | 5 | 2.26 | 4.10 | 2.38 | 96% | yes |
| 0.3 | 15 | 30 | 2.58 | 5.49 | 2.71 | 97% | yes |
| 0.3 | 25 | 1 | 1.29 | 2.45 | 1.41 | 96% | yes |
| 0.3 | 25 | 5 | 1.42 | 2.52 | 1.45 | 96% | yes |
| 0.3 | 25 | 30 | 1.58 | 3.34 | 1.64 | 97% | yes |
| 0.6 | 5 | 1 | 6.24 | 15.64 | 8.56 | 92% | yes |
| 0.6 | 5 | 5 | 6.63 | 16.81 | 8.67 | 92% | yes |
| 0.6 | 5 | 30 | 8.35 | 17.16 | 9.32 | 99% | yes |
| 0.6 | 10 | 1 | 3.93 | 8.42 | 4.78 | 95% | yes |
| 0.6 | 10 | 5 | 4.08 | 8.44 | 4.84 | 95% | yes |
| 0.6 | 10 | 30 | 5.01 | 9.54 | 5.20 | 97% | yes |
| 0.6 | 15 | 1 | 2.86 | 5.60 | 3.26 | 96% | yes |
| 0.6 | 15 | 5 | 2.90 | 5.50 | 3.30 | 95% | yes |
| 0.6 | 15 | 30 | 3.37 | 6.58 | 3.55 | 96% | yes |
| 0.6 | 25 | 1 | 1.79 | 3.41 | 1.98 | 96% | yes |
| 0.6 | 25 | 5 | 1.82 | 3.41 | 2.01 | 95% | yes |
| 0.6 | 25 | 30 | 2.07 | 4.02 | 2.16 | 96% | yes |
| 0.9 | 5 | 1 | 7.33 | 19.28 | 10.47 | 92% | yes |
| 0.9 | 5 | 5 | 7.38 | 20.26 | 10.55 | 93% | yes |
| 0.9 | 5 | 30 | 8.76 | 18.66 | 11.10 | 97% | yes |
| 0.9 | 10 | 1 | 4.59 | 10.41 | 5.85 | 95% | yes |
| 0.9 | 10 | 5 | 4.67 | 10.29 | 5.89 | 96% | yes |
| 0.9 | 10 | 30 | 5.67 | 11.00 | 6.20 | 98% | yes |
| 0.9 | 15 | 1 | 3.39 | 7.03 | 3.99 | 96% | yes |
| 0.9 | 15 | 5 | 3.46 | 6.84 | 4.02 | 95% | yes |
| 0.9 | 15 | 30 | 4.01 | 7.59 | 4.23 | 97% | yes |
| 0.9 | 25 | 1 | 2.19 | 4.10 | 2.42 | 96% | yes |
| 0.9 | 25 | 5 | 2.16 | 4.15 | 2.44 | 95% | yes |
| 0.9 | 25 | 30 | 2.44 | 4.63 | 2.57 | 96% | yes |

(Error medians/p90 are unchanged from the pre-fix table — the estimator
itself did not move, only the honesty of its reported sigma.)

### Before/after coverage (pooled, same seeds)

| rho | before (12 cells) | after (12 cells) | brief's bar |
|---:|---|---|---|
| 0.0 | 98-100 % | 93.8-98.5 % | no cell > 99.5 % (max now 98.5) |
| 0.3 | 76-99 % | 91.3-97.7 % | ~nominal 93-97 % |
| 0.6 | 71-98 % | 92.1-99.4 % | ~nominal 93-97 % |
| 0.9 | 69-96 % | 91.7-97.7 % | ~nominal 93-97 % |

The brief's regression cell (rho = 0.6, 15 m, 5 s): coverage **79 % ->
95.0 %**, final sigma 2.22 -> 3.30 deg against a p90 of 5.50 (the old
report was 66 % of the p90/1.645 error-sd estimate; the new one is
99 %).  Across the previously broken 1-5 s cells at rho >= 0.3
(coverage 71-91 %), every cell now reads 91-96 %.

### Honesty audit of the outliers

With ~480 heavily window-correlated readings per cell the binomial se
is ~1.5 %, so the fixed 24-seed table wobbles around the true means.
Re-running the out-of-band cells with 96 seeds (deterministic,
seeds 1000-1095) gives their converged values:

- rho = 0, 1 s / 30 s cells read 97.9-98.5 % on the protocol seeds;
  converged 95.7-96.8 % (in band).  The 5 s cells read 94-96 %.
- rho >= 0.3, 5 m baseline at 1-5 s read 91.3-92.5 %; converged
  93.4-95.2 % (in band).
- 30 s cells at rho >= 0.3 read up to 99.4 %; converged 97.0-97.7 % —
  systematically ~0.5-0.7 above the band top.  Cause: the protocol
  holds every node's REPORTED fix sigma at 1.5 m while the true white
  component is `1.5*sqrt(1-rho)`, so at rho > 0 the white floor carries
  the node's total error scale as if it were white — conservative by
  construction (a receiver cannot report the white/correlated split of
  its own error), bounded, and it never approaches the 99.5 % absurdity
  bar.  Not tuned away: shaving it would mean teaching the compass a
  split it cannot know.

### Reproduce

```sh
cd sim && python3 sweep.py --trials 24   # -> sweep.csv + post-fix table (~60 s)
```
