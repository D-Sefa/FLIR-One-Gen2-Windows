"""Actual Tk widgets: matched inset surfaces and readable keyboard selections."""
import importlib.util
import os
import pathlib
import tempfile
import tkinter.ttk as ttk
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]

def contrast(root, first, second):
    def lum(color):
        channels = [v / 65535 for v in root.winfo_rgb(color)]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return sum(a*b for a,b in zip(linear, (.2126,.7152,.0722)))
    a,b=sorted((lum(first),lum(second)))
    return (b+.05)/(a+.05)

class MobileThemeTests(unittest.TestCase):
    def test_real_controls_share_surfaces_and_keep_selection_legible(self):
        spec=importlib.util.spec_from_file_location('theme_viewer',ROOT/'outputs/flir_live_viewer.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'FLIR_EXTERNAL_CAPTURE':'1'}):
            temp=pathlib.Path(folder);m.DVR_DIR=temp
            for key,name in {'DVR_DB':'history.sqlite3','VIEWER_SETTINGS':'viewer.json','STORAGE_SETTINGS':'storage.json',
                             'LIVE_RAW':'none.raw16','LIVE_STATUS':'none.json','LIVE_VISUAL':'none.jpg'}.items():setattr(m,key,temp/name)
            v=m.Viewer();v.root.withdraw()
            try:
                self.assertEqual(v.graph.cget('background'),v.point_list.cget('background'), 'Chart and readings need the same inset surface')
                self.assertGreaterEqual(contrast(v.root,v.point_list.cget('selectforeground'),v.point_list.cget('selectbackground')),4.5)
                style=ttk.Style(v.root)
                self.assertGreaterEqual(contrast(v.root,style.lookup('Section.TLabel','foreground'),style.lookup('Section.TLabel','background')),4.5)
                self.assertEqual(str(style.lookup('TButton','relief')),'flat')
                # Restyling must not launch a worker or alter display/radiometry defaults.
                self.assertIsNone(v.process)
                self.assertEqual(v.scale_mode.get(),'Auto')
            finally:v.close()

if __name__=='__main__':unittest.main()
