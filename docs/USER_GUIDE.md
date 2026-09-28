# User Guide

## 1. Supported Hardware

This release targets the **FLIR ONE Gen 2 Lightning/iOS** model that enumerates
as USB vendor/product ID `09CB:1996`. The tested camera reports Rosebud firmware
`0.4.27` and a 160×120 Lepton thermal sensor.

The project does not convert the camera to Android mode and does not modify its
firmware or persistent configuration.

## 2. USB and Power Connection

The camera must have a stable power source and a real USB data connection.

### Stock or finished adapter

Use an adapter or breakout that carries USB `D+`, `D−` and ground correctly.
Cheap charge-only cables do not work. If Windows repeatedly plays connect and
disconnect sounds, repair or replace the cable before debugging the software.

### Custom-wired or open camera

The tested custom connection uses:

- USB `D+`
- USB `D−`
- common ground
- the camera's own correctly connected Li-ion battery/power circuitry

The PC cable's red 5 V conductor was left isolated in the tested build. Do not
inject USB 5 V into an unknown Lightning, test-pad or battery node. Do not guess
pin positions from wire colour alone. Verify the wiring with continuity tests
and the relevant connector documentation.

Safety rules:

- Check battery polarity before connecting it.
- Insulate the battery and all exposed conductors.
- Prevent the battery from moving or stressing its connector.
- Disconnect power immediately if a component becomes unusually hot, swells,
  smells, or the board draws abnormal current.
- Never parallel two independent USB hosts on the same `D+`/`D−` pair.

## 3. Confirm Windows Detection

Power the camera and connect USB. Windows should enumerate a composite device
with hardware ID:

```text
VID_09CB&PID_1996
```

The three FLIR interfaces normally appear as:

```text
MI_00  iAP Interface
MI_01  com.flir.rosebud.fileio
MI_02  com.flir.rosebud.frame
```

Names can vary, so always confirm the VID, PID and `MI_0x` value. The three
interfaces are functions of one camera, not three separate cameras.

You can also run:

```powershell
Get-PnpDevice -PresentOnly | Where-Object InstanceId -match 'VID_09CB&PID_1996'
```

## 4. Install WinUSB with Zadig

The Python USB backend needs WinUSB access to the composite interfaces.

1. Download Zadig only from its official website: <https://zadig.akeo.ie/>.
2. Run Zadig as Administrator.
3. Open **Options → List All Devices**.
4. Select the FLIR entry whose ID is `09CB:1996` and interface is `MI_00`.
5. Confirm the target driver on the right is **WinUSB**.
6. Choose **Install Driver** or **Replace Driver**.
7. Repeat for the same FLIR device's `MI_01` and `MI_02` interfaces.
8. Disconnect and reconnect the camera once.

Do not select a keyboard, mouse, Bluetooth adapter, storage device, phone or
any entry whose VID/PID is not `09CB:1996`. Replacing the driver of an unrelated
device can stop that device from working until its original driver is restored.

Installing WinUSB on all three FLIR interfaces does not disable the optical
camera. It only changes which Windows user-space driver can open each interface.

## 5. Install and Start the Viewer

1. Install 64-bit Python 3.11 or 3.12 from <https://python.org/> and enable
   **Add Python to PATH**.
2. Extract or clone this repository to a writable folder.
3. Run `setup.cmd`. It creates `.venv`, installs the dependencies and reports
   the detected FLIR interfaces and drivers.
4. Run `FLIR-One-Gen2-Windows.cmd`.

The first image can take several seconds while iAP2 authentication and the
Rosebud configuration session are established.

## 6. Main Controls

### Display

- **Palette** chooses the colour map.
- **Scale** chooses how temperatures map to colours.
- **Tone** moves the palette midpoint without changing measured temperatures.
- **Display span** changes colour sensitivity. A smaller percentage emphasises
  small temperature differences; a larger percentage covers a wider range.
- **Reset** restores only display defaults.
- **Reset tuning** resets tone/span, contrast, minimum span, detail, denoise and
  interpolation without changing the palette, selected mode or radiometry.
