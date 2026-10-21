# Tells — gateway: the next build stage

DESIGN §8 step 2 (v0.2). Build stage 1 — the host simulator — is done
and green (60 tests). This stage turns its proven pieces into the
operator-facing gateway: a CLI that claims fleets, keeps the live
table, shows the compass readout, hands down verdicts, and records
everything the fleet-consistency monitor (DESIGN §6) will need —
without building the full monitor yet.

Governing sources: DESIGN.md v0.2 · REVIEW-MCODE.md §1.4 (ceremony),
§2.4 (gateway radio), §2.6 (star) · `sim/` (the executable ceremony +
compass) · SHEAF-NOTES.md §2 (the monitor's math, proven there) ·
TELLS-STORY-AND-DERIVATION.md (the display contract).

## 1. Shape

- **Host + radio**: a Pi-class host (or the boat's Jetson) with an
  **ESP32-class radio dongle** for the fleet — a generic laptop cannot
  speak ESP-NOW — and an uplink that is **not** the fleet radio
  (Ethernet / cellular / second radio). The fence install is the same
  box, duty-cycled and driven past twice a week.
- **Package**: `gw/`, Python 3, **stdlib only** (the sim's discipline:
  deterministic, unittest, no dependencies). One CLI, two backends
  behind a common interface:
  - `--backend sim` (default): drives the real sim world headless with
    a seed — every operator action runs the same `world/radio/node/
    fleet/compass` code the 60 tests prove.
  - `--backend serial --port ...`: the ESP32 dongle, speaking a framed
    protocol to be documented with firmware (stage 3). The operator
    surface is identical across backends; only the transport differs.
- **Persistence**: a gateway state directory (JSON, atomic writes) —
  roster keyed by stable node id, per-node calibration and learned
  floors, verdict history, fleet config (id, channel, trust model).
  Survives restarts **and pseudonym rotations**: the stable id travels
  only inside authenticated frames, so state keys on it, never on the
  rotating radio address.

## 2. CLI

```
tells-gw listen                     # the live fleet table (default)
tells-gw claim [--fleet NAME]       # guided claim mode
tells-gw compass [--watch]          # the chart-table readout
tells-gw verdicts [--all]           # attribution log w/ states + horizons
tells-gw set-aside ID [--note ...]  # quarantine; declares the cost
tells-gw readmit ID                 # re-admission, no hardware visit
tells-gw history [--since T]        # store-and-forward dump, timestamps
tells-gw channel-scan               # commissioning aid (serial backend)
```

`listen` — one row per tell, the story's bottom lines:

```
ID          STATE    TIER      BATT    LAST HEARD   VERDICT
bow-p       claimed  service   3.52 V  12 s ago     ok
stern-p     claimed  service   3.49 V  12 s ago     ok
port-mid    claimed  service   3.41 V  9 s ago      suspected (0.4 m)
stbd-mid    claimed  eco       3.36 V  31 s ago     ok
bow-s       claimed  survival  3.21 V  4 min ago    ok
```

`compass` — the story's display contract, dashes included:

```
HEADING   031° ±4°
SWING     ±2°  (last 40 min)
HEEL      —    (lateral pair degraded: port-mid set aside)
```

plus the tier footer (four on eco, one on survival) and, when firmware
lands, the underway Doppler line. **Degraded is a state, not an
absence**: every line carries either a number with its ± or the reason
there is no number.

`claim` — the owner's whole dance, one person, no laptop:

```
$ tells-gw claim --fleet boat
press each tell's button for 5 s, then scan its label
  bow-p     window open, label read -> claiming .. claimed (confirmed)
  stern-p   window open, label read -> claiming .. claimed (confirmed)
  ...
6/6 claimed; fleet key issued; channel 6 published to fleet config
```

## 3. Claim flow (wired to the sim-proven ceremony)

The CLI drives exactly the frames `sim/fleet.py` + `sim/node.py`
implement — REVIEW §1.4's ceremony with the sim's refinements. Nothing
here is new protocol: **if the CLI needs a frame the sim lacks, the sim
grows first, with tests.**

1. Operator presses 5 s → the tell broadcasts its window beacon
   {nonce, session pk}. Nothing secret is on air, ever.
2. Operator scans the label QR → the gateway holds {S, nonce, pk} for
   the window's duration. Possession (the press) + secret (the label):
   the two credentials.
3. Gateway → CLAIM {N_g, fleet, pk, proof = HMAC(S, "claim"|N_g|fleet|
   pk)} — pk-addressed, so concurrent ceremonies on one bus cannot feed
   each other's failure counters.
4. The tell verifies (window ∧ its pk ∧ fresh nonce ∧ valid proof) →
   CLAIM_ACK; bad proofs count to a 3-strike lockout (5 min).
5. Gateway → KEY {fleet, K_f, proof under the pair key}; the tell
   installs, rotates its address, consumes S → KEYACK.
6. Both sides retransmit until confirmed (≤ 5 × 2 s); a replayed
   accepted claim re-acks idempotently. **The ceremony completes under
   loss** — proven at 25 % frame loss.

Proven in sim (60 tests): the window is mandatory; stranger fleets and
claims are refused; forged proofs lock out; nonce replays are refused;
concurrent ceremonies are safe; retransmission completes; re-home
revokes; factory reset cancels the arm; the window dies on reboot.

Not proven anywhere yet (firmware/hardware): real button debounce and
gloves-and-ice ergonomics, BLE bearer, label QR mechanics, NVS write
wear, real radio timing.

## 4. The monitor note: observation graph, not the routing star

This stage does not build the fleet-consistency monitor (DESIGN §6) —
the library prerequisites do not exist yet (Hodge decomposition,
streaming update, cycle localization; SHEAF-NOTES §1.3). But it must
**record what the monitor needs**, or the monitor lands later as a
rework:

- **Adjacency.** The gateway logs, per epoch, which pseudonyms it heard
  (its own observation), and telemetry carries each tell's
  confirmed-peer list — the liveness table it already keeps for §2.
  Together these give the **radio-observation graph**: who hears whom.
  This, *not* the routing star, is the graph the monitor runs over. A
  star is a tree; on a tree H¹ ≡ 0 for any sheaf; an obstruction alarm
  built on the routing graph is **silently dead forever** — it reports
  health while measuring nothing. [SHEAF-NOTES §2.4, proven and
  numerically verified over random trees]
- **The second silent trap.** The free edge field δs is always an
  exact coboundary, so its projection onto the obstruction space is
  identically zero. The monitor must watch the **calibrated residual**
  — per-edge offsets estimated online, with stalks augmented by a
  constant coordinate so a linear map can carry an offset at all.
  Recording per-edge / per-node offset estimates from day one is what
  makes that possible. [SHEAF-NOTES §2.2b/2.3]
- **Verdict objects** — the monitor's output contract, defined now:
  `{node, quantity_m, state: suspected|confirmed|set_aside|readmitted,
  first_seen, confirmed_at, floor_m, basis}`. A verdict names a tell
  and a quantity in metres; "obstruction dimension 3" is not a verdict.
- **Chain installs** (fences): no cycles → the obstruction space is
  empty → only the tree-safe H⁰/residual form. The fence install is
  the designated test case; a chain with one drifting sensor must be
  reported as *unattributable*, never as healthy.
- **Cost discipline.** Energy + per-node attribution shares are
  O(E·k²) with no factorization — fine every epoch; obstruction +
  cycle localization need a cached factorization and run on trigger.
- **This stage ships a provisional v0 verdict**: per-node *calibrated*
  residuals of the per-epoch rigid fit (§5's Umeyama fit produces
  them), where each node's mounting offset is estimated online from
  its own history — the nuisance absorbed, the residual watched —
  thresholded against a per-node floor learned from that history, with
  the suspected→confirmed horizon. **Marked provisional**: the alarm
  statistic is a design proposal until validated in sim against
  injected drift (acceptance test 5) — a simulator that only injects
  iid noise would "prove" the monitor measures noise (REVIEW §4.8's
  warning, applied verbatim to the monitor).

## 5. State and time

- Durable per-node state keyed by the stable id (calibration, floors,
  verdict history) — survives restarts and pseudonym rotations.
- Every verdict and every table row carries a timestamp; `history
  --since` replays the store-and-forward log. The fence's "post 22,
  last heard 9 hours ago" is this semantics, not a slogan.
- The gateway may duty-cycle: tells are independent; on return the
  table rebuilds from beacons and telemetry replays. Absence is an
  install property, not an outage.

## 6. What the sim already proves vs what only hardware can

**Proven in sim** (60 tests, deterministic — same seed in, same trace
out; the 48-cell sweep is byte-identical on rerun):

| Property | Where |
|---|---|
| Ceremony safety: window mandatory; strangers refused; forged proofs lock out; replays refused or idempotently re-acked | `test_fleet`, `test_node` |
| Ceremony completes by retransmission on a 25 %-loss bus | `test_fleet` |
| Concurrent ceremonies safe (pk addressing) | `test_fleet` |
| Re-home revokes; factory reset cancels the arm; the window dies on reboot | `test_node` |
| Leaderlessness: kill any tell; beacons, ceremony, compass persist | all suites |
| Common-mode error cancels exactly in node-to-node differencing | `test_compass` |
| Calibration: 95 % intervals cover 93–97 % post-fix (48 cells; cold-start pinned at ρ = 0.6, 15 m, 5 s) | sweep + regression tests |
| The correlated regime floors; the report carries the floor and never goes below it | `test_compass` |
| Heel separated from yaw (paired same-seed comparison) | `test_compass` |
| Radio loss → gaps with a wider σ, never garbage headings | `test_compass` |

**Only hardware can answer:**

| Question | Why it matters |
|---|---|
| Real radio-observation density on water — do all six tells hear each other? | The monitor's precondition: without cycles in the observation graph, the structural alarm is dead |
| Real per-node bias / ρ at the install | Sets the compass floor and the < 3° map (DESIGN §5); the sweep's ρ is a knob, the truth is a measurement |
| ESP-NOW range on water; channel noise; boat-Wi-Fi coexistence | Channel choice; the observation graph's edges |
| Wi-Fi/radio init energy (~300 ms @ ~70 mA is an estimate) | 56 % of the service tier; second-largest term in the budget |
| GNSS hot-start TTFF with the VBAT cell; real December σ_fix at 61° N | Power budget; the floor |
| LiFePO₄ cold-charge inhibit + usable-capacity fraction of the actual cell | The 120-day endurance sizing |
| Per-install insolation and shadow (the spruce post is the death case) | Per-node battery and tier expectations |
| Button, label, enclosure reality (QR wear, gloves, ice) | The one-person, no-laptop ceremony |

## 7. Acceptance

The stage is done when, on the sim backend (unittest, deterministic):

1. `claim` completes for six tells (presses + label reads) on a 25 %-
   loss bus — retries visible, all six confirmed; re-claiming a
   claimed tell is refused with the reason.
2. A stranger injecting forged claims and telemetry mid-ceremony
   produces lockout and refusal logs, and no fleet change.
3. Killing a tell mid-run: `listen` shows it going stale (last-heard
   aging, explicit); `compass` degrades to a dash with the reason; no
   garbage numbers anywhere.
4. Injecting a slow 1 m drift on one tell: `verdicts` shows
   suspected → confirmed with a metre quantity and a horizon;
   `set-aside` flips the compass' heel line to a dash and declares the
   cost; `readmit` restores it.
5. The v0 verdict statistic is validated in sim: no verdict on the
   ordinary (quasi-static per-node bias alone never crosses from
   suspected — the nuisance is absorbed), a confirmed verdict within
   the horizon on a real drift, the floor always reported.
6. `history --since` replays with timestamps; the same seed produces
   identical output — determinism held.

Firmware (stage 3) starts only after 1–4 pass; the serial backend then
replaces the sim backend behind the same CLI.
