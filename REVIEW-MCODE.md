# Tells — hard design review (REVIEW-MCODE)

**Scope:** hostile review of `DESIGN.md` v0 (commit `5bccadc`) and `README.md`, per the four attacks
requested: (1) the claim ceremony, (2) leaderless ESP-NOW at 30 nodes, (3) the December-in-Anchorage
power budget, (4) the compass fusion math. `DESIGN.md` was **not** modified.

**Method:** every quantitative claim below is either (a) taken from a datasheet or published dataset
(cited inline), or (b) computed by me from a stated model and marked **[A-n]** against the assumption
register in §7. Appendix A contains a self-contained Python script that regenerates the budget and the
Monte Carlo so a reader can check the arithmetic without trusting me.

---

## Verdict up front

1. **The claim ceremony is not safe as written, and the button window is necessary but not sufficient.**
   The window gates *when* a claim is accepted; nothing authenticates *who*. The key exchange is
   explicitly an open question (§3, §7) while the whole design depends on it (§3 step 3). Fix the
   exchange first; the window is secondary.

2. **§2 and §4 contradict each other.** §2/§README describe continuous whispering and a live peer
   table; §4 describes deep sleep between one-minute fixes. You cannot maintain a peer table by
   observation without the radio in RX, and radio RX is **99.8 % of the energy budget** and **20×
   over the ESP-NOW peer limit at 30 nodes**.

3. **The December budget does not close as specified — but for a reason the design has backwards.**
   It is not the insolation. It is (a) the unbudgeted radio RX duty, and (b) **LiFePO₄ cannot be
   charged below 0 °C, and Anchorage's December daily *maximum* is −3.9 °C.** Roughly 120 days a year
   the panel is worthless no matter how good it is. The tell is a *seasonal* instrument; the battery
   is the energy store and the panel is a recharge that only works in the warm half of the year.

4. **The compass accuracy claim is roughly right; the reasoning behind it is wrong; and the
   uncertainty reporting is unsound.** `σ ≈ σ_fix / baseline` omits a √2, and the "tightens with
   1/√N" claim silently assumes white noise. Real GNSS error is dominated by a slowly-varying
   per-node bias, which does **not** average down. In simulation the naive reported σ understates
   the true error by up to **9×** at N=300 — a confidently wrong compass, which is exactly what §5's
   "failure honesty" clause forbids.

5. **The single highest-leverage hardware decision in the entire design is a 3-cent coin cell on the
   GNSS VBAT pin.** Without it every duty-cycled fix is a 26-second cold start, and the GNSS load
   goes up **26×** (14 mWh/day → 374 mWh/day). With it, the GNSS hot-start is 1 s.

---

## 1. The claim ceremony

### 1.1 What the design actually specifies

§3: an unclaimed node beacons its state openly; a gateway broadcasts a CLAIM containing a fleet ID;
unclaimed nodes in earshot answer; the owner confirms a list; the gateway issues a per-fleet key;
nodes store it in NVS and "switch their ESP-NOW traffic to encrypted peer links (PMK/LMK)"; they
"stop answering strangers' claims."

The sketch of the mitigation is in §3 itself: *"claim only accepted while the button window is open
after a physical press; first-claim-wins + button reset as recovery."*

### 1.2 Is the button window enough? — **Necessary, not sufficient**

**Why it is necessary.** Without the window, the ceremony is "whichever radio-range device transmits
a CLAIM first wins." A stranger with a laptop and a 2 W transmitter claims every unclaimed node in
earshot, and the owner's nodes are now encrypted to the stranger's fleet key and will not answer the
real owner. That is a total loss of the fleet. The window converts the attacker from *radio-range* to
*physical-possession*, which is a large and correct improvement. Keep it.

**Why it is not sufficient.** The window answers "when," not "who." Nine specific holes follow. Every
one is exploitable by a device in radio range during an open window, except H3 and H8, which need
physical access.

### 1.3 The holes

**H1 — The key exchange is unauthenticated and replayable. (Critical.)**
The CLAIM, the owner confirmation, and the KEY that the gateway "issues" are all unauthenticated
plaintext over a broadcast medium. A recorded CLAIM can be replayed *inside* a legitimately opened
window and the node has no way to tell the legitimate CLAIM from the replayed one, because there is
no nonce, no timestamp, no expiry and no MAC in the protocol. This is not a theoretical gap: §7
lists "Key exchange at claim time" as an open question while §3 step 3 makes the entire scheme
depend on it. **Fix:** the node must verify the claimant, not merely accept the first well-formed
message. Concretely: the node never transmits anything secret-bearing in response to an unauthenticated
CLAIM; the gateway proves possession of a per-device secret over a fresh nonce; the node answers with
an ephemeral public key; the fleet key is derived from ECDH + HMAC over the nonce. This is a PAKE,
and it is a well-trodden pattern (Matter commissioning, Thread joiner, ESP-IDF secure provisioning).
A 6-digit passkey blinked out by the node's LED, or a QR on the enclosure label, both work.

**H2 — ESP-NOW cannot encrypt the beacons. (Critical, and it invalidates §3 step 3 as written.)**
Per the Espressif ESP-IDF documentation: *"Encrypting multicast vendor-specific action frame is not
supported."* And: *"To receive encrypted unicast packets, a paired device must be added, and the same
LMK must be set."* §3 says nodes "switch their ESP-NOW traffic to encrypted peer links (PMK/LMK)" —
but the link-layer LMK protects **unicast to a registered peer**, and the **discovery beacons are
broadcast and therefore always plaintext**, in both the unclaimed and the claimed state. So the
beacon that carries "node ID (MAC-derived), payload type, firmware version, fleet state (UNCLAIMED
or fleet hash), battery state" (§2) is readable by anyone, forever. The encryption covers the
*payload* path and nothing else. **Fix:** application-layer encryption (AES-GCM under a key derived
from the fleet key) for everything broadcast, and treat the link layer as transport only. Note the
20-peer ceiling makes a pure link-layer mesh impossible at 30 nodes anyway (§2.1).

**H3 — "Node ID (MAC-derived)" is a permanent hardware identifier broadcast in every frame. (High.)**
The MAC is in the 802.11 header of every frame, in the clear, forever. It is the node's identity to
any passive observer, in any state, including after the fleet key is set. Encryption of the payload
buys nothing against a passive tracker. **Fix:** randomize the STA MAC per session
(`esp_wifi_set_mac()`) and use a per-fleet rotating pseudonym as the protocol identity.

**H4 — The "fleet hash" is an offline-verifiable tracking beacon. (High.)**
§2 has nodes broadcast "fleet state (UNCLAIMED or fleet hash)". A *stable* per-fleet hash is a
pseudonymous, correlatable identifier: an observer can tell that two nodes belong to the same boat,
track that boat for years, and link it to a marina, a slip, a race entry, or a home berth — without
ever decrypting anything. **Fix:** a rotating pseudonym derived from the fleet key and a time-varying
nonce, or omit fleet identity from the beacon entirely and let "claimed" + a random ID suffice.

**H5 — Telemetry has no authentication, so a stranger can steer the compass. (Critical, safety.)**
The claim ceremony protects *membership*. It says nothing about the *data*. There is no per-frame MAC,
no sequence number, no anti-replay window anywhere in §2. An attacker inside radio range can inject
fabricated GPS fixes. The compass fuses them (§5) and reports a heading. The result is a **confidently
wrong heading on a boat** — a safety outcome, not a privacy one, and it directly violates §5's own
requirement that the compass "report its own uncertainty, not a confident wrong number."
**Fix:** per-node keys derived from the fleet key; a MAC over (node id, fix time, position, velocity);
a monotone counter with a sliding replay window; and the fusion layer must reject fixes that are
geometrically implausible (§4.4).

