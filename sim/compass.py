"""Compass-line fusion: asynchronous noisy fixes -> heading + honest sigma.

REVIEW-MCODE SS4 governs this file; the binding points:

  SS4.3/4.8 -- fix error is NOT iid.  ErrorModel injects a white term, a
    common-mode OU term shared by all nodes (must cancel in the
    differential -- that is the design's real working principle), a
    per-node OU bias (does not cancel, does not average down within the
    correlation time), and a separate slower per-node multipath bias.

  SS4.4    -- heel/pitch/heave are applied as rigid-body motion to
    body-frame tell positions; heading comes from a full 3-D rigid
    (Umeyama/Kabsch) fit over all available points, which separates heel
    from yaw.  Per-node clock offsets exist and the fusion time-aligns by
    a per-node least-squares motion state (SS4.7) predicted at the fusion
    epoch; the residual along-track error v*offset is the honest floor of
    that correction.  A node whose latest fix is staler than max_skew_s
    is a GAP for that epoch (SS4.8.6): loss shortens the baseline, it
    never corrupts it.

  SS4.7    -- raw positions are never averaged across time.  Per epoch the
    transform is estimated from contemporaneous (aligned) positions; only
    the heading is time-averaged.

  SS4.3    -- reported sigma = sqrt(max(white-model, measured-wander)^2 +
    const-bias-prior^2): a floor, so averaging can never talk the
    uncertainty below what per-node bias permits.  The constant component
    (multipath constant over a run) is unidentifiable without a truth
    reference, so it is carried as an install-time prior -- stated, not
    smuggled.
"""

import math

from world import World, slot_phase

R2D = 180.0 / math.pi
D2R = math.pi / 180.0


# --------------------------------------------------------------------------
# small linear algebra (stdlib only): 3x3 ops + Jacobi eigendecomposition
# --------------------------------------------------------------------------

def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)]


def mat_vec(a, v):
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def mat_t(a):
    return [[a[j][i] for j in range(3)] for i in range(3)]


def jacobi_eig3(s):
    """Eigendecomposition of a symmetric 3x3 (cyclic Jacobi).
    Returns (eigenvalues, eigenvectors) with eigenvectors as COLUMNS of
    the returned matrix: s ~ V diag(w) V^T."""
    a = [row[:] for row in s]
    v = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for _ in range(30):
        off = a[0][1] ** 2 + a[0][2] ** 2 + a[1][2] ** 2
        diag = a[0][0] ** 2 + a[1][1] ** 2 + a[2][2] ** 2
        if off <= 1e-24 * (diag + 1e-300):
            break
        for p, q in ((0, 1), (0, 2), (1, 2)):
            if abs(a[p][q]) < 1e-18:
                continue
            theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
            t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
            c = 1.0 / math.sqrt(t * t + 1.0)
            s_ = t * c
            for k in range(3):
                akp, akq = a[k][p], a[k][q]
                a[k][p] = c * akp - s_ * akq
                a[k][q] = s_ * akp + c * akq
            for k in range(3):
                apk, aqk = a[p][k], a[q][k]
                a[p][k] = c * apk - s_ * aqk
                a[q][k] = s_ * apk + c * aqk
            for k in range(3):
                vkp, vkq = v[k][p], v[k][q]
                v[k][p] = c * vkp - s_ * vkq
                v[k][q] = s_ * vkp + c * vkq
    return [a[0][0], a[1][1], a[2][2]], v


