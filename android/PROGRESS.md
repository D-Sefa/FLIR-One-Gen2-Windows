# Android port execution ledger — 2026-10-06

Intent: deliver an installable independent APK for the user's working iOS Gen2
USB wiring, no intermediate approval requests. Written design/plan: README.md.

Ruling: use a new `android/` directory, not a Git worktree. The active APK
workspace is not a Git checkout; no Windows file changes are needed.
Ruling: user explicitly requests no questions; perform design/plan choices inline.
Ruling: plain Java / Android API 26 minimum avoids closed-source SDK, Python and
native libraries; optional optical/MSX remains unsupported, as on Windows.

Core: ACK regression observed RED (AssertionError), encoder implemented GREEN.
Core suite: 24 frame/codec/session/radiometry/display checks passed.
Archive: lossless unsigned16 RAW, dates, inter-frame timing, clean EOF and truncated
archive rejection passed. Does not claim playback is a desktop DVR clone.
Transport: existing Python DETECT/SYN/config sequence translated without device
file writes, firmware changes, resets or speculative optical commands.

Build: signed APK produced, v2/v3 verified, minSdk26 / target35 verified.
Windows regression: 33/33 tests passed; no Windows source files were edited.
Fresh independent review found four Important lifecycle/archive issues:
unique archive allocation, writer finalization, replay callback retirement and
USB worker retirement. Fixed with exclusive file creation, completion guards,
generation gating and serialized USB lifetimes; targeted tests added.
Also skip unsupported short thermal records instead of reopening the USB link.
Radiometry parity regression observed RED and corrected to Windows raw14 x4
and the same Planck/reflected denominator. No claim of physical calibration.

Physical phone + camera test not available. Android permission/OTG operation,
actual streaming performance and optical availability were explicitly not judged
by the reviewer. Deliver as a preview, not a proven stable phone release.
Deferred: full desktop gallery/calendar features and background capture service.
