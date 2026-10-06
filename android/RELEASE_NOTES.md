# Android 0.1.0-preview

An independent Android port of the working FLIR ONE Gen 2 Lightning/iOS
Windows iAP2 capture. Installation and live thermal streaming were confirmed
by the project owner on his Android phone. Other phones are not yet verified.

## Download and install

**Hardware prerequisite:** the working camera is modified. Reproducing the
tested connection requires opening the Gen 2 Lightning/iOS camera, removing
its Lightning connector and soldering a USB data cable in its place to the
corresponding PCB USB data/ground connections. The APK is not a plug-and-play
solution for an untouched Lightning camera or an ordinary charging adapter.

This modification can damage the camera. Disconnect the battery and all power
before soldering. Verify signals and check for shorts; do not blindly connect
USB +5 V/VBUS to a Lightning pad or battery terminal. Camera power/charging
must use a verified arrangement. A universal pad-by-pad pinout is not provided.
Read the [hardware prerequisite and safety notes](https://github.com/D-Sefa/FLIR-One-Gen2-Windows/blob/main/android/README.md#hardware-prerequisite)
before attempting the modification.

Download **FLIR-Gen2-Android-preview.apk**, transfer it to your Android 8.0+
phone and install it. Allow installation from your browser/file manager if
Android asks. Turn on the camera and connect its suitable USB data cable
through OTG. Open **FLIR Gen2 Thermal** and allow Android USB access.

No root, Python, Zadig, network connection or FLIR SDK is required.
The camera needs its own stable power/battery. An ordinary Lightning charging
cable is not a substitute for the suitable data connection used by this project.

## Included

- Live 160x120 thermal frames through the Gen 2 iAP2/USB transport.
- Iron, Rainbow, White-hot and Black-hot palettes; auto/linear/manual scales.
- Tone/span, radiometry settings, reset, rotate and mirror.
- Touch measurement points, temperature history, graph pause/zoom/time cursor.
- PNG export, lossless RAW recording, import/export and playback.

## Limits

- Optical/visible and MSX are not working; this is thermal-only.
- First preview, not full Windows feature parity; compatibility with other
  phone models, Gen 3/Pro or arbitrary adapters is not established.
- Temperature conversion uses approximate desktop calibration constants,
  not laboratory calibration or medical accuracy.
- Recording is explicit and stops when the app leaves the foreground.
- App-private recordings must be exported before uninstalling.
- No background camera service or automatic storage quota.

The source is in `android/` in the repository and in the attached source ZIP.
Signing credentials are not distributed. APK v2/v3 signatures and all five
offline Java test suites were verified before publication.

The existing Windows release remains the latest stable release.
