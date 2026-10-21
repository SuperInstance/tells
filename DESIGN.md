# Tells — design v0.2

Casey's spec, as dictated 2026-10-20, engineered and corrected since.
Every claim below stands on one of three grounds, marked inline:
**[SIM]** proven in the host simulator (`sim/`, 60 tests green,
deterministic — same seed in, same trace out); **[REVIEW]** derived in
the hard review (REVIEW-MCODE.md, with its assumption register §7);
**[REQ]** a requirement stated by the story round
(TELLS-STORY-AND-DERIVATION.md) or the sheaf notes (SHEAF-NOTES.md),
awaiting firmware or hardware evidence.

## CHANGELOG

### v0.2 — 2026-10-21

The story round read the design backwards out of two scenes of ordinary
use (a December morning on the boat; a fence line two weeks later) and
marked 50 rows: 2 already in design, 12 contradictions, 36 gaps. This
rewrite fixes all 48 and folds in everything measured since v0.1. What
changed, and on what evidence:

- **§3 claiming** replaced by REVIEW §1.4's ceremony, refined and
  proven in the sim: a per-device secret on a single-use enclosure
  label, an HMAC proof-of-possession over a fresh nonce, a one-shot
  button window, pk-addressed claims (so concurrent ceremonies on one
  bus cannot lock each other out), claim lockout, re-home that revokes
  the old fleet, rotating pseudonyms and fleet tags, per-frame
  authenticated telemetry — and the property v0 assumed but never
  specified: the ceremony is **completable by retransmission** under
  loss (both sides retry; a node re-acks the claim it already accepted,
  idempotently; sim tests pin it on a 25 %-loss bus). [SIM + REVIEW]
- **§2 radio** rebuilt as a slotted star: nodes never relay, the
  gateway is the only sink, reception is a short per-epoch RX window at
  a phase hashed from the node id. Continuous reception — v0's implicit
  model — is 99.8 % of the energy budget and the 20-peer ESP-NOW
  ceiling forbids all-to-all peering at fleet scale; both are review
  findings the body text now carries. [REVIEW §2; SIM for the
  liveness/confirmation rules]
- **§4 power** rewritten around the December doctrine: the binding
  constraint is **cold charging** (LiFePO₄ cannot accept charge below
  0 °C; Anchorage's December daily maximum is −3.9 °C, so ~120 days a
  year the panel is discarded by the BMS at any panel size). The winter
  budget is therefore battery endurance at tier load, not December
  harvest; the tier ladder is autonomous and voltage-triggered; the
  GNSS backup cell is mandatory. [REVIEW §3]
- **§5 compass** rewritten with the corrected error model (REVIEW §4)
  and the measured surface from the 48-cell parameter sweep
  (sim/SWEEP.md, post-fix, 1 152 seeded trials): baseline dominance
  (5→25 m cuts median error 3.4–5.5×); fix-rate irrelevance under
  correlation (1→30 s costs 3.5–3.9× at ρ = 0 but only 1.1–1.2× at
  ρ = 0.9); reported-σ coverage 93–97 % post-fix; and the
  conservative-by-construction note for the 30 s cells. [SIM + REVIEW]
- **§6 fleet verdicts** (new): the relational failure behavior the
  story needs — a verdict that names a tell in metres ("port midships,
  1.1 m, confirmed"), suspected→confirmed with a horizon, set-aside
  with a declared observability cost, silence never reading as health —
  and the consistency monitor that produces it, running over the
  **radio-observation graph, not the routing star** (on a tree H¹ ≡ 0
  and the alarm is silently dead). [story F/G rows; SHEAF-NOTES §2,
  math proven and numerically verified there]
- **§7 gateway** (new): the only always-on device; owns a real ESP32
  radio (a laptop cannot speak ESP-NOW); holds per-node state across
  pseudonym rotations; its verdict is complete without the ladder.
  Specced for build in GATEWAY.md. [REVIEW §2.4; story G rows]
- v0.1's amendment list is superseded: everything it flagged now lives
  in the body text at its correct section.

### v0.1 — 2026-10-20
Post-review patch list (compass math, December budget, claim ceremony).
Superseded by this rewrite.

### v0 — 2026-10-20
As dictated. Commit 5bccadc.

---

## 0. Doctrine

Tells are the bottom rung of the fleet ladder: below the Pi (an OS with
no GPU), below the Uno Q (a sense organ with a reflex), a tell is a
*neuron* — one job, milliwatts, no generality. All intelligence is
borrowed from up the ladder: gateway → Jetson (the runabout) →
Thor/cloud (the mothership) when links allow. A tell must never *need*
the ladder to do its one job — and the boat's own answers (heading,
verdicts, liveness) are complete at the gateway rung; the ladder above
is for riches, never required.

