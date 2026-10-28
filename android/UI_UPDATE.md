# Android 0.3.0 preview

The current implementation and limitations are documented in [USER_GUIDE.md](USER_GUIDE.md).

This update extends the approved 0.2.0 full-window interface, adaptive overlays,
Rotate/Mirror, graph pause/zoom, Reset and storage controls. It adds display modes,
temperature units, fine tuning, MAX/MIN tracking, date-based recording selection,
timeline seeking, existing-RAW analysis and CSV export.

## Latest user decisions supersede the older RAW plan

Live latency is the priority. Recording is manual only, started with a corner
Record button, and saves at most one rendered JPEG frame per second in `.f1clip`.
There is no new RAW recording or automatic continuous recording. Older RAW files
remain supported for analysis. JPEG colours cannot be reprocessed into new
temperature maps. Controls auto-hide after four idle seconds; first tap reveals.

Full arbitrary Windows feature parity and optical/MSX availability are not claimed.
Source remains independent Java/Canvas; working USB/iAP2 and Windows sources are
unchanged. Phone-specific appearance, FPS and reconnect tests remain necessary.
