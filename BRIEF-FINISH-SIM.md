# Finish brief — ZCode seat: tells simulator, last mile
Your previous build run was cut off by its timeout mid-repair. Current state
(verified by Muse): sim/ modules + tests exist; suite = 58 tests, 2 FAILING:
  1. test_compass.TestCorrelatedRegime.test_reported_sigma_plateaus_instead_of_shrinking
  2. test_compass.TestGeometryAndGaps.test_radio_loss_and_latency_leave_gaps_not_garbage
and run_sim.py + sim/README.md are missing. BRIEF-BUILD.md is uncommitted-modified;
some sim files are uncommitted.

Tasks:
1. Fix both failures in the IMPLEMENTATION (compass fusion / radio delivery
   semantics). The reported sigma must plateau under correlated error — an
   overconfident compass is the one failure this project must never ship.
   Radio loss/latency must surface as gaps in the fix stream, never as
   garbage values. If you believe a test itself is wrong, say so explicitly
   in your summary and justify; do not quietly weaken a test.
2. Add run_sim.py per BRIEF-BUILD.md: 6 GPS nodes on a 15 m baseline,
   sigma=1.5 m, BOTH noise regimes, printing heading error and reported
   sigma over simulated time.
3. Add sim/README.md (how to run tests + demo, what the numbers mean).
4. Full suite green, small commits, print a summary with the measured
   compass accuracy in each regime.
Work in --mode yolo (as invoked). Write only inside ~/tells/.