Leaderless is a property of the *tells*: no tell has a role beyond its
own payload. It does not mean the gateway is absent from the topology —
traffic is a star (§2), and that star is what makes "kill any tell and
the rest carry on" trivially true, more strongly than any relay mesh.
[REVIEW §2.6]

## 1. The node

| Part | Reference choice | Notes |
|---|---|---|
| MCU/radio | ESP32-S3 or C6 | ESP-NOW + BLE; slotted epochs per §2 |
| Payload | u-blox-class GNSS (compass tell) | payload board is swappable without touching the radio, claim, or power contract [REQ] — later payloads: temp, tilt, reed switch |
| GNSS backup | coin cell on the VBAT pin | **mandatory**: keeps the hot start across sleeps; without it every duty-cycled fix is a 26 s cold start and the GNSS term goes ×26 (14.4 → 374 mWh/day) [REVIEW §3.2] |
| Power | LiFePO₄ cell + 1–2 W panel | sized per §4, **per node** |
| Enclosure | sealed, IP67, no ports | the button is the only control |
| Label | QR / short code = per-device secret S | single-use: consumed (rotated) at first claim [REVIEW §1.4] |
| Button | short = status blink · 5 s hold = pairing / re-home · 15 s hold = factory reset | the 15 s hold **cancels** the pairing arm; the LED blinks, never solid — a 15 s solid LED is 6× the service tier's whole daily energy [REVIEW H6, §3.5] |
| Identity | rotating pseudonym | the stable node id exists only inside authenticated frames; the radio address rotates at claim/re-home/reboot, the fleet tag daily [REVIEW H3/H4; SIM] |

## 2. Radio: a slotted star, observed as a mesh

- **Nodes never relay.** The gateway is the only sink and the only
  thing that needs a global view. A tell's peer table is what it
  *observes* (liveness), not what it routes to: entries confirm on
  2-of-3 beacon epochs and expire after 3 beacon periods. [REVIEW
  §2.3/2.6; SIM implements the confirm/TTL rules]
- **Reception is scheduled, not continuous.** A fixed sync epoch (60 s
  at service tier) with a per-node phase offset hashed from the node
  id; a short RX window per epoch (tens of ms) in which the tell also
  transmits; deep sleep otherwise. The gateway listens always.
  [REVIEW §2.5]
- Why: **listening, not talking, is the cost.** Wi-Fi RX is 88 mA —
  continuous RX is 6.97 Wh/day, 99.8 % of the energy budget and
  incompatible with deep sleep. Transmit is a whisper (≈ 1.4 mWh/day
  at two frames a minute). v0's "peer table from what it hears" and
  the README's "mostly whisper continuously" are superseded. [REVIEW
  §3.2]
- **Beacons** carry: pseudonym, payload type, firmware version,
  battery, state — and when claimed, a **fleet tag that rotates daily**
  (derived from the fleet key), never a stable fleet hash: a stable
  hash is a correlatable tracker readable by any passive observer.
  Broadcast frames cannot be link-layer encrypted (ESP-NOW prohibits
  encrypted multicast), so anything that matters is AES-GCM at the
  application layer under a fleet-derived key; ESP-NOW is transport
  only. [REVIEW H2/H4; SIM implements the rotating tag + pseudonyms]
