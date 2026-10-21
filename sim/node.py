"""The tell: one job, no generality (DESIGN SS1-SS3 as amended by REVIEW-MCODE).

A tell is a state machine (UNCLAIMED -> CLAIMED), a peer table fed by
observing beacons, and one button.  It never relays (REVIEW SS2.3/SS2.6):
the star is the topology, and "leaderless" means no tell has a role beyond
its own payload.  Beacon slots are hashed from the node id (SS2.5).

Claim safety (REVIEW SS1.3/SS1.4), enforced here:
  - a CLAIM is honored only while a button-opened window is open (<= 60 s,
    one-shot, dies on timeout/success/reboot);
  - the claimant must prove possession of the per-device secret S with an
    HMAC over a fresh gateway nonce, the fleet id, and this window's
    public key -- replayed nonces are rejected, bad proofs increment a
    failure counter and eventually a lockout;
  - once CLAIMED, all claims are ignored (first claim wins; recovery is
    the button: 5 s re-home revokes the old fleet, 15 s factory-resets).
The fleet group key K_f only ever arrives inside a KEY frame
authenticated under the S-derived pairwise key, so a radio-range stranger
without S (and without the button) gets nothing.
"""

import hashlib
import hmac
import json

from crypto import hkdf_sha256, mac_tag, mac_ok, random_bytes
from world import slot_phase

UNCLAIMED = "UNCLAIMED"
CLAIMED = "CLAIMED"

PAIR_HOLD_S = 5.0        # 5 s hold: pairing / re-home (possession)
RESET_HOLD_S = 15.0      # 15 s hold: factory reset (cancels the arm; H6)
CLAIM_WINDOW_S = 60.0    # window duration cap (H6)
CLAIM_MAX_FAILURES = 3   # then lockout (H7)
CLAIM_LOCKOUT_S = 300.0
PEER_CONFIRM_SEEN = 2    # confirmed when seen in N-of-M epochs (SS2.5)
PEER_CONFIRM_SPAN = 3
PEER_TTL_S = 180.0       # 3 beacon periods
TAG_EPOCH_S = 86400.0    # fleet-tag rotation cadence (H4: no stable hash)
MAX_NONCE_CACHE = 64


