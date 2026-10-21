"""Fleet tests: the SS1.4 ceremony end-to-end, and claim safety against
strangers, replays, and the old fleet (brief test b)."""

import unittest

from fleet import Gateway, Stranger, claim_fleet, press_button
from node import CLAIMED, UNCLAIMED, Tell, fleet_tag, telemetry_key
from radio import RadioBus
from world import World

NIDS = ["bow-p", "bow-s", "stn-p"]


def bring_up(seed=4, nids=NIDS, loss=0.0):
    w = World(seed)
    bus = RadioBus(w, loss=loss)
    gw = Gateway(w, bus, fleet_id="boat")
    nodes = [Tell(w, bus, nid) for nid in nids]
    done_by = claim_fleet(w, gw, nodes)
    w.run(done_by)
    return w, bus, gw, nodes


class TestCeremony(unittest.TestCase):
    def test_full_ceremony_claims_all(self):
        w, bus, gw, nodes = bring_up()
        for n in nodes:
            self.assertEqual(n.state, CLAIMED, n.node_id)
            self.assertEqual(n.fleet_id, "boat")
            self.assertEqual(n.fleet_key, gw.fleet_key)  # same K_f fleet-wide
            self.assertTrue(n.events("claimed"))
        self.assertEqual(set(gw.claimed), set(NIDS))

    def test_telemetry_flows_after_claim(self):
        w, bus, gw, nodes = bring_up()
        fixes = []
        gw.on_fix = fixes.append
        nodes[0].send_telemetry({"node": nodes[0].node_id, "t": 100.0,
                                 "pos": [1.0, 2.0, 0.0], "sigma": 1.5})
        w.run(w.now + 1.0)
        self.assertEqual(len(fixes), 1)
        self.assertEqual(len(gw.fix_log), 1)

    def test_claim_without_button_press_fails(self):
        # The button-window requirement: no press, no claim.
        w = World(5)
        bus = RadioBus(w)
        gw = Gateway(w, bus, "boat")
        n = Tell(w, bus, "bow-p")
        w.run(10.0)
        self.assertFalse(gw.claim_node(n))          # window not open
        w.run(w.now + 1.0)
        self.assertEqual(n.state, UNCLAIMED)
        self.assertTrue(gw.events("claim_refused_no_window"))
        # Now the owner presses: the same call succeeds.
        press_button(w, n, hold_s=6.0)
        w.run(w.now + 6.0)
        self.assertTrue(gw.claim_node(n))
        w.run(w.now + 1.0)
        self.assertEqual(n.state, CLAIMED)

    def test_window_expires_and_claims_stop_working(self):
        w = World(5)
        bus = RadioBus(w)
        gw = Gateway(w, bus, "boat")
        n = Tell(w, bus, "bow-p")
        press_button(w, n, hold_s=6.0, at=5.0)
        w.run(5.0 + 6.0)                    # window open
        self.assertTrue(gw.claim_node(n))
        w.run(5.0 + 6.0 + 1.0)
        self.assertEqual(n.state, CLAIMED)  # first claim landed

        n2 = Tell(w, bus, "stn-p")
        press_button(w, n2, hold_s=6.0, at=5.0)
        w.run(81.0)                                # window long expired
        self.assertFalse(gw.claim_node(n2))
        self.assertEqual(n2.state, UNCLAIMED)


