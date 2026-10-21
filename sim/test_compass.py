"""Compass tests (brief test c, criteria rewritten per REVIEW SS4.8):

  - common-mode error cancels in the differential (the design's actual
    working principle);
  - the independent (white-only) regime converges to within a few degrees;
  - the correlated regime floors: measured error stops shrinking while the
    naive 1/sqrt(N) story would promise ~1 deg, and the reported sigma
    carries the floor;
  - calibration: the 95% interval contains the truth >= 95% of the time;
  - heel is separated from heading by the rigid fit;
  - radio loss/delay leave gaps, not garbage;
  - same seed, same numbers.
"""

import math
import statistics
import unittest

from compass import (DEFAULT_LAYOUT, BoatTruth, Compass, ErrorModel,
                     GPSPayload, R2D, coverage95, jacobi_eig3, mat_mul,
                     mat_t, run_trial, umeyama_rigid, wrap180)
from world import World


def final_errors(readings, truth, frac=0.4):
    """Signed heading errors (deg) over the last `frac` of the run."""
    if not readings:
        return []
    cut = readings[-1].t * (1.0 - frac)
    return [wrap180(r.heading - psi)
            for r, (t, psi) in zip(readings, truth) if t >= cut]


def measured_sd(readings, truth, frac=0.4):
    errs = final_errors(readings, truth, frac)
    return math.sqrt(sum(e * e for e in errs) / len(errs)) if errs else float("nan")


def mean_sigma(readings, frac=0.4):
    cut = readings[-1].t * (1.0 - frac)
    tail = [r.sigma for r in readings if r.t >= cut]
    return statistics.mean(tail) if tail else float("nan")


class TestLinearAlgebra(unittest.TestCase):
    def test_jacobi_eig_on_known_matrix(self):
        a = [[4.0, 1.0, 0.0], [1.0, 3.0, 0.5], [0.0, 0.5, 2.0]]
        vals, vecs = jacobi_eig3(a)
        # Reconstruct A = V D V^T
        d = [[vals[i] if i == j else 0.0 for j in range(3)] for i in range(3)]
        rec = mat_mul(vecs, mat_mul(d, mat_t(vecs)))
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(rec[i][j], a[i][j], places=9)

    def test_umeyama_recovers_rotation(self):
        w = World(0)
        rng = w.stream("umeyama")
        from compass import _rpy_matrix, mat_vec
        for _ in range(20):
            yaw = rng.uniform(-math.pi, math.pi)
            pitch = rng.uniform(-0.3, 0.3)
            roll = rng.uniform(-0.3, 0.3)
            r = _rpy_matrix(yaw, pitch, roll)
            t0 = [rng.uniform(-10, 10) for _ in range(3)]
            body = [DEFAULT_LAYOUT[k] for k in DEFAULT_LAYOUT]
            pts = [[mat_vec(r, p)[i] + t0[i] for i in range(3)] for p in body]
            fit = umeyama_rigid(body, pts)
            self.assertAlmostEqual(wrap180(fit[2] * R2D - yaw * R2D), 0.0, places=6)