def umeyama_rigid(body, world_pts, weights=None):
    """Best-fit rigid rotation+translation mapping body -> world points
    (no scale).  Optional per-point weights (SS4.2: a point's yaw
    information is its along-baseline lever squared, divided by its
    prediction variance).  Returns (R, t, yaw, pitch, roll) or None if
    degenerate.  Roll about the baseline is unobservable for exactly
    collinear points (SS4.4); the fit still recovers yaw/pitch, which is
    all we score."""
    n = len(body)
    if weights is None:
        weights = [1.0] * n
    wsum = sum(weights)
    if wsum <= 0.0:
        return None
    w = [x / wsum for x in weights]
    cb = [sum(wi * p[i] for wi, p in zip(w, body)) for i in range(3)]
    cw = [sum(wi * q[i] for wi, q in zip(w, world_pts)) for i in range(3)]
    h = [[0.0] * 3 for _ in range(3)]
    for wi, p, q in zip(w, body, world_pts):
        pb = [p[i] - cb[i] for i in range(3)]
        qw = [q[i] - cw[i] for i in range(3)]
        for i in range(3):
            for j in range(3):
                h[i][j] += wi * qw[i] * pb[j]
    s = mat_mul(mat_t(h), h)
    vals, vecs = jacobi_eig3(s)
    if min(vals) <= 1e-9:
        # Clamp near-zero eigenvalues (collinear/clouded geometry): the
        # baseline direction is still determined.
        vals = [max(x, 1e-9) for x in vals]
    d_inv = [[0.0] * 3 for _ in range(3)]
    for i in range(3):
        d_inv[i][i] = 1.0 / math.sqrt(vals[i])
    s_inv_half = mat_mul(vecs, mat_mul(d_inv, mat_t(vecs)))
    r = mat_mul(h, s_inv_half)
    det = (r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
           - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
           + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0]))
    if det < 0.0:
        # Reflection guard: flip along the smallest eigenvalue.
        idx = vals.index(min(vals))
        for i in range(3):
            vecs[i][idx] = -vecs[i][idx]
        s_inv_half = mat_mul(vecs, mat_mul(d_inv, mat_t(vecs)))
        r = mat_mul(h, s_inv_half)
    t = [cw[i] - mat_vec(r, cb)[i] for i in range(3)]
    yaw = math.atan2(r[0][0], r[1][0])
    pitch = math.asin(max(-1.0, min(1.0, -r[2][0])))
    roll = math.atan2(r[2][1], r[2][2])
    return r, t, yaw, pitch, roll


# --------------------------------------------------------------------------
# circular statistics
# --------------------------------------------------------------------------

def wrap180(deg):
    return (deg + 180.0) % 360.0 - 180.0


def circ_mean_rad(rads):
    s = sum(math.sin(x) for x in rads)
    c = sum(math.cos(x) for x in rads)
    return math.atan2(s, c)


def circ_wmean_rad(rads, weights):
    """Information-weighted circular mean: an epoch's weight is its lever
    sum, so a fit through a stub of the baseline (SS4.2: only the endpoints
    carry lever arm) cannot drag the window average the way an unweighted
    mean would."""
    s = sum(w * math.sin(x) for x, w in zip(rads, weights))
    c = sum(w * math.cos(x) for x, w in zip(rads, weights))
    return math.atan2(s, c)


def circ_sd_deg(degs):
    if len(degs) < 2:
        return 0.0
    s = sum(math.sin(x * D2R) for x in degs)
    c = sum(math.cos(x * D2R) for x in degs)
    r_bar = math.hypot(s, c) / len(degs)
    r_bar = min(1.0, max(1e-12, r_bar))
    return math.sqrt(-2.0 * math.log(r_bar)) * R2D


# --------------------------------------------------------------------------
# ground truth: the boat as a rigid body (SS4.4: heel, pitch, heave)
# --------------------------------------------------------------------------

def _rpy_matrix(yaw, pitch, roll):
    """R = Rz(yaw) Ry(pitch) Rx(roll) with body axes x forward, y port, z
    up, and `yaw` the compass azimuth (clockwise from north/ENU-n)."""
    az = math.pi / 2.0 - yaw          # mathematical angle from east
    cy, sy = math.cos(az), math.sin(az)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cr, sr = math.cos(roll), math.sin(roll)
    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]


