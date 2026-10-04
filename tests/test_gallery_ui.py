import importlib.util
import csv
import io
import json
import os
import pathlib
import struct
import tempfile
import time
import unittest
from unittest.mock import patch
from PIL import ImageChops, ImageOps
from test_gallery import make_archive

ROOT = pathlib.Path(__file__).resolve().parents[1]


class GalleryUiTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('gallery_viewer',ROOT/'outputs'/'flir_live_viewer.py')
        self.m=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.m)
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.folder=pathlib.Path(self.tmp.name)
        self.m.DVR_DIR=self.folder
        for key,name in {'DVR_DB':'history.sqlite3','VIEWER_SETTINGS':'viewer.json','STORAGE_SETTINGS':'storage.json',
                         'LIVE_RAW':'live.raw16','LIVE_STATUS':'absent.json','LIVE_VISUAL':'absent.jpg'}.items():
            setattr(self.m,key,self.folder/name)
        self.env=patch.dict(os.environ,{'FLIR_EXTERNAL_CAPTURE':'1'}); self.env.start(); self.addCleanup(self.env.stop)
        self.start=time.time()-86400
        make_archive(self.folder,[self.start,self.start+1,self.start+2])
        self.v=self.m.Viewer(); self.v.root.withdraw(); self.addCleanup(self.v.close)

    def test_mirror_after_rotation_matches_pixels_coordinates_and_settings(self):
        v=self.v
        self.assertTrue(hasattr(v,'mirror_var'), 'Mirror option is missing')
        v.load_raw_blob(struct.pack('<19200H',*[7000+i%160*3 for i in range(19200)]))
        v.scale_mode.set('Manual'); v.manual_min.set('0'); v.manual_max.set('100')
        for angle in (0,90,180,270,33):
            v.mirror_var.set(False); v.set_rotation(angle); v.render()
            original=v.rendered_image.copy(); temps=tuple(v.temperatures)
            x,y=v.image_to_canvas(100,200)
            v.mirror_var.set(True); v.render()
            self.assertIsNone(ImageChops.difference(v.rendered_image,ImageOps.mirror(original)).getbbox())
            mx,my=v.image_to_canvas(100,200)
            self.assertAlmostEqual(mx,original.width-1-x); self.assertAlmostEqual(my,y)
            bx,by=v.canvas_to_image(mx,my)
            self.assertAlmostEqual(bx,100); self.assertAlmostEqual(by,200)
            self.assertEqual(tuple(v.temperatures),temps)
        v.save_viewer_settings()
        self.assertTrue(json.loads(self.m.VIEWER_SETTINGS.read_text())['mirror'])

    def test_recording_opens_in_shared_view_and_live_archive_continues(self):
        v=self.v
        self.assertTrue(hasattr(v,'open_recording'), 'Gallery playback integration is missing')
        live_points=v.points; live_max=v.max_point
        v.open_recording({'start':self.start,'end':self.start+2,'count':3,'date':'2026-10-02'})
        self.assertTrue(v.playback_mode)
        self.assertEqual(v.playback_time,self.start)
        v.mirror_var.set(True); v.set_rotation(90)
        for mode in ('Auto','Detail','Linear auto','Manual','Background relative'):
            v.scale_mode.set(mode); v.render(); self.assertIsNotNone(v.rendered_image)
        blob=struct.pack('<19200H',*[7100]*19200)
        self.m.LIVE_RAW.write_bytes(blob)
        v.refresh()
        self.assertEqual(v.playback_time,self.start)
        self.assertEqual(v.raw[0],7000)
        v.return_to_live()
        self.assertFalse(v.playback_mode)
        self.assertIs(v.points,live_points); self.assertIs(v.max_point,live_max)
        self.assertEqual(v.raw[0],7100)
        self.assertTrue(v.mirror_var.get())

    def test_live_history_and_csv_continue_while_viewing_recording(self):
        v=self.v
        v.load_raw_blob(struct.pack('<19200H',*[7100]*19200))
        live_max=v.max_point
        v.csv_file=io.StringIO(); v.csv_writer=csv.writer(v.csv_file)
        v.csv_series_names=['MAX']; v.record_start=time.time(); v.recording=True
        v.open_recording({'start':self.start,'end':self.start+2,'count':3})
        history_raw=tuple(v.raw)
        expected=v.raw_to_c(7100)
        v.temp_offset_var.set('50')
        self.assertEqual(float(v.viewer_settings_snapshot()['calibration_offset']),0.)
        v.archive_live_measurements_from_blob(time.time(),struct.pack('<19200H',*[7100]*19200))
        self.assertTrue(live_max['history'])
        self.assertAlmostEqual(live_max['history'][-1][1],expected)
        self.assertTrue(v.csv_file.getvalue())
        self.assertEqual(tuple(v.raw),history_raw)
        v.return_to_live()
        self.assertEqual(float(v.temp_offset_var.get()),0.)

    def test_async_analysis_recomputes_new_point_and_seek(self):
        v=self.v
        v.open_recording({'start':self.start,'end':self.start+2,'count':3})
        from collections import deque
        v.points.append(dict(name='P1',x=2,y=3,color='#ffff00',graph=True,history=deque()))
        v.smooth_var.set(False); v.request_recording_analysis()
        deadline=time.monotonic()+4
        while not v.points[0]['history'] and time.monotonic()<deadline:
            v.root.update(); time.sleep(.01)
        self.assertEqual(len(v.points[0]['history']),3)
        v.seek_recording_now(self.start+2)
        self.assertEqual(v.playback_time,self.start+2)
        self.assertAlmostEqual(v.points[0]['history'][-1][1],v.sample_temp(2,3),places=4)


if __name__=='__main__':unittest.main()