- Airtime is trivial at design rates (0.05 % of the channel at 30
  nodes × 1 beacon/min) — collisions are not the problem; and the
  20-peer ESP-NOW ceiling (17 encrypted) forbids all-to-all peering at
  fleet scale regardless. [REVIEW §2.1–2.2]
- **Channel** is a fleet-wide fact chosen at commissioning (scan
  1/6/11, publish in the fleet config, peers follow the local device).
  The gateway's fleet radio must be separable from its uplink (§7).
  [REVIEW §2.4]
- **The observation graph is not the routing graph.** Beacons are
  broadcast: a tell still hears every tell in range, and §6's
  consistency monitor runs over that observation adjacency — on a boat,
  six tells 15 m apart form a dense graph with cycles even though
  traffic is a star. Recording observation adjacency is a requirement
  from day one. [SHEAF-NOTES §2.4; REQ]

## 3. Claiming (the ceremony, as proven in the sim)

REVIEW §1.4 governs; `sim/fleet.py` + `sim/node.py` are the executable
spec (60 tests). The owner's whole dance — press, scan, done — is one
person with no laptop: the gateway device itself, or a phone.

1. A tell ships **UNCLAIMED** with a random 128-bit device secret S in
   NVS, never broadcast; the enclosure label carries S as a QR / short
   code. The label is single-use: S is consumed at first claim.
2. A **5 s button hold** opens a claim window: ≤ 60 s, one-shot,
   volatile — closed on success, on timeout, and on any reboot; the
   15 s reset hold cancels the arm. In the window the tell beacons
   {fresh nonce, session public key, state=UNCLAIMED}. Nothing secret
   is ever broadcast.
3. The gateway learns S by **reading the label** — the owner is
   standing there: the button press is possession, the label is the
   secret, and together they are the credential.
4. Gateway → CLAIM {fresh gateway nonce N_g, fleet id, the window's
   PK, proof = HMAC-SHA256(S, "claim" | N_g | fleet_id | PK)} —
   replay-proof by the fresh nonce, and **addressed to the window's
   PK**: on a shared bus a tell hears its siblings' ceremonies, and
   pk-addressing is what keeps six concurrent claims from feeding each
   other's failure counters. [SIM]
5. The tell verifies: window open ∧ its own PK ∧ nonce unseen ∧ proof
   valid. Bad proofs count toward a lockout (3 failures → 5 min
   cooldown); spent nonces are refused. On success it derives a
   pairwise key (HKDF over S, N_g, its nonce, its PK) and answers
   CLAIM_ACK.
6. Gateway → KEY {fleet id, fleet group key K_f, proof under the
   pairwise key}; the tell installs {fleet, K_f}, rotates its address,
   consumes S, clears its unclaimed-era peers, and confirms KEYACK.
   **Both sides retransmit until confirmed** (≤ 5 tries, 2 s apart),
   and a tell re-acks a replay of the claim it already accepted —
   idempotent, exploitable by nobody without S. The ceremony completes
   under loss. [SIM: pinned on a 25 %-loss bus]
7. **Claimed state**: beacons carry the rotating fleet tag; telemetry
   is per-node keyed and MAC'd over (node, seq, payload) with a
   monotone counter and a replay window at the gateway — a stranger
   cannot steer the compass with fabricated fixes. Claimed tells
   ignore stranger fleets and all claims (first claim wins; recovery
   is the button). [SIM]

- **Re-home** (5 s hold on a claimed tell) erases the fleet key, drops
  all peers, rotates the address, and refuses the old fleet's frames —
  the previous owner keeps no lever. [SIM]
- **Factory reset** (15 s hold) additionally wipes config and derived
  keys, cancels any armed window, and clears the claim lockout
  (possession was just demonstrated). A reset tell returns to claimable
  with a fresh random address; firmware must bound how long it
  advertises openly (a distress window, then quiet) so a stolen box is
  not an indefinite tracker. [REQ, review H9; the bound is not in the
  sim]
