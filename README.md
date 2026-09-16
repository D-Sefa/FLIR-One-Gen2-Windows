# FLIR ONE Gen 2 Lightning/iOS Windows Viewer

An independent Windows live viewer and radiometric analysis application for the
**FLIR ONE Gen 2 Lightning/iOS** camera. It authenticates the camera through
iAP2, reads the vendor-specific thermal frame interface with WinUSB, and
displays the 160×120 Lepton stream without an iPhone or the discontinued FLIR
mobile application.

![Thermal viewer sample](docs/sample-thermal-frame.png)

## Features

- Live 160×120 radiometric thermal stream on Windows 10/11
- Temperature under the pointer, scene minimum/centre/maximum and measurement points
- Measurement history, hover readout, graph pause/zoom and continuous DVR archive
- Iron, Lava, Rainbow, White-hot and Black-hot palettes
- FLIR HEQ, wall-detail, background-relative, scene, percentile and manual scaling
- Emissivity, reflected temperature and calibration-offset controls
- Separate **Reset** actions for display and temperature/radiometry settings
- Responsive FPS readout based on the latest two seconds
- Automatic iAP2 session setup, FFC-frame suppression and stream recovery
- One-click Windows launcher and first-run dependency/driver check

## Quick Start

1. Read the [USB connection and complete user guide](docs/USER_GUIDE.md).
2. Connect and power the camera.
3. Install **WinUSB** with Zadig on the three FLIR interfaces whose hardware ID
   is `VID_09CB&PID_1996` (`MI_00`, `MI_01`, `MI_02`). Do not modify unrelated devices.
4. Install Python 3.11 or 3.12.
5. Run `setup.cmd` once.
6. Run `FLIR-One-Gen2-Windows.cmd`.

## Visible/Optical Stream: Help Wanted

The thermal stream is working, but the Gen 2 visible-light camera is not yet
enabled by this project. The device advertises iAP2 protocols named
`com.flir.rosebud.fileio` and `com.flir.rosebud.frame`; however, all thermal
records captured with the current verified startup sequence report
`jpg_size = 0`. Installing WinUSB on all three interfaces is **not** the cause:
those drivers merely allow the application to access the composite USB device.

We welcome help from anyone who has one of the following:

- a reproducible USBPcap/Wireshark capture from a working Gen 2 iOS session;
- verified iAP2/FileIO/Frame commands that enable the 640×480 visual sensor;
- a working legacy SDK sample with corresponding USB traffic;
- analysis of the original Gen 2 native SDK that identifies the visual-stream command.

Please open an issue or pull request. Include hardware/firmware versions,
interface and endpoint information, and a capture or code that others can
repeat. Unverified “magic” control-transfer values are not sufficient evidence.
See [CONTRIBUTING.md](CONTRIBUTING.md).

## Status and Limitations

- Tested with a FLIR ONE Gen 2 Lightning/iOS unit running Rosebud firmware `0.4.27`.
- Thermal capture and analysis work; visible/optical and MSX do not yet work.
- Temperature accuracy depends on the camera calibration and selected radiometric settings.
- A stable battery/power source and reliable USB data connection are essential.
- This is an independent community project and is not affiliated with or endorsed by FLIR.

## License

Source code is released under the [MIT License](LICENSE). FLIR and FLIR ONE are
trademarks of their respective owner.