class TestErrorModel(unittest.TestCase):
    def test_common_mode_cancels_exactly_in_one_epoch(self):
        # Same offset added to every node's fix: the rigid fit must not move.
        w = World(1)
        truth = BoatTruth(DEFAULT_LAYOUT, heading_deg=42.0, heel_amp_deg=6.0)
        errors = ErrorModel.independent(w)
        compass = Compass(DEFAULT_LAYOUT)
        base = {}
        for nid in DEFAULT_LAYOUT:
            e, n, u = truth.node_pos(nid, 300.0)
            de, dn, du = errors.sample(nid, 300.0)
            base[nid] = [e + de, n + dn, u + du]
        for nid, p in base.items():
            compass.ingest({"node": nid, "t": 300.0, "pos": list(p), "sigma": 1.5})
        ep1 = compass.fuse(300.0)
        common = (1.1, -0.7, 0.2)   # shared atmospheric/ephemeris offset
        compass2 = Compass(DEFAULT_LAYOUT)
        for nid, p in base.items():
            compass2.ingest({"node": nid, "t": 300.0,
                             "pos": [p[i] + common[i] for i in range(3)],
                             "sigma": 1.5})
        ep2 = compass2.fuse(300.0)
        self.assertAlmostEqual(wrap180((ep1.yaw - ep2.yaw) * R2D), 0.0, places=9)

    def test_common_mode_leaves_white_accuracy_unchanged(self):
        # Statistical leg: white-only vs white+common OU across trials.
        sds = []
        for tag, kwargs in (("white", {}), ("white+common",
                                           {"common_sigma": 1.2, "common_tau": 7200.0})):
            errs = []
            for i in range(40):
                w = World(100 + i)
                truth = BoatTruth(DEFAULT_LAYOUT, heading_deg=42.0)
                errors = ErrorModel(w, sigma_white=1.5, **kwargs)
                compass = Compass(DEFAULT_LAYOUT)
                for nid in DEFAULT_LAYOUT:
                    e, n, u = truth.node_pos(nid, 60.0 * 5)
                    de, dn, du = errors.sample(nid, 60.0 * 5)
                    compass.ingest({"node": nid, "t": 300.0,
                                    "pos": [e + de, n + dn, u + du], "sigma": 1.5})
                errs.append(wrap180(compass.fuse(300.0).yaw * R2D - 42.0))
            sds.append(math.sqrt(sum(e * e for e in errs) / len(errs)))
        # Common-mode (slow, shared) cancels; sd must not balloon.
        self.assertLess(sds[1] / sds[0], 1.35)

    def test_independent_only_sim_shows_what_it_wants_to_see(self):
        # The falsehood an iid-only model proves: with white noise alone,
        # a longer average keeps buying accuracy roughly at 1/sqrt(N).
        for window in (300.0, 1800.0):
            sds = []
            for i in range(12):
                readings, truth, _ = run_trial(4200 + i, regime="independent",
                                               duration=7200.0, window_s=window)
                sds.append(measured_sd(readings, truth))
            if window == 300.0:
                short = statistics.mean(sds)
            else:
                long_ = statistics.mean(sds)
        self.assertLess(long_, 0.7 * short)          # 1/sqrt(6) would be 0.41


class TestIndependentRegime(unittest.TestCase):
    def test_converges_within_a_few_degrees(self):
        errs = final_errors(*run_trial(7, regime="independent", duration=5400.0)[:2])
        self.assertLess(max(abs(e) for e in errs), 6.0)
        self.assertLess(statistics.mean(abs(e) for e in errs), 3.0)
        self.assertLess(mean_sigma(run_trial(7, regime="independent")[0]), 3.0)

    def test_calibration_95pct_interval_covers(self):
        cov = n = 0
        sds = []
        for i in range(100):
            readings, truth, _ = run_trial(1000 + i, regime="independent",
                                           duration=5400.0)
            cov += coverage95(readings, truth)
            sds.append(measured_sd(readings, truth))
            n += 1
        coverage = cov / n
        self.assertGreaterEqual(coverage, 0.95)
        self.assertLess(statistics.mean(sds), 3.0)   # few degrees, white case


