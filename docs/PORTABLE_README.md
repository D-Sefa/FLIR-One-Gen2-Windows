# FLIR ONE Gen 2 Windows — Portable

Version 0.4.0 · matching Android navy/mint styling; existing desktop RAW DVR,
analysis and capture behavior retained.

Windows 10/11 x64. No Python installation, pip, setup.exe or internet connection
is needed to run the viewer. Extract the entire ZIP to a writable folder and
keep all its files together. Do not run the EXE inside the ZIP.

## First: install WinUSB with Zadig

**You must install WinUSB drivers with Zadig before using the camera.**
Skip this step if the three camera interfaces already use WinUSB.

1. Connect and power your FLIR ONE Gen 2 Lightning/iOS camera using the verified
   USB data wiring. This project's tested unit is physically modified: the
   Lightning connector is removed and a USB data cable soldered in its place.
   An ordinary Lightning charging adapter is not a verified substitute.
2. Close all camera applications. Run `drivers/zadig-2.9.exe`; accept its
   administrator/UAC prompt. Zadig is the unmodified official signed executable.
3. In Zadig select **Options → List All Devices**.
4. Identify ONLY the FLIR interfaces with hardware ID `VID_09CB&PID_1996`:
   `MI_00` (iAP2), `MI_01` (FileIO), and `MI_02` (Frame).
5. For each of these three interfaces, select **WinUSB**, then Install/Replace
   Driver. Do not select libusb-win32 or libusbK instead.
6. Never replace drivers for your keyboard, mouse, USB hub or unrelated devices.
   Disconnect/reconnect the camera after installation if necessary.

Driver installation is a separate first-time Windows requirement. The portable
viewer does not silently change any USB drivers.

## Run

Double-click **FLIR-One-Gen2.exe**. The viewer automatically starts its capture
worker; do not open another capture/viewer at the same time. Keep the camera
battery/power and data connection stable. The viewer does not need administrator
privileges once the WinUSB drivers are installed.

The viewer is unsigned. Windows SmartScreen may show an unknown-publisher
warning. On a personal PC, **More info → Run anyway** may be available. Security
policies/antivirus can still block execution; do not disable your security
software indiscriminately. Check the download source and published checksum.

## Recordings and settings

The application is portable: settings, logs and recordings are stored under
`Data/outputs/` next to the EXE, including `Data/outputs/FLIR_DVR`. Keep `Data/` when
upgrading and back it up before replacing the application. Use a writable
folder outside Program Files; avoid read-only media. Bundled libraries, DLLs,
Tcl/Tk data and application code are in `_internal/`: do not move the EXE alone.

The top-level folder is intentionally simple:

```text
FLIR-One-Gen2.exe   Start the viewer
README.md          Setup and usage
drivers/           Zadig and its source archive
licenses/          Third-party notices
_internal/         Required runtime files; leave unchanged
Data/              Settings, logs and recordings
```

To migrate from the earlier flat portable package, close it and copy the old
`outputs/` folder into the new `Data/` folder. Preserve the existing `Data/`
when replacing the application. Do not merge old runtime DLLs into `_internal/`.

Thermal view, analysis and RAW gallery are included. Optical/visible/MSX are
still unavailable. Display adjustments do not improve physical sensor resolution
or guarantee calibrated measurement accuracy.

Hardware modification risks permanent damage. Disconnect the battery and all
power before soldering; do not blindly connect USB +5 V to a Lightning pad or
battery terminal. A universal pad-by-pad wiring guide is not provided.

Project and full guide: https://github.com/D-Sefa/FLIR-One-Gen2-Windows
Official Zadig: https://zadig.akeo.ie/
Bundled licenses and source information are in `licenses/`; Zadig/libwdi source
is also supplied as `drivers/libwdi-1.5.1-source.zip`.
