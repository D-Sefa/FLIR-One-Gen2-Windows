import importlib.util
import pathlib
import sys
import tkinter as tk
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'work'))
from flir_display import ToneMapper

spec = importlib.util.spec_from_file_location('viewer', ROOT / 'outputs' / 'flir_live_viewer.py')
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)


class ViewerDisplayTests(unittest.TestCase):
    def setUp(self):
        self.interp = tk.Tcl()
        self.v = viewer.Viewer.__new__(viewer.Viewer)
        self.v.tone_mapper = ToneMapper()
        for name, value in {'scale_mode':'Manual', 'manual_min':'20', 'manual_max':'40',
                            'tone_var':'0', 'thermal_span_var':'100', 'contrast_var':'1.5',
                            'min_span_var':'1.5', 'detail_var':'35', 'denoise_var':'30'}.items():
            setattr(self.v, name, tk.StringVar(self.interp, value=value))
        self.v.playback_mode = False

    def test_viewer_uses_exact_manual_temperature_bounds(self):
        self.assertTrue(hasattr(self.v, 'display_levels'), 'Viewer must use the new display mapper')
        levels, low, high = self.v.display_levels([25.] * 19200)
        self.assertEqual((low, high), (20, 40))
        self.assertTrue(63 <= levels[0] <= 64)

    def test_editing_incomplete_numeric_value_does_not_crash(self):
        self.assertTrue(hasattr(self.v, 'display_levels'))
        for name in ('manual_min', 'manual_max', 'contrast_var', 'min_span_var', 'detail_var', 'denoise_var'):
            getattr(self.v, name).set('-')
        levels, low, high = self.v.display_levels([25.] * 19200)
        self.assertEqual(len(levels), 19200)
        self.assertLess(low, high)

    def test_reset_tuning_preserves_radiometry_and_scale(self):
        self.assertTrue(hasattr(self.v, 'reset_display_tuning'))
        self.v.emissivity_var = tk.StringVar(self.interp, value='0.81')
        self.v.interpolation_var = tk.StringVar(self.interp, value='Native pixels')
        self.v.render = lambda: None
        self.v.tone_var.set('40')
        self.v.thermal_span_var.set('50')
        self.v.reset_display_tuning()
        self.assertEqual(self.v.tone_var.get(), '0')
        self.assertEqual(self.v.thermal_span_var.get(), '100')
        self.assertEqual(self.v.scale_mode.get(), 'Manual')
        self.assertEqual(self.v.emissivity_var.get(), '0.81')


if __name__ == '__main__':
    unittest.main()