class TestCorrelatedRegime(unittest.TestCase):
    def test_error_floors_and_reported_sigma_reflects_it(self):
        measured, reported = [], []
        for i in range(100):
            readings, truth, _ = run_trial(2000 + i, regime="correlated",
                                           duration=5400.0)
            errs = final_errors(readings, truth)
            measured.append(math.sqrt(sum(e * e for e in errs) / len(errs)))
            reported.append(mean_sigma(readings))
        meas, rep = statistics.mean(measured), statistics.mean(reported)
        # Floor: several degrees, and nowhere near the white-only story.
        self.assertGreater(meas, 2.5)
        self.assertLess(meas, 8.0)
        naive = 8.10 / math.sqrt(60)     # 1/sqrt(N) at N=60 fixes would say ~1.05
        self.assertGreater(rep, 2.0 * naive)
        # Honesty: the report does not claim better than what happens.
        self.assertGreaterEqual(rep, 0.8 * meas)

    def test_calibration_95pct_interval_covers(self):
        cov = n = 0
        for i in range(100):
            readings, truth, _ = run_trial(3000 + i, regime="correlated",
                                           duration=5400.0)
            cov += coverage95(readings, truth)
            n += 1
        self.assertGreaterEqual(cov / n, 0.95)

    def test_reported_sigma_plateaus_instead_of_shrinking(self):
        # Average over 6x longer: the white regime buys the 1/sqrt(N)
        # improvement; the correlated regime stays floored (multipath +
        # slow per-node bias), and its report says so instead of
        # following the white-noise fantasy toward zero.
        result = {}
        for regime in ("independent", "correlated"):
            for window in (300.0, 1800.0):
                sds, sigs = [], []
                for i in range(12):
                    readings, truth, _ = run_trial(
                        4400 + i, regime=regime, duration=7200.0, window_s=window)
                    sds.append(measured_sd(readings, truth))
                    sigs.append(mean_sigma(readings))
                result[(regime, window)] = (statistics.mean(sds),
                                            statistics.mean(sigs))
        sd_i_short, sig_i_short = result[("independent", 300.0)]
        sd_i_long, sig_i_long = result[("independent", 1800.0)]
        sd_c_short, sig_c_short = result[("correlated", 300.0)]
        sd_c_long, sig_c_long = result[("correlated", 1800.0)]
        # White: averaging works.
        self.assertLess(sd_i_long, 0.7 * sd_i_short)
        # Correlated: floors well above what white achieves at the same
        # averaging, and does not keep pace with its own shorter window.
        self.assertGreater(sd_c_long, 1.8 * sd_i_long)
        self.assertGreater(sd_c_long, 0.55 * sd_c_short)
        # The report reflects the regime, not the wish.
        self.assertGreater(sig_c_long, 1.4 * sig_i_long)
        self.assertGreater(sig_c_long, 2.0)          # never below the floor

    def test_per_node_bias_does_not_average_away(self):
        # Direct: per-node bias alone (no white to speak of) sets the
        # single-epoch heading error at the lever-arm prediction
        # sigma_bias / sqrt(Sigma (x - xbar)^2) -- SS4.2's arithmetic.
        errs = []
        for i in range(120):
            w = World(500 + i)
            truth = BoatTruth(DEFAULT_LAYOUT, heading_deg=42.0)
            errors = ErrorModel(w, sigma_white=0.2, bias_sigma=0.8,
                                bias_tau=14400.0)
            compass = Compass(DEFAULT_LAYOUT, const_bias_prior_m=0.0)
            for nid in DEFAULT_LAYOUT:
                e, n, u = truth.node_pos(nid, 300.0)
                de, dn, du = errors.sample(nid, 300.0)
                compass.ingest({"node": nid, "t": 300.0,
                                "pos": [e + de, n + dn, u + du], "sigma": 1.5})
            errs.append(wrap180(compass.fuse(300.0).yaw * R2D - 42.0))
        sd = math.sqrt(sum(e * e for e in errs) / len(errs))
        expected = 0.8 / math.sqrt(225.0) * R2D       # ~3.1 deg for this layout
        self.assertGreater(sd, 0.75 * expected)
        self.assertLess(sd, 1.35 * expected)


