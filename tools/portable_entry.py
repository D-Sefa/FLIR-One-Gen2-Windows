"""Portable dispatcher for the unchanged viewer and capture scripts."""
from pathlib import Path
import os
import runpy
import sys


def data_directory(bundle_root, frozen):
    root = Path(bundle_root)
    return root.parent / 'Data' if frozen else root


def selected_script(args, root):
    root = Path(root)
    if not args:
        return root / 'outputs' / 'flir_live_viewer.py'
    if len(args) == 2 and args[0] == '-u' and Path(args[1]).name == 'flir_iap2_frame.py':
        return root / 'work' / 'flir_iap2_frame.py'
    raise ValueError('Unsupported portable launch arguments')


def main():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    data = data_directory(root, bool(getattr(sys, 'frozen', False)))
    if getattr(sys, 'frozen', False):
        os.environ['FLIR_PORTABLE_DATA_ROOT'] = str(data)
    (data / 'outputs').mkdir(parents=True, exist_ok=True)
    (data / 'work').mkdir(exist_ok=True)
    os.chdir(data)
    sys.path.insert(0, str(root / 'work'))
    args = sys.argv[1:]
    diagnostic = args == ['--self-test'] or (args and args[-1] == '--self-test')
    if diagnostic:
        mode = 'viewer' if len(args) == 1 else selected_script(args[:-1], root).stem
        import json
        import numpy
        import libusb_package
        from PIL import Image
        import tkinter
        if libusb_package.get_libusb1_backend() is None:
            raise RuntimeError('Bundled libusb backend not found')
        state = runpy.run_path(str(root / 'outputs' / 'flir_live_viewer.py'), run_name='portable_diagnostic')
        assert state['ROOT'] == data
        print(json.dumps({'ok': True, 'mode': mode, 'root': str(root),
                          'data': str(data), 'frozen': bool(getattr(sys, 'frozen', False)),
                          'numpy': numpy.__version__, 'pillow': Image.__version__,
                          'tk': tkinter.TkVersion}), flush=True)
        return
    if args == ['--smoke-test']:
        os.environ['FLIR_EXTERNAL_CAPTURE'] = '1'
        state = runpy.run_path(str(root / 'outputs' / 'flir_live_viewer.py'), run_name='portable_smoke')
        viewer = state['Viewer']()
        viewer.root.withdraw()
        viewer.root.after(1200, viewer.close)
        viewer.run()
        print('PASS portable Tk viewer startup/shutdown without USB', flush=True)
        return
    script = selected_script(args, root)
    if not args and os.name == 'nt':
        # Hide only our own console. FreeConsole invalidates inherited stdin
        # and breaks the unchanged viewer's Popen on Windows.
        import ctypes
        console_pids = (ctypes.c_ulong * 8)()
        if ctypes.windll.kernel32.GetConsoleProcessList(console_pids, 8) == 1:
            ctypes.windll.kernel32.GetConsoleWindow.restype = ctypes.c_void_p
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            ctypes.windll.user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
    if args and sys.stdout is not None:
        sys.stdout.reconfigure(line_buffering=True, write_through=True)
    sys.argv = [str(script)]
    runpy.run_path(str(script), run_name='__main__')


if __name__ == '__main__':
    original_args = sys.argv[1:]
    try:
        main()
    except Exception:
        import traceback
        root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
        error_root = root.parent if getattr(sys, 'frozen', False) else root
        (error_root / 'portable-error.log').write_text(traceback.format_exc(), encoding='utf-8')
        if original_args:
            raise
        import tkinter.messagebox
        tkinter.messagebox.showerror('FLIR ONE Gen 2', 'Startup failed. See portable-error.log in the application folder.')
        sys.exit(1)
