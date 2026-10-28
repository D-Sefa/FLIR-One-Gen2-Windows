# FLIR ONE Gen 2 — Android 0.3.0 preview

Independent Java USB-host/iAP2 app for the FLIR ONE Gen 2 Lightning/iOS camera.
Android 8.0+ and USB OTG are required. No root, Python, Zadig, FLIR SDK, network
connection or firmware conversion is needed on the phone.

## Install

Download **FLIR-Gen2-Android-0.3.0.apk** from the
[Android release](https://github.com/D-Sefa/FLIR-One-Gen2-Windows/releases/tag/android-v0.3.0-preview).
Install over the existing preview to keep private recordings; do not uninstall.
Turn on the camera, connect the verified USB data cable through OTG and accept
Android USB access. Select Always / Use by default if offered. Android remains
in control of USB permission and may ask again on reconnect or camera reset.

## Hardware prerequisite

**The tested Gen 2 Lightning/iOS camera is physically modified.** Reproducing
this connection requires opening the camera, removing its Lightning connector
and soldering a USB data cable in its place to the corresponding PCB USB
data/ground connections. The APK or an ordinary Lightning charging adapter
does not make an untouched Lightning unit compatible.

Fine soldering can permanently damage the camera. Disconnect the battery and
all external power before opening or soldering. Do not identify signals by
wire colour alone. Verify connections, check for shorts, insulate the cable
and add strain relief.

**This is not a verified pad-by-pad wiring guide.** No universal PCB pinout or
safe replacement charging connection is documented. Do not blindly connect
USB +5 V/VBUS to a Lightning pad or battery terminal. Data and camera charging
are separate concerns: retain a verified power arrangement and charged camera
battery. Have a qualified technician make changes you cannot verify.
Unmodified-camera adapters, Gen 3/Pro and other variants are not verified.
No connector_type change or firmware conversion is required.

## Current features

- Full-window aspect-preserving thermal image, dark navy/mint settings panel.
- Controls hide after four idle seconds; first tap reveals without adding a pin.
- Adaptive transparent point readings and MAX graph with thin axes/min/max labels.
- Rotate, Mirror, image zoom, MAX/MIN tracking and measurement reset.
- Seven palettes, five scale modes, fine tone/span/contrast/detail/denoise tuning,
  mode-specific controls and separate display/temperature resets.
- Celsius/Fahrenheit, emissivity/reflected temperature/offset and optional 3x3 averaging.
- Graph inspection with date/time/age crosshair, pause, pan and zoom; collection
  continues while the graph viewport is paused.
- Live display uses replaceable latest-frame worker/UI mailboxes. JPEG encoding
  and disk writing are independent. No claimed benchmark FPS for this phone build.
- **Manual Record only:** one rendered JPEG per second in .f1clip segments.
  No automatic recording and no new RAW recording. Live is not limited to 1 FPS.
- Recording dates/calendar, timeline seeking, stepping/speed and PNG export.
  Saved JPEG colours cannot be reprocessed into temperature maps.
- Existing .f1raw import/playback/analysis and temperature CSV export remain available.
- Default 1,000 MB quota, adjustable 100–10,000 MB; oldest completed app recordings
  are pruned on writes while active recording/playback/export files are protected.

See the [complete user guide](USER_GUIDE.md). Desktop DVR archives and phone
archives have different formats. App-private recordings are removed on uninstall:
export important files first. Recording stops when the app leaves the foreground.

## Limits and verification

Thermal only: optical/visible/MSX remains unavailable. This is not arbitrary full
Windows feature parity or a background camera service. Temperature values use the
existing approximate calibration model, not laboratory or medical calibration.
Installation/live streaming were confirmed by the owner on his modified Gen 2
and Android phone; other phones and quantitative FPS/reconnection performance
for this build remain unverified.

All 14 offline JVM test programs pass, Android sources compile, and APK v2/v3
signatures verify. Those checks do not substitute for physical phone tests.
The original signing identity and package ID support in-place upgrades.

## Build

Run build.ps1 with -Toolchain pointing to your local toolchain directory containing
JDK 17, Android API 35 and build-tools 35.0.0 in the layout used by that script.
The default ../../android-toolchain is a developer workspace path, not a bundled
dependency. The script runs tests, javac, D8, aapt2, zipalign and apksigner.
It creates a local signing key outside source. Keep your own key for future
updates; signing credentials and toolchain binaries are never distributed here.
Prebuilt APK has no native libraries and is architecture-independent.

USB initialization, authentication/session keepalive and EP85 parsing are the
existing working transport, not a new firmware or MFi chip modification.
