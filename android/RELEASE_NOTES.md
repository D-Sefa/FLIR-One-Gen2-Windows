# Android 0.3.0-preview

Download **FLIR-Gen2-Android-0.3.0.apk**, transfer to an Android 8.0+ phone and
install over the earlier preview. Connect the powered, modified camera through
USB OTG and accept Android USB access. No root, Python, Zadig or FLIR SDK needed.

## Hardware prerequisite

The verified Gen 2 Lightning/iOS unit is physically modified: its Lightning
connector is removed and a USB data cable is soldered to the PCB data/ground
connections. An ordinary charging adapter is not a verified substitute.
Opening/soldering can permanently damage the camera. Disconnect all power first;
never blindly connect USB +5 V to a Lightning pad or battery terminal.
Read [hardware prerequisites and safety](https://github.com/D-Sefa/FLIR-One-Gen2-Windows/blob/main/android/README.md#hardware-prerequisite).

## Included

- Full-window navy/mint UI; four-second idle control auto-hide and first-tap reveal.
- Transparent adaptive pin readings and MAX graph, thin axes and min/max labels.
- Rotate/Mirror/zoom, MAX/MIN tracking, seven palettes and five scale modes.
- Fine display/radiometry controls and separate resets; Celsius/Fahrenheit/3x3 averaging.
- Touch graph time/temperature/age inspection, pause/pan/zoom without stopping collection.
- Latest-only display processing; independent JPEG encoding and disk writing.
- Manual corner **Record** button saves one rendered JPEG per second in .f1clip.
  No new RAW recording or automatic continuous recording. Live remains independent.
- Capture-date/calendar gallery, timeline seeking, stepping, speed and PNG export.
- Default 1 GB recording cap, editable 100 MB–10 GB; active/playback/export protection.
- Existing RAW imports remain reprocessable and can export temperature CSV.

Saved JPEG colours are baked in: new clips cannot be recalibrated or recoloured
as RAW temperature data. Desktop and phone recording formats differ.

## Limits and verification

Optical/visible/MSX remains unavailable. No background camera service. Android
controls USB permission; duplicate requests are suppressed but a permanent grant
cannot be forced. Other phones/cameras/adapters are not verified.
Temperature estimates are not laboratory-calibrated or medical measurements.
Recording stops on leaving the foreground. Export private records before uninstalling.

All 14 JVM test programs and Android compile pass; the distributed APK's v2/v3
signatures verify. The original signing identity is retained. Owner confirmed
installation/live use on his modified camera and phone; this is not a quantitative
phone FPS or universal compatibility claim.

Source is in android/ and the clean source ZIP. No signing key or personal
recordings are distributed. See [USER_GUIDE.md](USER_GUIDE.md).