**H6 — Window semantics are unspecified, and the button state machine is ambiguous. (High.)**
§1 defines "5 s hold = pairing mode · 15 s hold = factory reset". A 15-second hold necessarily
passes through the 5-second threshold, so the state machine must explicitly cancel the armed pairing
window before the wipe — otherwise every factory reset first opens a claim window. Separately, nothing
specifies the window's *duration*, whether it is one-shot, whether it survives a reboot, or whether a
reset node re-arms it. A window that stays open, or that a power cycle re-opens, is a standing
vulnerability. **Fix:** window ≤ 60 s, opened by a physical press, closed on success, on timeout, and
on any reboot; factory reset requires a *fresh* post-reboot press; the pairing arm must be cancelled
by the 15 s hold.

**H7 — Possession is the credential, with no rate limit. (Medium, but it is the design's actual
trust model and should be written down as such.)**
The window converts the first claim into a possession-based claim: whoever can pick the node up and
press the button owns it. That is a legitimate choice — §3 step 5 already admits it for re-homing —
but it means the threat model includes a contractor who installed the node, a marina neighbour, a
thief, and a curious kid, and none of them are addressed. There is also no lockout, so an attacker
with brief physical access can attempt repeatedly or simply DoS the node. **Fix:** state the trust
model explicitly ("first claim requires possession of the device *and* of its per-device secret"),
and add a lockout: N failed attempts → refuse all claims for a cooldown.

**H8 — Re-homing does not revoke the old fleet. (Medium.)**
§3 step 5 puts a node into pairing mode on a 5 s hold, but nothing says the old fleet ID and key are
erased, that the old fleet's membership is dropped, or that the node stops accepting traffic from the
previous owner. A node that still honours the old fleet key can be told to beacon continuously, reset,
or report at high rate — a remote DoS and battery-drain lever held by someone who no longer has the
device. **Fix:** re-home = erase the fleet key, derive a new fleet key, drop all peers, and refuse
frames from the old fleet.

**H9 — Factory reset re-opens the node to anyone. (Medium.)**
A reset node returns to UNCLAIMED and beacons openly, so it becomes claimable by anyone who can press
the button (H7). A stolen node is therefore a liability that keeps advertising where the boat is.
**Fix:** (a) randomize the MAC in the unclaimed state too (H3); (b) consider a "distress" mode where
a reset node beacons a null claim for a limited time and then goes quiet, rather than advertising
indefinitely; (c) note that the reset path must erase *derived* keys, not just the fleet key, or the
old key material stays recoverable from flash.

### 1.4 What the ceremony should look like

```
1. Node ships UNCLAIMED with a random 128-bit device secret S in NVS (never broadcast).
   Enclosure carries S as a QR / short code; the label is single-use.
2. Owner presses the button 5 s  -> node enters CLAIM WINDOW (60 s, one shot, volatile).
   Node beacons: {random pubkey PK, nonce N, state=UNCLAIMED}. Nothing secret.
3. Gateway scans (BLE or a QR read) -> learns S.
4. Gateway sends CLAIM {N_g, proof = HMAC(S, N_g || fleet_id || PK)} -- replay-proof.
5. Node verifies HMAC(S, ...). If it fails: increment failure counter, no response, no state change.
   If it succeeds: node sends {fleet_id, MAC(N, PK)} and derives the fleet key as
   HKDF(S, N_g || N || PK).
6. Node rotates its MAC, stores {fleet_id, key, PK}, and stops answering unauthenticated claims.
   The device secret is consumed (rotated) so the label is worthless after first claim.
```

Everything above is standard and none of it needs a display, a port, or a second button. Steps 2–5
also work over BLE instead of ESP-NOW, which is worth considering: BLE gives you 37 channels and
frequency hopping against a jamming or congested 2.4 GHz band, and the ESP32 already has it.

---

## 2. Leaderless ESP-NOW at 30 nodes

### 2.1 Three hard protocol limits that the design runs into immediately

All three are from the Espressif ESP-IDF `esp_now` documentation.

| Limit | Consequence for this design |
|---|---|
| *"The maximum number of paired devices is 20, and the paired encryption devices are no more than 17, the default is 7."* | **A 30-node all-to-all mesh does not fit in one peer table.** Each node would need 29 peers; the table holds 20, and the encrypted-peer subset holds 17. `CONFIG_ESP_WIFI_ESPNOW_MAX_ENCRYPT_NUM` raises the encrypted number but not the 20-peer total. Also, the broadcast MAC must itself be added as a peer to send broadcast data — it counts. |
| *"Encrypting multicast vendor-specific action frame is not supported."* | Discovery beacons cannot be link-layer encrypted. §3's "switch to encrypted peer links" applies to unicast only. See §1 H2. |
| *"The range of the channel of paired devices is from 0 to 14. If the channel is set to 0, data will be sent on the current channel. Otherwise, the channel must be set as the channel that the local device is on."* | All peers must effectively share one channel. Channel hopping is not free: it drops frames during the switch. `esp_now_switch_channel_tx()` and `esp_now_remain_on_channel()` exist for a graceful hop, and `esp_now_set_peer_rate_config()` exists for per-peer rate limiting (useful for §2.3). |

**The 20-peer ceiling is the finding.** The design's model — "every node keeps a peer table from what
it hears," "telemetry … sent ESP-NOW to any peer that wants them" — is an all-to-all mesh, O(N²) = 870
directed links at N=30, each of which needs a peer-table slot and an LMK. It does not fit. It does not
fail gracefully; `esp_now_add_peer()` returns `ESP_ERR_ESPNOW_FULL`.

### 2.2 Collisions and airtime: the beacon rate is not the problem

Take an ESP-NOW vendor action frame of ~100 bytes payload. At 802.11b (1 Mbps, which is what ESP-NOW
uses for compatibility), airtime is ~0.8 ms of payload plus ~72 µs preamble/header, ~26 µs MAC header,
6 µs FCS, 10 µs inter-frame space, and an average backoff of ~67 µs (CWmin = 15 slots × 9 µs). A
unicast also pays a SIFS + ACK (~58 µs). **τ ≈ 1.0 ms for a broadcast, ~1.2 ms for a unicast** [A1].

Channel utilisation for N nodes beaconing every T_b:

| T_b | beacons/s across fleet | airtime duty | verdict |
|---|---|---|---|
| 60 s | 0.5 | 0.05 % | trivial |
| 1 s | 30 | 3.0 % | fine |
| 0.25 s | 120 | 12 % | CSMA/CA starts to bite |
| 0.1 s | 300 | 30 % | saturated |
| 0.05 s | 600 | 60 % | unusable |

At the design's implicit rate ("a whisper per fix", 1 fix/min) the beacon traffic is **0.05 % of the
channel**. Collisions are not your problem at 30 nodes on a boat. Two caveats:

- **Broadcasts are unacknowledged**, so a sender never learns it collided. Any blind retransmission
  policy turns a collision into a storm. The correct response to a lost broadcast is *repetition on a
  later slot*, not retransmission.
- **Hidden terminals** are negligible at 50 ft (all nodes are within a couple of metres of each
  other) but are real if "30 nodes" ever means 30 nodes around a marina rather than 30 on one boat.
  CSMA/CA handles this partially; a hidden-node-specific RTS/CTS scheme is not available for ESP-NOW
  broadcasts.

