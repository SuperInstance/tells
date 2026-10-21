"""Kernel + radio bus tests: determinism, ordering, loss, latency."""

import unittest

from radio import RadioBus
from world import World, slot_phase


class _Sink:
    def __init__(self, sid, world):
        self.id = sid
        self.alive = True
        self.world = world
        self.received = []

    def receive(self, frame, sender_id):
        self.received.append((self.world.now, sender_id, frame))


class TestWorld(unittest.TestCase):
    def test_stream_is_stable_and_separated(self):
        w = World(7)
        a1 = w.stream("a").random()
        a2 = w.stream("a").random()  # same stream object -> next draw
        w2 = World(7)
        b1 = w2.stream("a").random()
        c1 = w2.stream("b").random()
        self.assertNotEqual(a1, a2)          # stream state persists
        w3 = World(7)
        self.assertEqual(w3.stream("a").random(), a1)  # same seed -> same draw
        w4 = World(8)
        self.assertNotEqual(a1, w4.stream("a").random())  # new seed -> new numbers
        self.assertNotEqual(a1, w2.stream("b").random())  # new name -> new numbers

    def test_events_run_in_time_then_seq_order(self):
        w = World(0)
        order = []
        w.schedule(2.0, lambda: order.append("t2a"))
        w.schedule(1.0, lambda: order.append("t1"))
        w.schedule(2.0, lambda: order.append("t2b"))
        w.schedule(0.5, lambda: order.append("t0.5"))
        n = w.run(10.0)
        self.assertEqual(order, ["t0.5", "t1", "t2a", "t2b"])
        self.assertEqual(n, 4)
        self.assertEqual(w.now, 10.0)

    def test_run_stops_at_until(self):
        w = World(0)
        hits = []
        w.schedule(5.0, lambda: hits.append(1))
        w.run(2.0)
        self.assertEqual(hits, [])
        self.assertEqual(w.now, 2.0)
        w.run(5.0)
        self.assertEqual(hits, [1])

    def test_slot_phase_stable_and_bounded(self):
        self.assertEqual(slot_phase("bow", 60.0), slot_phase("bow", 60.0))
        self.assertTrue(0.0 <= slot_phase("bow", 60.0) < 60.0)
        phases = {slot_phase(f"n{i}", 60.0) for i in range(8)}
        self.assertGreater(len(phases), 1)  # not all aligned


class TestRadioBus(unittest.TestCase):
    def _world_with_sinks(self, seed=3, **kw):
        w = World(seed)
        bus = RadioBus(w, **kw)
        sinks = [_Sink(f"s{i}", w) for i in range(3)]
        for s in sinks:
            bus.attach(s)
        return w, bus, sinks

    def test_delivery_to_all_others_with_latency(self):
        w, bus, sinks = self._world_with_sinks(latency=0.5, jitter=0.0)
        bus.broadcast("s0", {"type": "PING"})
        w.run(2.0)
        for s in sinks[1:]:
            self.assertEqual(len(s.received), 1)
            self.assertGreaterEqual(s.received[0][0], 0.5)
        self.assertEqual(sinks[0].received, [])  # sender does not hear itself
        self.assertEqual(bus.stats["delivered"], 2)

    def test_loss_is_deterministic(self):
        counts = []
        for _ in range(2):
            w, bus, sinks = self._world_with_sinks(seed=11, loss=0.5)
            bus.broadcast("s0", {"type": "X"})
            w.run(1.0)
            counts.append(sum(len(s.received) for s in sinks))
        self.assertEqual(counts[0], counts[1])

    def test_total_loss_drops_everything(self):
        w, bus, sinks = self._world_with_sinks(loss=1.0)
        bus.broadcast("s0", {"type": "X"})
        w.run(1.0)
        self.assertEqual(bus.stats["lost"], 2)
        self.assertEqual(bus.stats["delivered"], 0)

    def test_range_predicate_excludes_links(self):
        w, bus, sinks = self._world_with_sinks(in_range=lambda a, b: b != "s2")
        bus.broadcast("s0", {"type": "X"})
        w.run(1.0)
        self.assertEqual(len(sinks[1].received), 1)
        self.assertEqual(sinks[2].received, [])
        self.assertEqual(bus.stats["out_of_range"], 1)

    def test_dead_or_detached_participant_not_delivered(self):
        w, bus, sinks = self._world_with_sinks()
        sinks[2].alive = False          # killed: scheduled frames are dropped
        bus.broadcast("s0", {"type": "X"})
        bus.detach(sinks[1])            # detached: filtered before scheduling
        w.run(1.0)
        self.assertEqual(len(sinks[1].received), 0)
        self.assertEqual(len(sinks[2].received), 0)
        self.assertEqual(len(sinks[0].received), 0)

    def test_two_worlds_same_seed_same_trace(self):
        traces = []
        for _ in range(2):
            w, bus, sinks = self._world_with_sinks(seed=99, loss=0.3, jitter=0.01)
            for i in range(20):
                bus.broadcast(f"s{i % 3}", {"type": "X", "i": i})
            w.run(2.0)
            traces.append([len(s.received) for s in sinks] + [dict(bus.stats)])
        self.assertEqual(traces[0], traces[1])


if __name__ == "__main__":
    unittest.main()
