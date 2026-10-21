"""Node tests: button state machine, peer table, claim verification rules."""

import unittest

from crypto import hkdf_sha256, mac_tag, random_bytes
from node import (CLAIMED, UNCLAIMED, Peer, Tell, fleet_tag, telemetry_key,
                  telemetry_mac_ok)
from radio import RadioBus
from world import World


def make_node(seed=1, nid="a", **kw):
    w = World(seed)
    bus = RadioBus(w)
    return w, bus, Tell(w, bus, nid, **kw)


def open_window(node, world, at=None):
    if at is not None:
        world.run(at)
    node.button_press()
    world.run(world.now + 5.1)   # cross the 5 s arm threshold
    node.button_release()


def craft_claim(node, fleet_id="boat", secret=None, nonce=None, pk=None):
    secret = node.device_secret if secret is None else secret
    nonce = nonce or random_bytes(node.world.stream("test.claim"), 16)
    if pk is None:
        pk = node._session_pk or random_bytes(node.world.stream("test.pk"), 32)
    return {"type": "CLAIM", "claim": {
        "nonce": nonce.hex(), "fleet_id": fleet_id, "pk": pk.hex(),
        "proof": mac_tag(secret, b"claim", nonce, fleet_id.encode(), pk).hex()}}, nonce


def craft_key(node, fleet_id="boat", fleet_key=None, pair_key=None, ng_hex=None):
    pp = node._pending_pair
    pair_key = pair_key if pair_key is not None else pp["pair_key"]
    ng_hex = ng_hex if ng_hex is not None else pp["gateway_nonce"]
    fleet_key = fleet_key or random_bytes(node.world.stream("test.key"), 32)
    return {"type": "KEY", "key": {
        "fleet_id": fleet_id, "fleet_key": fleet_key.hex(),
        "proof": mac_tag(pair_key, b"fleetkey", bytes.fromhex(ng_hex),
                         fleet_id.encode(), fleet_key).hex()}}, fleet_key


class TestButton(unittest.TestCase):
    def test_short_press_is_just_a_blink(self):
        w, _, n = make_node()
        n.button_press()
        w.run(2.0)
        n.button_release()
        self.assertFalse(n.window_open())
        self.assertIn("button_short_press", [e[1] for e in n.log])

    def test_five_second_hold_opens_one_shot_window(self):
        w, _, n = make_node()
        n.button_press()
        w.run(6.0)
        n.button_release()
        self.assertTrue(n.window_open())
        w.run(70.0)
        self.assertFalse(n.window_open())
        closes = [e for e in n.log if e[1] == "claim_window_closed"]
        self.assertEqual(closes[-1][2], "timeout")

    def test_fifteen_second_hold_resets_and_cancels_window(self):
        w, _, n = make_node()
        n.button_press()
        w.run(6.0)
        self.assertTrue(n.window_open())      # armed on the way to 15 s...
        w.run(16.0)                           # ...but 15 s hold wins
        n.button_release()
        self.assertFalse(n.window_open())
        self.assertIn("factory_reset", [e[1] for e in n.log])
        closes = [e for e in n.log if e[1] == "claim_window_closed"]
        self.assertEqual(closes[-1][2], "factory_reset")   # H6: arm cancelled

    def test_reboot_closes_window(self):
        w, _, n = make_node()
        n.button_press()
        w.run(6.0)
        n.button_release()
        self.assertTrue(n.window_open())
        n.reboot()
        self.assertFalse(n.window_open())

    def test_factory_reset_wipes_fleet(self):
        w, _, n = make_node()
        n.state = CLAIMED
        n.fleet_id = "boat"
        n.fleet_key = b"\x11" * 32
        n.peers["x"] = Peer("x", CLAIMED, "aa", 0.0)
        n.factory_reset()
        self.assertEqual(n.state, UNCLAIMED)
        self.assertIsNone(n.fleet_key)
        self.assertEqual(n.peers, {})


