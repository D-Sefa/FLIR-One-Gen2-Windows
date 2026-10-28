"""Catch frozen worker relaunches opening another viewer instead of capture."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
import portable_entry
from portable_entry import selected_script


class PortableEntryTests(unittest.TestCase):
    def test_frozen_layout_separates_runtime_from_writable_data(self):
        self.assertTrue(hasattr(portable_entry, 'data_directory'), 'Portable data layout is missing')
        self.assertEqual(portable_entry.data_directory(pathlib.Path('package/_internal'), True),
                         pathlib.Path('package/Data'))

    def test_source_layout_keeps_existing_outputs_location(self):
        self.assertTrue(hasattr(portable_entry, 'data_directory'), 'Portable data layout is missing')
        self.assertEqual(portable_entry.data_directory(pathlib.Path('source'), False), pathlib.Path('source'))

    def test_normal_launch_selects_viewer(self):
        self.assertEqual(selected_script([], pathlib.Path('bundle')),
                         pathlib.Path('bundle/outputs/flir_live_viewer.py'))

    def test_existing_python_worker_command_selects_bundled_capture(self):
        self.assertEqual(selected_script(['-u', 'work/flir_iap2_frame.py'], pathlib.Path('bundle')),
                         pathlib.Path('bundle/work/flir_iap2_frame.py'))

    def test_arbitrary_script_is_not_executed(self):
        with self.assertRaises(ValueError):
            selected_script(['-u', 'other.py'], pathlib.Path('bundle'))

    def test_incomplete_worker_arguments_are_rejected(self):
        with self.assertRaises(ValueError):
            selected_script(['-u'], pathlib.Path('bundle'))
