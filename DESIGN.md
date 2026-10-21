# Tells — design v0

Casey's spec, as dictated 2026-10-20, with engineering filled in.
Anything not yet measured is marked UNVERIFIED.

## 0. Doctrine

Tells are the bottom rung of the fleet ladder: below the Pi (an OS with no GPU),
below the Uno Q (a sense organ with a reflex), a tell is a *neuron* — one job,
milliwatts, no generality. All intelligence is borrowed from up the ladder:
gateway → Jetson (the runabout) → Thor/cloud (the mothership) when links allow.
A tell must never *need* the ladder to do its one job.

## 1. The node

| Part | Reference choice | Notes |
|---|---|---|
| MCU/radio | ESP32-S3 or C6 | ESP-NOW, Wi-Fi, BLE for provisioning |
| Payload | u-blox-class GNSS (compass-line tell) | Other payloads later: temp, tilt, reed switch… |
| Power | LiFePO4 cell + 1–2 W solar panel | Sized per §4 |
| Enclosure | Sealed, IP67 target | No ports. The button is the only control. |
| Button | 1 physical button | short = status blink · 5 s hold = pairing mode · 15 s hold = factory reset (wipe fleet key + config from NVS) |

## 2. Radio: ESP-NOW, leaderless

- Nodes broadcast short discovery beacons (ESP-NOW broadcast) carrying:
  node ID (MAC-derived), payload type, firmware version, fleet state
  (UNCLAIMED or fleet hash), battery state.
- Every node keeps a **peer table** from what it hears. There is no election
  and no coordinator; liveness is gossiped by observation.
- Telemetry: payload readings sent ESP-NOW to any peer that wants them,
  and specifically toward a gateway when one is present. ESP-NOW range
  (~200 m+ line-of-sight class) covers a boat and its dock easily. UNVERIFIED on-water.

## 3. Claiming (pairing)

1. Factory / reset state = **UNCLAIMED**. The node beacons its state openly.
2. The owner runs the gateway in claim mode. The gateway broadcasts a CLAIM
   containing a fleet ID; unclaimed nodes in earshot answer.
3. The owner confirms the list (these specific nodes = this boat). The gateway
   issues a per-fleet key; nodes store fleet ID + key in NVS and switch their
   ESP-NOW traffic to encrypted peer links (PMK/LMK). They stop answering
   strangers' claims.
4. Adding a node later: owner opens a claim window at the gateway; new node is
   claimed exactly as at first setup.
5. Re-homing a node: physical button, 5 s hold → pairing mode (possession is
   the credential — you must be able to touch the node).

Open: exact key-exchange ceremony — see REVIEW questions. Claim security must
answer: what stops a stranger with a laptop from claiming your unclaimed nodes
first? (Mitigations sketched: claim only accepted while the button window is
open after a physical press; first-claim-wins + button reset as recovery.)

## 4. Power budget (design targets, UNVERIFIED)

- ESP32 deep sleep: ~10 µA class. GPS is the hungry part: duty-cycle fixes
  (e.g. one fix per minute while "in service", stretching to hourly when the
  fleet is quiet) — the fix schedule is a fleet-level setting, not a constant.
- ESP-NOW transmit bursts are milliseconds at ~100–200 mA: a whisper per fix
  costs almost nothing against a solar day. Telemetry does not need to be
  polled; continuous whispering is affordable.
- Alaskan winter is the sizing case: weeks of near-dark. The budget must close
  at December light levels, or the duty cycle must degrade gracefully and say so.

## 5. Reference mission: compass line

- ~6 GPS tells along a ~15 m baseline (50-ft boat): bow, stern, midships pairs.
- The gateway fuses asynchronous fixes into a heading estimate. Raw per-fix
  noise (σ ≈ 1.5 m class) makes any single instant's heading crude
  (σ ≈ σ_fix / baseline per axis), but asynchronous samples averaged over
  minutes tighten it roughly with 1/√N; yaw rate and swing come from the
  estimate's derivative. The design claim to prove in simulation first:
  filtered heading good to a few degrees at anchor and underway.
- Failure honesty: if geometry or fix quality degrades, the compass must
  report its own uncertainty, not a confident wrong number.

## 6. Build order

1. **Host simulator** (Python, stdlib only, deterministic seeds): node state
   machines, the discovery gossip, the claim ceremony, and the compass fusion
   over synthetic noisy fixes. Properties to test: leaderlessness (kill any
   node mid-run; the mesh persists), claim safety (an unclaimed node ignores
   fleet traffic; a claimed node ignores strangers), compass accuracy vs.
   noise/rate/baseline.
2. **Gateway CLI**: claim mode, live table of nodes, compass readout.
3. **Firmware skeleton** (ESP-IDF): beacon + peer table + button state machine
   on real ESP-NOW.
4. **Hardware**: first sealed GPS tell; on-boat trial.

## 7. Open questions

- Key exchange at claim time (see §3).
- ESP-NOW channel coexistence with boat Wi-Fi; channel choice strategy.
- Time sync across nodes (GPS gives the compass-line nodes a shared clock for
  free — a rare luxury; non-GPS payloads need a gossip clock).
- Store-and-forward when the gateway is absent for days.
- Solar sizing from real December data at Casey's latitude.

## v0.1 amendments (post-review, 2026-10-20)

Geordi's hard review (REVIEW-MCODE.md) landed real hits on v0. Until a v1
rewrite, these amendments govern:

- **Compass math corrected.** The §5 noise formula was wrong by a factor of
  √2 (REVIEW §4.1), and the "averaging tightens as 1/√N" claim is **withdrawn
  as stated**: co-located GPS receivers share correlated errors (atmosphere,
  multipath, constellation geometry), so averaging buys far less than the
  independent-error math promises (REVIEW §4.3). Any simulator that models
  fix noise as independent per node will "prove" a falsehood — the sim must
  model a correlated error component (REVIEW §4.8). Six collinear nodes are
  also not six independent baselines (§4.2), heel/pitch and fix-epoch skew
  belong in the model (§4.4), and underway the primary observable changes
  (§4.5).
- **December power budget does NOT close as specified.** The decisive factor
  is the cold-charge constraint (a frozen battery cannot accept charge),
  ahead of panel wattage (REVIEW §3.3–3.4). Fixes and a reframed budget are
  in §3.4–3.6; treat §4 above as targets under revision, not a closed budget.
- **Claim ceremony: button window is necessary, not sufficient.** The §3
  sketch is superseded by the ceremony in REVIEW §1.4; the holes are
  catalogued in §1.3 (claim races, replay, and stranger-pre-claim among them).
