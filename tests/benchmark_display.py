"""Offline AGC benchmark and optional comparison; never accesses USB.

python tests/benchmark_display.py [--raw path.raw16] [--image comparison.png]
"""
import argparse
import importlib.util
import pathlib
import statistics
import sys
import time
import tkinter as tk

import numpy as np
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'work'))
from flir_display import ToneMapper


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw', type=pathlib.Path)
    parser.add_argument('--image', type=pathlib.Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('viewer', ROOT/'outputs'/'flir_live_viewer.py')
    viewer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(viewer)
    if args.raw:
        v = viewer.Viewer.__new__(viewer.Viewer)
        interp = tk.Tcl()
        for name, val in [('emissivity_var','.95'), ('reflected_var','20'), ('temp_offset_var','0')]:
            setattr(v, name, tk.StringVar(interp, value=val))
        decoded = v.decode_raw_blob(args.raw.read_bytes())
        if decoded is None:
            raise ValueError('Expected a 38400-byte 160x120 RAW16 file')
        vals = decoded[2]
    else:
        rng = np.random.default_rng(42)
        vals = rng.normal(25, .04, (160, 120))
        vals[50:100, 40:80] += .5
        vals[60:63, 70:73] = 30
        vals = vals.ravel()
    panels = []
    for mode in ('Auto', 'Detail', 'Linear auto', 'Manual'):
        m, timings = ToneMapper(), []
        for i in range(100):
            begin = time.perf_counter()
            levels, lo, hi = m.map(vals, 120, 160, mode=mode, temporal=False,
                                    low=float(np.min(vals)), high=max(float(np.min(vals))+.1,float(np.max(vals))))
            timings.append((time.perf_counter()-begin)*1000)
        print(f'{mode}: median={statistics.median(timings):.2f}ms p95={sorted(timings)[94]:.2f}ms')
        im = Image.frombytes('P',(120,160),levels.tobytes())
        im.putpalette([c for n in range(256) for c in viewer.palette_color('Iron',n)])
        panel = Image.new('RGB',(360,510),'#101216')
        panel.paste(im.convert('RGB').resize((360,480),Image.Resampling.BILINEAR),(0,30))
        ImageDraw.Draw(panel).text((10,8),f'{mode} | {lo:.1f} to {hi:.1f} C',fill='white')
        panels.append(panel)
    if args.image:
        comparison=Image.new('RGB',(1440,510))
        for i, panel in enumerate(panels):comparison.paste(panel,(i*360,0))
        comparison.save(args.image)


if __name__ == '__main__':
    main()
