# Building the Windows portable package

Build on Windows x64 with Python 3.12 and Tcl/Tk installed. The existing
source viewer and capture script are shipped as explicit data files, with only
an optional portable data-root override; their algorithms are unchanged.
The dispatcher handles their existing `sys.executable -u capture.py` command.
`--contents-directory _internal` puts runtimes and scripts under `_internal/`.
The dispatcher sets `FLIR_PORTABLE_DATA_ROOT` to the sibling `Data/` directory,
so writable files stay separate from runtime files. Source launches without
that environment variable retain their original paths.

1. Create `.venv` and install `requirements.txt` as for the source release.
2. Install build-only `pyinstaller==6.22.0` in that environment.
3. Prepare a vendor folder containing the official `zadig-2.9.exe`,
   `libwdi-1.5.1-source.zip`, and `COPYING` / `COPYING-LGPL` extracted from
   that source archive. Download from https://zadig.akeo.ie/ and verify the
   executable's Authenticode signature is valid for Akeo Consulting.
4. Add upstream `libusb-1.0.30.tar.bz2`, its `COPYING` saved as `libusb-COPYING`,
   and GitHub tag v1.0.30.0 source `libusb-package-1.0.30.0-source.zip` from
   https://github.com/pyocd/libusb-package to the vendor folder.
   The package includes both libusb's LGPL 2.1 text and corresponding source.
   Verify downloaded archives against upstream published digests.
5. Run `tools/build_portable.ps1 -VendorPath <vendor-folder> -Version 0.4.0`.
6. Run `tools/test_portable.ps1 -Archive <built-zip>` to exercise the extracted
   package with Python removed from PATH, normal GUI/worker launch, capture
   stdout, and failure reporting. The test retains its temporary extracted
   copy for inspection; it does not install/change drivers.

The ZIP is written under `portable-dist/`. The offline Python suite runs before
the build; compiled runtime/worker self-tests and Tk startup run afterward.
Smoke-generated settings and empty DVR data are removed only from the generated
distribution before packing. Real source recordings are never copied or deleted.
No signing key, user camera dump, existing settings or personal recording belongs
in the release. Test fresh-machine USB streaming separately before claiming it.

No runtime Python installation is required by the end user. WinUSB is still a
first-time prerequisite, documented in the portable README. Never run Zadig
automatically or replace unrelated device drivers.