- **Trust model, stated per install**: the credential is possession +
  the label secret. On a boat rail, possession is strong; on a
  county-road fence post anyone can press the button, and the label is
  the real credential. The fleet config states which model the install
  runs. [REQ, story C4]
- BLE is a candidate bearer for steps 2–6 (37 channels, frequency
  hopping); the sim models the bus abstractly — the bearer choice is
  firmware's. [open]

## 4. Power: battery endurance, not December harvest

The binding constraint is **cold charging**. [REVIEW §3.3–3.4]

- LiFePO₄ must not be charged below 0 °C (plating → permanent failure);
  commercial BMSs inhibit it. Anchorage's December daily *maximum* is
  −3.9 °C, and the monthly maxima stay below 0 °C from roughly
  mid-November to mid-March — about **120 days a year when the panel's
  energy is discarded by the BMS at any panel size**. A 2 W panel
  cannot warm the cell above ambient (≈ 0.12 W in against ≈ 0.25 W of
  convective loss at −10 °C).
- So the winter question is **battery endurance**: can the node carry
  120 days on stored charge at its tier? Yes, comfortably:

| Tier | trigger (own voltage) | wake | fix rate | load | 120-day battery |
|---|---|---|---|---|---|
| service | V > 3.45 V | 60 s | 1/min | 49.9 mWh/day | 2.88 Ah |
| eco | 3.30–3.45 V | 300 s | 1/5 min | 10.4 mWh/day | 0.60 Ah |
| survival | 3.15–3.30 V | 900 s | 1/15 min | 3.9 mWh/day | 0.22 Ah |
| emergency | < 3.15 V | 3600 s | 1/hr | ~0.6 mWh/day | — |

  (65 % of rated capacity usable between 3.40–3.00 V, 3.2 V nominal
  [REVIEW A8]; one 32700 cell (6 Ah) covers service with ~2× margin;
  two 18650s cover eco. December harvest of a 2 W panel, 0.28–0.85
  Wh/day, matters only Mar–Oct — the panel is a warm-season recharge.)

