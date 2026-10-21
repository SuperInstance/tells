"""Gateway + claim ceremony (REVIEW-MCODE SS1.4 governs; DESIGN SS3 superseded).

The gateway is the star's sink and the only thing that needs a global view
(REVIEW SS2.6).  Claiming a tell takes all three of:

  1. possession  -- the owner physically held the button 5 s, so a claim
     window (<= 60 s, one-shot) is open on the node;
  2. the secret  -- the gateway learned the tell's per-device secret S from
     the enclosure label (out of band; in the sim, read at press time,
     which is also when a real owner would be standing there with the QR);
  3. freshness   -- the CLAIM carries a gateway nonce never used before and
     an HMAC proof over (nonce, fleet id, the window's public key), so a
     recorded claim cannot be replayed.

The fleet group key K_f only ever travels inside a KEY frame
authenticated under HKDF(S, ...), a key no radio-range stranger holds.
"""

import hmac

from crypto import hkdf_sha256, mac_tag, random_bytes
from node import (CLAIM_WINDOW_S, PAIR_HOLD_S, Tell, fleet_tag,
                  telemetry_key, telemetry_mac_ok)


class Gateway:
    def __init__(self, world, radio, fleet_id="boat"):
        self.world = world
        self.radio = radio
        self.fleet_id = fleet_id
        self.id = "gw-" + fleet_id
        self.alive = True
        self.labels = {}       # node_id -> {"secret", "nonce", "pk"} (QR reads)
        self.pending = {}      # node_id -> ceremony state between CLAIM and KEY
        self.claimed = {}      # node_id -> {"fleet_key", "last_seq"}
        self.fleet_key = None  # K_f, common to the fleet
        self.roster = {}       # pseudonym -> last beacon (live table)
        self.fix_log = []      # verified telemetry payloads, in arrival order
        self.on_fix = None     # callback(payload) -- the compass hooks here
        self.log = []
        radio.attach(self)

    # -- ceremony -------------------------------------------------------------

    def scan_open_node(self, node):
        """Read the label of a tell whose claim window is open (the owner is
        standing there, pressing the button).  Returns False if the window
        is not open: no button, no secret, no claim."""
        if not node.alive or node.state != "UNCLAIMED" or not node.window_open():
            return False
        self.labels[node.node_id] = {"secret": node.device_secret,
                                     "nonce": node._claim_nonce.hex(),
                                     "pk": node._session_pk.hex()}
        return True

    def claim_node(self, node):
        if not self.scan_open_node(node):
            self.log.append((self.world.now, "claim_refused_no_window", node.node_id))
            return False
        label = self.labels[node.node_id]
        ng = random_bytes(self.world.stream(f"gw.{self.fleet_id}.nonce"), 16)
        pk = bytes.fromhex(label["pk"])
        proof = mac_tag(label["secret"], b"claim", ng, self.fleet_id.encode(), pk)
        self.pending[node.node_id] = {
            "ng": ng, "nonce": label["nonce"], "pk": pk,
            "pair_key": hkdf_sha256(label["secret"],
                                    info=b"pair|" + ng + bytes.fromhex(label["nonce"]) + pk),
        }
        self.radio.broadcast(self.id, {"type": "CLAIM", "claim": {
            "nonce": ng.hex(), "fleet_id": self.fleet_id, "pk": pk.hex(),
            "proof": proof.hex()}})
        return True

    def _issue_key(self, node_id, entry):
        if self.fleet_key is None:
            self.fleet_key = random_bytes(
                self.world.stream(f"gw.{self.fleet_id}.fleetkey"), 32)
        kf = self.fleet_key
        proof = mac_tag(entry["pair_key"], b"fleetkey", entry["ng"],
                        self.fleet_id.encode(), kf)
        self.radio.broadcast(self.id, {"type": "KEY", "key": {
            "fleet_id": self.fleet_id, "fleet_key": kf.hex(),
            "proof": proof.hex()}})
        self.claimed[node_id] = {"fleet_key": kf, "last_seq": 0}
        self.log.append((self.world.now, "key_issued", node_id))

    # -- radio ----------------------------------------------------------------

    def receive(self, frame, sender_id):
        kind = frame.get("type")
        if kind == "CLAIM_ACK":
            self._on_ack(frame)
        elif kind == "BEACON":
            self.roster[frame.get("id")] = (self.world.now, frame)
        elif kind == "TELEMETRY":
            self._on_telemetry(frame)

    def _on_ack(self, frame):
        proof = frame.get("proof", "")
        for node_id, entry in self.pending.items():
            label = self.labels.get(node_id)
            if not label:
                continue
            expect = mac_tag(label["secret"], b"ack",
                             bytes.fromhex(entry["nonce"]), entry["ng"])
            if hmac.compare_digest(expect.hex(), proof):
                self._issue_key(node_id, entry)
                del self.pending[node_id]
                return
        self.log.append((self.world.now, "ack_unverified", None))

    def _on_telemetry(self, frame):
        # H5: telemetry is authenticated per-node and replay-windowed.
        if self.fleet_key is None or frame.get("fleet_tag") != self.fleet_tag_now():
            self.log.append((self.world.now, "telemetry_stranger", frame.get("id")))
            return
        if not telemetry_mac_ok(frame, lambda nid: telemetry_key(self.fleet_key, nid)):
            self.log.append((self.world.now, "telemetry_bad_mac", frame.get("id")))
            return
        body = frame["body"]
        state = self.claimed.get(body.get("node"))
        if state is None:
            self.log.append((self.world.now, "telemetry_unknown_node", body.get("node")))
            return
        if body.get("seq", 0) <= state["last_seq"]:
            self.log.append((self.world.now, "telemetry_replay", body.get("node")))
            return
        state["last_seq"] = body["seq"]
        self.fix_log.append((self.world.now, body["payload"]))
        if self.on_fix is not None:
            self.on_fix(body["payload"])

    def fleet_tag_now(self):
        return fleet_tag(self.fleet_key, self.world.now) if self.fleet_key else None

    def events(self, name):
        return [e for e in self.log if e[1] == name]


