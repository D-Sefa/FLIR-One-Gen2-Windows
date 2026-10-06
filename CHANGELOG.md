# Changelog

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