- The ladder is **autonomous and voltage-triggered on the node**, never
  a fleet setting — the gateway may be gone for days. Every tier still
  beacons at least hourly, so a starving tell can be found. [REVIEW
  §3.4; the beacon duty is REQ'd for firmware]
- Every load above **assumes the slotted radio (§2) and the GNSS
  backup cell (§1)**. Continuous RX (6.985 Wh/day) and cold-start
  fixes (GNSS ×26) are each alone fatal to the winter budget; both are
  forbidden. The per-wake radio init (~300 ms at ~70 mA) is 56 % of
  the service tier — the wake-up, not the airtime, is the cost, which
  is what the longer tiers buy. [REVIEW §3.2; A4 is an estimate to
  bench-measure]
- Power is **per node, not per fleet**: each tell's battery is sized
  for its own worst month — the tell in the wheelhouse shadow or under
  a spruce dies first, and an average-sized battery kills exactly it.
  Panel orientation is per install: **flat on a boat** (a swung boat
  cannot aim; a tilted panel facing away from a 5.3° December sun
  collects almost nothing — horizontal beats it), aimed at the sun on a
  fixed post (~7× the December light; fence tells hold service tier
  all winter for this reason). [REQ, story P7/P8; REVIEW §3.6]
- LED feedback blinks, never solid; the battery-voltage divider is
  switched or high-value with a switched sample (at survival tier a
  permanent divider is a load). [REVIEW §3.5]

## 5. Reference mission: the compass line

- ~6 GNSS tells on a ~15 m baseline (50-ft boat): bow, stern, and a
  midships **lateral** pair. **Heading comes from the longitudinal
  baseline only**: heel rotates an athwartships baseline by exactly the
  heel angle (5° heel = 5° of bias), and fix-epoch skew underway
  destroys it (30 s of skew at 3 m/s = 80° of azimuth error across the
  boat athwartships, 0.00° longitudinal). The lateral pair exists to
  make heel and pitch observable; it never sets heading. [REVIEW §4.4;
  SIM: heel separated from yaw in paired same-seed tests]
- Fixes are aligned to a **common epoch** (per-node clock offsets
  solved against GPS time) before anything is differenced. Raw
  positions are never averaged across time: the rigid transform is
  estimated per 30 s fusion epoch from contemporaneous per-node motion
  states (position + velocity, ridge-regularized toward the at-anchor
  prior), and only the **heading** is time-averaged
  (information-weighted circular mean over a 600 s window). [REVIEW
  §4.4/4.7; SIM]
- The estimator is a full 3-D rigid-body fit (Umeyama/Kabsch) over all
  tells, each node weighted by lever² / prediction variance; a node
  whose latest fix is staler than the skew bound is a **gap** for that
  epoch, not a contributor. [REVIEW §4.4; SIM]
- **Underway**, the heading observable is Doppler relative velocity,
  not position differencing: ≈ 0.19° at σ_v = 0.05 m/s against 8.10°
  for a single position difference at 15 m — 20–40× better, and yaw
  rate comes out directly. At anchor, yaw rate and swing come from a
  process-model state estimator (heading + coordinated turn), **never
  a differentiated heading** (a random walk: 115° of integrated drift
  in ten minutes at N = 1). Swing is weakly observable (1° of yaw at
  15 m moves a tip 0.26 m = 0.17 σ of one fix; ~33 fixes to detect at
  1σ) — it is reported with its floor or not at all. [REVIEW §4.5–4.6;
  Doppler is firmware/REQ — the sim runs at anchor]
- **Error model and honesty.** Per-fix error is white + common-mode
  (shared by co-located receivers; cancels *exactly* in node-to-node
  differencing — the design's actual working principle) + a per-node
  bias OU + a slower per-node multipath OU (these do **not** cancel
  and do **not** average down within their correlation times). The
  reported σ therefore carries a floor,
  σ_ψ = √((σ_white/√N)² + σ_quasi-const²), and never goes below it.
  In the sim: the white floor comes from the estimator's own per-fix
  sensitivity coefficients (a fix shared by overlapping tracks is
  never counted as independent information), the quasi-constant prior
  is carried at its full scale (√(bias² + multipath²)) through the
  fit's linearized yaw sensitivity, a measured-wander term takes over
  after 40 min of window history, and a 1.1× cold-start guard covers
  the gap. [SIM; REVIEW §4.3]
- **The measured surface** (48-cell sweep: baseline {5,10,15,25 m} ×
  fix interval {1,5,30 s} × correlated fraction ρ {0, 0.3, 0.6, 0.9},
  σ_fix held at 1.5 m; sim/SWEEP.md post-fix; 24 seeded trials per
  cell, ~480 readings each):
  - **Baseline dominates.** 5→25 m cuts median error 3.4–5.5× at every
    ρ and interval. At ρ = 0.9 and 25 m the median 2.19° sits within
    6 % of the quasi-constant differential model — i.e. at the floor
    itself, measured rather than asserted.
  - **Fix rate stops buying accuracy once error is correlated.**
    1→30 s costs 3.5–3.9× at ρ = 0 (a white-noise knob) but only
    1.1–1.2× at ρ = 0.9. REVIEW §4.3's floor, now measured.
  - **Where "a few degrees" holds** (median < 3°): at ρ = 0 everywhere
    except the 5 m + 30 s corner; at ρ = 0.3 it takes ≥ 15 m at any
    interval (or 10 m at 1 s); at ρ = 0.6 it takes 25 m, or 15 m at
    fixes ≤ 5 s; at ρ = 0.9 only 25 m clears it. The reference 15 m
    boat holds < 3° median up to ρ = 0.6 with fixes ≤ 5 s; past that,
    the floor is the honest answer.
  - **Honesty.** Post-fix, pooled coverage of the 95 % interval reads
    93–97 % across the correlated cells (nominal 95 %; pre-fix it
    broke to 71–91 % everywhere ρ > 0 at 1–5 s intervals). The 30 s
    cells sit systematically at ~97–98 % (converged) — **conservative
    by construction**: the protocol holds every node's reported fix σ
    at 1.5 m while the true white component is 1.5·√(1−ρ), and a
    receiver cannot report the white/correlated split of its own
    error, so the white floor carries the total scale as if white.
    Bounded, never approaching absurdity, and not tuned away — shaving
    it would mean teaching the compass a split it cannot know.
- Failure honesty, restated as the sim proves it: if geometry or fix
  quality degrades — or tells go missing — the compass reports its own
  uncertainty and emits **gaps** (a shortened baseline with a wider σ),
  never garbage headings. [SIM: 25 %-loss bus]

## 6. Fleet verdicts: relational failure behavior

The reason six boxes beat a stranger's binoculars is not any one
receiver; it is that the fleet can stop believing one of its own. [story]

- **The verdict is relational and names a tell**: "port midships,
  1.1 m, confirmed" — a quantity in units a person can act on,
  attributed to a node. A per-sensor threshold trip cannot produce
  this; the fleet's *views disagreeing* is the signal, and each of six
  individually plausible tells is exactly the case it catches. [REQ;
  SHEAF-NOTES §2.5]
- **It does not fire on the ordinary.** Per-node bias does not average
  down (§5), so a rigid edge-difference alarm is permanently lit — and
  a permanently lit alarm is an unwatched alarm. The nuisance (each
  node's static error) is estimated and folded into calibrated
  per-edge offsets; the alarm watches the residual against a baseline
  learned from the node's own history, and carries its own floor,
  below which it never reports. [REQ; SHEAF-NOTES §2.2/2.3]
- **States and horizon**: suspected → confirmed (a night of
  accumulated fixes — a metre of offset on one tell out of six is
  smaller than any single fix's noise), then **set aside** by the
  owner with a *declared cost*: what the fleet can no longer observe.
  With the lateral pair's tell set aside, heel is a dash on the
  display — and the display says so. Re-admission is a gateway
  command, not a hardware visit; or the exclusion is declared
  permanent. [REQ]
- **The monitor runs over the radio-observation graph — who hears
  whom — never the routing star.** A star is a tree, and on a tree
  H¹ ≡ 0 for any sheaf: an obstruction alarm built on the routing
  graph is *silently dead forever*, reporting health while measuring
  nothing. The second silent trap: the free edge field δs is always an
  exact coboundary, so its projection onto the obstruction space is
  identically zero — the alarm must watch the **calibrated residual**
  (δs + per-edge offsets), which is not exact. Stalks are augmented
  with a constant coordinate so a linear restriction map can carry an
  offset at all. Both traps are proven and numerically verified in
  SHEAF-NOTES §2.3–2.4; both fail silently, so both get "the alarm
  fires when it should" tests, not just arithmetic tests. [SIM to
  build; REQ]
- **Cost discipline.** The cheap alarms — total disagreement energy
  (sᵀLs = ‖δs‖²) and per-node attribution shares — are O(E·k²) with no
  factorization and run every epoch; the structural alarms (obstruction
  energy, cycle localization that names the offending loop, H⁰/H¹
  dimensions) need a cached factorization and run on trigger.
  [SHEAF-NOTES §2.3]
- **Chain installs** (a fence line — the second life of the same
  hardware) have no cycles: the obstruction space is empty and only
  the tree-safe H⁰ form survives (residual after the best global
  section; H⁰ deficit). A fence either gets a second way across the
  field or accepts that one drifting sensor is indistinguishable from
  a leaning post — the story's post 31 is this case, stated as a
  requirement, not an anecdote. [SHEAF-NOTES §2.4; story scene 2]
- **Silence never reads as health.** Missing data is its own state —
  "last heard 9 h ago", "unknown" for a genuinely three-valued payload
  (a gate is open / closed / unknown, and survives loss of contact).
  A dead box is distinguishable from a taken or re-homed one: a re-home
  revokes (§3) and a stranger's fleet is refused, so silence plus a
  fresh pseudonym nearby reads as re-homed, not dead. [REQ]
- **"The boat moved" ≠ "the telling drifted."** A single node off is a
  local signal (its incident edges carry the residual energy); a
  structural change moves the obstruction. The mathematics separates
  them; the display must too. [SHEAF-NOTES §2.3]

## 7. The gateway

- The gateway is the **only always-on device**; tells are leaves.
  [REVIEW §2.6]
- It **owns an ESP32-class radio** — a generic laptop cannot speak
  ESP-NOW (no host-OS API exists on any desktop OS). The shape: an
  ESP32 dongle or HAT on a Pi-class host, with an uplink that is
  **not** the fleet radio (Ethernet, cellular, or a second radio) —
  one radio cannot sit on the router's channel and the fleet's
  channel at once. [REVIEW §2.4]
- Its **verdict is complete without the ladder**: compass,
  attribution, freshness. [doctrine]
- Its state is durable: per-node baselines, calibrations, learned
  floors, verdict history — surviving restarts **and pseudonym
  rotations** (state is keyed by the stable node id, which travels
  only inside authenticated frames). [REQ]
- It can be **absent for days** (the fence's Pi, driven past twice a
  week): tells run independently; on return, store-and-forward history
  and timestamped verdicts catch up. A duty-cycled gateway is a valid
  install. [REQ]
- Build stage 2 is specced in **GATEWAY.md**: CLI shape, the claim
  flow wired to the sim-proven ceremony, the observation-graph monitor
  note, and the sim-proves / hardware-only ledger.

## 8. Build order

1. **Host simulator — DONE** (`sim/`, 60 tests green, deterministic,
   stdlib only). It proves: leaderlessness (kill any tell mid-run;
   beacons, ceremony, and a gracefully degraded compass persist);
   claim safety (window mandatory; stranger fleets and claims refused;
   forged proofs lock out; nonce replays refused; concurrent
   ceremonies safe; **completable by retransmission** on a 25 %-loss
   bus; re-home revokes; reset cancels the arm; the window dies on
   reboot); and the compass surface of §5 (common-mode cancellation;
   93–97 % coverage post-fix; the floor; heel/yaw separation; gaps not
   garbage).
2. **Gateway CLI** — next. GATEWAY.md governs.
3. **Firmware skeleton** (ESP-IDF): slotted beacon + peer table +
   button state machine + the ceremony on real ESP-NOW; application-
   layer AES-GCM; VBAT-backed GNSS; the voltage-triggered tier ladder;
   the distress bound on reset advertising.
4. **Hardware**: first sealed GPS tell; on-boat trial; measure the
   hardware-only ledger (§9, GATEWAY.md §6).

## 9. Open questions

- The observation graph's real density on water — the monitor's
  precondition (§6). Hardware.
- Real ρ / per-node bias scale at the install: the sweep's ρ is a
  knob; the truth sets the floor and the < 3° map. One afternoon, two
  receivers, a rooftop. Hardware.
- ESP-NOW range on water; channel noise; coexistence with boat Wi-Fi
  (commissioning scan). Hardware.
- Wi-Fi/radio init energy (~300 ms at ~70 mA is an estimate, and it
  is 56 % of the service tier — bench it). Hardware.
- Real December σ_fix at 61° N near a cabin (1.5 m is an open-sky
  summer figure). Hardware.
- BLE vs ESP-NOW as the claim bearer. Firmware.
- Time sync for non-GPS payloads (GPS tells share a clock for free;
  others need a gossip clock). Firmware.
- Node-side store-and-forward capacity and retention while the
  gateway is away. Firmware.
- The monitor's alarm statistic (self-learned baseline, floor,
  horizon) is a design proposal until validated in sim against
  injected drift — and the library prerequisites (Hodge decomposition,
  streaming update, cycle localization) do not exist yet. Sim +
  library.
