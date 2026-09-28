# Changelog

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