class BoatTruth:
    def __init__(self, layout, heading_deg=42.0, swing_amp_deg=0.0,
                 swing_period_s=2700.0, heel_amp_deg=0.0, heel_period_s=620.0,
                 pitch_amp_deg=0.0, pitch_period_s=480.0, heave_amp_m=0.0,
                 heave_period_s=120.0):
        self.layout = dict(layout)
        self.heading0 = heading_deg
        self.swing_amp = swing_amp_deg
        self.swing_period = swing_period_s
        self.heel_amp = heel_amp_deg
        self.heel_period = heel_period_s
        self.pitch_amp = pitch_amp_deg
        self.pitch_period = pitch_period_s
        self.heave_amp = heave_amp_m
        self.heave_period = heave_period_s

    def pose(self, t):
        yaw = self.heading0 + (self.swing_amp * math.sin(2 * math.pi * t / self.swing_period)
                               if self.swing_amp else 0.0)
        heel = self.heel_amp * math.sin(2 * math.pi * t / self.heel_period) if self.heel_amp else 0.0
        pitch = self.pitch_amp * math.sin(2 * math.pi * t / self.pitch_period) if self.pitch_amp else 0.0
        heave = self.heave_amp * math.sin(2 * math.pi * t / self.heave_period) if self.heave_amp else 0.0
        return yaw, pitch, heel, heave

    def heading(self, t):
        return self.pose(t)[0]

    def node_pos(self, node_id, t):
        yaw, pitch, heel, heave = self.pose(t)
        r = _rpy_matrix(yaw * D2R, pitch * D2R, heel * D2R)
        p = self.layout[node_id]
        q = mat_vec(r, p)
        return (q[0], q[1], q[2] + heave)


# --------------------------------------------------------------------------
# error model (SS4.8: correlated components, not iid alone)
# --------------------------------------------------------------------------

def _ou_advance(x, dt, sigma, tau, rng):
    """Ornstein-Uhlenbeck step: bounded, mean-reverting, time-correlated."""
    if dt <= 0.0:
        return x
    a = math.exp(-dt / tau)
    return x * a + rng.gauss(0.0, sigma * math.sqrt(1.0 - a * a))


class ErrorModel:
    """Per-fix position error, by component:

      white   -- iid per fix per axis, sigma_white;
      common  -- ONE OU process shared by every node (atmosphere, ephemeris,
                 geometry): must cancel in node-to-node differencing;
      bias    -- an OU process PER node (receiver clock, local conditions),
                 correlation time of minutes: does not average down inside
                 the window;
      mult    -- a separate, slower OU PER node (multipath from each node's
                 own antenna/reflectors): effectively constant over a run.

    regime presets:
      independent -- white only (the naive model the brief asked for; kept
        so the falsehood it proves is measurable, not asserted);
      correlated  -- white + common + per-node bias + multipath (the
        physically honest model; REVIEW SS4.8's minimum).
    """

    def __init__(self, world, sigma_white=1.5, common_sigma=0.0, common_tau=1800.0,
                 bias_sigma=0.0, bias_tau=900.0, mult_sigma=0.0, mult_tau=14400.0):
        self.world = world
        self.sigma_white = sigma_white
        self.cs, self.ct = common_sigma, common_tau
        self.bs, self.bt = bias_sigma, bias_tau
        self.ms, self.mt = mult_sigma, mult_tau
        self._common = {"t": 0.0, "e": 0.0, "n": 0.0}
        self._node = {}

    @classmethod
    def independent(cls, world, sigma_white=1.5):
        return cls(world, sigma_white=sigma_white)

    @classmethod
    def correlated(cls, world, sigma_white=1.5, common_sigma=0.8, common_tau=1800.0,
                   bias_sigma=0.8, bias_tau=1800.0, mult_sigma=0.4, mult_tau=14400.0):
        # bias_tau = 30 min: the upper end of REVIEW SS4.8's "tau ~ 5-30
        # min" range.  At the shorter end a 30-min averaging window spans
        # several correlation times and the bias averages away, which
        # understates the floor SS4.3 puts at 4-6 deg; 30 min keeps the
        # floor honest over the windows this compass reports.
        return cls(world, sigma_white=sigma_white, common_sigma=common_sigma,
                   common_tau=common_tau, bias_sigma=bias_sigma, bias_tau=bias_tau,
                   mult_sigma=mult_sigma, mult_tau=mult_tau)

    def sample(self, node_id, t):
        """Error (de, dn, du) at true time t for node_id.  OU states start
        from their STATIONARY distribution (a real receiver's bias exists
        from power-on; starting at zero would understate early error)."""
        c = self._common
        c_rng = self.world.stream("gps.common")
        if not c.get("init"):
            c["e"] = c_rng.gauss(0.0, self.cs)
            c["n"] = c_rng.gauss(0.0, self.cs)
            c["init"] = True
        dt = t - c["t"]
        c["e"] = _ou_advance(c["e"], dt, self.cs, self.ct, c_rng)
        c["n"] = _ou_advance(c["n"], dt, self.cs, self.ct, c_rng)
        c["t"] = t
        st = self._node.get(node_id)
        if st is None:
            st = {"t": 0.0, "init": False}
            self._node[node_id] = st
        b_rng = self.world.stream(f"gps.{node_id}.bias")
        m_rng = self.world.stream(f"gps.{node_id}.mult")
        w_rng = self.world.stream(f"gps.{node_id}.white")
        if not st["init"]:
            st["be"] = b_rng.gauss(0.0, self.bs)
            st["bn"] = b_rng.gauss(0.0, self.bs)
            st["me"] = m_rng.gauss(0.0, self.ms)
            st["mn"] = m_rng.gauss(0.0, self.ms)
            st["init"] = True
        dt = t - st["t"]
        st["be"] = _ou_advance(st["be"], dt, self.bs, self.bt, b_rng)
        st["bn"] = _ou_advance(st["bn"], dt, self.bs, self.bt, b_rng)
        st["me"] = _ou_advance(st["me"], dt, self.ms, self.mt, m_rng)
        st["mn"] = _ou_advance(st["mn"], dt, self.ms, self.mt, m_rng)
        st["t"] = t
        de = (w_rng.gauss(0.0, self.sigma_white) + c["e"] + st["be"] + st["me"])
        dn = (w_rng.gauss(0.0, self.sigma_white) + c["n"] + st["bn"] + st["mn"])
        du = w_rng.gauss(0.0, self.sigma_white)
        return de, dn, du