### 2.3 The beacon storm is a *gossip* problem, not an airtime problem

§2 says liveness is "gossiped by observation." If every peer-table change is re-gossiped, and gossip is
itself gossiped, one original observation can fan out to O(N) transmissions per node — up to 30 × 30 =
**900 transmissions for a single event**, each of which is another event that may be re-gossiped. This
is the classic epidemic-amplification failure, and the design specifies no defence: no TTL, no
sequence numbers, no anti-entropy, no damping.

**Fix, in priority order:**
1. **Don't relay.** The gateway is already assumed to exist (§2, §6 step 2) and is the only thing that
   needs a global view. Nodes talk to the gateway and to nobody else. "Leaderless" then means *no tell
   has a role* — which is the property §6 actually tests ("kill any node mid-run; the mesh persists") —
   rather than *no node is a sink*. This removes the amplification entirely and drops the peer table
   from 29 entries to 1.
2. If relay is genuinely wanted: a monotone per-origin sequence number, a hop limit of 1–2, and a
   "do not re-gossip what arrived via gossip" rule.
3. Per-peer rate limiting via `esp_now_set_peer_rate_config()` as a backstop.

### 2.4 Channel choice

- 2.4 GHz has 13 channels (1–13; 14 is Japan-only); the non-overlapping set is 1/6/11. All nodes and
  the gateway must be on the same channel, so this is a **fleet-wide** decision made once at
  commissioning.
- **The gateway problem, which the design does not address at all.** §3 says "a gateway (any laptop,
  Pi, or Jetson)." **A generic laptop cannot speak ESP-NOW.** There is no host-OS API on macOS, Windows
  or Linux; ESP-NOW is an ESP-IDF/ESP32 radio feature. The ESP-IDF docs note that the ESP32-P4 "has no
  radio of its own," requiring the *ESP32 Hosted* component with a co-processor running ESP-NOW
  firmware. So the gateway needs either a dedicated ESP32 radio (USB dongle, or a Pi with an ESP32
  HAT) or to *be* an ESP32.