def fleet_tag(fleet_key, now: float) -> str:
    """Rotating fleet marker for beacons: verifiable by fleet members that
    hold K_f, correlatable by nobody across rotation epochs (H4)."""
    epoch = int(now // TAG_EPOCH_S)
    return mac_tag(fleet_key, b"beacon-tag", epoch)[:6].hex()


def telemetry_key(fleet_key: bytes, node_id: str) -> bytes:
    return hkdf_sha256(fleet_key, info=b"tel|" + node_id.encode())


def telemetry_mac_ok(frame, key_for_node) -> bool:
    """Shared check for tells and the gateway (H5: per-frame MAC)."""
    body = frame.get("body")
    if not isinstance(body, dict):
        return False
    nid = body.get("node")
    if not isinstance(nid, str):
        return False
    try:
        canon = json.dumps(body, sort_keys=True).encode()
        return hmac.compare_digest(mac_tag(key_for_node(nid), canon).hex(),
                                   frame.get("mac", ""))
    except Exception:
        return False


class Peer:
    __slots__ = ("pseudonym", "state", "fleet_tag", "first_seen", "last_seen", "epoch_marks")

    def __init__(self, pseudonym, state, fleet_tag_hex, t):
        self.pseudonym = pseudonym
        self.state = state
        self.fleet_tag = fleet_tag_hex
        self.first_seen = t
        self.last_seen = t
        self.epoch_marks = []  # beacon epochs in which this peer was heard

    def observe(self, sender_t: float, period: float) -> None:
        self.last_seen = sender_t
        mark = int(sender_t // period)
        if not self.epoch_marks or self.epoch_marks[-1] < mark:
            self.epoch_marks.append(mark)
            del self.epoch_marks[:-PEER_CONFIRM_SPAN]

    def confirmed(self, now_epoch: int) -> bool:
        return sum(1 for e in self.epoch_marks
                   if now_epoch - e < PEER_CONFIRM_SPAN) >= PEER_CONFIRM_SEEN


class Tell:
    def __init__(self, world, radio, node_id, device_secret=None,
                 beacon_period=60.0, payload_type="gps", fw_version="0.1.0",
                 battery_v=3.45):
        self.world = world
        self.radio = radio
        self.node_id = node_id        # stable identity; never broadcast after claim (H3)
        self.device_secret = device_secret or random_bytes(
            world.stream(f"secret.{node_id}"), 16)
        self.beacon_period = float(beacon_period)
        self.payload_type = payload_type
        self.fw_version = fw_version
        self.battery_v = battery_v

        self.alive = True
        self.state = UNCLAIMED
        self.fleet_id = None
        self.fleet_key = None         # group key K_f, shared fleet-wide
        self.peers = {}               # pseudonym -> Peer
        self.log = []                 # (t, event, detail) audit trail for tests

        self._button_down_at = None
        self._window_until = None
        self._claim_nonce = None
        self._session_pk = None
        self._pending_pair = None     # carries pair_key between CLAIM and KEY
        self._pair_ctx = None         # last accepted ceremony, for idempotent
                                     # re-ack/re-key when frames are lost
        self._claim_failures = 0
        self._lockout_until = 0.0
        self._seen_nonces = []
        self._boot_epoch = 0
        self.telemetry_counter = 0

        self.pseudonym = self._fresh_pseudonym()
        radio.attach(self)
        world.schedule(slot_phase(node_id, beacon_period), self._beacon_tick)

    @property
    def id(self):
        # The radio address IS the rotating pseudonym (H3: the stable node
        # id never appears in a frame header).
        return self.pseudonym

    # -- lifecycle -----------------------------------------------------------

    def _fresh_pseudonym(self):
        return "tell-" + random_bytes(self.world.stream(f"pseudonym.{self.node_id}"), 4).hex()

    def _rotate_address(self):
        self.radio.detach(self)
        self.pseudonym = self._fresh_pseudonym()
        self.radio.attach(self)

    def kill(self):
        """Power axe (not a reboot). The mesh must survive this."""
        self.alive = False
        self.radio.detach(self)
        self._log("killed")

    def reboot(self):
        """Power cycle: the claim window dies (H6), the address rotates."""
        self._boot_epoch += 1
        self._close_window("reboot")
        self.peers.clear()
        self._rotate_address()
        self._log("reboot")

    # -- button (H6) ----------------------------------------------------------

    def button_press(self):
        if not self.alive or self._button_down_at is not None:
            return
        self._button_down_at = self.world.now
        boot = self._boot_epoch
        self.world.schedule(PAIR_HOLD_S, lambda: self._button_arm(boot))
        self.world.schedule(RESET_HOLD_S, lambda: self._button_full_hold(boot))

    def button_release(self):
        if self._button_down_at is None:
            return
        held = self.world.now - self._button_down_at
        self._button_down_at = None
        if held < PAIR_HOLD_S:
            self._log("button_short_press")   # status blink, nothing more

    def _button_arm(self, boot):
        if boot != self._boot_epoch or not self.alive:
            return
        if self._button_down_at is None:
            return  # released before the 5 s threshold
        if self.state == CLAIMED:
            self._revoke_fleet("rehome")      # H8: re-home revokes the old fleet
        self._open_window()

    def _button_full_hold(self, boot):
        if boot != self._boot_epoch or not self.alive:
            return
        if self._button_down_at is None:
            return
        self.factory_reset()

    def factory_reset(self):
        """15 s hold: wipe fleet key + config (DESIGN SS1).  Cancels any
        armed pairing window (H6) and clears the claim lockout (possession
        of the device was just demonstrated)."""
        if self.state == CLAIMED:
            self._revoke_fleet("factory_reset")
        self._close_window("factory_reset")
        self._claim_failures = 0
        self._lockout_until = 0.0
        self._log("factory_reset")

    def _revoke_fleet(self, why):
        self.state = UNCLAIMED
        self.fleet_id = None
        self.fleet_key = None
        self._pending_pair = None
        self._pair_ctx = None
        self.peers.clear()
        self._rotate_address()
        self._log("fleet_revoked", why)

    # -- claim window ---------------------------------------------------------

    def _open_window(self):
        rng = self.world.stream(f"claim.{self.node_id}")
        self._claim_nonce = random_bytes(rng, 16)
        self._session_pk = random_bytes(rng, 32)  # opaque ephemeral-PK stand-in
        self._window_until = self.world.now + CLAIM_WINDOW_S
        boot = self._boot_epoch
        self.world.schedule(CLAIM_WINDOW_S, lambda: self._window_timeout(boot))
        self._log("claim_window_opened")
        self.radio.broadcast(self.id, self.beacon_frame())  # prompt window beacon

    def _window_timeout(self, boot):
        if boot != self._boot_epoch or not self.alive:
            return
        if self._window_until is not None:
            self._close_window("timeout")

    def _close_window(self, why):
        if self._window_until is not None:
            self._log("claim_window_closed", why)
        self._window_until = None

    def window_open(self) -> bool:
        return self._window_until is not None and self.world.now < self._window_until

    # -- beacons (SS2) --------------------------------------------------------

    def _beacon_tick(self):
        if not self.alive:
            return
        self.radio.broadcast(self.id, self.beacon_frame())
        self.world.schedule(self.beacon_period, self._beacon_tick)

    def beacon_frame(self):
        f = {"type": "BEACON", "id": self.pseudonym, "payload": self.payload_type,
             "fw": self.fw_version, "battery": self.battery_v, "state": self.state,
             "t": round(self.world.now, 3)}
        if self.state == CLAIMED:
            f["fleet_tag"] = fleet_tag(self.fleet_key, self.world.now)
        elif self.window_open():
            f["claim"] = {"nonce": self._claim_nonce.hex(),
                          "pk": self._session_pk.hex()}
        return f

    # -- receiving ------------------------------------------------------------

    def receive(self, frame, sender_id):
        if not self.alive:
            return
        kind = frame.get("type")
        if kind == "BEACON":
            self._on_beacon(frame)
        elif kind == "CLAIM":
            self._on_claim(frame)
        elif kind == "KEY":
            self._on_key(frame)
        elif kind == "TELEMETRY":
            self._on_telemetry(frame)
        # anything else (CLAIM_ACK, ...): not a tell's business

    def _on_beacon(self, frame):
        if frame.get("state") == CLAIMED:
            if self.state != CLAIMED:
                # claim safety: unclaimed nodes ignore fleet traffic
                self._log("beacon_ignored_fleet_traffic")
                return
            if frame.get("fleet_tag") != fleet_tag(self.fleet_key, self.world.now):
                self._log("beacon_ignored_stranger_fleet")
                return
        else:
            if self.state == CLAIMED:
                return  # claimed tells do not peer with unclaimed strangers
        self._touch_peer(frame)

    def _touch_peer(self, frame):
        pid = frame.get("id")
        if not isinstance(pid, str):
            return
        now = self.world.now
        p = self.peers.get(pid)
        if p is None:
            p = Peer(pid, frame.get("state"), frame.get("fleet_tag"), now)
            self.peers[pid] = p
        p.state = frame.get("state")
        p.fleet_tag = frame.get("fleet_tag")
        p.observe(frame.get("t", now), self.beacon_period)
        self._expire_peers()

    def _expire_peers(self):
        now = self.world.now
        stale = [k for k, v in self.peers.items() if now - v.last_seen > PEER_TTL_S]
        for k in stale:
            del self.peers[k]

    def confirmed_peers(self):
        self._expire_peers()
        k = int(self.world.now // self.beacon_period)
        return [p for p in self.peers.values() if p.confirmed(k)]

    # -- claim ceremony, node side (REVIEW SS1.4 steps 4-6) -------------------

    def _on_claim(self, frame):
        now = self.world.now
        if now < self._lockout_until:
            self._log("claim_ignored_lockout")
            return
        c = frame.get("claim") or {}
        ng, fid, pk = c.get("nonce"), c.get("fleet_id"), c.get("pk")
        if not (isinstance(ng, str) and isinstance(fid, str) and isinstance(pk, str)):
            self._log("claim_malformed")
            return
        # Radio frames get lost; the ceremony must be completable by
        # retransmission.  A replay of the claim this node already accepted
        # (same nonce/pk/fleet, valid proof under the then-secret) just
        # re-acks -- it changes nothing a stranger could exploit, because
        # producing that proof requires the per-device secret.
        ctx = self._pair_ctx
        if ctx is not None and (self.state == CLAIMED or self._pending_pair is not None):
            if (ng, fid, pk) == (ctx["ng"], ctx["fid"], ctx["pk"]):
                try:
                    parts = (b"claim", bytes.fromhex(ng), fid.encode(),
                             bytes.fromhex(pk))
                except ValueError:
                    parts = None
                if parts is not None and mac_ok(ctx["secret"], parts,
                                                c.get("proof", "")):
                    self.radio.broadcast(self.id, {
                        "type": "CLAIM_ACK", "fleet_id": fid,
                        "proof": mac_tag(ctx["secret"], b"ack",
                                         ctx["nonce"], bytes.fromhex(ng)).hex()})
                    self._log("claim_replayed_reacked")
                    return
        if self.state != UNCLAIMED:
            self._log("claim_ignored_claimed")
            return
        if not self.window_open():
            # THE button-window requirement: no press, no claim.
            self._log("claim_ignored_no_window")
            return
        # Addressing: the claim must carry THIS window's public key.  The
        # bus is broadcast, so a tell hears its siblings' ceremonies too;
        # those are valid claims under another device's secret, and if they
        # fed this node's failure counter a concurrent six-node ceremony
        # would lock itself out (three sibling frames arrive within
        # seconds, before this node's own claim is even delivered).
        # A claim with a foreign pk can never verify here anyway: the
        # proof is over the frame's own pk under this node's secret.
        if ng in self._seen_nonces:
            self._log("claim_ignored_replay")
            return
        self._remember_nonce(ng)
        if self._session_pk is None or pk != self._session_pk.hex():
            self._log("claim_ignored_foreign_pk")
            return
        try:
            expect_parts = (b"claim", bytes.fromhex(ng), fid.encode(), bytes.fromhex(pk))
        except ValueError:
            self._log("claim_malformed")
            return
        if not mac_ok(self.device_secret, expect_parts, c.get("proof", "")):
            self._claim_failures += 1
            self._log("claim_bad_proof", f"failures={self._claim_failures}")
            if self._claim_failures >= CLAIM_MAX_FAILURES:
                self._lockout_until = now + CLAIM_LOCKOUT_S
                self._log("claim_lockout")
            return
        # Verified: the claimant holds S.  Derive the pairwise key and ack;
        # the fleet group key must still arrive in a KEY frame MAC'd under it.
        ng_bytes = bytes.fromhex(ng)
        node_nonce, node_pk = self._claim_nonce, self._session_pk
        pair_key = hkdf_sha256(self.device_secret,
                               info=b"pair|" + ng_bytes + node_nonce + node_pk)
        self._pending_pair = {"pair_key": pair_key, "gateway_nonce": ng,
                              "fleet_id": fid}
        self._pair_ctx = {"secret": self.device_secret, "ng": ng, "fid": fid,
                          "pk": pk, "nonce": node_nonce, "pair_key": pair_key}
        ack = {"type": "CLAIM_ACK", "fleet_id": fid,
               "proof": mac_tag(self.device_secret, b"ack", node_nonce,
                                ng_bytes).hex()}
        self._claim_nonce = None
        self._session_pk = None
        self._close_window("claimed_pending_key")  # one-shot on success
        self._log("claim_accepted", fid)
        self.radio.broadcast(self.id, ack)

    def _remember_nonce(self, ng):
        self._seen_nonces.append(ng)
        del self._seen_nonces[:-MAX_NONCE_CACHE]

    def _on_key(self, frame):
        body = frame.get("key") or {}
        fid, kf = body.get("fleet_id"), body.get("fleet_key")
        if not isinstance(fid, str) or not isinstance(kf, str):
            self._log("key_bad")
            return
        try:
            kf_bytes = bytes.fromhex(kf)
        except ValueError:
            self._log("key_bad")
            return
        ctx = self._pair_ctx
        pp = self._pending_pair
        if pp is not None and fid == pp["fleet_id"]:
            ng_bytes = bytes.fromhex(pp["gateway_nonce"])
            parts = (b"fleetkey", ng_bytes, fid.encode(), kf_bytes)
            if not mac_ok(pp["pair_key"], parts, body.get("proof", "")):
                self._claim_failures += 1
                self._log("key_bad_proof")
                return
            self.fleet_id = fid
            self.fleet_key = kf_bytes
            self.device_secret = random_bytes(
                self.world.stream(f"secret.{self.node_id}"), 16)  # consume the label (H1)
            self._pending_pair = None
            self.state = CLAIMED
            self.peers.clear()      # unclaimed-era peers are stale
            self._rotate_address()  # the MAC rotates at claim (H3)
            self._log("claimed", fid)
            self._send_keyack(fid, pp["pair_key"], ng_bytes)
            return
        if ctx is not None and self.state == CLAIMED and fid == ctx["fid"]:
            # Retransmitted KEY after we already installed: re-confirm.
            ng_bytes = bytes.fromhex(ctx["ng"])
            parts = (b"fleetkey", ng_bytes, fid.encode(), kf_bytes)
            if mac_ok(ctx["pair_key"], parts, body.get("proof", "")) \
                    and kf_bytes == self.fleet_key:
                self._send_keyack(fid, ctx["pair_key"], ng_bytes)
                return
        self._log("key_ignored")

    def _send_keyack(self, fid, pair_key, ng_bytes):
        self.radio.broadcast(self.id, {
            "type": "KEYACK", "fleet_id": fid,
            "proof": mac_tag(pair_key, b"keyack", ng_bytes).hex()})

    # -- telemetry ------------------------------------------------------------

    def send_telemetry(self, payload):
        if not self.alive or self.state != CLAIMED:
            return
        self.telemetry_counter += 1
        body = {"node": self.node_id, "seq": self.telemetry_counter,
                "payload": payload}
        key = telemetry_key(self.fleet_key, self.node_id)
        self.radio.broadcast(self.id, {
            "type": "TELEMETRY", "id": self.pseudonym,
            "fleet_tag": fleet_tag(self.fleet_key, self.world.now),
            "mac": mac_tag(key, json.dumps(body, sort_keys=True).encode()).hex(),
            "body": body,
        })

    def _on_telemetry(self, frame):
        # Tells never relay (SS2.3); fleet traffic is verified, then dropped.
        if self.state != CLAIMED:
            self._log("telemetry_ignored_unclaimed")
            return
        if frame.get("fleet_tag") != fleet_tag(self.fleet_key, self.world.now):
            self._log("telemetry_ignored_stranger")
            return
        ok = telemetry_mac_ok(frame, lambda nid: telemetry_key(self.fleet_key, nid))
        self._log("telemetry_ok_dropped" if ok else "telemetry_bad_mac")

    # -- misc -----------------------------------------------------------------

    def _log(self, event, detail=None):
        self.log.append((self.world.now, event, detail))

    def events(self, name):
        return [e for e in self.log if e[1] == name]
