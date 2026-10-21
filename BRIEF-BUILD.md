# Build brief — ZCode seat: tells simulator v0
Read ~/tells/DESIGN.md and ~/tells/README.md first. Build step 1 of DESIGN §6
in ~/tells/sim/ :

- Python 3, **stdlib only**, deterministic (seeded RNG), unittest-based tests.
- Modules: `node.py` (state machine: UNCLAIMED -> CLAIMED; peer table; beacon
  gossip), `radio.py` (in-process broadcast bus with latency/loss knobs),
  `fleet.py` (claim ceremony per DESIGN §3, incl. button-window requirement),
  `compass.py` (fuse asynchronous noisy GPS fixes from nodes on a baseline
  into heading + uncertainty), `run_sim.py` (demo: 6 GPS nodes on a 15 m
  baseline, sigma=1.5 m fixes, prints heading error over simulated time).
- Tests must prove: (a) leaderlessness — kill any node mid-run, mesh persists;
  (b) claim safety — unclaimed nodes ignore fleet traffic, claimed nodes
  ignore stranger claims; (c) compass — filtered heading converges to within
  a few degrees and reported uncertainty is honest vs. measured error.
- Small commits as you go. A short sim/README.md explaining how to run it.
- Print a summary when done: files, test results, measured compass accuracy.
