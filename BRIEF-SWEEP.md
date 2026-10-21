# Experiment brief — ZCode seat: compass parameter sweep (tells sim)
The simulator is green (58 tests). Now measure, don't argue.
Using sim/ (run from ~/tells/sim), sweep the compass design space:
- baseline: 5, 10, 15, 25 m
- fix interval: 1 s, 5 s, 30 s
- correlated-error fraction rho: 0.0, 0.3, 0.6, 0.9 (sigma_fix = 1.5 m)
- >= 20 seeded trials per cell, 10 simulated minutes each
Record per cell: median + p90 heading error (deg), final reported sigma,
and whether reported sigma honestly covered the measured error.
Write ~/tells/sim/SWEEP.md (the table + the 5 lines that matter: where is
heading good to <3 deg, where does honesty break, what dominates) and the
raw CSV beside it. Commit + push. Print a summary.
