# Tells

*Named for a sailor's tells — the little streamers on a sail that reveal what the wind is doing.*

A **tell** is a small, sealed, single-purpose sensor node: an ESP32, one payload
(GPS in the reference design), a battery, and a small solar panel. You stick it
somewhere and it just works — for seasons. Tells find each other on their own over
**ESP-NOW**, with **no leader and no infrastructure**: power a few on near each
other and they form a mesh that knows it's a mesh.

- **Leaderless.** No node is in charge. Discovery is organic: nodes beacon,
  listen, and keep peer tables. Kill any node and the rest carry on.
- **Claimed, not configured.** A gateway (any laptop, Pi, or Jetson running the
  tells gateway) claims unclaimed nodes into a *fleet* — "these belong to this
  boat." New nodes are claimed the same way when they're installed. One button
  on the node: long-press re-enters pairing, longer-press restores factory state.
- **Frugal.** Telemetry is milliwatt-cheap, so nodes mostly whisper continuously
  and sleep deeply between duties, topping up their batteries whenever the sun
  is up. If nobody is listening, they idle down to almost nothing.
- **Single-purpose by design.** A tell knows one thing and knows it well. Rich
  interpretation lives up the ladder — gateway, Jetson, cloud — never in the node.

## Reference mission: the compass line

Half a dozen GPS tells spaced along a 50-foot boat. No single GPS can say which
way a nearly-stationary boat is pointing — but a line of them, reporting
asynchronously and fused over time, yields heading, yaw, and anchor swing that
no one node possesses. The compass exists only at the fleet level.

## Status

Design + host-side simulation first (the protocol and fusion math are provable
without hardware). Firmware targets ESP-IDF on ESP32-S3/C6.

See [DESIGN.md](DESIGN.md) for the architecture and open questions.
