"""Deterministic discrete-event kernel for the tells simulator.

Everything runs on a World: a monotone clock, a priority queue of
callbacks, and named RNG streams.  Determinism rule: a component draws
randomness ONLY from its own named stream, so its numbers never depend on
how events interleave.  Same seed in, same trace out.
"""

import hashlib
import heapq
import random


def slot_phase(key: str, period: float) -> float:
    """Stable per-key offset inside `period` (REVIEW-MCODE SS2.5: hash the
    node id so co-located tells spread across the epoch instead of
    colliding)."""
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") % period


class World:
    def __init__(self, seed: int = 0):
        self.seed = int(seed)
        self.now = 0.0
        self._seq = 0
        self._queue = []  # (time, seq, callback)
        self._streams = {}

    def stream(self, name: str) -> random.Random:
        """A cached RNG stream: same (seed, name) -> same numbers, forever,
        independent of every other stream."""
        rng = self._streams.get(name)
        if rng is None:
            digest = hashlib.sha256(f"{self.seed}|{name}".encode()).digest()
            rng = random.Random(int.from_bytes(digest[:8], "big"))
            self._streams[name] = rng
        return rng

    def schedule(self, delay: float, fn) -> None:
        if delay < 0.0:
            delay = 0.0
        self._seq += 1
        heapq.heappush(self._queue, (self.now + delay, self._seq, fn))

    def run(self, until: float) -> int:
        """Advance to `until`, executing due callbacks in (time, seq) order.
        Returns the number of events executed."""
        n = 0
        while self._queue and self._queue[0][0] <= until:
            t, _, fn = heapq.heappop(self._queue)
            self.now = max(self.now, t)
            fn()
            n += 1
        self.now = max(self.now, until)
        return n

    def pending(self) -> int:
        return len(self._queue)
