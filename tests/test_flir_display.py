"""Display-only AGC contracts; no USB or Tk process is started."""
import importlib.util
import pathlib
import unittest

import numpy as np

SOURCE = pathlib.Path(__file__).resolve().parents[1] / 'work' / 'flir_display.py'


def engine():
    assert SOURCE.exists(), 'Display-only tone mapper has not been implemented'
    spec = importlib.util.spec_from_file_location('flir_display', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ToneMapper()


class DisplayTests(unittest.TestCase):
    def test_manual_widened_span_maps_temperatures_outside_original_bounds(self):
        out, lo, hi = engine().map([15., 20., 25., 30., 35.], 5, 1,
                                   mode='Manual', low=20, high=30, span=200)
        np.testing.assert_allclose(out, [0, 64, 128, 191, 255], atol=1)
        self.assertEqual((lo, hi), (15, 35))

    def test_manual_shifted_tone_moves_actual_temperature_window(self):
        out, lo, hi = engine().map([17., 22., 27.], 3, 1,
                                   mode='Manual', low=20, high=30, tone=50)
        np.testing.assert_allclose(out, [0, 128, 255], atol=1)
        self.assertAlmostEqual(lo, 17)
        self.assertAlmostEqual(hi, 27)

    def test_manual_range_does_not_snap_to_scene(self):
        out, lo, hi = engine().map([25., 26., 27.], 3, 1, mode='Manual', low=20, high=40)
        np.testing.assert_allclose(out, [64, 76, 89], atol=1)
        self.assertEqual((lo, hi), (20, 40))

    def test_manual_same_temperature_same_colour_in_different_scenes(self):
        m = engine()
        a, _, _ = m.map([20., 25., 30.], 3, 1, mode='Manual', low=20, high=40)
        b, _, _ = m.map([0., 25., 90.], 3, 1, mode='Manual', low=20, high=40)
        self.assertEqual(a[1], b[1])

    def test_constant_scene_is_neutral_not_white(self):
        for mode in ('Auto', 'Detail', 'Linear auto'):
            out, _, _ = engine().map([25.] * 19200, 120, 160, mode=mode)
            self.assertLess(np.ptp(out.astype(float)), 1)
            self.assertTrue(115 <= out[0] <= 140, (mode, out[0]))

    def test_low_contrast_noise_is_not_stretched_to_full_palette(self):
        vals = np.random.default_rng(12).normal(25, .025, 19200)
        for mode in ('Auto', 'Detail'):
            out, _, _ = engine().map(vals, 120, 160, mode=mode)
            self.assertLess(np.std(out), 18, mode)

    def test_global_mapping_preserves_temperature_order(self):
        vals = np.linspace(20, 35, 19200)
        out, _, _ = engine().map(vals, 120, 160, mode='Auto', denoise=0)
        self.assertTrue(np.all(np.diff(out.astype(float)) >= 0))

    def test_small_hot_target_remains_visible(self):
        vals = np.full(19200, 25.)
        vals[1000:1004] = 30.
        out, _, _ = engine().map(vals, 120, 160, denoise=50)
        self.assertGreater(float(out[1001]) - float(np.median(out)), 70)

    def test_input_measurements_are_unchanged(self):
        vals = np.linspace(20, 35, 19200)
        original = vals.copy()
        engine().map(vals, 120, 160, mode='Detail', denoise=100)
        np.testing.assert_array_equal(vals, original)

    def test_range_smoothing_tracks_physical_temperature_not_bin_index(self):
        m = engine()
        m.map(np.linspace(20, 30, 19200), 120, 160, now=1)
        _, lo, hi = m.map(np.linspace(21, 31, 19200), 120, 160, now=1.1)
        self.assertTrue(20 < lo < 21.1)
        self.assertTrue(29.8 < hi < 31)

    def test_scene_cut_adapts_immediately(self):
        m = engine()
        m.map([25.] * 19200, 120, 160, now=1)
        out, lo, hi = m.map([60.] * 19200, 120, 160, now=1.1)
        self.assertTrue(lo < 60 < hi)
        self.assertTrue(115 <= out[0] <= 140)

    def test_stateless_playback_does_not_change_live_state(self):
        m = engine()
        m.map([25.] * 19200, 120, 160, now=1)
        m.map([90.] * 19200, 120, 160, temporal=False, now=2)
        _, lo, hi = m.map([25.] * 19200, 120, 160, now=1.1)
        self.assertTrue(lo < 25 < hi)

    def test_invalid_manual_range_rejected(self):
        for low, high in ((30, 20), (20, 20), (float('nan'), 30)):
            with self.assertRaises(ValueError):
                engine().map([25.], 1, 1, mode='Manual', low=low, high=high)

    def test_nonfinite_pixels_do_not_break_mapping(self):
        out, lo, hi = engine().map([25., float('nan'), float('inf'), 26.], 2, 2)
        self.assertTrue(np.isfinite([lo, hi]).all())
        self.assertEqual(out[1], 0)
        self.assertEqual(out[2], 0)

    def test_reset_removes_previous_scene(self):
        m = engine()
        m.map([25.] * 100, 10, 10, now=1)
        m.reset()
        a = m.map([27.] * 100, 10, 10, now=1.1)[0]
        b = engine().map([27.] * 100, 10, 10, now=1.1)[0]
        np.testing.assert_array_equal(a, b)

    def test_tone_and_span_are_display_only_and_effective(self):
        vals = np.array([24., 25., 26.])
        base = engine().map(vals, 3, 1, mode='Manual', low=20, high=30)[0]
        bright = engine().map(vals, 3, 1, mode='Manual', low=20, high=30, tone=20)[0]
        narrow = engine().map(vals, 3, 1, mode='Manual', low=20, high=30, span=50)[0]
        self.assertTrue(np.all(bright > base))
        self.assertGreater(np.ptp(narrow.astype(float)), np.ptp(base.astype(float)))
        np.testing.assert_array_equal(vals, [24, 25, 26])

    def test_clahe_reveals_local_structure_without_tile_seams(self):
        vals = np.tile(np.linspace(24, 26, 120), (160, 1))
        vals[:, 60:] += .15
        out, _, _ = engine().map(vals.ravel(), 120, 160, mode='Detail', denoise=0)
        image = out.reshape(160, 120).astype(float)
        self.assertGreater(image[:, 61].mean(), image[:, 58].mean())
        self.assertLess(np.max(np.abs(np.diff(image, axis=0))), 2)


if __name__ == '__main__':
    unittest.main()
