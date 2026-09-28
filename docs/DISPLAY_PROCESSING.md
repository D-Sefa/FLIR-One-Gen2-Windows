# Display processing

The display mapper operates on a separate array of converted temperatures.
Pointer measurements, point histories and lossless RAW16 records do not use the
filtered or tone-mapped image. Absolute temperature calibration is unchanged.

## Algorithms and references

- **Auto:** global plateau histogram equalization, 256 bins, capped histogram
  counts with uniform redistribution, blended with a linear mapping. FLIR
  describes the plateau approach in its
  [Lepton video/AGC overview](https://oem.flir.com/en-ca/learn/thermal-integration-made-easy/general-video-and-command-interfacing---lepton/).
  This is our implementation, not FLIR SDK code or a bit-exact reconstruction.
- **Detail:** 4×4-tile CLAHE with bilinear interpolation between tile centres,
  blended with Auto. See the
  [OpenCV explanation of contrast-limited histogram equalization](https://docs.opencv.org/4.13.0/d5/daf/tutorial_py_histogram_equalization.html).
  The implementation uses NumPy, not an OpenCV runtime dependency.
- **Linear auto:** robust 0.1–99.9 percentile bounds with a minimum Celsius span.
- **Manual:** exact temperature-domain linear mapping; does not snap bounds to
  pixels present in the current frame. Out-of-window temperatures clip only after
  tone/span adjustment. A partially typed invalid range uses a safe temporary
  fallback until a valid range is entered.
- **Background relative:** retained specialised warm-target mapping, not
  per-pixel reference subtraction or a calibrated delta-temperature image.

Auto/Detail/Linear auto use an optional 3×3 bilateral-style spatial filter with
0.15 °C range sigma. This is a display tuning choice, not a measured camera NETD.
At zero strength it is bypassed; Manual always bypasses it. A small real target
can still be affected by any spatial filter, so use zero denoise/native pixels
when inspecting individual sensor samples.

Automatic range adaptation has a 0.25-second time constant and resets on large
scene cuts. It smooths limits, not successive images. There is no temporal frame
accumulation, added frame queue or super-resolution. Local enhancement cannot
recover out-of-focus detail or turn 160×120 into a higher-resolution sensor.

## Controls

Tone adds a display brightness offset. Display span expands/contracts the mapping
around its midpoint (25–400%). Contrast sets the histogram clip ratio (1–4).
Minimum span bounds the automatic gain in nearly uniform scenes. These controls
are deliberately independent of emissivity, reflected temperature and offset.

## Offline validation

Run in the setup virtual environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests\benchmark_display.py
```

The tests cover constant and noisy scenes, small hot targets, monotonic global
mapping with filtering disabled, exact Manual bounds and widened/shifted windows,
input immutability, range adaptation, scene cuts, playback isolation, resets,
numeric editing, real Tk mode rendering and EP85 framing regression tests.
No test starts USB capture. The UI test redirects its settings/database to a
temporary folder. Imports create the normal empty output directories if absent.

The benchmark uses a deterministic synthetic scene by default. An optional
`--raw file.raw16 --image comparison.png` renders a local 38400-byte sensor record.
Never include private camera records or archives in a public release by accident.

On the development PC, one saved frame gave median mapping times around 10 ms
(Auto), 12 ms (Detail), 9 ms (Linear auto), 5 ms (Manual). These are not sensor FPS,
USB latency or display-to-photon measurements; performance varies by PC.