# --------------------------------------------------------------------------
# fix generation: slotted, asynchronous, with per-node clock offsets
# --------------------------------------------------------------------------

class GPSPayload:
    """A tell's GNSS payload: one fix per interval at a slot hashed from the
    node id (SS2.5), timestamped by the node's own clock."""

    def __init__(self, node_id, truth, errors, world, sink, alive_fn=None,
                 interval=60.0, clock_sigma_s=1.5, sigma_reported=1.5):
        self.node_id = node_id
        self.truth = truth
        self.errors = errors
        self.world = world
        self.sink = sink                     # callable(fix_dict)
        self.alive_fn = alive_fn or (lambda: True)
        self.interval = interval
        self.sigma_reported = sigma_reported
        self.clock_offset = world.stream(f"clock.{node_id}").uniform(
            -clock_sigma_s, clock_sigma_s)
        self.fixes = 0
        world.schedule(slot_phase(node_id, interval), self._tick)

    def _tick(self):
        if not self.alive_fn():
            return
        t_true = self.world.now
        e, n, u = self.truth.node_pos(self.node_id, t_true)
        de, dn, du = self.errors.sample(self.node_id, t_true)
        fix = {"node": self.node_id,
               "t": t_true + self.clock_offset,   # the node's clock, not truth
               "pos": [e + de, n + dn, u + du],
               "sigma": self.sigma_reported}
        self.fixes += 1
        self.sink(fix)
        self.world.schedule(self.interval, self._tick)


# --------------------------------------------------------------------------
# the compass
# --------------------------------------------------------------------------

# Student-t inflation for a sd estimated from K window means: the factor
# (t_{0.975,K-1} / z_{0.975}) keeps a 95% interval honest with few windows.
_T95_INFL = {3: 1.624, 4: 1.416, 5: 1.312, 6: 1.249, 7: 1.207, 8: 1.177,
             9: 1.154, 10: 1.137, 12: 1.112, 15: 1.094, 18: 1.072,
             22: 1.058, 28: 1.045, 35: 1.036, 45: 1.028, 60: 1.021}


def _t95(k):
    keys = sorted(_T95_INFL)
    for kk in keys:
        if k <= kk:
            return _T95_INFL[kk]
    return 1.0


class _Epoch:
    __slots__ = ("t", "yaw", "s_layout", "fix_contrib", "n_nodes", "info")

    def __init__(self, t, yaw, s_layout, fix_contrib, n_nodes, info):
        self.t = t
        self.yaw = yaw
        self.s_layout = s_layout
        self.fix_contrib = fix_contrib   # {(node, fix_t): lever^2 / var}
        self.n_nodes = n_nodes
        self.info = info                 # total yaw information of the epoch


