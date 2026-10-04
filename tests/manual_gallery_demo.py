"""Offline visual smoke test: synthetic archive only, never opens USB."""
import pathlib
import sys
import time
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
from test_gallery_ui import GalleryUiTests

case=GalleryUiTests()
case.setUp()
viewer=case.v
viewer.root.title('FLIR Gallery — OFFLINE TEST')
viewer.root.geometry('1420x920')
viewer.root.deiconify()
viewer.open_recording({'start':case.start,'end':case.start+2,'count':3})
viewer.open_gallery()
viewer.gallery.window.title('Recordings — OFFLINE TEST')
viewer.root.after(180000,viewer.close)
try:viewer.root.mainloop()
finally:
    case.env.stop()
    case.tmp.cleanup()
