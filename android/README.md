# FLIR ONE Gen 2 — Android

Independent Android USB-host port of the working Windows iAP2 capture.
No FLIR APK/SDK code is bundled. No root, Python, Zadig, network connection,
or firmware conversion is required on the phone. Android 8.0+ and USB OTG are required.

Install the signed APK, turn on the camera, connect its data cable through OTG,
open the app and accept Android's USB permission dialog. Keep the camera's
own battery charged. This app cannot repair an intermittent USB cable.

The iOS/Lightning camera must already have a suitable USB data connection;
an ordinary passive USB-C/Lightning charging cable is not a substitute.

## Install the preview APK

1. Download `FLIR-Gen2-Android-preview.apk` from the Android GitHub release.
2. Transfer it to your phone and open it. If prompted, allow installation from
   the browser or file manager you used, then install. You can revoke this
   installation permission afterward.
3. Turn on the camera with its battery charged and connect its suitable USB
   data cable through a USB OTG adapter. Open **FLIR Gen2 Thermal**.
4. Accept the Android USB access prompt. The thermal stream starts automatically.

Windows WinUSB/Zadig drivers do not apply to Android. This is not a general
USB webcam app: the verified target is the Gen 2 Lightning/iOS camera using
VID `09CB`, PID `1996`. Gen 3/Pro and arbitrary Lightning adapters are not verified.
If USB permission is denied, disconnect/reconnect and grant permission.
If no camera is detected, check USB host/OTG support, data wiring and camera power.
No firmware conversion or persistent camera configuration change is required.

## Design / constraints

- Separate project: never modify the working Windows capture or viewer.
- Java USB Host API, native Canvas UI; no closed-source SDK or JNI dependencies.
- Port the existing DETECT/SYN/identification/certificate/challenge/config session
  sequence, MI01/MI02 alternate settings and 30-second autoFFC keepalive.
- AuthenticationSucceeded is the host's acknowledgement as in the Windows code;
  this app does not validate Apple's certificate cryptographically or emulate iOS.
- EP85 records end at `28 + FrameSize`; reject section sum greater than FrameSize.
- Raw 160x120 samples retain the known Gen2 VoSPI layout; JPEG offsets use ThermalSize.
- Latest frame only; no growing rendering queue. Camera access runs off the UI thread.
- Thermal view, palettes, auto/linear/manual scales, tone/span, rotate/mirror,
  touch temperatures and measurement graph; raw recording and replay with display controls.
- Optical availability remains unverified; do not claim MSX when no JPEG arrives.
- Celsius measurements use the desktop's approximate calibration constants,
  not a claim of laboratory calibration or medical accuracy.
- USB permission is a mandatory Android system prompt, not a removable setup step.
- Compile, sign and verify the APK; desktop protocol fixtures and JVM tests are
  evidence of the port, not evidence of physical phone/USB compatibility.

## Implementation plan

1. Core: packet/checksum/CSM codec, reassembly, iAP2 state machine, frame parser,
   radiometry and tone mapping. Test missing behavior RED, then GREEN against
   known Windows packets and chunked/malformed EP85 fixtures.
2. Transport: descriptor-based endpoint lookup, permission flow, worker lifecycle,
   sequence handling, bounded recovery, keepalive and last-frame-age reporting.
3. UI: latest-frame rendering, settings, point graph, screenshots, RAW archive/replay;
   no modifications of captured samples by display settings.
4. Build: isolated pinned JDK/Android tools, reproducible PowerShell build, local
   signing key kept outside source distribution. Check manifest, APK signature,
   JVM suite and existing Windows regression suite. Report phone testing honestly.

Review focus: fragmented link packets; malformed/oversized frame headers; unplug
during handshake; denied permission; background/reopen/replay transitions.

## Build

`build.ps1` uses a local pinned JDK 17 and Google Android API 35 / build-tools 35.0.0.
The toolchain lives outside the source tree in `../../android-toolchain` by default.
Pass `-Toolchain <path>` to override it. The script runs the JVM tests, javac,
D8, aapt2, zipalign and apksigner. It creates a private local preview signing key
outside the source tree. Keep that key for future updates of your own build.
The prebuilt APK contains no native libraries and is architecture-independent.

## Verification status

The preview APK compiles and its v2/v3 signature verifies. JVM tests cover link
framing, checksums, the Windows handshake, authoritative frame lengths, RAW
extraction, radiometry, callback retirement, USB lifetime serialization and RAW
archive finalization. The existing Windows suite passes (33 tests).

**Physically tested by the project owner:** installation and live thermal streaming
worked with his Gen 2 Lightning/iOS camera connected to an Android phone over OTG.
Compatibility with other phone models and Android versions is not yet established.
This is a first Android port, not full desktop feature parity: no optical/MSX,
desktop-style calendar seeking, background camera service or automatic disk quota.
RAW files stay in app-private storage until exported; uninstalling removes them.
Recording is explicit and stops when the app leaves the foreground. A graph pause
does not stop measurement or RAW recording; an image freeze holds only the display.
