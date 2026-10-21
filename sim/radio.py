"""In-process broadcast bus, ESP-NOW-shaped.

Every frame is a broadcast heard by the whole radio cell (a boat is one
cell).  Knobs: per-link loss probability, latency with jitter, and an
optional range predicate.  The bus never inspects frame contents; security
lives at the application layer (REVIEW-MCODE SS1.3 H2), not here.
"""


class RadioBus:
    def __init__(self, world, loss=0.0, latency=0.010, jitter=0.005, in_range=None):
        self.world = world
        self.loss = float(loss)
        self.latency = float(latency)
        self.jitter = float(jitter)
        self.in_range = in_range  # optional fn(sender_id, dest_id) -> bool
        self.participants = {}    # id -> participant (has .id/.alive/.receive)
        self.rng = world.stream("radio")
        self.stats = {"tx": 0, "delivered": 0, "lost": 0, "out_of_range": 0}

    def attach(self, node) -> None:
        self.participants[node.id] = node

    def detach(self, node) -> None:
        self.participants.pop(node.id, None)

    def broadcast(self, sender_id, frame) -> None:
        self.stats["tx"] += 1
        for nid in sorted(self.participants):
            if nid == sender_id:
                continue
            if self.in_range is not None and not self.in_range(sender_id, nid):
                self.stats["out_of_range"] += 1
                continue
            if self.rng.random() < self.loss:
                self.stats["lost"] += 1
                continue
            delay = self.latency + self.jitter * (2.0 * self.rng.random() - 1.0)
            dest = self.participants[nid]
            self.world.schedule(max(0.0, delay),
                                lambda d=dest: self._deliver(d, frame, sender_id))

    def _deliver(self, dest, frame, sender_id) -> None:
        # The destination may have died or detached while the frame was in
        # flight; radio addresses rotate, so key off current membership.
        if dest.id not in self.participants:
            return
        if not getattr(dest, "alive", True):
            return
        self.stats["delivered"] += 1
        dest.receive(frame, sender_id)
