# tells simulator v0

Python 3, **stdlib only**, deterministic (seeded RNG streams — same seed
in, same trace out). It simulates the whole stack of the tells design:
button-armed claim ceremony, a leaderless ESP-NOW-shaped broadcast bus,
and the compass-line fusion of asynchronous GNSS fixes into
heading + honest uncertainty.

Governing spec: `../DESIGN.md` as amended by `../REVIEW-MCODE.md`
(the review's §1.4 claim ceremony and §4 compass math are binding; the
code comments cite the sections they implement).

## Run

```sh
cd sim
python3 -m unittest discover -v   # full suite (58 tests, ~35 s)
python3 run_sim.py                # demo: both noise regimes + a lossy radio
python3 run_sim.py --seed 42 --duration 7200
```

## Modules

| file | what it is |
|---|---|
| `world.py` | discrete-event kernel: monotone clock, callback queue, named RNG streams |
| `radio.py` | in-process broadcast bus with per-link loss / latency / jitter knobs |
| `node.py` | the tell: UNCLAIMED→CLAIMED state machine, button, peer table, telemetry |
| `fleet.py` | gateway + claim ceremony (possession + secret + freshness), stranger model |
| `compass.py` | fix generation, error model, fusion: heading + honest sigma |
| `run_sim.py` | the demo |

## What the demo's numbers mean

The demo prints, over simulated time, the signed heading error against
truth, the reported sigma (1-sigma), whether the true heading sits
inside the reported 95 % interval, and how many tells fed that reading.
Three regimes are run on the same 6-tell, 15 m baseline, sigma_fix =
1.5 m geometry:

- **independent** — white noise only. This is the model an iid-only
  simulator would use; it is kept so the falsehood it proves is
  measurable. Averaging buys ~1/√N without end (review §4.3).
- **correlated** — white + a common-mode OU term shared by all nodes
  (cancels exactly in node-to-node differencing — the design's actual
  working principle) + a per-node bias OU (does **not** cancel, does
  not average away within its correlation time) + a slower per-node
  multipath term. The compass floors at a few degrees.
- **lossy radio** — the correlated regime through a real claimed fleet
  on a 25 %-loss, 80 ms-latency bus. Loss shows up as gaps: readings on
  a shortened baseline with a wider sigma, never as garbage headings.

The **steady-state** lines summarize the last 40 % of each run: rms
error, mean reported sigma, and coverage (the fraction of readings
whose 95 % interval contained the truth). Calibration — coverage ≥
95 % — is the pass criterion, not a bare error bound (review §4.8).

The reported sigma is `sqrt(max(white-floor, measured-wander)² +
const-bias-prior²)`: the white floor is `sigma_fix / sqrt(Σ lever²)`
over the distinct fixes feeding the window (only baseline endpoints
carry yaw lever — review §4.2), the wander term is measured from the
estimator's own window-to-window scatter (Student-t inflated), and the
constant multipath component is carried as a stated install-time prior
because it is unidentifiable without a truth reference (review §4.3).
Averaging can never talk the report below the floor.

## Fusion in one paragraph

Fixes arrive asynchronously (per-node hashed slots) on each tell's own
clock. Per 30 s fusion epoch, each node's fresh track is reduced to a
least-squares motion state (position + velocity), velocity
ridge-regularized toward the at-anchor prior (a slope built from two
noisy fixes is noise, not motion), and predicted at the epoch; the
prediction variance follows from the exact effective weights. Heading
comes from a full 3-D rigid (Umeyama/Kabsch) fit over the tells'
body-frame layout, each node weighted by lever² / prediction variance,
which separates heel from yaw (review §4.4) and refuses to let the
athwartships midships pair set heading. A node whose latest fix is
staler than `max_skew_s` is a gap for that epoch. Only the heading is
time-averaged (information-weighted circular mean over the window);
raw positions are never averaged across time (review §4.7).

## Tests

The suite proves the three brief criteria and the review's additions:

- **leaderlessness** — kill any node mid-run; beacons, the claim
  ceremony under loss, and the compass (gracefully degraded) persist;
- **claim safety** — unclaimed nodes ignore fleet traffic, claimed
  nodes ignore stranger fleets and claims; the button window is
  mandatory; forged claims (right pk, wrong secret) lock out; replayed
  owner claims are refused; concurrent ceremonies cannot lock each
  other out;
- **compass** — common-mode cancels; the independent regime converges
  and is calibrated; the correlated regime floors while its report
  carries the floor; heel is separated from yaw (paired same-seed
  comparison); radio loss leaves gaps, not garbage; determinism.