- **The STA/ESP-NOW channel conflict.** If the gateway is an ESP32 doing both ESP-NOW and a Wi-Fi STA
  uplink (the boat's hotspot or the cloud), **both share one radio and one channel**. The uplink wants
  the router's channel; the fleet wants the fleet channel. They are usually different. Every channel
  hop drops frames and delays the peer table. Options, in order of preference: (a) give the gateway a
  **separate** ESP-NOW radio from its internet link (Ethernet or cellular); (b) put the fleet on the
  same channel as the boat's Wi-Fi and accept the contention; (c) channel-hop with a scheduled epoch
  and accept the loss.
- **Recommendation:** at commissioning, scan 1/6/11 for noise and pick the quietest; publish the
  channel in the fleet config; set every peer's `channel = 0` so peers follow the local device and a
  channel change is transparent; re-announce on the new channel after any change.

### 2.5 The contradiction with §4 — this is the real 30-node problem

§2 and README describe nodes that "mostly whisper continuously" and maintain a peer table by
observation. §4 describes deep sleep (~10 µA) between one-minute fixes. These cannot both be true:

> **To hear a peer, the radio must be in RX.** ESP32-S3 Wi-Fi RX is 88 mA [A2]. To maintain a peer
> table by observation with a 1-minute beacon period, the radio must be in RX essentially continuously.
> That is 99.8 % of the entire energy budget (§3.2) and it is incompatible with deep sleep.

The resolution is not "be cleverer"; it is to **stop needing continuous reception**. Design discovery
as a *slotted, scheduled* protocol:

- A fixed **sync epoch** (e.g. every 60 s) with a per-node **phase offset hashed from its node ID**,
  spreading beacons uniformly across the epoch instead of aligning them.
- A short **RX window** per epoch (tens of ms), during which the node also transmits its beacon and
  receives peers'. Everything outside the window is deep sleep.
- The gateway is always listening; nodes listen only in their window. Because the phase offsets are
  hashed and not synchronised, a node can miss a given peer in a given epoch — so a peer table entry
  needs **N-of-M confirmation** (say, seen in 2 of the last 3 epochs) and an explicit **TTL/expiry**,
  neither of which §2 specifies.
- `esp_now_set_wake_window()` exists in ESP-IDF for exactly this ("configure Window for ESP-NOW RX at
  sleep"), though note the docs' caveat that "sleep is supported only when ESP32 is configured as
  station."

### 2.6 What 30 nodes should actually look like

A star around the always-powered gateway. Nodes never relay; the gateway aggregates; the peer table is
one entry (the gateway), not 29; the "kill any node and the mesh persists" property holds trivially and
in fact *more* strongly than in an all-to-all mesh, where killing a node that was relaying could
partition it. **Do not build the general mesh and then scale it to 30 — build the star and keep the
node-side protocol general enough to allow it later.** Leaderless is a property of the *tells* (no tell
is a coordinator, no tell has a job beyond its own payload); it does not require the gateway to be
absent from the topology.

---

## 3. The December-in-Anchorage power budget

**Location:** Anchorage, AK. 61.22° N, 149.90° W.

### 3.1 The harvest side

| Quantity | Value | Source |
|---|---|---|
| December day length | 5.05 h (solstice) – 5.65 h (Dec 1) | computed from NOAA solar equations; matches "6 h 10 min" on Dec 1 from NOAA daily normals |
| Solar elevation at solar noon, Dec 21 | **5.34°** | 90° − (61.22° + 23.44°) |
| December GHI, horizontal | **0.61 kWh/m²/day** | NREL via UAF *Solar Design Manual for Alaska*; my own clear-sky model gives ~0.2, so treat 0.61 as an upper bound [A3] |
| Annual GHI | 2.34–2.40 kWh/m²/day | SOLMET/NSRDB, Anchorage station 26451 |
| December snowfall | 46 cm (18.2 in) | NOAA 1991–2020 normals |
| **December mean daily maximum temperature** | **−3.9 °C** | NOAA 1991–2020 normals, station USW00026451 |
| December mean daily minimum | −10.7 °C | same |

Two consequences that the design does not draw:

- **The sun is 5.3° above the horizon at solar noon.** A *horizontal* panel sees cos(zenith) = 0.093
  at noon. A panel tilted to face the sun sees cos(85°) ≈ 1 — an **~11× geometric gain at noon**, and
  ~7× integrated over the day. But see the trap in §3.6.
- **December's high is −3.9 °C.** The ambient never reaches freezing. See §3.3.

### 3.2 The load side

Per-node daily energy, computed as Joules and converted (Appendix A):

| Mode | Wi-Fi init | Wi-Fi RX | Wi-Fi TX | GNSS | Deep sleep | **Total** |
|---|---|---|---|---|---|---|
| **A — "design as written"** (radio RX continuous, 1 fix/min) | — | **6.970 Wh** | 1.35 mWh | 14.40 mWh | — | **6.985 Wh/day** |
| **B — slotted radio** (60 s wake, 50 ms RX window, 1 fix/min) | 27.72 mWh | 5.81 mWh | 1.35 mWh | 14.40 mWh | 0.62 mWh | **49.89 mWh/day** |
| **B2 — slotted, 250 ms window** | 27.72 mWh | 29.04 mWh | 1.35 mWh | 14.40 mWh | 0.62 mWh | **73.12 mWh/day** |
| **B3 — eco** (300 s wake, 1 fix/5 min) | 5.54 mWh | 1.16 mWh | 0.14 mWh | 2.88 mWh | 0.63 mWh | **10.35 mWh/day** |
| **S — survival** (900 s wake, 1 fix/15 min) | 1.85 mWh | 0.39 mWh | 0.05 mWh | 0.96 mWh | 0.63 mWh | **3.87 mWh/day** |
| **C — resident radio** (modem-sleep 15 mA, 1 fix/min) | — | 1.188 Wh | — | 14.40 mWh | — | **1.202 Wh/day** |

Read the table against §4's claims:

> **"GPS is the hungry part."** In Mode A the GNSS is **0.2 %** of the budget and the radio is
> **99.8 %**. The design has identified the wrong hungry part. §4's own arithmetic is right about the
> one thing it measures and wrong about the thing that matters: "a whisper per fix costs almost
> nothing" is *true* (1.35 mWh/day for 2 beacons/min) and *irrelevant*, because **listening** costs
> 6.97 Wh/day — 1 300× more than talking.
>
> **"ESP32 deep sleep: ~10 µA class."** True (datasheet: 7–8 µA), and also irrelevant at 0.62 mWh/day.

Two more findings from the same table:

- **The per-wake Wi-Fi initialisation dominates the radio budget.** `esp_wifi_init()` + `esp_now_init()`
  costs ~300 ms at ~70 mA [A4]. At a 60-second wake period that is **27.7 mWh/day, 56 % of Mode B** —
  more than the RX window itself. *The airtime is not the cost; the wake-up is.* The fix is a longer
  wake period (Mode B3: 5.5 mWh/day), which is exactly what the survival tier does.
- **Duty-cycling the GNSS requires a backup supply.** The MAX-M10S hot-start TTFF is 1 s; cold start
  is 24–26 s. Hot start requires the receiver to retain RTC/almanac/ephemeris, which needs the **VBAT
  pin powered**. With no backup cell, every wake is a cold start: 12 mA × 3.0 V × 26 s = 936 mJ per
  fix instead of 36 mJ — **26×**, and the GNSS term goes from 14.40 mWh/day to **374 mWh/day**, making
  it 92 % of the total budget. This flips §4's claim back to true: the GNSS *would* be the hungry part,
  but only because of a missing three-cent coin cell.

### 3.3 The cold-charge constraint — the decisive one

LiFePO₄ must not be charged below 0 °C; charging a lithium-iron cell below freezing causes lithium
plating, internal short, and permanent failure. Commercial BMSs therefore inhibit charging below 0 °C
by default. From the NOAA normals, the monthly daily *maximum* is:

| Oct | Nov | Dec | Jan | Feb | Mar |
|---|---|---|---|---|---|
| +5.6 °C | −2.0 °C | **−3.9 °C** | −5.3 °C | −2.6 °C | +0.6 °C |

So the ambient is below 0 °C from roughly **mid-November to mid-March — about 120 days**. In that
window the panel's energy is not merely scarce, it is **discarded by the BMS**.

Could a 2 W panel warm the cell above 0 °C? No:

- Cell thermal mass: 100 g × 1.0 J/(g·K) = 100 J/K [A5].
- Convective loss at −10 °C: 50 cm² of exposed area × 5 W/(m²·K) × 10 K ≈ **0.25 W** [A6].
- Panel output at December noon, horizontal, clear sky: 2 W × ~60 W/m² / 1000 ≈ **0.12 W**.

Input < loss. **The cell cannot rise above ambient; there is no December charging, at any panel size
that fits on a boat.** (A larger panel could warm the cell, but then you are heating a battery with a
solar panel to store energy in a battery, which is a worse version of the problem.)

### 3.4 Does it close? — **No as specified; yes with the fixes; and the question needs reframing**

**As specified: it does not close.** The design gives a radio duty cycle that requires continuous RX
(6.985 Wh/day), a 1–2 W panel, and no battery size at all. The December harvest of a 2 W horizontal
panel is 0.28–0.85 Wh/day [A3, A7] — **8–25× less than the load** — and even that is unusable because
of §3.3. The node would be dead well before Christmas.

**With the fixes, it closes — and the margin is large:**

| | load | December harvest (2 W, horizontal) | harvest / load | 120-day battery need |
|---|---|---|---|---|
| Mode B (service) | 49.9 mWh/day | 280–854 mWh/day | 5.6× – 17× | 5.99 Wh → **2.88 Ah** LiFePO₄ |
| Mode B2 | 73.1 mWh/day | 280–854 mWh/day | 3.8× – 12× | 8.78 Wh → **4.22 Ah** |
| Mode B3 (eco) | 10.4 mWh/day | — | 27× – 82× | 1.24 Wh → 0.60 Ah |
| Mode S (survival) | 3.9 mWh/day | — | 72× – 219× | 0.47 Wh → 0.22 Ah |
| Mode C (resident radio) | 1.202 Wh/day | — | 0.23× – 0.71× | 144 Wh → **69 Ah** — infeasible |

Battery figures assume 120 days of no charging, 65 % of rated LiFePO₄ capacity usable between 3.40 V
and 3.00 V [A8], and 3.2 V nominal. A single 32700 LiFePO₄ (6 Ah) covers Mode B with ~2× margin; two
18650s (1.5 Ah each) covers Mode B3.

**But the harvest column is a red herring in December**, and this is the reframe:

> The December budget is **not** a harvest-versus-load question. The panel cannot charge the battery
> in December regardless of size. The December question is a **battery-endurance** question: *can the
> node carry 120 days on stored charge at survival-tier load?* Yes — 0.47 Wh of usable energy, i.e. a
> fraction of one 18650.

Which means §7's open question — *"Solar sizing from real December data at Casey's latitude"* — is
aimed at the wrong input. The right inputs are:
1. **the length of the no-charge window** (120 days at Anchorage), not the December insolation;
2. **the survival-tier daily load** (3.9 mWh/day, or 374 mWh/day if you forget the GNSS VBAT backup);
3. **the battery's usable window**, which for LiFePO₄ is only ~65 % of rated capacity between 3.40 V
   and 3.00 V — a factor-of-1.5 that a naive "capacity × 3.2 V" calculation misses entirely.

And §4's instinct — *"the duty cycle must degrade gracefully and say so"* — is exactly right, but it
must be **autonomous**, because the gateway may be absent for days (§7 lists store-and-forward when
the gateway is gone as an open question). The ladder must trigger on the node's own battery voltage,
not on a gateway command:

| Tier | Trigger | Wake | Fix rate | Load |
|---|---|---|---|---|
| Service | V > 3.45 V | 60 s | 1/min | 49.9 mWh/day |
| Eco | 3.30–3.45 V | 300 s | 1/5 min | 10.4 mWh/day |
| Survival | 3.15–3.30 V | 900 s | 1/15 min | 3.9 mWh/day |
| Emergency | < 3.15 V | 3600 s | 1/hr | ~0.6 mWh/day |

Every tier must still beacon hourly, so the owner can find a starving node. The design already has
the right instinct here — §2 puts "battery state" in the beacon — but it must be *acted on*, not merely
reported.

### 3.5 Other December specifics the design misses

- **Snow.** 46 cm falls in December. A horizontal panel is buried; a tilted panel sheds. This is an
  independent argument for tilt.
- **GPS geometry degrades in winter at 61° N.** More satellites sit at low elevation → worse
  ionospheric delay and worse multipath. σ_fix = 1.5 m [A9] is the MAX-M10S open-sky figure and is
  optimistic for December on a boat.
- **The LED.** A solid LED during a 15-second button hold draws ~20 mA × 15 s = 0.30 J — **6× Mode B's
  entire daily energy budget**. The button feedback must be blinked, not solid, and the firmware should
  cap the LED duty cycle. This is an easy mistake with an easy fix.
- **Battery voltage sense.** A divider permanently across the cell can dominate the survival-tier
  budget. Switch it, or use a high-value divider and a switched sample.

### 3.6 The panel tilt trap

A tilted panel is much better in December — *if it faces the sun*. But a panel bolted to a boat faces
the boat's heading, and a boat at anchor swings. On the December solstice, a 90°-tilted panel collects
**0.04 kWh/m²/day if the boat faces south and ~0.00 if it faces north** [A10] — i.e. in the worst
orientation a tilted panel is *worse* than horizontal (0.61 per the published figure). You cannot
tilt your way out of this problem; the boat's heading is not yours to choose.

**Therefore: the horizontal panel is the correct default** for a heading-unconstrained install, and the
real fixes are (a) tilt only if the install is heading-stable, (b) use two panels at complementary
azimuths if the volume allows, (c) treat the panel as a recharge that only matters Mar–Oct, and (d)
size the battery for 120 days regardless.

---

## 4. The compass fusion math

### 4.1 The formula in §5 is wrong by a factor of √2

§5: *"Raw per-fix noise (σ ≈ 1.5 m class) makes any single instant's heading crude (σ ≈ σ_fix /
baseline per axis)."*

For two points with independent errors **e₁**, **e₂** and a true baseline **b** of length L:

- b̂ = b + (e₂ − e₁), so Var(e₂ − e₁) = 2σ² per axis — the difference of two independent errors has
  √2 times the noise of one.
- δψ = |b̂ × (e₂ − e₁)| / L², so **σ_ψ = √2 · σ / L**.

With σ = 1.5 m and L = 15 m: **σ_ψ = 8.10°, not the 5.73° the design implies.** The design's
"per axis" phrasing is also loose: the relevant σ is the *perpendicular* component, and GPS error is
elliptical (much worse in the north-south direction at these latitudes).

### 4.2 Six collinear nodes are not six baselines

A total-least-squares line fit through N points at positions x_i with iid noise σ gives
**σ_ψ = σ / √(Σ(x_i − x̄)²)**. For six tells evenly spread over 15 m (x = 0, 3, 6, 9, 12, 15):

- Σ(x_i − x̄)² = 157.5 m², √ = 12.55 m → **σ_ψ = 6.85°**
- best single pair: Σ = 112.5, √ = 10.61 m → **σ_ψ = 8.10°**

So the six-node fit beats the best pair by only **1.18×**, not the √6 = 2.45× a naive "six
independent measurements" reading suggests. Intermediate collinear points contribute almost nothing;
**only the endpoints carry lever arm.** The design's "σ_fix / baseline per axis" hides this, and §5's
implied leverage from 6 tells is overstated.

### 4.3 The "1/√N" claim is the deepest error — and it breaks the honesty requirement

§5: *"asynchronous samples averaged over minutes tighten it roughly with 1/√N."*

1/√N holds only for **white** noise. Real GNSS position error at a static site is dominated by a
**slowly varying bias**, not white noise. I ran 1500 independent trials of a circular-mean heading
estimator over a bow–stern baseline (Appendix A, full output in the script):

| Error model | N | true bias | true sd | naive reported σ | ratio |
|---|---|---|---|---|---|
| white noise only | 1 | −0.07° | 8.03° | 8.10° | 0.99 |
| white noise only | 60 | 0.04° | 1.06° | 1.05° | 1.01 |
| white noise only | 300 | 0.00° | 0.47° | 0.47° | 1.01 |
| **common-mode bias 0.8 m (shared)** | 1 | −0.08° | 8.27° | 8.10° | 1.02 |
| **common-mode bias 0.8 m (shared)** | 300 | −0.02° | 0.45° | 0.47° | 0.97 |
| per-node independent bias 0.8 m | 60 | −0.21° | 4.47° | 1.05° | **4.27** |
| per-node independent bias 0.8 m | 300 | −0.16° | 4.33° | 0.47° | **9.26** |
| bias ρ = 0.5, 0.8 m | 300 | −0.03° | 3.04° | 0.47° | **6.49** |

Three things fall out of this, and they are the heart of the matter:

1. **Common-mode error cancels exactly.** An error identical at both nodes cancels in the difference —
   the trial statistics are indistinguishable from the white-noise-only case. This is *good news* for
   heading and it is the actual reason a GPS line can work: regional ionospheric error, ephemeris
   error, and common clock error are largely common-mode and vanish in the differential.
2. **Per-node error does not cancel, and does not average down.** A receiver's own clock bias and its
   own local multipath are node-specific. With σ_b = 0.8 m of per-node bias, the effective differential
   σ is σ_b·√(2(1−ρ)): 1.13 m at ρ=0, 0.80 m at ρ=0.5, 0.57 m at ρ=0.75, 0 at ρ=1. This sets a **floor
   of ~4–6° on the heading** that no amount of averaging removes.
3. **The reported uncertainty diverges from the truth without bound.** The naive reported σ follows
   1/√N toward zero while the true error sits at ~4.3°. At N=300 the compass would report ±0.5° while
   being wrong by 4°. **This is precisely the "confident wrong number" that §5 forbids.** The fix is
   to report σ_ψ = √((σ_white/√N)² + σ_diff,bias²) — a floor term — and to estimate σ_diff,bias from
   the data (e.g. the high-frequency-to-low-frequency power ratio of the differential error series, or
   an explicit Allan-variance-style estimate of the bias correlation time).

**So: is "good to a few degrees" sound?** Under white noise, yes — 8.10°/√N reaches 2.6° at N=10 and
1.05° at N=60. Under a realistic per-node bias, the truth converges to ~4–6°, which *is* "a few
degrees." **The accuracy claim is roughly right; the reasoning is wrong; and the uncertainty estimate
is wrong by up to 9×.** Ship the claim with the floor term or the compass will lie.

### 4.4 Geometry: heel, pitch, and epoch skew

This is where the design's specific choice of "bow, stern, midships pairs" bites, and the design never
mentions it.

**Heel contaminates athwartships baselines; pitch does not contaminate longitudinal ones.**

- A **longitudinal** (bow–stern) baseline is invariant under roll (roll rotates the transverse axis)
  and only *shortened* by pitch: cos(2°) = 0.06 %, i.e. an azimuth error of ~0.00°.
- An **athwartships** baseline rotates in azimuth by exactly the heel angle. **5° of heel = 5° of
  heading error**, as a pure bias, with no GPS quality improvement possible. At anchor in a December
  Anchorage seaway, ±5–10° of heel is routine; underway in 15–25 kt it is worse.

So the midships pair — which is athwartships — **cannot be used for heading**. It must be used for
what it is actually good for: observing heel and pitch.

**Epoch skew destroys athwartships baselines.** The fixes are asynchronous by design (§5). Underway at
3 m/s, a 30 s stagger between two tells' fixes means the stern's fix describes a position 90 m astern
of where the bow's fix does. Against a 15 m athwartships lever, that is an azimuth error of
**atan(90/15) = 80.5°** — not degradation, garbage. Against a *longitudinal* baseline the same skew
changes the length but not the azimuth: **0.00°**.

| Epoch skew @ 3 m/s | along-track error | athwartships azimuth error | longitudinal azimuth error |
|---|---|---|---|
| 10 s | 30 m | 63.4° | 0.00° |
| 30 s | 90 m | 80.5° | 0.00° |
| 60 s | 180 m | 85.2° | 0.00° |

Two structural conclusions:

1. **Heading must come from the longitudinal (bow–stern) baseline only.** The midships pair is for
   heel/pitch (and for redundancy/cross-check), never for heading.
2. **Fixes must be time-aligned to a common epoch before differencing.** This is where §7's "GPS gives
   the compass-line nodes a shared clock for free — a rare luxury" becomes load-bearing rather than
   decorative: you need the epoch, and you need to solve for the per-node time offset. (Solving for a
   per-node clock offset is a standard, well-conditioned GNSS technique — it is also how you make
   asynchronous fixes usable at all.)

**Observability caveat.** Six tells on a straight line cannot observe **roll** at all: rotation about
the line through them is unobservable. The lateral offset of a midships pair is what makes the third
rotation DOF observable. So the geometry is right — but the *purpose* of the midships pair must be
stated, and the estimator must be a **rigid-body fit (Kabsch/Umeyama) over all six points**, not the
"σ_fix / baseline per axis" scalar the design implies. A Kabsch fit over the six body-frame → ENU
correspondences estimates heading, pitch and roll *jointly*, which is the only way the lateral pair's
heel contamination can be separated from heading instead of corrupting it.

### 4.5 Underway, the design is using the wrong observable

Position differencing at anchor (a boat barely moving) throws away almost all the information the
receiver has. **Doppler velocity does not.** The heading of the baseline can be estimated from the
*relative* velocity between bow and stern:

| Observable | σ | σ_ψ (L = 15 m) | vs position-based |
|---|---|---|---|
| Position difference | σ = 1.5 m | 8.10° | 1× |
| Doppler, σ_v = 0.05 m/s | 0.05 m/s | **0.19°** | **42× better** |
| Doppler, σ_v = 0.10 m/s | 0.10 m/s | **0.38°** | 21× better |
| Doppler, σ_v = 0.30 m/s | 0.30 m/s | 1.15° | 7× better |

**Recommendation: two estimators, selected by motion state.**
- **At anchor** (no Doppler): position-based heading from the longitudinal baseline, time-averaged,
  with the bias floor of §4.3 reported honestly.
- **Underway** (Doppler available): relative-velocity heading, which is instantaneous and ~20–40×
  more accurate than the position-based estimate. This also fixes yaw rate (below).

### 4.6 Yaw rate and swing

§5: *"yaw rate and swing come from the estimate's derivative."* Differentiating a noisy estimate is the
worst possible way to get a rate:

| N | Δt | σ_ψ | σ_yaw_rate | 10-minute integrated drift |
|---|---|---|---|---|
| 1 | 60 s | 8.10° | 0.191 °/s | **115°** |
| 60 | 60 s | 1.05° | 0.025 °/s | 15° |
| 60 | 10 s | 1.05° | 0.148 °/s | **89°** |
| 300 | 60 s | 0.47° | 0.011 °/s | 7° |

An unfiltered derivative of a heading estimate is a random walk in the integrated heading. The fix is a
state estimator with a process model, not a difference: state = [heading, yaw rate], process =
coordinated turn (constant yaw rate), measurement = heading from the §4.4 rigid fit with its
covariance. From Doppler, yaw rate comes out directly at σ = σ_v/L = 0.0033 rad/s (0.19 °/s) at
σ_v = 0.05 m/s — far better than any differentiated position estimate.

**Swing at anchor** is weakly observable and the design should say so. One degree of hull yaw at a
15 m lever arm moves the tip by **0.262 m**, which is **0.17 σ** of a single GPS fix. Detecting 1° at
1σ takes ~33 fixes. So swing is a *statistical* observable: it requires averaging, and therefore it
inherits the bias floor of §4.3 — a bias in the differential error looks exactly like a persistent
swing. Report swing with an uncertainty, and do not report it at all until the geometry supports it.

### 4.7 One more fusion bug: averaging positions across a turn

§5 says the gateway "fuses asynchronous fixes" and that samples are "averaged over minutes." If the
fusion literally averages *positions* over a window, then during any manoeuvre the average is the
**chord** of the arc, not the position at any instant, and the baseline direction is biased toward the
course over ground. Averaging positions across a 60° turn is not a small error.
**Fix:** never average raw positions across time. Maintain a per-node state estimate (position,
velocity, and a per-node time offset), estimate the rigid transform **per epoch** from contemporaneous
estimates, then time-average the *heading* with a process model. Averaging headings is correct;
averaging positions is not.

### 4.8 What the simulator in BRIEF-BUILD.md will and will not prove

BRIEF-BUILD.md specifies "σ=1.5 m fixes" and a test that "filtered heading converges to within a few
degrees and reported uncertainty is honest vs. measured error." If the simulator injects iid Gaussian
noise, it will reproduce my "white noise only" row exactly: the reported σ matches the truth at every
N, the test passes, and **it proves nothing about the real system** — because the dominant error term
is not white. The simulator must inject, at minimum:

1. a **common-mode bias** shared across nodes (should cancel — a test that this *does* cancel is worth
   as much as any other test in the suite);
2. a **per-node independent bias**, ideally as an OU process with a correlation time (τ ≈ 5–30 min) so
   the 1/√N failure is visible;
3. **per-node multipath** as a separate slow bias (different antenna, different reflection);
4. **heel, pitch and heave** as a rigid-body motion applied to the body-frame tell positions;
5. **per-node epoch offsets** and the associated along-track error;
6. **loss and delay** on the radio link, so the fusion sees gaps.

And the pass criteria should be rewritten: not "error ≤ 3°" but "the 95 % interval contains the truth
≥ 95 % of the time (calibration), **and** the estimator never claims better than the bias floor." A
simulator that only asserts an error bound will happily certify an estimator that is confidently wrong
— the failure mode the design explicitly says it wants to avoid.

---

## 5. Ranked fixes

### S1 — Critical. Fix before writing firmware.

| # | Fix | Addresses |
|---|---|---|
| 1 | **Authenticate the claim.** Per-device secret (QR / BLE-provisioned), gateway proves possession over a fresh nonce, fleet key derived via ECDH+HMAC. The node answers nothing secret-bearing to an unauthenticated CLAIM. | §1 H1, H6, H7 |
| 2 | **Encrypt at the application layer, not just the link layer.** ESP-NOW cannot encrypt broadcasts. AES-GCM under a fleet-derived key over everything; treat ESP-NOW as transport. | §1 H2, H2.1 |
| 3 | **Authenticate telemetry.** Per-node key, MAC over (id, time, fix), monotone counter, replay window. A stranger must not be able to steer the compass. | §1 H5 |
| 4 | **Stop the identity leak.** Randomized STA MAC per session; rotating pseudonym derived from the fleet key; no stable "fleet hash" in the beacon. | §1 H3, H4, H9 |
| 5 | **Replace continuous reception with a slotted sync epoch.** Per-node phase offset hashed from the node ID, short RX window, gateway as the always-on sink, nodes never relay. Peer table entries need N-of-M confirmation and a TTL. | §2.1, §2.3, §2.5, §3.2 |
| 6 | **Put the GNSS on a backup supply.** Coin cell or supercap on the MAX-M10S VBAT pin, so duty-cycled fixes are 1 s hot starts. 26× on the GNSS term. | §3.2 |
| 7 | **Size the battery for the 120-day no-charge window, not for December insolation.** ≥ 3 Ah LiFePO₄ for the service tier, ≥ 1 Ah for eco; low-temperature charge-inhibit BMS; voltage-triggered tier ladder (service → eco → survival → emergency) that is **autonomous**. | §3.3, §3.4 |
| 8 | **Fix the compass error model and the uncertainty floor.** σ_ψ = √((σ_white/√N)² + σ_diff,bias²); estimate the bias term from the data; report the floor, never report below it. | §4.3, §4.7 |

### S2 — Major. Fix before the on-boat trial.

| # | Fix | Addresses |
|---|---|---|
| 9 | **Heading comes from the longitudinal baseline only.** Fit a rigid transform (Kabsch) over all six points; use the lateral midships pair for heel/pitch, never for heading. | §4.4 |
| 10 | **Time-align the fixes.** Solve for per-node clock offsets against the GPS clock and propagate every fix to a common epoch before differencing. | §4.4, §7 |
| 11 | **Use Doppler for underway heading and yaw rate.** Relative velocity between bow and stern: ~20–40× better than position differencing; yaw rate comes out directly. | §4.5, §4.6 |
| 12 | **Never average raw positions across time.** Estimate the transform per epoch, then average the heading with a coordinated-turn process model. | §4.7 |
| 13 | **Specify the gateway's radio hardware.** A laptop cannot speak ESP-NOW. Use an ESP32 gateway with a separate uplink radio, or a Pi with an ESP32 HAT / USB dongle. Resolve the STA/ESP-NOW channel conflict. | §2.4 |
| 14 | **Write the button state machine down.** 5 s arms pairing and is cancelled by the 15 s reset; window is one-shot, ≤ 60 s, dies on reboot; reset requires a fresh post-reboot press. | §1 H6 |
| 15 | **Re-home revokes the old fleet.** Erase the fleet key and peer list; refuse frames from the previous fleet. | §1 H8 |
| 16 | **Add a claim lockout.** N failed attempts → refuse for a cooldown. | §1 H7 |
| 17 | **Upgrade BRIEF-BUILD.md's compass tests** to inject correlated bias, heel/pitch, and epoch offsets, and to assert *calibration* of the reported interval, not just a bound on the error. | §4.8 |
| 18 | **Re-derive σ_fix for the actual install.** 1.5 m is an open-sky summer figure; winter geometry at 61° N, and antennas near a cabin, are worse. Carry a per-fix σ from the receiver and weight by it. | §4.1, §3.5 |

### S3 — Minor. Fix when convenient.

| # | Fix | Addresses |
|---|---|---|
| 19 | Panel tilt: default horizontal (heading-constrained); consider two azimuths; snow shedding is an independent argument for tilt. | §3.1, §3.6 |
| 20 | Blink the status LED, never solid, during long holds. A 15 s solid LED = 6× the service-tier daily budget. | §3.5 |
| 21 | Switch the battery-voltage divider, or use a high-value divider with a switched sample. | §3.5 |
| 22 | Specify the beacon period and the peer-table expiry rule. | §2.2, §2.5 |
| 23 | Add `esp_now_set_peer_rate_config()` and `esp_wifi_config_espnow_rate()` as storm backstops; add a gossip TTL and per-origin sequence numbers if any relaying survives fix 5. | §2.3 |
| 24 | Commissioning-time channel scan across 1/6/11; publish the channel in the fleet config; set peer `channel = 0`. | §2.4 |
| 25 | Consider BLE for the claim handshake (37 channels, hopping) instead of ESP-NOW. | §1.4 |
| 26 | Use the `esp_now_set_wake_window()` API rather than a hand-rolled sleep window if the radio stays in station mode. | §2.5 |

---

## 6. What I could not verify

- **On-water RF behaviour.** The 200 m ESP-NOW range figure in §2 is marked UNVERIFIED in the design
  and I have no way to check it. My 30-node analysis assumes all nodes are in range of one another
  (true for a 50-ft boat, not necessarily for a marina).
- **The published December GHI.** NREL's NSRDB grid returned "no data" for Anchorage, so I used the UAF
  *Solar Design Manual for Alaska* figure (0.61 kWh/m²/day, horizontal). My own clear-sky model gives
  ~0.2, so I have carried a 0.2–0.61 band rather than a single number. **This does not change any
  conclusion**, because the panel cannot charge the battery in December regardless (§3.3).
- **The Wi-Fi init cost (300 ms at 70 mA)** is my estimate, not a datasheet number. It is the second
  largest term in the budget, so it deserves a bench measurement. Even if it is 2× worse, the fix
  (longer wake period) is unchanged.
- **Per-node GNSS bias magnitude (σ_b = 0.8 m)** is a plausible placeholder, not a measurement. It
  sets the compass floor, so it is worth one afternoon with two receivers and a rooftop.
- **ESP-NOW behaviour under the specific traffic pattern** (N=30, slotted beacons) is modelled from
  the documented limits and CSMA/CA theory; it has not been measured.
- **LiFePO₄ usable-capacity fraction (65 % between 3.40 V and 3.00 V)** is a typical-curve assumption.
  Get the actual cell's discharge curve.

---

## 7. Assumption register

| # | Assumption | Basis |
|---|---|---|
| A1 | ESP-NOW frame airtime ≈ 1.0 ms broadcast / 1.2 ms unicast at 802.11b 1 Mbps | computed from payload + preamble + MAC header + FCS + IFS + mean backoff |
| A2 | ESP32-S3: Wi-Fi RX 88 mA, TX 340 mA peak, deep sleep 7–8 µA, modem-sleep 13–25 mA @ 3.3 V | Espressif ESP32-S3 datasheet §5.6 |
| A3 | December horizontal GHI = 0.61 kWh/m²/day (upper bound); my clear-sky model gives ~0.2 | NREL via UAF Solar Design Manual for Alaska; SOLMET/NSRDB station 26451 |
| A4 | Wi-Fi + ESP-NOW init ≈ 300 ms at ~70 mA per wake | estimate, not a datasheet figure |
| A5 | Cell thermal mass 100 J/K | 100 g cell × 1.0 J/(g·K) |
| A6 | Convective loss 5 W/(m²·K) over 50 cm² | standard natural-convection coefficient |
| A7 | Panel end-to-end efficiency 70% at these low light levels | typical for a small panel with a simple MPPT at 60 W/m² |
| A8 | 65 % of rated LiFePO₄ capacity usable between 3.40 V and 3.00 V | typical LiFePO₄ discharge curve |
| A9 | σ_fix = 1.5 m per axis, iid, zero-mean, open sky | design's own figure; MAX-M10S quotes 1.5 m CEP50 (≈1.27 m per-axis σ), but December at 61° N and near a cabin is worse |
| A10 | 90°-tilted panel POA ≈ 0 if the boat faces away from the sun | computed from solar geometry with the sun at 5.3° elevation |
| A11 | 120-day no-charge window (mid-Nov → mid-Mar) | NOAA 1991–2020 monthly daily-max temperatures for Anchorage |
| A12 | Dock-to-anchor range ≈ 1 h at 3 m/s for the epoch-skew analysis | typical 6 kt boat speed |

---

## Appendix A — reproduction script

Save as `review_calc.py` and run with `python3 review_calc.py`. Stdlib only.

```python
import math, random, statistics

# ---------- POWER ----------
I_DEEP, V_DEEP = 8e-6, 3.3        # ESP32-S3 deep sleep, RTC on
I_RX,   V_RX   = 88e-3, 3.3       # ESP32-S3 Wi-Fi RX
I_TX,   V_TX   = 340e-3, 3.3      # ESP32-S3 Wi-Fi TX peak
I_INIT, V_INIT, T_INIT = 70e-3, 3.3, 0.30
I_GPS,  V_GPS  = 12e-3, 3.0       # MAX-M10S acquisition @3.0V
T_FIX, T_BEACON = 1.0, 1.5e-3

def mode(T_wake, T_rx, n_beacon, n_fix):
    per = (I_INIT*V_INIT*T_INIT + I_RX*V_RX*T_rx
           + n_beacon*I_TX*V_TX*T_BEACON + n_fix*I_GPS*V_GPS*T_FIX
           + I_DEEP*V_DEEP*max(0.0, T_wake - T_INIT - T_rx - n_fix*T_FIX))
    return per * (86400.0/T_wake)            # Joules/day

# mode A: continuous RX
A = I_RX*V_RX*86400 + 2880*I_TX*V_TX*T_BEACON + 1440*I_GPS*V_GPS*T_FIX
B, B2, B3, S = mode(60, .050, 2, 1), mode(60, .250, 2, 1), mode(300, .050, 1, 1), mode(900, .050, 1, 1)
C = 15e-3*3.3*86400 + 1440*I_GPS*V_GPS*T_FIX
for nm, J in [("A", A), ("B", B), ("B2", B2), ("B3", B3), ("S", S), ("C", C)]:
    Ah = (J/3600.0)*120/0.65/3.2
    print(f"{nm:3s} {J/3.6:9.2f} mWh/day   120-day battery -> {Ah:8.2f} Ah")

# ---------- COMPASS ----------
SIG, L = 1.5, 15.0
def trial(N, mode="white", bias_sig=0.8, seed=0):
    """mode: 'white'      -> no bias
             'common'    -> the SAME bias at both nodes (cancels in the difference)
             'independent'-> a separate bias at each node (does NOT cancel, does not average down)"""
    rng = random.Random(seed)
    if mode == "common":        bias = [rng.gauss(0, bias_sig)] * 2
    elif mode == "independent":  bias = [rng.gauss(0, bias_sig), rng.gauss(0, bias_sig)]
    else:                       bias = [0.0, 0.0]
    sx = sy = 0.0
    for _ in range(N):
        e = [(rng.gauss(0, SIG)+bias[i], rng.gauss(0, SIG)+bias[i]) for i in range(2)]
        dx = L + e[1][0]-e[0][0]; dy = e[1][1]-e[0][1]
        sx += math.sin(math.atan2(dy, dx)); sy += math.cos(math.atan2(dy, dx))
    return math.degrees(math.atan2(sx, sy))

for nm, kw in [("white", {}), ("common", dict(mode="common")), ("independent", dict(mode="independent"))]:
    for N in (1, 10, 60, 300):
        errs = [trial(N, seed=1000+i, **kw) for i in range(1500)]
        naive = math.degrees(math.sqrt(2)*SIG/L/math.sqrt(N))
        print(f"{nm:12s} N={N:4d} bias={statistics.mean(errs):6.2f} "
              f"sd={statistics.pstdev(errs):6.2f} naive={naive:6.2f} ratio={statistics.pstdev(errs)/naive:5.2f}")
```

---

## Summary

**The design is sound in its instincts and wrong in its arithmetic.** The doctrine (one job, milliwatts,
no generality, intelligence borrowed from up the ladder) is right and the compass-line concept is
genuinely good. But four claims do not survive contact with the numbers:

- **The claim ceremony is a radio-range vulnerability with a physical-presence bandage on it.** The
  button window is *necessary* (without it, first-claim-wins is first-random-device-wins) and
  *insufficient* (the key exchange is unauthenticated and replayable; ESP-NOW cannot encrypt the
  beacons at all; the MAC-derived node ID and the "fleet hash" leak identity in the clear; telemetry is
  unauthenticated, so a stranger can steer the compass; the button state machine is ambiguous at 5 s
  vs 15 s; re-homing does not revoke the old fleet). Fix the key exchange first — a per-device secret
  plus a challenge-response — then harden everything else around it.
- **30 nodes is not a discovery problem, it is a peer-table and power problem.** The ESP-NOW peer limit
  is 20 (17 encrypted); an all-to-all mesh of 30 nodes cannot fit in one peer table and will return
  `ESP_ERR_ESPNOW_FULL`. Beacon airtime at the design's rates is 0.05 % of the channel — collisions
  are a non-issue. The storm is in the *gossip*: re-gossiped observations amplify up to 900
  transmissions per event with no TTL, sequence number or damping. And channel choice is constrained
  by a fact the design misses entirely: a generic laptop cannot speak ESP-NOW, so the gateway needs
  a real ESP32 radio, whose channel then collides with its own Wi-Fi uplink. The fix is a star around
  an always-powered gateway, a slotted sync epoch with hashed phase offsets, and nodes that never relay.
- **The December budget does not close as written, and the binding constraint is not the one the
  design is looking at.** The radio's *receive* current is 99.8 % of the energy budget — §4's "GPS is
  the hungry part" is wrong by two orders of magnitude, while its correct observation that whispering
  is cheap is beside the point. But the real December killer is chemistry: **Anchorage's December daily
  maximum is −3.9 °C, so a LiFePO₄ cell cannot be charged at all for ~120 days a year, and a 2 W panel
  cannot warm a cell above ambient against 0.25 W of convective loss.** The budget closes comfortably
  — 3.9 mWh/day at survival tier, 0.47 Wh over the whole dark season, a fraction of one 18650 — but
  only if the node has an **autonomous, voltage-triggered duty-cycle ladder** and a GNSS backup cell
  (without it, every fix is a 26 s cold start and the GNSS term goes up 26×). §7's open question
  ("solar sizing from real December data") is aimed at the wrong input; size the battery for the
  no-charge window, not the panel for December.
- **The compass claim is roughly right for the wrong reasons, and the honesty requirement is
  unsatisfiable as written.** σ = σ_fix/baseline omits a √2 (8.10°, not 5.73°); six collinear tells buy
  only 1.18× over the best pair, not √6; and the 1/√N averaging claim assumes white noise when the
  dominant error is a per-node bias that does not average down — my Monte Carlo shows the naive
  reported σ understating the true error by up to **9× at N=300**, which is exactly the "confident
  wrong number" §5 forbids. Meanwhile heel of 5° puts 5° of bias into any athwartships baseline, and
  30 s of epoch skew at 3 m/s puts 80° into one — so heading must come from the longitudinal
  bow–stern baseline only, with the lateral midships pair reserved for heel/pitch, and all fixes
  time-aligned to a common epoch. Underway, the design uses the wrong observable: **Doppler relative
  velocity is 20–40× better than position differencing** (0.19° vs 8.10°) and gives yaw rate directly.
  And the simulator as briefed would certify a white-noise-only model and prove nothing.

**The cheapest three wins**, in order: (1) a coin cell on the GNSS VBAT pin — a few cents, 26× on the
largest term; (2) a slotted sync epoch instead of continuous reception — turns 6.985 Wh/day into
0.050 Wh/day and simultaneously makes 30 nodes fit inside the peer-table limit; (3) a rigid-body
(Kabsch) fit on the longitudinal baseline with a reported bias floor — costs an afternoon of code and
is the difference between a compass that is right and a compass that is confidently wrong.

**Design.md was not modified.**