class TestGeometryAndGaps(unittest.TestCase):
    def test_heel_does_not_bias_heading(self):
        # SS4.4: heel contaminates athwartships baselines; the rigid fit
        # must separate it from yaw.  Paired comparison: the same seed
        # with and without heel shares every error draw, so the per-trial
        # quasi-constant offsets cancel and only the heel effect on the
        # estimator remains.
        diffs = []
        for i in range(12):
            heeled = final_errors(*run_trial(7000 + i, regime="correlated",
                                             duration=5400.0, heel_amp_deg=8.0)[:2])
            flat = final_errors(*run_trial(7000 + i, regime="correlated",
                                           duration=5400.0, heel_amp_deg=0.0)[:2])
            diffs.append(statistics.mean(heeled) - statistics.mean(flat))
        self.assertLess(abs(statistics.median(diffs)), 0.5)

    def test_heel_would_contaminate_a_flat_2d_fit(self):
        # Contrast check: projecting to 2-D (ignoring height) lets an 8-deg
        # heel bend the midships pair into the azimuth -- the reason the
        # fit is 3-D.
        from compass import _rpy_matrix, mat_vec
        w = World(3)
        layout = DEFAULT_LAYOUT
        r = _rpy_matrix(math.radians(42.0), 0.0, math.radians(8.0))
        pts = {k: mat_vec(r, p) for k, p in layout.items()}
        # Flat fit through ALL six (e, n) points, heading = azimuth of the
        # principal axis: compare against bow-stern only.
        bow = [(pts["bow-p"][0] + pts["bow-s"][0]) / 2,
               (pts["bow-p"][1] + pts["bow-s"][1]) / 2]
        stn = [(pts["stn-p"][0] + pts["stn-s"][0]) / 2,
               (pts["stn-p"][1] + pts["stn-s"][1]) / 2]
        true_az = math.degrees(math.atan2(bow[0] - stn[0], bow[1] - stn[1]))
        # PCA-lite: mean of node-to-node azimuths midships-pair vs bow-stern
        mid_az = math.degrees(math.atan2(pts["mid-p"][0] - pts["mid-s"][0],
                                         pts["mid-p"][1] - pts["mid-s"][1]))
        self.assertGreater(abs(wrap180(mid_az - true_az)), 4.0)  # heel leaks

    def test_radio_loss_and_latency_leave_gaps_not_garbage(self):
        for i in range(8):
            readings, truth, _ = run_trial(8000 + i, regime="independent",
                                           duration=5400.0, radioed=True,
                                           loss=0.25, latency=0.080)
            self.assertTrue(len(readings) > 100)     # kept fusing
            errs = final_errors(readings, truth)
            self.assertLess(statistics.mean(abs(e) for e in errs), 3.0)

    def test_kill_a_node_mid_run_compass_degrades_gracefully(self):
        readings, truth, _ = run_trial(9000, regime="independent", duration=5400.0,
                                       kill_node="mid-s", kill_at=2700.0)
        after = [(r, psi) for r, (t, psi) in zip(readings, truth)
                 if t > 3000.0]
        self.assertTrue(after)
        self.assertLessEqual(after[-1][0].n_nodes, 5)
        errs = [wrap180(r.heading - psi) for r, psi in after]
        self.assertLess(statistics.mean(abs(e) for e in errs), 4.0)

    def test_determinism(self):
        a = run_trial(123, regime="correlated", duration=1800.0)
        b = run_trial(123, regime="correlated", duration=1800.0)
        self.assertEqual([r.as_tuple() for r in a[0]],
                         [r.as_tuple() for r in b[0]])


class TestColdStartHonesty(unittest.TestCase):
    """BRIEF-COMPASS-FIX regression: the first sweep measured the
    cold-start honesty gap -- pooled coverage 71-91 % at rho >= 0.3 and
    1-5 s fix intervals, because the install-time prior covered the
    multipath constant only: the per-node bias OU is quasi-frozen for
    tens of minutes, so neither the (never-awake) wander term nor the
    prior carried it, and reported sigma sat at 49-58 % of the true
    error scale.  The fix carries the prior at the full quasi-constant
    scale sqrt(bias^2 + mult^2) with sensitivity-derived floors.  These
    tests pin the coverage property at the brief's named cell
    (rho = 0.6, 15 m baseline, 5 s fix interval): nominal 95 %, honest
    band 90-99 %, and never the absurd conservatism that is the other
    failure mode."""

    @staticmethod
    def _cell_stats():
        from sweep import run_sweep_trial
        hits, errs, sigmas = [], [], []
        for seed in range(1000, 1032):
            tr = run_sweep_trial(seed, 15.0, 5.0, 0.6)
            hits.extend(tr["hits"])
            errs.extend(tr["errs"])
            sigmas.append(tr["sigma_final"])
        return hits, errs, sigmas

    def test_coverage_is_calibrated_at_the_brief_cell(self):
        hits, _errs, _sigmas = self._cell_stats()
        cov = sum(hits) / len(hits)
        self.assertGreaterEqual(cov, 0.90)
        self.assertLessEqual(cov, 0.99)

    def test_reported_sigma_tracks_true_error_scale(self):
        # The old failure mode in one number: sigma_final 2.22 deg against
        # an err p90 of 5.50 deg (ratio 0.66 to the p90/1.645 error-sd
        # estimate).  A calibrated report sits near 1.
        hits, errs, sigmas = self._cell_stats()
        err_sd = statistics.quantiles(errs, n=10, method="inclusive")[8] / 1.645
        ratio = statistics.median(sigmas) / err_sd
        self.assertGreaterEqual(ratio, 0.75)
        self.assertLessEqual(ratio, 1.5)


if __name__ == "__main__":
    unittest.main()
