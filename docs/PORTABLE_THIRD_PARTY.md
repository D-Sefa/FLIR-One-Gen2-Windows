# Portable third-party software

The FLIR application source remains MIT licensed. This ZIP is an aggregation
of the application and separately licensed runtimes/tools, not a relicensing
of those components. Preserve their notices when redistributing.

- Python: PSF license and bundled notices (Python-LICENSE.txt), https://www.python.org/
- Tcl/Tk: license.terms files, https://www.tcl.tk/
- NumPy: BSD license and bundled third-party notices, https://numpy.org/
- Pillow: HPND and bundled dependency notices, https://python-pillow.github.io/
- PyUSB: BSD license, https://github.com/pyusb/pyusb
- libusb-package: Apache-2.0; bundled libusb: LGPL-2.1-or-later,
  https://github.com/pyocd/libusb-package and https://github.com/libusb/libusb
  The libusb LGPL text is in `libusb-LGPL-2.1.txt`; corresponding upstream libusb
  1.0.30 and libusb-package 1.0.30.0 source archives are in `sources/`.
  The dynamically loaded `_internal/libusb-1.0.dll` may be replaced with a
  compatible rebuilt library; changing it can affect camera compatibility.
- importlib-resources: Apache-2.0, https://github.com/python/importlib_resources
- PyInstaller bootloader: GPL with distribution exception permitting bundled
  applications; https://pyinstaller.org/en/stable/license.html
- Zadig 2.9: GPL-3.0-or-later; libwdi 1.5.1: LGPL-3.0-or-later.
  Official unmodified executable, COPYING/COPYING-LGPL and accompanying
  source archive are provided. Source/build documentation:
  https://github.com/pbatard/libwdi/tree/v1.5.1
  https://github.com/pbatard/libwdi/wiki/Install
  The official source includes Zadig under examples/. Bundled driver components
  retain their upstream licenses. No affiliation with Akeo Consulting is implied.

Package notices collected from installed distributions are provided in
subdirectories here. The official libusb source archive SHA256 is
`fea36f34f9156400209595e300840767ab1a385ede1dc7ee893015aea9c6dbaf`, matching
https://github.com/libusb/libusb/releases/tag/v1.0.30. Wrapper/build source is
from https://github.com/pyocd/libusb-package/tree/v1.0.30.0, commit
`3ea4db141ef013c070f28738cae6ee8ed85688be`. The matching wheel metadata identifies
this upstream project; no source distribution is supplied on PyPI for that version.
Its `src/libusb` submodule points to `87a55632db62c9bdc58cd31d3ccfa673f1bb017f`,
which is exactly the upstream libusb v1.0.30 commit supplied in the source archive.