def press_button(world, node, hold_s=6.0, at=None):
    """Owner presses a tell's button at `at` (default: now), holds `hold_s`
    (5 <= hold < 15 arms the claim window)."""
    t0 = world.now if at is None else at
    world.schedule(t0 - world.now, node.button_press)
    world.schedule(t0 - world.now + hold_s, node.button_release)


def claim_fleet(world, gateway, nodes, hold_s=6.0):
    """The owner's whole dance: press every button (possession), read every
    label (secret), claim every tell.  Schedules everything; run the world
    to `world.now + hold_s + PAIR_HOLD_S + 3` afterwards.  Returns that
    completion time."""
    for i, node in enumerate(nodes):
        press_button(world, node, hold_s, at=world.now + 0.5 + 0.25 * i)
    done_by = world.now + PAIR_HOLD_S + 3.0 + 0.25 * len(nodes)
    for i, node in enumerate(nodes):
        arm_at = world.now + 0.5 + 0.25 * i + PAIR_HOLD_S + 0.5
        world.schedule(arm_at - world.now,
                       lambda n=node: gateway.claim_node(n))
    return done_by


class Stranger:
    """Radio-range attacker with no device secret and no finger (SS1.3 H1,
    H5, H7): forges claims, replays recorded frames, injects telemetry."""

    def __init__(self, world, radio, name="stranger"):
        self.world = world
        self.radio = radio
        self.id = name
        self.alive = True
        self.sent = []
        radio.attach(self)

    def receive(self, frame, sender_id):
        pass  # listens, never reacts

    def _send(self, frame):
        self.sent.append(frame)
        self.radio.broadcast(self.id, frame)

    def forged_claim(self, target_pk_hex="00" * 32, fleet_id="evil-fleet"):
        rng = self.world.stream("stranger")
        ng = random_bytes(rng, 16)
        wrong_secret = random_bytes(rng, 16)
        proof = mac_tag(wrong_secret, b"claim", ng, fleet_id.encode(),
                        bytes.fromhex(target_pk_hex))
        frame = {"type": "CLAIM", "claim": {
            "nonce": ng.hex(), "fleet_id": fleet_id, "pk": target_pk_hex,
            "proof": proof.hex()}}
        self._send(frame)
        return frame

    def forged_telemetry(self, fleet_tag_hex, node_id="bow-p", seq=1,
                          pos=(0.0, 0.0, 0.0)):
        body = {"node": node_id, "seq": seq,
                "payload": {"node": node_id, "t": self.world.now,
                            "pos": list(pos), "sigma": 1.5}}
        frame = {"type": "TELEMETRY", "id": "stranger",
                 "fleet_tag": fleet_tag_hex, "body": body, "mac": "00" * 32}
        self._send(frame)
        return frame
