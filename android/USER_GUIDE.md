# FLIR Gen2 Thermal · Android 0.3.0 preview

## Install and connect

Install `FLIR-Gen2-Android-0.3.0.apk` over the existing app; do not uninstall if
you want to retain private recordings. Android 8.0+ and USB host/OTG are required.
Turn on the camera and connect the **previously verified USB data wiring** through
OTG. Accept Android's USB access prompt. Select Always / Use by default if your
phone offers it. Android may still ask again after reconnection; the app cannot
force a permanent grant.

The tested device is a physically modified Gen 2 Lightning/iOS camera. This APK
does not make an ordinary charging adapter compatible with an untouched Lightning
camera. See README.md for the hardware prerequisite and safety warnings.

## Live view first

- The thermal image occupies an aspect-preserving full-window canvas.
- Controls hide after **4 seconds** without interaction. Tap once to reveal them;
  that first tap does not create a measurement point.
- Tap a visible image point to pin its temperature; tap near a pin to remove it.
  Up to eight pins appear as small transparent rows at the bottom.
- Pinch the image to zoom (1–8×). Settings → Reset zoom returns to the full sensor.
- Settings → Rotate 90° / Mirror apply to live images and playback.
- MAX and optional MIN tracking show their changing position and temperature.
- A transparent MAX trace, thin axes and min/max labels appear above the pin rows.
- Text adapts to bright/dark image areas with a contrasting outline.

The top FPS number measures the last two seconds of incoming accepted thermal
frames, not the rate at which a timer repaints a repeated image. Display processing
runs on its own worker with **one replaceable latest pending frame**, and the UI
also uses a latest-only mailbox. JPEG encoding and disk writes run separately.
There is no artificial 1 FPS live limit. Actual FPS and USB latency depend on the
phone, camera and connection; they have not been measured on a phone for this build.

## Display and temperature

Settings → Display opens mode-specific fine controls with direct numeric entry
and +/− steps. All temperature ranges in the controls are entered in Celsius;
the Fahrenheit switch changes measurement display and CSV output.

| Scale | Purpose |
|---|---|
| Auto | Plateau histogram equalization with limited contrast amplification |
| Detail | Local CLAHE blended with global contrast for subtle scene detail |
| Linear auto | Adaptive linear temperature range |
| Manual | Fixed temperature-to-colour mapping |
| Background relative | Learned scene background, subdued background tones and highlighted heat |

Seven palettes are available: Iron, White hot, Black hot, Rainbow, Lava, Arctic,
Viridis. Tone shifts brightness; lower Display span increases colour sensitivity.
Contrast, minimum span, denoise, local detail and background learning controls
appear only in modes where they are used. Denoise is a spatial display filter,
not a temporal frame stack; it does not alter temperature measurements.

Reset display and Reset temperature are separate. Emissivity, reflected
temperature and calibration offset retain the existing approximate calibration
model. Optional 3×3 averaging affects point readings, not the captured sensor data.
These are **not laboratory-calibrated or medical measurements**.

## Graph inspection

Settings → Measurement history shows MAX plus pinned temperatures.
Touch for a dashed crosshair, temperature(s), capture date/time and elapsed age
(`17h 4m 0s ago`). Drag to browse and pinch or use +/− Zoom to change the range.
Pause / Live freezes only the graph viewport: incoming measurements continue.
Returning to Live moves to the newest sample without intentionally dropping
the measurements collected while paused. Missing camera periods appear as gaps.
In-memory history is bounded; this is not an unlimited background logger.

Reset clears pins, cursor and graph histories. It does **not** delete recordings,
change calibration/display preferences, or reset the USB device.

## Manual image recording — no new RAW

Recording is **off at launch**. Tap **● Record** in the top corner when needed;
tap **■ Stop** to finish. At most one rendered JPEG frame per second is saved.
The live preview remains independently full-rate. Recording stops when the app
leaves the foreground. There is no automatic or hidden continuous recording.

Clips use the small `.f1clip` container (timestamp + JPEG frames). They preserve
the chosen colours, not raw sensor temperatures. Rotate/mirror and PNG snapshots
remain available in playback, but changing palette, scale or radiometry cannot
reconstruct temperatures from a JPEG. Measurement overlays are not burned into
the stored sensor image. Keep a PNG screenshot when you want the on-screen overlay.

Settings → Recordings lists capture dates/times and durations. Choose date or
Calendar filters by the actual first capture timestamp. Open a clip to play/pause,
seek with the timeline, step frames, select playback speed or return to Live.
Export retains the original `.f1clip` file; use this app's Import to reopen it.
The format is not MP4. PNG exports are ordinary viewable images.

Default recording storage is **1,000 MB**; configurable **100–10,000 MB**.
Clips rotate into segments no larger than about 16 MB. On new recording writes,
old completed app recordings are removed to stay under the cap. Active recording,
playback and pending-export files are protected. Export anything important.
Uninstalling the app deletes unexported private files.

## Existing RAW recordings

Old `.f1raw` files remain readable/importable. Their palette, scale, radiometry,
pins, rotation and mirror can still be changed during analysis. A RAW recording's
actions also offer streaming CSV export of date/time, epoch, min/max/center and
current pinned readings, using selected units and averaging.
Large imports and validation run in background workers; stale loads are discarded
after a newer selection, Live action or lifecycle stop.

## Known limits and verification

- Visible/optical/MSX remains unavailable. No firmware or USB initialization
  changes were made by this update.
- The application works in the foreground; it is not a background camera service.
- Date gallery is a compact list/calendar rather than a full phone photo-gallery clone.
- JPEG clips are intentionally not reprocessable RAW archives, per the updated request.
- JVM tests, compile, APK signing and Windows regression tests can be checked on
  the development PC. A real-phone test is still needed for appearance, OTG
  reconnection and measured live FPS. No emulated or physical phone test is claimed
  for this version when no such device is available.
