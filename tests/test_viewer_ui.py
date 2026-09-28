"""Real Tk smoke test with isolated settings/archive and no USB access."""
import importlib.util
import os
import pathlib
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ViewerUiTests(unittest.TestCase):
    def test_all_modes_render_and_reset_without_changing_measurements(self):
        spec = importlib.util.spec_from_file_location('isolated_viewer', ROOT/'outputs'/'flir_live_viewer.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'FLIR_EXTERNAL_CAPTURE':'1'}):
            temp = pathlib.Path(folder)
            module.DVR_DIR = temp
            for key, name in {'DVR_DB':'history.sqlite3', 'VIEWER_SETTINGS':'viewer.json',
                              'STORAGE_SETTINGS':'storage.json', 'LIVE_RAW':'absent.raw16',
                              'LIVE_STATUS':'absent.json', 'LIVE_VISUAL':'absent.jpg'}.items():
                setattr(module, key, temp/name)
            v = module.Viewer()
            v.root.withdraw()
            try:
                blob = struct.pack('<19200H', *[7000 + (i % 160)*3 for i in range(19200)])
                self.assertTrue(v.load_raw_blob(blob))
                original = tuple(v.temperatures)
                for mode in ('Auto', 'Detail', 'Linear auto', 'Manual', 'Background relative'):
                    v.scale_mode.set(mode)
                    v.root.update_idletasks()
                    v.render()
                    self.assertEqual(tuple(v.temperatures), original)
                    self.assertIsNotNone(v.rendered_image)
                    self.assertEqual(bool(v.manual_wrap.winfo_manager()), mode == 'Manual')
                    self.assertEqual(bool(v.bg_wrap.winfo_manager()), mode == 'Background relative')
                    self.assertEqual(bool(v.agc_controls['Detail %'].winfo_manager()), mode == 'Detail')
                v.scale_mode.set('Manual')
                v.fit_manual_range()
                self.assertLessEqual(float(v.manual_min.get()), min(original))
                self.assertGreaterEqual(float(v.manual_max.get()), max(original))
                v.reset_display_settings()
                self.assertEqual(v.scale_mode.get(), 'Auto')
                self.assertEqual(tuple(v.temperatures), original)
                v.save_viewer_settings()
                self.assertTrue(module.VIEWER_SETTINGS.exists())
                self.assertIsNone(v.process)
            finally:
                v.close()


if __name__ == '__main__':
    unittest.main()