class Reading:
    __slots__ = ("t", "heading", "sigma", "n_nodes", "sigma_white", "sigma_emp",
                 "floor_const")

    def __init__(self, t, heading, sigma, n_nodes, sigma_white, sigma_emp,
                 floor_const):
        self.t = t
        self.heading = heading
        self.sigma = sigma
        self.n_nodes = n_nodes
        self.sigma_white = sigma_white      # model white floor at this window
        self.sigma_emp = sigma_emp          # measured wander (None when cold)
        self.floor_const = floor_const      # carried constant-bias prior

    def as_tuple(self):
        return (self.t, self.heading, self.sigma, self.n_nodes)


class Compass:
    def __init__(self, layout, epoch_s=30.0, window_s=600.0, freshness_s=150.0,
                 const_bias_prior_m=0.0, history_windows=6.0, cold_infl=1.6,
                 max_skew_s=90.0, vel_prior_mps=0.05):
        self.layout = dict(layout)
        self.epoch_s = epoch_s
        self.window_s = window_s
        self.freshness_s = freshness_s
        self.const_bias_prior_m = const_bias_prior_m
        self.history_windows = history_windows
        self.cold_infl = cold_infl
        self.max_skew_s = max_skew_s
        self.vel_prior_mps = vel_prior_mps
        self.tracks = {}          # node -> list of (t, pos, sigma)
        self.history = []         # _Epoch records
        self._sigma_fix = 1.5

    # -- ingest ---------------------------------------------------------------

    def ingest(self, fix):
        tr = self.tracks.setdefault(fix["node"], [])
        tr.append((fix["t"], fix["pos"], fix.get("sigma", self._sigma_fix)))
        del tr[:-40]
        self._sigma_fix = fix.get("sigma", self._sigma_fix)

    # -- per-epoch estimation (SS4.7: transform per epoch, never avg positions)

    @staticmethod
    def _predict(track, t, lam=0.0):
        """Linear motion (position + velocity) through the node's fresh
        track, predicted at the fusion epoch: SS4.7's per-node state
        estimate, with the velocity ridge-regularized toward zero
        (SS4.6's process model; this is the at-anchor estimator of
        SS4.5 -- a boat's swing rates are ~1e-4 rad/s, so a slope built
        from two noisy fixes is noise, not motion).  lam = (sigma_fix /
        sigma_v_prior)^2.  Returns (pos, var_factor) with var_factor the
        prediction variance in units of sigma_fix^2, computed from the
        exact effective weights on the fixes (they sum to 1, so a
        per-node bias passes through undamped -- the floor survives)."""
        k = len(track)
        if k == 1:
            return list(track[0][1]), 1.0
        tbar = sum(f[0] for f in track) / k
        stt = sum((f[0] - tbar) ** 2 for f in track)
        if stt <= 1.0:
            return list(track[-1][1]), 1.0
        denom = stt + lam
        dt = t - tbar
        ws = [1.0 / k + (f[0] - tbar) * dt / denom for f in track]
        var = sum(w * w for w in ws)
        out = []
        for i in range(3):
            pbar = sum(f[1][i] for f in track) / k
            v = sum((f[0] - tbar) * (f[1][i] - pbar) for f in track) / denom
            out.append(pbar + v * dt)
        return out, var

    def _aligned(self, t):
        """Per-node state at epoch t as {node: (pos, var_factor)}, from
        fixes no older than freshness_s.  A node whose latest fix is older
        than max_skew_s is a GAP for this epoch (SS4.8.6): it sits out
        rather than being projected many slot-times along a velocity
        estimated from noisy fixes -- radio loss must shorten the
        baseline, never corrupt it."""
        out = {}
        for nid, tr in self.tracks.items():
            recent = [f for f in tr if t - f[0] <= self.freshness_s]
            if not recent:
                continue
            recent.sort(key=lambda f: f[0])
            if t - recent[-1][0] > self.max_skew_s:
                continue
            sig = recent[-1][2]
            lam = (sig / self.vel_prior_mps) ** 2 if self.vel_prior_mps > 0 else 0.0
            out[nid] = self._predict(recent, t, lam)
        return out

    def fuse(self, t):
        aligned = self._aligned(t)
        nids = [nid for nid in sorted(aligned) if nid in self.layout]
        if len(nids) < 2:
            return None
        xs = [self.layout[nid][0] for nid in nids]
        xbar = sum(xs) / len(xs)
        s_layout = sum((x - xbar) ** 2 for x in xs)
        if s_layout < 4.0:
            return None  # degenerate geometry (all tells at one station)
        # Yaw information per SS4.2/SS4.4: lever arm squared over prediction
        # variance.  The midships pair carries no yaw lever and must never
        # set heading (an athwartships 3 m separation plus fix noise swings
        # a subset fit by tens of degrees); a node extrapolated hard across
        # a radio gap is heard from, just not believed.
        weights = [(self.layout[nid][0] - xbar) ** 2 / aligned[nid][1]
                   for nid in nids]
        info = sum(weights)
        if info <= 0.0:
            return None  # no endpoint survived: heading is a gap this epoch
        fix_contrib = {(nid, self.tracks[nid][-1][0]): w
                       for nid, w in zip(nids, weights)}
        body = [self.layout[nid] for nid in nids]
        world_pts = [aligned[nid][0] for nid in nids]
        if len(nids) >= 3:
            fit = umeyama_rigid(body, world_pts, weights)
            if fit is None:
                return None
            yaw = fit[2]
        else:
            # Two tells left: the axis through them, fore end to aft end.
            fore, aft = (nids[1], nids[0]) if xs[1] > xs[0] else (nids[0], nids[1])
            yaw = math.atan2(aligned[fore][0][0] - aligned[aft][0][0],
                             aligned[fore][0][1] - aligned[aft][0][1])
        ep = _Epoch(t, yaw, s_layout, fix_contrib, len(nids), info)
        self.history.append(ep)
        cut = t - self.window_s * self.history_windows
        self.history = [e for e in self.history if e.t >= cut]
        return ep

    # -- reporting ------------------------------------------------------------

    def _white_floor(self, t):
        """Model white term: sigma_fix / sqrt(sum of lever-arm-squared over
        the DISTINCT fixes feeding this window) (SS4.2)."""
        contribs = {}
        for ep in self.history:
            if ep.t > t - self.window_s:
                for key, c in ep.fix_contrib.items():
                    contribs.setdefault(key, c)
        s_dist = sum(contribs.values())
        if s_dist <= 0.0:
            return None
        return self._sigma_fix / math.sqrt(s_dist) * R2D

    def _const_floor(self):
        """Carried prior for the constant per-node component (SS4.3):
        sqrt(2) * prior / lever arm of the CURRENT geometry."""
        if self.const_bias_prior_m <= 0.0 or not self.history:
            return 0.0
        return math.sqrt(2.0) * self.const_bias_prior_m / math.sqrt(
            self.history[-1].s_layout) * R2D

    def _wander(self, t):
        """Measured slow wander of window means (the OU-bias part of the
        floor, estimated from the estimator's own output).  Returns
        (sigma_emp_deg, K) or (None, 0) when history is too short."""
        if not self.history:
            return None, 0
        t_end = self.history[-1].t
        span = t_end - self.history[0].t
        k = int(span // self.window_s)
        if k < 4:
            return None, 0
        means = []
        for j in range(k):
            lo = t_end - (j + 1) * self.window_s
            hi = t_end - j * self.window_s
            eps = [e for e in self.history if lo < e.t <= hi]
            if eps:
                means.append(circ_wmean_rad([e.yaw for e in eps],
                                            [e.info for e in eps]) * R2D)
        if len(means) < 4:
            return None, 0
        return circ_sd_deg(means) * _t95(len(means)), len(means)

    def report(self, t):
        win = [e for e in self.history if e.t > t - self.window_s]
        if not win:
            return None
        heading = circ_wmean_rad([e.yaw for e in win],
                                 [e.info for e in win]) * R2D
        n_nodes = max(e.n_nodes for e in win)
        white = self._white_floor(t)
        if white is None:
            return None
        floor_const = self._const_floor()
        sigma_emp, k = self._wander(t)
        if sigma_emp is None:
            # Cold start: no wander estimate yet -- be conservative.
            sigma = math.sqrt((white * self.cold_infl) ** 2 + floor_const ** 2)
        else:
            sigma = math.sqrt(max(white, sigma_emp) ** 2 + floor_const ** 2)
        return Reading(t, heading, sigma, n_nodes, white, sigma_emp, floor_const)


# --------------------------------------------------------------------------
# one-trial driver shared by tests, demo, and the calibration table
# --------------------------------------------------------------------------

DEFAULT_LAYOUT = {
    # body frame: x forward (m from midships), y port, z up; 15 m baseline,
    # bow/stern/midships pairs (DESIGN SS5).
    "bow-p": (7.5, 1.5, 1.2), "bow-s": (7.5, -1.5, 1.2),
    "mid-p": (0.0, 1.5, 0.9), "mid-s": (0.0, -1.5, 0.9),
    "stn-p": (-7.5, 1.5, 1.2), "stn-s": (-7.5, -1.5, 1.2),
}


def run_trial(seed, regime="independent", duration=5400.0, heading_deg=42.0,
              swing_amp_deg=0.0, heel_amp_deg=0.0, pitch_amp_deg=0.0,
              heave_amp_m=0.0, loss=0.0, latency=0.010, kill_node=None,
              kill_at=None, const_bias_prior_m=None, epoch_s=30.0,
              window_s=600.0, radioed=False, sigma_white=1.5):
    """Run one compass trial.  Returns (readings, truth, world).  With
    radioed=False fixes flow straight into the compass (fast path); with
    radioed=True they cross a lossy RadioBus through a real claimed fleet."""
    from node import Tell
    from radio import RadioBus

    world = World(seed)
    truth = BoatTruth(DEFAULT_LAYOUT, heading_deg=heading_deg,
                      swing_amp_deg=swing_amp_deg, heel_amp_deg=heel_amp_deg,
                      pitch_amp_deg=pitch_amp_deg, heave_amp_m=heave_amp_m)
    if regime == "correlated":
        errors = ErrorModel.correlated(world, sigma_white=sigma_white)
        prior = 0.4 if const_bias_prior_m is None else const_bias_prior_m
    else:
        errors = ErrorModel.independent(world, sigma_white=sigma_white)
        prior = 0.0 if const_bias_prior_m is None else const_bias_prior_m
    compass = Compass(DEFAULT_LAYOUT, epoch_s=epoch_s, window_s=window_s,
                      const_bias_prior_m=prior)

    nodes = {}
    if radioed:
        from fleet import Gateway, claim_fleet
        bus = RadioBus(world, loss=loss, latency=latency)
        gw = Gateway(world, bus, fleet_id="boat")
        for nid in DEFAULT_LAYOUT:
            nodes[nid] = Tell(world, bus, nid)
        done_by = claim_fleet(world, gw, list(nodes.values()))
        world.run(done_by)
        sink_for = {nid: n.send_telemetry for nid, n in nodes.items()}
        alive = {nid: (lambda n=n: n.alive) for nid, n in nodes.items()}
        gw.on_fix = compass.ingest
    else:
        sink_for = {nid: compass.ingest for nid in DEFAULT_LAYOUT}
        flags = {nid: True for nid in DEFAULT_LAYOUT}
        alive = {nid: (lambda nid=nid: flags[nid]) for nid in DEFAULT_LAYOUT}

    for nid in DEFAULT_LAYOUT:
        GPSPayload(nid, truth, errors, world, sink=sink_for[nid],
                   alive_fn=alive[nid])

    if kill_node is not None:
        if radioed:
            world.schedule(kill_at - world.now, nodes[kill_node].kill)
        else:
            def _kill(nid=kill_node):
                flags[nid] = False
            world.schedule(kill_at - world.now, _kill)

    readings = []
    truth_log = []

    def _epoch_tick():
        t = world.now
        compass.fuse(t)
        r = compass.report(t)
        if r is not None:
            readings.append(r)
            truth_log.append((t, truth.heading(t)))
        world.schedule(epoch_s, _epoch_tick)

    world.schedule(epoch_s, _epoch_tick)
    world.run(duration)
    return readings, truth_log, world


def coverage95(readings, truth_log, after_s=None):
    """Fraction of readings whose 95% interval contains the true heading."""
    n = hit = 0
    for r, (t, psi_true) in zip(readings, truth_log):
        if after_s is not None and t < after_s:
            continue
        n += 1
        if abs(wrap180(r.heading - psi_true)) <= 1.959964 * r.sigma:
            hit += 1
    return hit / n if n else 0.0