class TestPeerTable(unittest.TestCase):
    def _fleet_pair(self):
        w = World(5)
        bus = RadioBus(w)
        a = Tell(w, bus, "a")
        b = Tell(w, bus, "b")
        for n in (a, b):
            n.state = CLAIMED
            n.fleet_id = "boat"
            n.fleet_key = b"\x22" * 32
        return w, bus, a, b

    def test_unclaimed_peers_discover_each_other(self):
        w = World(5)
        bus = RadioBus(w)
        a = Tell(w, bus, "a")
        b = Tell(w, bus, "b")
        w.run(200.0)  # several beacon epochs, hashed phases
        self.assertTrue(any(p.pseudonym == b.pseudonym for p in a.confirmed_peers()))

    def test_confirmed_needs_two_of_three_epochs(self):
        w = World(5)
        bus = RadioBus(w)
        a = Tell(w, bus, "a")
        b = Tell(w, bus, "b")
        # One manual beacon: heard, but not yet confirmed.
        a.receive(b.beacon_frame(), b.id)
        self.assertEqual(len(a.peers), 1)
        self.assertEqual(a.confirmed_peers(), [])
        a.receive(b.beacon_frame(), b.id)   # same epoch: still one epoch mark
        self.assertEqual(a.confirmed_peers(), [])

    def test_peers_expire_after_ttl(self):
        w, bus, a, b = self._fleet_pair()
        a.receive(b.beacon_frame(), b.id)   # seed the entry
        b.kill()                            # b goes silent for good
        w.run(200.0)                        # longer than PEER_TTL_S
        self.assertEqual(a.confirmed_peers(), [])
        self.assertEqual(a.peers, {})       # entry aged out

    def test_claimed_peers_match_fleet_tag(self):
        w, bus, a, b = self._fleet_pair()
        a.receive(b.beacon_frame(), b.id)
        self.assertEqual(len(a.peers), 1)
        stranger = Tell(w, bus, "c")
        stranger.state = CLAIMED
        stranger.fleet_id = "other"
        stranger.fleet_key = b"\x33" * 32
        a.receive(stranger.beacon_frame(), stranger.id)
        self.assertEqual(len(a.peers), 1)   # stranger fleet not peered
        self.assertIn("beacon_ignored_stranger_fleet", [e[1] for e in a.log])

    def test_unclaimed_node_ignores_fleet_traffic(self):
        # Brief test (b), leg 1: unclaimed nodes ignore fleet traffic.
        w, bus, a, b = self._fleet_pair()
        a.state = UNCLAIMED
        a.fleet_id = None
        a.fleet_key = None
        a.receive(b.beacon_frame(), b.id)                       # claimed beacon
        a.receive({"type": "TELEMETRY", "id": b.pseudonym,
                   "fleet_tag": fleet_tag(b.fleet_key, w.now),
                   "mac": "00", "body": {"node": "b", "seq": 1, "payload": {}}},
                  b.id)                                          # fleet telemetry
        self.assertEqual(a.peers, {})
        self.assertIn("beacon_ignored_fleet_traffic", [e[1] for e in a.log])
        self.assertIn("telemetry_ignored_unclaimed", [e[1] for e in a.log])


