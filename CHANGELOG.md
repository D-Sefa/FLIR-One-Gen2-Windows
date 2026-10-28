# Changelog

## 0.4.0 — 2026-10-28 — Matched desktop / mobile design

- Match the approved Android design with deep navy surfaces, mint accents,
  flatter controls, readable selection text and thin graph lines.
- Style the recording gallery and section headings consistently.
- Preserve desktop layout, radiometry, scaling, RAW DVR/gallery and USB/iAP2.
- Publish a portable Windows x64 package (no Python required), official Zadig 2.9,
  licenses and accompanying source archive; verify extracted-bundle startup.

## Android 0.3.0-preview — 2026-10-28

- Publish the owner-approved full-window interface with four-second idle control
  auto-hide, first-tap reveal, adaptive transparent pins and MAX graph.
- Five scale modes, seven palettes, fine controls, separate resets, Celsius /
  Fahrenheit, optional 3×3 averaging and Rotate/Mirror.
- Latest-only worker and UI mailboxes; separate JPEG encoding and disk writing.
  Real phone FPS has not been benchmarked.
- Manual corner Record button: one JPEG per second in `.f1clip` segments. No new
  RAW capture and no automatic continuous recording. Saved colours are baked in.
- Date/calendar recording selection, seek/step/speed, and old RAW import/CSV.
- Storage default 1 GB, adjustable 100 MB–10 GB; active/playback/export protection.
- Same signing identity and package ID support upgrades without uninstalling.
  Optical/MSX remains unavailable. Desktop and phone archives are different formats.

## 0.3.1 — Portable Windows package

- Add a Windows x64 portable EXE/ZIP with bundled Python, Pillow, NumPy,
  Tcl/Tk, PyUSB and libusb; users no longer need to install Python.
- Bundle the official signed Zadig 2.9 executable, license notices and its
  accompanying libwdi/Zadig source archive. Document first-time WinUSB setup.
- Add frozen worker dispatch and extracted-package startup/error regression checks.
- Existing viewer, capture protocol, rendering and recording algorithms are unchanged.

## Android 0.1.0-preview — 2026-10-06

- Publish an independent Android 8+ USB-host/iAP2 thermal viewer and signed APK.
- Include palettes/scaling, rotate/mirror, touch temperatures, graphs, PNG export
  and RAW recording/playback with timestamps and adjustable display settings.
- Installation and live streaming confirmed by the owner on his Android phone.
- Other phones remain unverified; optical/MSX and full desktop feature parity
  are not included. Windows capture and viewer are unchanged.

## 0.3.0 — 2026-10-04

- Added live/recorded horizontal mirror with consistent rotation and point coordinates.
- Added date-grouped thumbnail gallery, calendars, date/time seek, playback controls and speed.
- Reanalyze saved RAW frames with new measurement points, palettes/scales and radiometry.
- Keep live recording, point history and CSV running while viewing recordings.
- Isolate archive radiometry and point state from live measurements.
- Added archive corruption, date-range, mirror and playback regression tests.
- USB/iAP2 initialization and thermal capture are unchanged; visible stream remains unresolved.

## 0.2.0 — 2026-09-28

- Replace experimental HEQ/wall display modes with independently implemented
  plateau Auto, local CLAHE Detail and restrained Linear auto.
- Correct Manual scaling to honour actual Celsius bounds, including tone/span
  adjustments; add Fit scene.
- Add contrast, minimum span, local-detail and spatial-denoise tuning, smooth/native
  interpolation and Reset tuning. Retain separate Display and Temperature resets.
- Preserve raw measurement and archive paths. No new USB/iAP2 initialization or
  firmware commands were introduced for this display update.
- Include the previously developed low-latency capture/viewer path and authoritative
  EP85 record-size parser in the public distribution, with protocol regression tests.
- Add NumPy to setup, offline display/UI tests and a reproducible mapper benchmark.
- Optical/visible stream remains unresolved; this release does not enable MSX.

## 0.1.0 — 2026-09-16

- Initial public Windows thermal viewer and installation guide.