class TestClaimSafety(unittest.TestCase):
    def test_stranger_claims_fail_and_lockout(self):
        w, bus, gw, nodes = bring_up(nids=["bow-p"])
        n = nodes[0]
        # Fresh unclaimed node with an open window for the stranger to hit.
        target = Tell(w, bus, "loose")
        press_button(w, target, hold_s=6.0, at=10.0)
        w.run(17.0)
        stranger = Stranger(w, bus)
        for _ in range(3):
            stranger.forged_claim(target_pk_hex="11" * 32)
            w.run(w.now + 0.1)
        self.assertEqual(target.state, UNCLAIMED)
        self.assertTrue(target.events("claim_lockout"))
        # Even the rightful owner is refused during the lockout...
        press_button(w, target, hold_s=6.0)     # fresh press, fresh window
        w.run(w.now + 6.0)
        self.assertTrue(gw.claim_node(target))
        w.run(w.now + 0.2)
        self.assertEqual(target.state, UNCLAIMED)
        # ...until the cooldown passes and a fresh press re-arms.
        w.run(target._lockout_until + 1.0)
        press_button(w, target, hold_s=6.0)
        w.run(w.now + 6.0)
        self.assertTrue(gw.claim_node(target))
        w.run(w.now + 0.5)
        self.assertEqual(target.state, CLAIMED)

    def test_claimed_nodes_ignore_stranger_claims(self):
        # Brief test (b), leg 2: claimed nodes ignore stranger claims.
        w, bus, gw, nodes = bring_up()
        stranger = Stranger(w, bus)
        for _ in range(5):
            stranger.forged_claim()
            w.run(w.now + 0.1)
        for n in nodes:
            self.assertEqual(n.state, CLAIMED)
            self.assertEqual(n.fleet_id, "boat")
            self.assertEqual(n.fleet_key, gw.fleet_key)
            self.assertTrue(n.events("claim_ignored_claimed"))

    def test_replayed_owner_claim_is_rejected(self):
        w, bus, gw, nodes = bring_up(nids=["bow-p"])
        n = nodes[0]
        # A radio-range stranger records a fresh, legitimate claim...
        recorded = []
        orig = bus.broadcast
        target = Tell(w, bus, "bow-s")
        press_button(w, target, hold_s=6.0, at=10.0)
        w.run(16.0)
        bus.broadcast = lambda sender, frame: (
            frame.get("type") == "CLAIM" and recorded.append(frame),
            orig(sender, frame))[1]
        gw.claim_node(target)
        w.run(w.now + 1.0)
        bus.broadcast = orig
        self.assertEqual(target.state, CLAIMED)
        self.assertEqual(len(recorded), 1)
        # ...node is factory-reset (fresh window on a fresh press) and the
        # stranger replays the recording inside it: refused.
        target.factory_reset()
        press_button(w, target, hold_s=6.0)
        w.run(w.now + 6.0)
        stranger = Stranger(w, bus)
        stranger._send(dict(recorded[0]))
        w.run(w.now + 1.0)
        self.assertEqual(target.state, UNCLAIMED)
        self.assertTrue(target.events("claim_ignored_replay") or
                        target.events("claim_bad_proof"))

    def test_stranger_cannot_steal_fleet_key_channel(self):
        # KEY frames are MAC'd under the S-derived pair key; a stranger's
        # injection cannot install a fleet key on a pending node.
        from test_node import craft_claim
        w = World(8)
        bus = RadioBus(w)
        gw = Gateway(w, bus, "boat")
        n = Tell(w, bus, "bow-p")
        press_button(w, n, hold_s=6.0)
        w.run(w.now + 6.0)
        frame, _ = craft_claim(n, fleet_id="boat")
        orig = bus.broadcast
        sent = []
        bus.broadcast = lambda s, f: (f.get("type") == "CLAIM_ACK" and sent.append(f),
                                      orig(s, f))[1]
        n.receive(frame, gw.id)          # hand-deliver the CLAIM; capture ack
        bus.broadcast = orig
        w.run(w.now + 0.5)
        self.assertEqual(len(sent), 1)
        self.assertIsNotNone(n._pending_pair)
        stranger = Stranger(w, bus)
        from crypto import mac_tag, random_bytes
        evil = random_bytes(w.stream("evil"), 32)
        stranger._send({"type": "KEY", "key": {
            "fleet_id": "boat", "fleet_key": evil.hex(),
            "proof": mac_tag(b"\x00" * 32, b"fleetkey", b"", b"", b"").hex()}})
        w.run(w.now + 0.5)
        self.assertEqual(n.state, UNCLAIMED)
        self.assertIsNone(n.fleet_key)
        self.assertTrue(n.events("key_bad_proof"))
        # The real gateway's KEY still lands afterwards (hand-delivered,
        # the ceremony's claim having bypassed the radio above).
        from test_node import craft_key
        key, _ = craft_key(n)
        n.receive(key, gw.id)
        self.assertEqual(n.state, CLAIMED)


