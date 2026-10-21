# Brief — ZCode seat: fix the compass cold-start honesty gap (tells sim)
Your sweep (sim/SWEEP.md) found it: reported sigma lands at ~50-58% of the
true error scale whenever correlated error is present at 1-5 s fix rates,
because the quasi-frozen per-node bias is carried by neither the wander
estimate (needs ~40 min of history) nor the multipath prior, and a
10-minute run never wakes the wander term.

Implement the fix your own sweep prescribed, in sim/compass.py:
- carry the per-node bias prior at the full quasi-constant scale
  (~2.2x today's), AND/OR keep cold-start inflation until 40 minutes of
  history exists — use both if they compose honestly.
Then prove it by re-running the sweep grid (same seeds/protocol): coverage
must return to ~nominal (93-97%) across rho in {0, .3, .6, .9} WITHOUT the
rho=0 cells turning absurdly conservative (>99.5% is also a failure).
Add regression tests pinning the coverage property at rho=0.6, 15 m, 5 s.
Full suite green. Update SWEEP.md with a "post-fix" section (new table,
before/after coverage). Commit in small pieces; push will fail (gh token
dead) — leave commits local and say so. Print the before/after numbers.