- Numeric fields and sliders support the mouse wheel and arrow keys. Hold Shift
  for a ten-times larger step. Values are saved between sessions.

| Scale | Best use | Behaviour |
|---|---|---|
| Auto | General inspection | Global plateau HEQ, bounded contrast amplification |
| Detail | PCB and low-contrast structure | Locally adaptive, contrast-limited histogram equalization |
| Linear auto | Walls and natural temperature gradients | Adaptive linear temperature range |
| Manual | Comparing scenes at the same scale | Fixed minimum/maximum in Celsius, independent of scene extrema |
| Background relative | Locating warm objects | Learns a background interval and renders it dark |

**Contrast** (Auto/Detail) controls histogram clipping, 1.0–4.0. Higher values
show more contrast but may amplify noise. Start at 1.5.
**Min span °C** prevents almost uniform scenes from filling the entire palette
with sensor noise. Start at 1.5 °C; lower it deliberately for small differences.
**Detail %** blends local CLAHE into the global mapping. Start at 35%; 100% is
not necessarily better. Equal colours in different regions may correspond to
different temperatures in this mode; use point measurements for comparison.
**Denoise %** blends a small edge-preserving spatial filter before colour mapping.
It is display-only, adds no frame queue and is not used in Manual mode.
**Interpolation** selects a smooth enlarged picture or visible native pixels.
It does not increase true sensor resolution.

In Manual, **Fit scene** copies the current scene min/max into the range and
resets tone/span. The entries are always Celsius even when readings use °F.
At neutral tone and 100% span they are the exact black/white endpoints.
Tone/span adjustments change the effective endpoints shown beneath the image.
For Auto/Detail the displayed limits are the nonlinear AGC domain, not a linear
colour thermometer. Increasing sensitivity can amplify noise; it cannot improve NETD.

Scale-specific controls are shown only when relevant. Manual mode exposes the
manual temperature range. Background-relative mode exposes deadband, minimum
hot span and learning time.

The legacy settings `FLIR HEQ`, `Wall detail`, `Scene min–max` and percentile
modes migrate to Auto or Linear auto. Background relative and Manual are retained.
No camera firmware, USB initialization or iAP2 settings are changed by these controls.

### Temperature / radiometry

- **Emissivity** compensates for surface emissivity.
- **Reflected temp** is the estimated reflected apparent temperature.
- **Calibration offset** applies a user offset after conversion.
- **3×3 point average** reduces single-pixel noise in cursor/point readings.
- **°C / °F** changes displayed units.
- **Reset** restores `0.95`, `20.0 °C`, zero offset, 3×3 averaging and Celsius.

The status FPS is a rolling average over the latest two seconds, so it reacts
quickly when the USB stream slows or recovers.

## 7. Measurements and History

- Move the pointer over the image for the local temperature.
- Left-click the thermal image to add a measurement point.
- Right-click near a point to remove it.
- Use **Start logging** for CSV measurements.
- Use **Open History** to inspect the continuous raw-frame archive.
- Pausing or zooming the graph does not stop collection; it changes only the
  graph view.

## 8. Periodic Shutter Flash

A click and brief disturbed frame are normally the camera's flat-field
correction (FFC). The backend detects and suppresses settling frames so they do
not enter the display, graph or archive.

## 9. Troubleshooting

### Camera not found

- Confirm `VID_09CB&PID_1996` is present.
- Check battery/power and common ground.
- Verify the cable carries data, not just charging power.
- Try another direct PC USB port instead of a passive splitter.
- Run `tools\driver_check.ps1` or `setup.cmd`.

### Connect/disconnect loop

This is usually unstable power, battery contact or USB wiring. Software cannot
repair a physical disconnect. Secure the battery and test another data cable.

### Image freezes

The application attempts endpoint and process recovery automatically. If the
camera has disappeared from Device Manager, fix power/cabling first. If it is
still present, close and reopen the viewer. As a last step, reconnect the camera.

### Optical image is unavailable

This is the current known limitation, not a Zadig configuration error. Thermal
records currently arrive with `jpg_size = 0`. See the help-wanted section in
the main README if you can contribute a verified Gen 2 iOS capture or protocol
implementation.