class TestRehome(unittest.TestCase):
    def test_rehome_revokes_old_fleet(self):
        # H8: 5 s hold erases the old fleet; its traffic is refused after.
        w, bus, gw, nodes = bring_up()
        n = nodes[0]
        old_key = n.fleet_key
        press_button(w, n, hold_s=6.0)
        w.run(w.now + 6.0)
        self.assertEqual(n.state, UNCLAIMED)
        self.assertIsNone(n.fleet_key)
        self.assertTrue(n.events("fleet_revoked"))
        # Old-fleet telemetry is stranger traffic now.
        n.receive({"type": "TELEMETRY", "id": "x",
                   "fleet_tag": fleet_tag(old_key, w.now), "mac": "00",
                   "body": {"node": "bow-p", "seq": 99, "payload": {}}}, "x")
        self.assertTrue(n.events("telemetry_ignored_unclaimed") or
                        n.events("telemetry_ignored_stranger"))
        # Re-claim into a different fleet; the old fleet's key never returns.
        gw2 = Gateway(w, bus, fleet_id="other-boat")
        self.assertTrue(gw2.claim_node(n))
        w.run(w.now + 1.0)
        self.assertEqual(n.state, CLAIMED)
        self.assertEqual(n.fleet_id, "other-boat")
        self.assertNotEqual(n.fleet_key, old_key)
        # And the old gateway no longer accepts this node's telemetry.
        gw2_key = n.fleet_key
        n.send_telemetry({"node": "bow-p", "t": 1.0, "pos": [0, 0, 0],
                          "sigma": 1.5})
        w.run(w.now + 0.5)
        self.assertTrue(gw.events("telemetry_stranger"))


class TestTelemetryPath(unittest.TestCase):
    def test_replayed_telemetry_not_ingested_twice(self):
        w, bus, gw, nodes = bring_up(nids=["bow-p"])
        n = nodes[0]
        frames = []
        orig = bus.broadcast
        bus.broadcast = lambda s, f: (f.get("type") == "TELEMETRY" and frames.append(f),
                                      orig(s, f))[1]
        n.send_telemetry({"node": "bow-p", "t": 1.0, "pos": [0, 0, 0],
                          "sigma": 1.5})
        bus.broadcast = orig
        w.run(w.now + 0.5)
        self.assertEqual(len(gw.fix_log), 1)
        stranger = Stranger(w, bus)
        stranger._send(dict(frames[0]))          # exact replay of the frame
        w.run(w.now + 0.5)
        self.assertEqual(len(gw.fix_log), 1)     # not ingested twice
        self.assertTrue(gw.events("telemetry_replay"))

    def test_stranger_telemetry_rejected(self):
        w, bus, gw, nodes = bring_up()
        stranger = Stranger(w, bus)
        stranger.forged_telemetry(fleet_tag_hex="deadbeef")   # wrong tag
        stranger.forged_telemetry(fleet_tag_hex=gw.fleet_tag_now(),
                                  node_id="bow-p", seq=1)     # right tag, no MAC
        w.run(w.now + 0.5)
        self.assertEqual(gw.fix_log, [])
        self.assertEqual(len(gw.events("telemetry_stranger")), 1)
        self.assertEqual(len(gw.events("telemetry_bad_mac")), 1)


if __name__ == "__main__":
    unittest.main()