class TestClaimHandling(unittest.TestCase):
    def test_claim_without_window_is_ignored(self):
        w, _, n = make_node()
        frame, _ = craft_claim(n)
        n.receive(frame, "gw")
        self.assertEqual(n.state, UNCLAIMED)
        self.assertIn("claim_ignored_no_window", [e[1] for e in n.log])

    def test_valid_claim_claims_node_via_key_frame(self):
        w, _, n = make_node()
        open_window(n, w)
        frame, _ = craft_claim(n)
        n.receive(frame, "gw")
        self.assertIsNotNone(n._pending_pair)
        self.assertFalse(n.window_open())          # one-shot on success
        key, fleet_key = craft_key(n)
        n.receive(key, "gw")
        self.assertEqual(n.state, CLAIMED)
        self.assertEqual(n.fleet_id, "boat")
        self.assertEqual(n.fleet_key, fleet_key)
        # Label consumed: the pre-claim secret can no longer authenticate.
        self.assertNotEqual(n.device_secret, n._pending_pair)

    def test_bad_proofs_fail_and_lockout(self):
        w, _, n = make_node()
        open_window(n, w)
        wrong = b"\x44" * 16
        for i in range(3):
            frame, _ = craft_claim(n, secret=wrong)
            n.receive(frame, "stranger")
        self.assertEqual(n.state, UNCLAIMED)
        self.assertIn("claim_lockout", [e[1] for e in n.log])
        # Even a valid claim is refused during the lockout.
        good, _ = craft_claim(n)
        n.receive(good, "gw")
        self.assertEqual(n.state, UNCLAIMED)
        self.assertIn("claim_ignored_lockout", [e[1] for e in n.log])

    def test_lockout_expires_and_owner_recovers(self):
        w, _, n = make_node()
        open_window(n, w, at=10.0)
        wrong = b"\x44" * 16
        for _ in range(3):
            frame, _ = craft_claim(n, secret=wrong)
            n.receive(frame, "stranger")
        w.run(320.0)                                # cooldown passes, window too
        self.assertFalse(n.window_open())
        open_window(n, w)                           # fresh press: fresh window
        frame, _ = craft_claim(n)
        n.receive(frame, "gw")
        key, _ = craft_key(n)
        n.receive(key, "gw")
        self.assertEqual(n.state, CLAIMED)

    def test_replayed_nonce_is_rejected(self):
        w, _, n = make_node()
        open_window(n, w)
        frame, nonce = craft_claim(n, secret=b"\x44" * 16)  # fails proof anyway
        n.receive(frame, "stranger")
        n.receive(frame, "stranger")                 # exact replay
        bad = [e for e in n.log if e[1] == "claim_bad_proof"]
        self.assertEqual(len(bad), 1)                # second hit was a replay
        self.assertIn("claim_ignored_replay", [e[1] for e in n.log])

    def test_claimed_node_ignores_all_claims(self):
        w, _, n = make_node()
        open_window(n, w)
        frame, _ = craft_claim(n)
        n.receive(frame, "gw")
        key, _ = craft_key(n)
        n.receive(key, "gw")
        self.assertEqual(n.state, CLAIMED)
        again, _ = craft_claim(n, nonce=random_bytes(w.stream("x"), 16))
        n.receive(again, "whoever")
        self.assertIn("claim_ignored_claimed", [e[1] for e in n.log])
        self.assertEqual(n.state, CLAIMED)

    def test_key_frame_with_wrong_mac_is_rejected(self):
        w, _, n = make_node()
        open_window(n, w)
        frame, _ = craft_claim(n)
        n.receive(frame, "gw")
        bad = {"type": "KEY", "key": {"fleet_id": "boat",
                                      "fleet_key": (b"\x55" * 32).hex(),
                                      "proof": "00"}}
        n.receive(bad, "stranger")
        self.assertEqual(n.state, UNCLAIMED)
        self.assertIn("key_bad_proof", [e[1] for e in n.log])

    def test_fleet_tag_is_rotating_and_not_the_fleet_id(self):
        key = b"\x66" * 32
        t1 = fleet_tag(key, 0.0)
        t2 = fleet_tag(key, 86400.0 * 2)             # two tag epochs later
        self.assertNotEqual(t1, t2)                  # rotates (H4)
        self.assertNotIn("boat", t1)                 # leaks no fleet identity
        self.assertEqual(t1, fleet_tag(b"\x66" * 32, 5.0))    # stable within epoch
        self.assertNotEqual(t1, fleet_tag(b"\x77" * 32, 0.0)) # keyed


class TestTelemetryAuth(unittest.TestCase):
    def _claimed(self, with_sink=False):
        w = World(9)
        bus = RadioBus(w)
        n = Tell(w, bus, "a")
        sink = Tell(w, bus, "sink") if with_sink else None
        open_window(n, w)
        frame, _ = craft_claim(n)
        n.receive(frame, "gw")
        key, fleet_key = craft_key(n)
        n.receive(key, "gw")
        if sink is not None:
            sink.state = CLAIMED
            sink.fleet_id = n.fleet_id
            sink.fleet_key = fleet_key
        return w, n, fleet_key, sink

    def test_telemetry_frame_verifies_to_fleet_peers(self):
        w, n, fk, sink = self._claimed(with_sink=True)
        n.send_telemetry({"node": "a", "t": 1.0, "pos": [0, 0, 0], "sigma": 1.5})
        w.run(w.now + 1.0)                 # let the frame cross the air
        self.assertTrue(any(e[1] == "telemetry_ok_dropped" for e in sink.log))
        self.assertEqual(n.telemetry_counter, 1)

    def test_tampered_body_fails_mac(self):
        w, n, fk, _ = self._claimed()
        import json
        body = {"node": "a", "seq": 1, "payload": {"pos": [0, 0, 0]}}
        frame = {"type": "TELEMETRY", "id": "x",
                 "fleet_tag": fleet_tag(fk, w.now), "body": body,
                 "mac": mac_tag(telemetry_key(fk, "a"),
                                json.dumps(body, sort_keys=True).encode()).hex()}
        self.assertTrue(telemetry_mac_ok(frame, lambda nid: telemetry_key(fk, nid)))
        body["payload"]["pos"] = [999, 0, 0]        # tamper after signing
        self.assertFalse(telemetry_mac_ok(frame, lambda nid: telemetry_key(fk, nid)))

    def test_claimed_node_ignores_stranger_telemetry(self):
        w, n, fk, _ = self._claimed()
        stranger_tag = fleet_tag(b"\x99" * 32, w.now)
        n.receive({"type": "TELEMETRY", "id": "x", "fleet_tag": stranger_tag,
                   "mac": "00", "body": {"node": "x", "seq": 1, "payload": {}}},
                  "x")
        self.assertIn("telemetry_ignored_stranger", [e[1] for e in n.log])


if __name__ == "__main__":
    unittest.main()
