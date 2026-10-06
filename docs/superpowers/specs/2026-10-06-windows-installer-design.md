# Windows installer design

## Goal and supported baseline

Deliver one offline Setup.exe for Windows 10/11 x64, bundling the existing
standalone viewer and its runtime. No Python installation or paid code-signing
certificate is required. Administrator consent and Windows security warnings
may still be required. Compatibility with every computer, enterprise policy,
ARM64 machine or hardware fault is not promised.

## Approach

Use an installer shell plus a narrowly scoped native libwdi helper. Compared
with launching Zadig interactively, this permits automatic device selection and
verification. Compared with distributing a custom kernel driver, it reuses
Microsoft WinUSB and libwdi's established package preparation/installation path.
Zadig remains a documented manual recovery option, not the automatic mechanism.

## Application files and data

Install the existing frozen application and `_internal` runtime together in a
per-user writable application directory, with a Start Menu shortcut. Preserve
the existing `Data` directory on upgrade. Never delete recordings or settings
during installation, failure recovery or ordinary uninstallation. The launcher
and viewer run without administrator privileges. Elevate only the driver helper.
Do not overwrite the user's current working development installation.

## Driver helper safety boundary

Enumerate present devices using libwdi. Allow writes only for exact VID 09CB,
PID 1996 composite child interfaces MI_00, MI_01 and MI_02. Never select the
composite parent, a hub, or another device. If more than one matching camera
is present, stop and ask the user to connect only one camera. Skip interfaces
already using WinUSB. Log original drivers, device IDs, installation results
and final verification. Never interpret a helper exit code alone as proof that
all three interfaces are usable.

Disclose that libwdi generates a local certificate and installs trust-store
entries for the device-specific package. Do not disable Secure Boot, driver
signature enforcement, antivirus, or enterprise policy. Bundle upstream source
and license notices appropriate to the distributed libwdi components.

## Connection and failure handling

Show connection instructions for the project's tested modified Lightning/iOS
unit. Detect a missing camera and wait with a cancel option. Install interfaces
sequentially and re-enumerate after each step because Windows may remove and
recreate device nodes. Use bounded retries/timeouts; preserve detailed logs.
Partial success is reported as partial success, not a completed installation.
Cancellation or a denied administrator prompt must not be reported as success.

Once all interfaces are verified, start the unchanged working application as
the original user. Do not introduce firmware/configuration writes, optical
probes, new USB initialization, or a second process claiming the camera.
Driver installation can interrupt enumeration. The installer cannot guarantee
that the camera never resets, nor can it cure power or cable faults. Session
recovery remains the responsibility of the existing capture implementation.

## Verification and delivery

Before implementation, add failing tests for the hardware-ID allowlist,
composite-parent exclusion, already-installed behavior, multiple-camera
ambiguity, missing devices, cancellation, partial failure and final validation.
Use fake enumeration/install results for tests that must not alter real drivers.
Run the existing regression suite and standalone application smoke tests.
Test extraction/install paths containing spaces and non-ASCII characters,
upgrade data preservation, and launch without installed Python or elevated GUI.

Actual first-time driver installation and streaming require physical-camera
tests on clean Windows 10/11 x64 systems. Existing WinUSB drivers on this PC do
not constitute a clean-install test. Report untested configurations explicitly.
Deliver a local preview installer first; do not publish a GitHub release until
the preview has been validated. This document approves no immediate driver
replacement on the user's current working PC.
