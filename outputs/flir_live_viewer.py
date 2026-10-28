"""One-click radiometric FLIR ONE Gen 2 live viewer for Windows."""

from __future__ import annotations
import bisect, csv, datetime as dt, json, math, os, pathlib, queue, re, sqlite3, statistics, struct, subprocess, sys, threading, time, tkinter as tk, zlib
from collections import deque
from tkinter import filedialog, messagebox, ttk

ROOT = pathlib.Path(os.environ.get("FLIR_PORTABLE_DATA_ROOT", pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "work" / "pydeps"))
sys.path.insert(0, str(ROOT / "work"))
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageTk
from flir_display import ToneMapper, MODES, migrate_mode
from flir_playback import PlaybackMixin
from flir_gallery import age_label, timestamp_label

CAPTURE = ROOT / "work" / "flir_iap2_frame.py"
LIVE_RAW = ROOT / "outputs" / "flir-live.raw16"
LIVE_VISUAL = ROOT / "outputs" / "flir-live-visible.jpg"
LIVE_STATUS = ROOT / "outputs" / "flir-live-status.json"
CAPTURE_LOG = ROOT / "outputs" / "flir-capture.log"
CAPTURE_DIR = ROOT / "outputs" / "FLIR Kayitlari"
CAPTURE_DIR.mkdir(exist_ok=True)

DVR_DIR = ROOT / "outputs" / "FLIR_DVR"
DVR_DIR.mkdir(exist_ok=True)
DVR_DB = DVR_DIR / "history.sqlite3"
STORAGE_SETTINGS = ROOT / "outputs" / "flir-storage-settings.json"
VIEWER_SETTINGS = ROOT / "outputs" / "flir-viewer-settings.json"
DVR_MAGIC = b"F1D1"
DVR_HEADER = struct.Struct("<4sQII")  # magic, timestamp_ns, raw_size, compressed_size
SRC_W, SRC_H, VIEW_W, VIEW_H, SCALE = 160, 120, 120, 160, 4
CANVAS_W, CANVAS_H = VIEW_W * SCALE, VIEW_H * SCALE
# Calibration constants from the supplied FlirOneForWindows Gen 2 source.
R1, B, F, O, R2 = 16528.178, 1427.5, 1.0, -1307.0, 0.012258549

def clamp(v, lo, hi): return lo if v < lo else hi if v > hi else v

def interpolate(stops, value):
    pos = clamp(value, 0, 255) * (len(stops)-1) / 255
    left = int(pos)
    if left >= len(stops)-1: return stops[-1]
    f = pos-left; a, b = stops[left], stops[left+1]
    return tuple(int(a[i]+(b[i]-a[i])*f) for i in range(3))

def palette_color(name, v):
    if name == "White hot": return (v, v, v)
    if name == "Black hot": return (255-v, 255-v, 255-v)
    if name == "Rainbow":
        return interpolate([(0,0,80),(0,90,255),(0,255,180),(255,255,0),(255,0,0),(255,255,255)], v)
    if name == "Lava":
        return interpolate([(0,0,0),(70,0,110),(210,0,40),(255,100,0),(255,255,80),(255,255,255)], v)
    return interpolate([(0,0,10),(13,0,118),(72,0,150),(170,28,92),(238,92,18),(255,205,45),(255,255,255)], v)

class Viewer(PlaybackMixin):
    def __init__(self):
        self.root=tk.Tk(); self.root.title("FLIR ONE Gen 2 — Thermal Analysis"); self.root.configure(bg="#050609"); self.root.minsize(1040,780)
        self.root.after(10,self.enable_dark_titlebar)
        self.viewer_settings=self.load_viewer_settings_file()
        self._settings_save_after=None
        self.raw=None; self.display_values=[]; self.temperatures=[]; self.photo=None; self.rendered_image=None; self.last_mtime=0; self.stream_mtime=0; self.visual_mtime=0; self.visible_image=None; self.visual_available=False; self.rotation_angle=float(self.viewer_settings.get("rotation_angle",0.0))%360.0; self.rotation_transform=None; self.rotation_drag_start_x=0; self.rotation_drag_start_angle=0.0; self.rotation_dragged=False; self.viewport_scale=max(0.60,min(1.60,float(self.viewer_settings.get("viewport_scale",1.0)))); self.base_canvas_w=CANVAS_W; self.base_canvas_h=CANVAS_H
        self.frame_times=deque(maxlen=60); self.fps_window_seconds=2.0; self.frozen=False; self.points=[]; self.next_point=1

        # Robust frame guard. The Gen 2 may occasionally publish post-FFC
        # settling frames whose whole radiometric image is shifted by many
        # degrees. Those frames must never enter the live graph or DVR.
        self.frame_guard_prev_samples=None
        self.frame_guard_candidate_samples=None
        self.frame_guard_candidate_count=0
        self.frame_guard_rejected=0
        self.frame_guard_last_reason=""
        self.history_retention_seconds=6*3600
        self.history_max_samples=100000

        # One automatic hottest point only. Its coordinates follow the current
        # hottest pixel; its graph trace remains a single continuous MAX series.
        self.max_point={
            "name":"MAX",
            "x":0,"y":0,
            "color":"#d8e8ef",
            "history":deque(maxlen=self.history_max_samples),
            "graph":bool(self.viewer_settings.get("max_graph_visible",True)),
            "auto_hot":True,
        }

        self.graph_windows=[30,60,120,300,600,1800,3600,7200]
        try:self.graph_window_index=int(self.viewer_settings.get("graph_window_index",3))
        except (TypeError,ValueError):self.graph_window_index=3
        self.graph_window_index=int(clamp(self.graph_window_index,0,len(self.graph_windows)-1))
        self.graph_paused=False; self.graph_pause_anchor=None; self.graph_dirty=True; self.graph_last_draw=0.0
        self.graph_photo=None; self.graph_render_state=None; self.graph_hover_stamp=None
        self.graph_selected_series="MAX"
        self.graph_detail_text=tk.StringVar(value="Selected: MAX • waiting for data")
        self.graph_origin=None
        self.graph_paused_page_start=None

        # Free pan/zoom state.  None means follow the live timeline.
        self.graph_view_t0_override=None
        self.graph_y_pan_c=0.0
        self.graph_drag_start=None
        self.graph_dragging=False
        self.graph_drag_threshold=5

        # Point-level transient guard. The existing frame guard rejects global
        # FFC/shutter corruption; this second guard rejects isolated one-frame
        # spikes that affect MAX or an individual measurement point.
        self.graph_filter_state={}
        self.graph_transient_rejected=0

        # Continuous DVR archive: every RAW16 frame, losslessly compressed.
        self.dvr_dir=DVR_DIR
        self.dvr_db=DVR_DB
        self.storage_max_gb=20.0
        self.storage_warned_near_limit=False
        self.storage_warned_disk_low=False
        self.storage_delete_warned=False
        self.storage_check_last=0.0
        self._pending_archive_quality="Max FPS"
        self.load_storage_settings()

        self.dvr_queue=queue.Queue(maxsize=256)
        self.dvr_stop=threading.Event()
        self.dvr_frames_written=0
        self.dvr_bytes_written=0
        self.dvr_last_saved_ts=0.0
        self.archive_quality_var=tk.StringVar(value=self._pending_archive_quality)
        self.archive_size_var=tk.StringVar(value="Estimating storage…")
        self.playback_mode=False
        self.init_playback()
        self.mirror_var=tk.BooleanVar(value=bool(self.viewer_settings.get("mirror",False)))
        self.playback_running=False
        self.playback_speed=1.0
        self.playback_time=None
        self.playback_after_id=None
        self.playback_window_seconds=300
        self.history_window=None
        self.history_graph=None
        self.history_scroll=None
        self.history_preview=None
        self.history_preview_photo=None
        self.history_status_var=None
        self.history_point_var=tk.StringVar(value="")
        self.history_sessions=[]
        self.history_map=[]
        self.history_hover_after=None
        self.history_play_after=None
        self.history_playing=False
        self.history_play_ts=None
        self.history_session_index=None
        self.history_selected_ts=None
        self.history_selected_session_index=None
        self.history_speed=1.0
        self.history_selected_var=tk.StringVar(value="Selected: —")
        self.history_speed_var=tk.StringVar(value="1×")
        self.last_text_update=0.0; self.last_point_list_update=0.0
        self.recording=False; self.csv_file=None; self.csv_writer=None; self.csv_series_names=[]
        vs=self.viewer_settings
        palette=vs.get("palette","Iron")
        if palette not in ("Iron","Lava","Rainbow","White hot","Black hot"):palette="Iron"
        unit=vs.get("unit","°C")
        if unit not in ("°C","°F"):unit="°C"
        view_mode=vs.get("view_mode","Thermal")
        if view_mode not in ("Thermal","Visible","Overlay","MSX edges"):view_mode="Thermal"
        scale_mode=migrate_mode(vs.get("scale_mode","Auto"))
        self.tone_mapper=ToneMapper()
        self.contrast_var=tk.StringVar(value=str(vs.get("agc_contrast","1.5")))
        self.min_span_var=tk.StringVar(value=str(vs.get("agc_min_span","1.5")))
        self.detail_var=tk.StringVar(value=str(vs.get("agc_detail","35")))
        self.denoise_var=tk.StringVar(value=str(vs.get("agc_denoise","30")))
        interp=vs.get("display_interpolation","Smooth")
        self.interpolation_var=tk.StringVar(value=interp if interp in ("Smooth","Native pixels") else "Smooth")

        self.palette_var=tk.StringVar(value=palette); self.unit_var=tk.StringVar(value=unit)
        self.view_mode=tk.StringVar(value=view_mode); self.overlay_alpha=tk.IntVar(value=int(clamp(float(vs.get("overlay_alpha",35)),0,100)))
        self.visual_x=tk.IntVar(value=int(clamp(float(vs.get("visual_x",0)),-80,80)))
        self.visual_y=tk.IntVar(value=int(clamp(float(vs.get("visual_y",0)),-80,80)))
        self.visual_zoom=tk.IntVar(value=int(clamp(float(vs.get("visual_zoom",100)),60,180)))
        self.emissivity_var=tk.StringVar(value=str(vs.get("emissivity","0.95")))
        self.reflected_var=tk.StringVar(value=str(vs.get("reflected_temp","20.0")))
        self.temp_offset_var=tk.StringVar(value=str(vs.get("calibration_offset","0.0")))
        self.scale_mode=tk.StringVar(value=scale_mode)
        self.manual_min=tk.StringVar(value=str(vs.get("manual_min","15")))
        self.manual_max=tk.StringVar(value=str(vs.get("manual_max","35")))
        self.tone_var=tk.IntVar(value=int(clamp(float(vs.get("display_tone",0)),-100,100)))
        self.thermal_span_var=tk.IntVar(value=int(clamp(float(vs.get("thermal_span",100)),25,400)))
        self.tone_label_var=tk.StringVar(value=f"{self.tone_var.get():+d}")
        self.thermal_span_label_var=tk.StringVar(value=f"{self.thermal_span_var.get()}%")

        # Background-relative tone mapping affects display only; radiometric
        # temperatures, graph samples and the RAW16 DVR stay untouched.
        self.background_deadband_var=tk.StringVar(value=str(vs.get("background_deadband","0.25")))
        self.background_hot_span_var=tk.StringVar(value=str(vs.get("background_hot_span","3.0")))
        self.background_learning_var=tk.StringVar(value=str(vs.get("background_learning_seconds","120")))
        self.background_variance_tau=15.0
        self.background_stability_sigma=0.22
        self.background_mean=None
        self.background_var=None
        self.background_last_update=None
        self.background_age=0.0
        self.background_key=None
        self.background_center=None
        self.background_low=None
        self.background_high=None
        self.background_scene_resets=0

        self.smooth_var=tk.BooleanVar(value=bool(vs.get("smooth_3x3",True))); self.status=tk.StringVar(value="Starting iAP2/frame capture…")
        self.hover_text=tk.StringVar(value="Move the pointer over the thermal image"); self.scene_text=tk.StringVar(value="Min —   Center —   Max —")
        self.range_text=tk.StringVar(value="Display range —"); self.record_text=tk.StringVar(value="● Start logging")
        _span=self.graph_window_seconds()
        if _span>=3600:_graph_label=f"History: {_span/3600:g} h"
        elif _span>=60:_graph_label=f"History: {_span//60} min"
        else:_graph_label=f"History: {_span} s"
        self.graph_range_text=tk.StringVar(value=_graph_label)
        self.build_ui()
        self.apply_restored_view_settings()
        self.install_settings_autosave()
        self.messages=queue.Queue()
        self.init_dvr_database()
        self.dvr_thread=threading.Thread(target=self.dvr_writer_loop,daemon=True)
        self.dvr_thread.start()
        flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
        self.process=None; self.capture_flags=flags; self.capture_has_streamed=False
        self.capture_start_wall=0.; self.last_live_monotonic=0.; self.next_capture_restart=0.
        self.external_capture=os.environ.get("FLIR_EXTERNAL_CAPTURE") == "1"
        if not self.external_capture:self.start_capture()
        self.root.protocol("WM_DELETE_WINDOW",self.close); self.root.after(40,self.refresh)

    def load_viewer_settings_file(self):
        try:
            data=json.loads(VIEWER_SETTINGS.read_text(encoding="utf-8"))
            return data if isinstance(data,dict) else {}
        except (OSError,ValueError,json.JSONDecodeError):
            return {}

    def viewer_settings_snapshot(self):
        try:geometry=self.root.geometry()
        except Exception:geometry=""
        return {
            "version":1,
            "palette":self.palette_var.get(),
            "unit":self.unit_var.get(),
            "view_mode":self.view_mode.get(),
            "overlay_alpha":int(self.overlay_alpha.get()),
            "visual_x":int(self.visual_x.get()),
            "visual_y":int(self.visual_y.get()),
            "visual_zoom":int(self.visual_zoom.get()),
            "emissivity":self.radiometry_settings(live=True)[0],
            "reflected_temp":self.radiometry_settings(live=True)[1],
            "calibration_offset":self.radiometry_settings(live=True)[2],
            "scale_mode":self.scale_mode.get(),
            "manual_min":self.manual_min.get(),
            "manual_max":self.manual_max.get(),
            "display_tone":int(self.tone_var.get()),
            "thermal_span":int(self.thermal_span_var.get()),
            "agc_contrast":self.contrast_var.get(),
            "agc_min_span":self.min_span_var.get(),
            "agc_detail":self.detail_var.get(),
            "agc_denoise":self.denoise_var.get(),
            "display_interpolation":self.interpolation_var.get(),
            "background_deadband":self.background_deadband_var.get(),
            "background_hot_span":self.background_hot_span_var.get(),
            "background_learning_seconds":self.background_learning_var.get(),
            "smooth_3x3":bool(self._live_average if self.playback_mode and self._live_analysis else self.smooth_var.get()),
            "rotation_angle":float(self.rotation_angle),
            "mirror":bool(self.mirror_var.get()),
            "viewport_scale":float(self.viewport_scale),
            "graph_window_index":int(self.graph_window_index),
            "max_graph_visible":bool((self._live_analysis['max_point'] if self.playback_mode and self._live_analysis else self.max_point).get("graph",True)),
            "window_geometry":geometry,
        }

    def save_viewer_settings(self):
        try:
            VIEWER_SETTINGS.parent.mkdir(parents=True,exist_ok=True)
            tmp=VIEWER_SETTINGS.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.viewer_settings_snapshot(),indent=2,ensure_ascii=False),encoding="utf-8")
            tmp.replace(VIEWER_SETTINGS)
        except (OSError,tk.TclError,ValueError,TypeError):
            pass

    def schedule_save_viewer_settings(self,*_):
        try:
            if self._settings_save_after is not None:
                self.root.after_cancel(self._settings_save_after)
            self._settings_save_after=self.root.after(350,self._flush_scheduled_settings)
        except (tk.TclError,AttributeError):
            pass

    def _flush_scheduled_settings(self):
        self._settings_save_after=None
        self.save_viewer_settings()

    def install_settings_autosave(self):
        for var in (
            self.palette_var,self.unit_var,self.view_mode,self.overlay_alpha,
            self.visual_x,self.visual_y,self.visual_zoom,
            self.emissivity_var,self.reflected_var,self.temp_offset_var,
            self.scale_mode,self.manual_min,self.manual_max,
            self.tone_var,self.thermal_span_var,
            self.contrast_var,self.min_span_var,self.detail_var,self.denoise_var,self.interpolation_var,
            self.background_deadband_var,self.background_hot_span_var,
            self.background_learning_var,self.smooth_var,self.mirror_var
        ):
            var.trace_add("write",self.schedule_save_viewer_settings)
        for var in (self.emissivity_var,self.reflected_var,self.temp_offset_var,self.smooth_var):
            var.trace_add("write",self.request_recording_analysis)

    def apply_restored_view_settings(self):
        shown=int(round(self.rotation_angle)) if abs(self.rotation_angle-round(self.rotation_angle))<0.05 else round(self.rotation_angle,1)
        try:
            self.rotation_angle_label.configure(text=f"{shown}°")
            new_w=max(240,int(round(self.base_canvas_w*self.viewport_scale)))
            new_h=max(320,int(round(self.base_canvas_h*self.viewport_scale)))
            self.canvas.configure(width=new_w,height=new_h)
            self.canvas.coords(self.placeholder_id,new_w//2,new_h//2)
            self._last_canvas_w=new_w; self._last_canvas_h=new_h
            self.viewport_scale_label.configure(text=f"{int(round(self.viewport_scale*100))}%")
        except (tk.TclError,AttributeError):
            pass
        geometry=self.viewer_settings.get("window_geometry","")
        if isinstance(geometry,str) and geometry:
            m=re.match(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$",geometry)
            if m and int(m.group(1))>=1040 and int(m.group(2))>=700:
                try:self.root.geometry(geometry)
                except tk.TclError:pass

    def enable_dark_titlebar(self):
        """Use the Windows DWM dark caption/title bar when available."""
        if sys.platform!="win32":
            return
        try:
            import ctypes
            self.root.update_idletasks()
            hwnd=ctypes.windll.user32.GetParent(self.root.winfo_id())
            value=ctypes.c_int(1)
            # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE on current Windows builds.
            # Older builds used attribute 19, so try both.
            for attr in (20,19):
                try:
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd,attr,ctypes.byref(value),ctypes.sizeof(value)
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def build_ui(self):
        style=ttk.Style(self.root)
        # "vista" ignores several field/background colors on Windows.
        # "clam" is used so every ttk control can actually be rendered dark.
        try: style.theme_use("clam")
        except tk.TclError: pass

        BG="#050609"
        PANEL="#111923"
        FIELD="#0d141e"
        FIELD2="#15202c"
        BORDER="#263545"
        TEXT="#eff5ff"
        MUTED="#98adb9"
        ACCENT="#7fded2"
        BUTTON="#1c2a39"
        BUTTON_HOVER="#293d4d"

        style.configure(".",background=PANEL,foreground=TEXT,font=("Segoe UI",9),
                        fieldbackground=FIELD,bordercolor=BORDER,
                        lightcolor=BORDER,darkcolor=BORDER,
                        troughcolor=FIELD2,arrowcolor=TEXT)

        style.configure("Dark.TFrame",background=BG)
        style.configure("Panel.TFrame",background=PANEL)

        style.configure("TLabel",background=PANEL,foreground=TEXT)
        style.configure("Panel.TLabel",background=PANEL,foreground=TEXT)
        style.configure("Title.TLabel",background=PANEL,foreground=TEXT,
                        font=("Segoe UI Semibold",11))
        style.configure("Section.TLabel",background=PANEL,foreground=ACCENT,
                        font=("Segoe UI Semibold",10))
        style.configure("Muted.TLabel",background=PANEL,foreground=MUTED,
                        font=("Segoe UI",8))

        style.configure("TLabelframe",background=PANEL,foreground=TEXT,
                        bordercolor=BORDER,lightcolor=BORDER,darkcolor=BORDER,relief="solid")
        style.configure("TLabelframe.Label",background=PANEL,foreground=ACCENT)

        style.configure("TButton",background=BUTTON,foreground=TEXT,
                        bordercolor=BORDER,lightcolor=BUTTON,darkcolor=BUTTON,
                        padding=(10,7),relief="flat",focuscolor=ACCENT)
        style.map("TButton",
                  background=[("active",BUTTON_HOVER),("pressed",ACCENT)],
                  foreground=[("disabled","#718494"),("pressed","#071014")])
        style.configure("TSeparator",background=BORDER)
        style.configure("Treeview",background=FIELD,fieldbackground=FIELD,foreground=TEXT,
                        rowheight=27,borderwidth=0)
        style.map("Treeview",background=[("selected",ACCENT)],foreground=[("selected","#071014")])
        style.configure("Treeview.Heading",background=BUTTON,foreground=TEXT,relief="flat",padding=(8,6))

        style.configure("TEntry",fieldbackground=FIELD,foreground=TEXT,
                        insertcolor=TEXT,bordercolor=BORDER,
                        lightcolor=BORDER,darkcolor=BORDER)
        style.map("TEntry",
                  fieldbackground=[("disabled",FIELD2)],
                  foreground=[("disabled","#718494")])

        style.configure("TCombobox",fieldbackground=FIELD,background=FIELD,
                        foreground=TEXT,arrowcolor=TEXT,
                        bordercolor=BORDER,lightcolor=BORDER,darkcolor=BORDER)
        style.map("TCombobox",
                  fieldbackground=[("readonly",FIELD),("disabled",FIELD2)],
                  background=[("readonly",FIELD),("active",FIELD2)],
                  foreground=[("readonly",TEXT),("disabled","#718494")],
                  selectbackground=[("readonly",FIELD)],
                  selectforeground=[("readonly",TEXT)])

        style.configure("TSpinbox",fieldbackground=FIELD,background=FIELD,
                        foreground=TEXT,arrowcolor=TEXT,
                        bordercolor=BORDER,lightcolor=BORDER,darkcolor=BORDER)
        style.map("TSpinbox",
                  fieldbackground=[("readonly",FIELD),("disabled",FIELD2)],
                  foreground=[("disabled","#718494")])

        style.configure("TCheckbutton",background=PANEL,foreground=TEXT,
                        indicatorbackground=FIELD,indicatorforeground=TEXT)
        style.map("TCheckbutton",
                  background=[("active",PANEL)],
                  foreground=[("disabled","#718494")])

        style.configure("TRadiobutton",background=PANEL,foreground=TEXT,
                        indicatorbackground=FIELD,indicatorforeground=TEXT)
        style.map("TRadiobutton",
                  background=[("active",PANEL)],
                  foreground=[("disabled","#718494")])

        style.configure("Horizontal.TScale",background=PANEL,troughcolor=FIELD2,
                        bordercolor=BORDER,lightcolor=BORDER,darkcolor=BORDER)
        style.configure("Horizontal.TScrollbar",background=BUTTON,troughcolor=FIELD,
                        bordercolor=BORDER,arrowcolor=TEXT)

        # Dark dropdown list used by ttk.Combobox on Windows.
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#071014")
        self.root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 9))
        outer=ttk.Frame(self.root,style="Dark.TFrame"); outer.pack(fill="both",expand=True,padx=10,pady=10)
        left=ttk.Frame(outer,style="Dark.TFrame"); left.pack(side="left",fill="y")
        right=ttk.Frame(outer,style="Panel.TFrame",width=465); right.pack(side="left",fill="both",expand=True,padx=(10,0))
        # Image controls live outside the picture so they never cover thermal data.
        image_toolbar=tk.Frame(left,bg="#050609",bd=0)
        image_toolbar.pack(fill="x",pady=(0,6))
        ttk.Checkbutton(image_toolbar,text="Mirror",variable=self.mirror_var,
                        command=self.render).pack(side="left",padx=(0,8))

        tk.Label(
            image_toolbar,text="Rotate",bg="#050609",fg="#8ba1b5",
            font=("Segoe UI",8)
        ).pack(side="left")

        self.rotate_button=tk.Label(
            image_toolbar,text="↻ 90°",bg="#15202c",fg="#d8e8ef",
            activebackground="#293d4d",activeforeground="#ffffff",
            font=("Segoe UI Semibold",9),padx=7,pady=3,cursor="sb_h_double_arrow"
        )
        self.rotate_button.pack(side="left",padx=(5,4))

        self.rotation_angle_label=tk.Label(
            image_toolbar,text="0°",bg="#050609",fg="#98adb9",
            font=("Segoe UI",8),width=6
        )
        self.rotation_angle_label.pack(side="left")

        self.rotation_reset=tk.Label(
            image_toolbar,text="Reset",bg="#15202c",fg="#98adb9",
            font=("Segoe UI",8),padx=6,pady=3,cursor="hand2"
        )
        self.rotation_reset.pack(side="left",padx=(2,14))

        tk.Label(
            image_toolbar,text="Window",bg="#050609",fg="#8ba1b5",
            font=("Segoe UI",8)
        ).pack(side="left")

        self.size_minus=tk.Label(
            image_toolbar,text="−",bg="#15202c",fg="#d8e8ef",
            font=("Segoe UI Semibold",10),width=2,pady=2,cursor="hand2"
        )
        self.size_minus.pack(side="left",padx=(5,2))

        self.viewport_scale_label=tk.Label(
            image_toolbar,text="100%",bg="#050609",fg="#d8e8ef",
            font=("Segoe UI",8),width=6
        )
        self.viewport_scale_label.pack(side="left")

        self.size_plus=tk.Label(
            image_toolbar,text="+",bg="#15202c",fg="#d8e8ef",
            font=("Segoe UI Semibold",10),width=2,pady=2,cursor="hand2"
        )
        self.size_plus.pack(side="left",padx=(2,2))

        self.size_reset=tk.Label(
            image_toolbar,text="100%",bg="#15202c",fg="#98adb9",
            font=("Segoe UI",8),padx=5,pady=3,cursor="hand2"
        )
        self.size_reset.pack(side="left",padx=(2,0))

        self.rotate_button.bind("<ButtonPress-1>",self.rotation_press)
        self.rotate_button.bind("<B1-Motion>",self.rotation_drag)
        self.rotate_button.bind("<ButtonRelease-1>",self.rotation_release)
        self.rotation_reset.bind("<Button-1>",lambda _e:self.reset_view())
        self.size_minus.bind("<Button-1>",lambda _e:self.adjust_viewport_scale(-0.10))
        self.size_plus.bind("<Button-1>",lambda _e:self.adjust_viewport_scale(+0.10))
        self.size_reset.bind("<Button-1>",lambda _e:self.set_viewport_scale(1.0))

        self.build_playback_controls(left)
        self.canvas=tk.Canvas(left,width=CANVAS_W,height=CANVAS_H,bg="#050609",highlightthickness=1,highlightbackground="#263545",cursor="crosshair"); self.canvas.pack()
        self.image_id=self.canvas.create_image(0,0,anchor="nw")

        self.placeholder_id=self.canvas.create_text(
            CANVAS_W//2,CANVAS_H//2,
            text="Waiting for camera…\nReconnect USB if necessary.",
            fill="#d8e8ef",font=("Segoe UI",14),justify="center"
        )
        self.canvas.bind("<Motion>",self.on_motion); self.canvas.bind("<Leave>",self.on_leave); self.canvas.bind("<Button-1>",self.add_point); self.canvas.bind("<Button-3>",self.remove_nearest)
        tk.Label(left,textvariable=self.hover_text,bg="#050609",fg="white",font=("Segoe UI Semibold",12),anchor="w").pack(fill="x",pady=(7,0))
        tk.Label(left,textvariable=self.scene_text,bg="#050609",fg="#b7cad6",font=("Segoe UI",10),anchor="w").pack(fill="x")
        tk.Label(left,textvariable=self.range_text,bg="#050609",fg="#8ba1b5",font=("Segoe UI",9),anchor="w").pack(fill="x")
        tk.Label(left,text="Left click: add measurement point  •  Right click: remove nearest point",bg="#050609",fg="#8ba1b5",font=("Segoe UI",9),anchor="w").pack(fill="x")

        header=ttk.Frame(right,style="Panel.TFrame"); header.pack(fill="x",padx=12,pady=(10,6))

        self.live_dot=tk.Canvas(
            header,width=14,height=14,bg="#111923",
            highlightthickness=0,bd=0
        )
        self.live_dot.pack(side="left",padx=(0,5))
        self.live_dot_id=self.live_dot.create_oval(
            3,3,11,11,fill="#b94a44",outline=""
        )

        ttk.Label(header,text="LIVE STREAM",style="Title.TLabel").pack(side="left")
        tk.Label(
            header,textvariable=self.status,bg="#111923",
            fg="#7fded2",font=("Segoe UI",9),anchor="e"
        ).pack(side="right",fill="x",expand=True)


        controls=ttk.Frame(right,style="Panel.TFrame"); controls.pack(fill="x",padx=12)

        # --- Display ---------------------------------------------------------
        display_box=ttk.LabelFrame(controls,padding=(6,4))
        display_heading=ttk.Frame(display_box)
        ttk.Label(display_heading,text="DISPLAY",style="Section.TLabel").pack(side="left")
        ttk.Button(
            display_heading,text="Reset",width=6,command=self.reset_display_settings
        ).pack(side="left",padx=(8,0))
        display_box.configure(labelwidget=display_heading)
        display_box.pack(fill="x",pady=(0,7))
        display_box.columnconfigure(1,weight=1)
        display_box.columnconfigure(3,weight=1)

        # Visible/MSX controls stay hidden until a real, fresh optical stream
        # exists.  Showing a single-choice "View: Thermal" selector only adds
        # noise to the normal thermal-only UI.
        self.view_label=ttk.Label(display_box,text="View")
        self.view_combo=ttk.Combobox(display_box,textvariable=self.view_mode,
                                    values=["Thermal","Visible","Overlay","MSX edges"],
                                    state="readonly",width=17)

        ttk.Label(display_box,text="Palette").grid(row=0,column=0,sticky="w",padx=(8,6),pady=5)
        self.palette_combo=ttk.Combobox(
            display_box,textvariable=self.palette_var,
            values=["Iron","Lava","Rainbow","White hot","Black hot"],
            state="readonly",width=17
        )
        self.palette_combo.grid(row=0,column=1,sticky="ew",padx=(0,12),pady=5)

        ttk.Label(display_box,text="Scale").grid(row=0,column=2,sticky="w",padx=(0,6),pady=5)
        self.scale_combo=ttk.Combobox(
            display_box,textvariable=self.scale_mode,
            values=MODES,
            state="readonly",width=17
        )
        self.scale_combo.grid(row=0,column=3,sticky="ew",padx=(0,8),pady=5)

        tone_wrap=ttk.Frame(display_box)
        tone_wrap.grid(row=1,column=0,columnspan=4,sticky="ew",padx=8,pady=(2,5))
        tone_wrap.columnconfigure(1,weight=1)
        tone_wrap.columnconfigure(4,weight=1)
        ttk.Label(tone_wrap,text="Tone").grid(row=0,column=0,sticky="w",padx=(0,6))
        self.tone_scale=ttk.Scale(tone_wrap,from_=-100,to=100,variable=self.tone_var)
        self.tone_scale.grid(row=0,column=1,sticky="ew")
        ttk.Label(tone_wrap,textvariable=self.tone_label_var,width=5,anchor="e").grid(row=0,column=2,padx=(5,16))
        ttk.Label(tone_wrap,text="Display span").grid(row=0,column=3,sticky="w",padx=(0,6))
        self.thermal_span_scale=ttk.Scale(tone_wrap,from_=25,to=400,variable=self.thermal_span_var)
        self.thermal_span_scale.grid(row=0,column=4,sticky="ew")
        ttk.Label(tone_wrap,textvariable=self.thermal_span_label_var,width=6,anchor="e").grid(row=0,column=5,padx=(5,0))

        self.manual_wrap=ttk.Frame(display_box)
        ttk.Label(self.manual_wrap,text="Manual range").pack(side="left",padx=(0,6))
        self.manual_min_entry=ttk.Entry(self.manual_wrap,textvariable=self.manual_min,width=7)
        self.manual_min_entry.pack(side="left")
        ttk.Label(self.manual_wrap,text=" – ").pack(side="left")
        self.manual_max_entry=ttk.Entry(self.manual_wrap,textvariable=self.manual_max,width=7)
        self.manual_max_entry.pack(side="left")
        ttk.Label(self.manual_wrap,text=" °C").pack(side="left")
        ttk.Button(self.manual_wrap,text="Fit scene",command=self.fit_manual_range).pack(side="left",padx=8)

        self.agc_wrap=ttk.Frame(display_box)
        self.agc_controls={}
        for title,var,step,lower,upper,digits in (
            ("Contrast",self.contrast_var,.1,1,4,1),
            ("Min span °C",self.min_span_var,.1,.1,20,1),
            ("Detail %",self.detail_var,5,0,100,0),
            ("Denoise %",self.denoise_var,5,0,100,0),
        ):
            wrap=ttk.Frame(self.agc_wrap)
            ttk.Label(wrap,text=title).pack(side="left",padx=(0,4))
            entry=ttk.Entry(wrap,textvariable=var,width=5)
            entry.pack(side="left",padx=(0,12))
            self.bind_numeric_control(entry,var,step,lower,upper,digits)
            self.agc_controls[title]=wrap
        finishing=ttk.Frame(display_box)
        finishing.grid(row=3,column=0,columnspan=4,sticky="ew",padx=8,pady=(0,5))
        ttk.Label(finishing,text="Interpolation").pack(side="left",padx=(0,6))
        ttk.Combobox(finishing,textvariable=self.interpolation_var,values=("Smooth","Native pixels"),state="readonly",width=13).pack(side="left")
        ttk.Button(finishing,text="Reset tuning",command=self.reset_display_tuning).pack(side="right")
        self.scale_help=tk.StringVar()
        ttk.Label(display_box,textvariable=self.scale_help,wraplength=620).grid(row=4,column=0,columnspan=4,sticky="w",padx=8,pady=(0,5))

        self.bg_wrap=ttk.Frame(display_box)
        ttk.Label(self.bg_wrap,text="Deadband").pack(side="left")
        self.deadband_entry=ttk.Entry(self.bg_wrap,textvariable=self.background_deadband_var,width=5)
        self.deadband_entry.pack(side="left",padx=(4,2))
        ttk.Label(self.bg_wrap,text="°C   Minimum hot span").pack(side="left")
        self.hot_span_entry=ttk.Entry(self.bg_wrap,textvariable=self.background_hot_span_var,width=5)
        self.hot_span_entry.pack(side="left",padx=(4,2))
        ttk.Label(self.bg_wrap,text="°C   Learning time").pack(side="left")
        self.learning_entry=ttk.Entry(self.bg_wrap,textvariable=self.background_learning_var,width=6)
        self.learning_entry.pack(side="left",padx=(4,2))
        ttk.Label(self.bg_wrap,text="s").pack(side="left")

        # --- Visible image / alignment --------------------------------------
        self.visible_box=ttk.LabelFrame(controls,text=" Visible image ",padding=(6,4))
        visible_box=self.visible_box
        visible_box.columnconfigure(1,weight=1)

        ttk.Label(visible_box,text="Blend").grid(row=0,column=0,sticky="w",padx=(8,6),pady=5)
        ttk.Scale(visible_box,from_=0,to=100,variable=self.overlay_alpha,
                  command=lambda _v:self.render()).grid(row=0,column=1,sticky="ew",pady=5)
        self.alpha_label=ttk.Label(visible_box,text="35%",width=5)
        self.alpha_label.grid(row=0,column=2,sticky="e",padx=(6,8),pady=5)

        align_wrap=ttk.Frame(visible_box)
        align_wrap.grid(row=1,column=0,columnspan=3,sticky="w",padx=8,pady=(1,7))
        ttk.Label(align_wrap,text="Alignment").pack(side="left",padx=(0,10))
        ttk.Label(align_wrap,text="X").pack(side="left")
        ttk.Spinbox(align_wrap,from_=-80,to=80,textvariable=self.visual_x,width=5,
                    command=self.render).pack(side="left",padx=(3,10))
        ttk.Label(align_wrap,text="Y").pack(side="left")
        ttk.Spinbox(align_wrap,from_=-80,to=80,textvariable=self.visual_y,width=5,
                    command=self.render).pack(side="left",padx=(3,10))
        ttk.Label(align_wrap,text="Zoom").pack(side="left")
        ttk.Spinbox(align_wrap,from_=60,to=180,textvariable=self.visual_zoom,width=6,
                    command=self.render).pack(side="left",padx=(3,2))
        ttk.Label(align_wrap,text="%").pack(side="left")

        self.visible_unavailable_label=ttk.Label(
            controls,
            text="Visible camera stream unavailable — thermal controls only",
            style="Panel.TLabel"
        )
        # Intentionally not packed while only thermal data is available.

        # --- Temperature / radiometry ---------------------------------------
        temp_box=ttk.LabelFrame(controls,padding=(6,4))
        temperature_heading=ttk.Frame(temp_box)
        ttk.Label(temperature_heading,text="TEMPERATURE / RADIOMETRY",style="Section.TLabel").pack(side="left")
        ttk.Button(
            temperature_heading,text="Reset",width=6,
            command=self.reset_temperature_settings
        ).pack(side="left",padx=(8,0))
        temp_box.configure(labelwidget=temperature_heading)
        temp_box.pack(fill="x",pady=(0,7))
        for c in (1,3): temp_box.columnconfigure(c,weight=1)

        ttk.Label(temp_box,text="Emissivity ε").grid(row=0,column=0,sticky="w",padx=(8,6),pady=5)
        self.emissivity_entry=ttk.Entry(temp_box,textvariable=self.emissivity_var,width=8)
        self.emissivity_entry.grid(row=0,column=1,sticky="w",pady=5)

        ttk.Label(temp_box,text="Reflected temp").grid(row=0,column=2,sticky="w",padx=(14,6),pady=5)
        reflected_wrap=ttk.Frame(temp_box)
        reflected_wrap.grid(row=0,column=3,sticky="w",padx=(0,8),pady=5)
        self.reflected_entry=ttk.Entry(reflected_wrap,textvariable=self.reflected_var,width=8)
        self.reflected_entry.pack(side="left")
        ttk.Label(reflected_wrap,text=" °C").pack(side="left")

        ttk.Label(temp_box,text="Calibration offset").grid(row=1,column=0,sticky="w",padx=(8,6),pady=5)
        offset_wrap=ttk.Frame(temp_box)
        offset_wrap.grid(row=1,column=1,sticky="w",pady=5)
        self.offset_entry=ttk.Entry(offset_wrap,textvariable=self.temp_offset_var,width=8)
        self.offset_entry.pack(side="left")
        ttk.Label(offset_wrap,text=" °C").pack(side="left")

        options=ttk.Frame(temp_box)
        options.grid(row=1,column=2,columnspan=2,sticky="e",padx=(14,8),pady=5)
        ttk.Checkbutton(options,text="3×3 point average",variable=self.smooth_var).pack(side="left",padx=(0,14))
        ttk.Radiobutton(options,text="°C",value="°C",variable=self.unit_var).pack(side="left")
        ttk.Radiobutton(options,text="°F",value="°F",variable=self.unit_var).pack(side="left")

        self.bind_numeric_control(self.manual_min_entry,self.manual_min,0.1,-1000,2000,1)
        self.bind_numeric_control(self.manual_max_entry,self.manual_max,0.1,-1000,2000,1)
        self.bind_numeric_control(self.deadband_entry,self.background_deadband_var,0.05,0,2,2)
        self.bind_numeric_control(self.hot_span_entry,self.background_hot_span_var,0.5,0.5,20,1)
        self.bind_numeric_control(self.learning_entry,self.background_learning_var,10,1,3600,0)
        self.bind_numeric_control(self.emissivity_entry,self.emissivity_var,0.01,0.01,1,2)
        self.bind_numeric_control(self.reflected_entry,self.reflected_var,0.5,-100,1000,1)
        self.bind_numeric_control(self.offset_entry,self.temp_offset_var,0.1,-100,100,1)
        self.bind_numeric_control(self.tone_scale,self.tone_var,1,-100,100,0)
        self.bind_numeric_control(self.thermal_span_scale,self.thermal_span_var,1,25,400,0)
        self.scale_mode.trace_add("write",lambda *_:self.update_scale_controls())
        self.tone_var.trace_add("write",lambda *_:self.update_display_adjustment_labels())
        self.thermal_span_var.trace_add("write",lambda *_:self.update_display_adjustment_labels())
        self.update_scale_controls()
        self.update_display_adjustment_labels()

        toolbar=ttk.Frame(right,style="Panel.TFrame"); toolbar.pack(fill="x",padx=12,pady=(0,7))
        self.freeze_button=ttk.Button(toolbar,text="⏸ Freeze image",command=self.toggle_freeze); self.freeze_button.pack(side="left",padx=(0,5))
        ttk.Button(toolbar,text="📷 PNG",command=self.snapshot).pack(side="left",padx=5)
        ttk.Button(toolbar,textvariable=self.record_text,command=self.toggle_record).pack(side="left",padx=5)
        ttk.Button(toolbar,text="Clear points",command=self.clear_points).pack(side="right")

        ttk.Separator(right).pack(fill="x",padx=12,pady=2)
        ph=ttk.Frame(right,style="Panel.TFrame"); ph.pack(fill="x",padx=12,pady=(6,2))
        ttk.Label(ph,text="MEASUREMENT POINTS",style="Section.TLabel").pack(side="left")

        tk.Label(ph,textvariable=self.graph_range_text,bg="#111923",fg="#8ba1b5",font=("Segoe UI",8)).pack(side="right")

        self.point_list=tk.Listbox(
            right,height=6,bg="#0d141e",fg="#eff5ff",
            selectbackground="#7fded2",selectforeground="#071014",borderwidth=0,highlightthickness=0,
            font=("Consolas",10),activestyle="none"
        )
        self.point_list.pack(fill="x",padx=12)
        self.point_list.bind("<<ListboxSelect>>",self.on_point_list_select)
        self.point_list.bind("<Button-1>",self.on_point_list_click)

        graph_toolbar=ttk.Frame(right,style="Panel.TFrame"); graph_toolbar.pack(fill="x",padx=12,pady=(7,3))
        self.graph_pause_button=ttk.Button(graph_toolbar,text="⏸ Pause graph",command=self.toggle_graph_pause); self.graph_pause_button.pack(side="left")
        ttk.Button(graph_toolbar,text="− Zoom out",command=lambda:self.zoom_graph_at(+1,None)).pack(side="left",padx=(6,3))
        ttk.Button(graph_toolbar,text="+ Zoom in",command=lambda:self.zoom_graph_at(-1,None)).pack(side="left",padx=3)
        ttk.Button(graph_toolbar,text="Live",command=self.resume_graph_live).pack(side="right")

        history_bar=ttk.Frame(right,style="Panel.TFrame"); history_bar.pack(fill="x",padx=12,pady=(0,4))
        ttk.Button(history_bar,text="▦ Recordings",command=self.open_history_window).pack(side="left")

        ttk.Label(history_bar,text="Recording",style="Panel.TLabel").pack(side="left",padx=(12,5))
        self.archive_quality_combo=ttk.Combobox(
            history_bar,textvariable=self.archive_quality_var,
            values=["Max FPS","1 FPS"],state="readonly",width=9
        )
        self.archive_quality_combo.pack(side="left")
        self.archive_quality_combo.bind("<<ComboboxSelected>>",lambda _e:(self.update_archive_size_label(),self.save_storage_settings()))
        ttk.Button(history_bar,text="Storage…",command=self.open_storage_settings).pack(side="left",padx=(8,0))

        tk.Label(
            history_bar,textvariable=self.archive_size_var,
            bg="#111923",fg="#98adb9",font=("Segoe UI",8)
        ).pack(side="left",padx=(10,0))

        self.dvr_time_var=tk.StringVar(value="Continuous archive: active")
        tk.Label(history_bar,textvariable=self.dvr_time_var,bg="#111923",fg="#8ba1b5",font=("Segoe UI",8)).pack(side="right")

        self.graph=tk.Canvas(right,height=230,bg="#0d141e",highlightthickness=1,highlightbackground="#263545")
        self.graph.pack(fill="both",expand=True,padx=12,pady=(4,4))
        self.graph_image_id=self.graph.create_image(0,0,anchor="nw")
        self.graph.bind("<Motion>",self.on_graph_motion)
        self.graph.bind("<Leave>",self.on_graph_leave)
        self.graph.bind("<ButtonPress-1>",self.on_graph_press)
        self.graph.bind("<B1-Motion>",self.on_graph_drag)
        self.graph.bind("<ButtonRelease-1>",self.on_graph_release)
        self.graph.bind("<MouseWheel>",self.on_graph_wheel)
        self.graph.bind("<Button-4>",lambda e:self.zoom_graph_at(-1,e.x))
        self.graph.bind("<Button-5>",lambda e:self.zoom_graph_at(+1,e.x))
        self.graph.bind("<Configure>",lambda _e:self.request_graph_redraw(force=True))
        self.graph_detail_label=tk.Label(
            right,textvariable=self.graph_detail_text,bg="#15202c",fg="#eff5ff",
            font=("Segoe UI",9),anchor="w",justify="left",padx=10,pady=6
        )
        self.graph_detail_label.pack(fill="x",padx=12,pady=(0,10))
        self.refresh_point_list()  # MAX exists even before the first live frame.
        self.draw_graph(force=True)
        self.update_visible_controls(force=True)

        for var in (self.palette_var,self.unit_var,self.emissivity_var,self.reflected_var,self.temp_offset_var,self.scale_mode,self.manual_min,self.manual_max,self.tone_var,self.thermal_span_var,self.background_deadband_var,self.background_hot_span_var,self.view_mode,self.overlay_alpha,self.visual_x,self.visual_y,self.visual_zoom,self.contrast_var,self.min_span_var,self.detail_var,self.denoise_var,self.interpolation_var):
            var.trace_add("write",lambda *_: self.render())
        for var in (self.emissivity_var,self.reflected_var,self.temp_offset_var,self.scale_mode):
            var.trace_add("write",lambda *_: self.reset_heq_state())

    @staticmethod
    def control_row(parent,label,widget):
        row=ttk.Frame(parent,style="Panel.TFrame"); row.pack(fill="x",pady=2); ttk.Label(row,text=label,style="Panel.TLabel",width=15).pack(side="left"); widget.pack(side="left",fill="x",expand=True)

    def bind_numeric_control(self,widget,var,step,minimum=None,maximum=None,digits=None):
        """Make every numeric control respond consistently to wheel and arrows."""
        def adjust(direction,event=None):
            try:value=float(var.get())
            except (ValueError,TypeError,tk.TclError):value=0.0
            multiplier=10.0 if event is not None and (getattr(event,"state",0)&0x0001) else 1.0
            value+=direction*step*multiplier
            if minimum is not None:value=max(minimum,value)
            if maximum is not None:value=min(maximum,value)
            if digits==0:
                var.set(int(round(value)))
            elif digits is not None:
                var.set(f"{value:.{digits}f}")
            else:
                var.set(value)
            return "break"

        widget.bind("<Up>",lambda e:adjust(+1,e),add="+")
        widget.bind("<Down>",lambda e:adjust(-1,e),add="+")
        widget.bind("<Right>",lambda e:adjust(+1,e),add="+")
        widget.bind("<Left>",lambda e:adjust(-1,e),add="+")
        widget.bind("<MouseWheel>",lambda e:adjust(+1 if e.delta>0 else -1,e),add="+")
        widget.bind("<Button-4>",lambda e:adjust(+1,e),add="+")
        widget.bind("<Button-5>",lambda e:adjust(-1,e),add="+")

    def reset_display_settings(self):
        """Restore only display/tone-mapping controls to their defaults."""
        self.palette_var.set("Iron")
        self.scale_mode.set("Auto")
        self.manual_min.set("15")
        self.manual_max.set("35")
        self.reset_display_tuning()
        self.background_deadband_var.set("0.25")
        self.background_hot_span_var.set("3.0")
        self.background_learning_var.set("120")
        self.reset_heq_state()
        self.update_scale_controls()
        self.update_display_adjustment_labels()
        self.status.set("Display settings reset")
        self.render()

    def reset_temperature_settings(self):
        """Restore radiometric conversion and temperature display defaults."""
        self.emissivity_var.set("0.95")
        self.reflected_var.set("20.0")
        self.temp_offset_var.set("0.0")
        self.smooth_var.set(True)
        self.unit_var.set("°C")
        self.reset_heq_state()
        self.reset_background_model()
        self.status.set("Temperature settings reset")
        self.render()

    def update_scale_controls(self):
        """Expose only settings that affect the currently selected scale."""
        mode=self.scale_mode.get()
        try:self.manual_wrap.grid_forget()
        except (AttributeError,tk.TclError):pass
        try:self.bg_wrap.grid_forget()
        except (AttributeError,tk.TclError):pass
        self.agc_wrap.grid_forget()
        for wrap in self.agc_controls.values():wrap.pack_forget()
        if mode=="Manual":
            self.manual_wrap.grid(row=2,column=0,columnspan=4,sticky="w",padx=8,pady=(0,6))
        elif mode=="Background relative":
            self.bg_wrap.grid(row=2,column=0,columnspan=4,sticky="w",padx=8,pady=(0,6))
        else:
            self.agc_wrap.grid(row=2,column=0,columnspan=4,sticky="w",padx=8,pady=(0,6))
            names=["Min span °C","Denoise %"]
            if mode in ("Auto","Detail"):names.insert(0,"Contrast")
            if mode=="Detail":names.insert(2,"Detail %")
            for name in names:self.agc_controls[name].pack(side="left")
        self.scale_help.set({
            "Auto":"Plateau HEQ: balanced contrast with limited noise amplification.",
            "Detail":"Local CLAHE: reveals structure; equal colours may represent different temperatures.",
            "Linear auto":"Adaptive linear range: consistent ordering, restrained surface contrast.",
            "Manual":"Fixed temperature range. Tone / display span shift the effective limits shown below.",
            "Background relative":"Highlights warm objects against a learned dark background.",
        }.get(mode,""))

    def reset_display_tuning(self):
        self.tone_var.set(0)
        self.thermal_span_var.set(100)
        self.contrast_var.set("1.5")
        self.min_span_var.set("1.5")
        self.detail_var.set("35")
        self.denoise_var.set("30")
        self.interpolation_var.set("Smooth")
        self.tone_mapper.reset()
        self.render()

    @staticmethod
    def numeric_value(var,default):
        try:
            value=float(var.get())
            return value if math.isfinite(value) else default
        except (ValueError,TypeError,tk.TclError):return default

    def fit_manual_range(self):
        values=sorted(t for t in self.temperatures if math.isfinite(t))
        if not values:return
        low,high=values[0],values[-1]
        self.manual_min.set(f"{math.floor(low*10)/10:.1f}")
        self.manual_max.set(f"{max(math.ceil(high*10)/10,math.floor(low*10)/10+.1):.1f}")
        self.tone_var.set(0)
        self.thermal_span_var.set(100)

    def display_levels(self,temperatures):
        low=self.numeric_value(self.manual_min,15.)
        high=self.numeric_value(self.manual_max,35.)
        if high<=low:high=low+.1
        return self.tone_mapper.map(temperatures,VIEW_W,VIEW_H,
            mode=self.scale_mode.get(),low=low,high=high,
            tone=self.numeric_value(self.tone_var,0),span=self.numeric_value(self.thermal_span_var,100),
            contrast=self.numeric_value(self.contrast_var,1.5),min_span=self.numeric_value(self.min_span_var,1.5),
            detail=self.numeric_value(self.detail_var,35),denoise=self.numeric_value(self.denoise_var,30),
            temporal=not self.playback_mode)

    def update_display_adjustment_labels(self):
        try:self.tone_label_var.set(f"{int(round(float(self.tone_var.get()))):+d}")
        except (ValueError,tk.TclError):self.tone_label_var.set("0")
        try:self.thermal_span_label_var.set(f"{int(round(float(self.thermal_span_var.get())))}%")
        except (ValueError,tk.TclError):self.thermal_span_label_var.set("100%")

    def adjusted_palette_level(self,level):
        """Apply display-only thermal level/span controls to an 8-bit level."""
        try:span=clamp(float(self.thermal_span_var.get()),25.0,400.0)/100.0
        except (ValueError,tk.TclError):span=1.0
        try:tone=clamp(float(self.tone_var.get()),-100.0,100.0)
        except (ValueError,tk.TclError):tone=0.0
        # Smaller span behaves like zooming into the temperature range; tone
        # moves the palette midpoint without changing any measured temperature.
        return int(round(clamp(127.5+(float(level)-127.5)/span+tone*0.60,0.0,255.0)))

    def background_learning_seconds(self):
        try:return clamp(float(self.background_learning_var.get()),1.0,3600.0)
        except (ValueError,tk.TclError):return 120.0

    def start_capture(self):
        self.capture_start_wall=time.time(); self.last_live_monotonic=time.monotonic(); self.capture_has_streamed=False
        capture_env=os.environ.copy(); capture_env["FLIR_SKIP_PPM"]="1"
        self.process=subprocess.Popen([sys.executable,"-u",str(CAPTURE)],cwd=str(ROOT),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,creationflags=self.capture_flags,env=capture_env)
        threading.Thread(target=self.read_output,args=(self.process,),daemon=True).start()

    def read_output(self,process):
        if process.stdout is None:return
        with CAPTURE_LOG.open("a",encoding="utf-8",errors="replace") as log:
            log.write(f"\n--- capture PID {process.pid} started {dt.datetime.now().isoformat()} ---\n"); log.flush()
            for line in process.stdout:
                clean=line.strip(); self.messages.put(clean)
                log.write(clean+"\n"); log.flush()

    def restart_capture(self,reason):
        if self.external_capture:return
        process=self.process
        if process is not None and process.poll() is None:
            try:process.terminate()
            except OSError:pass
        self.process=None; self.capture_has_streamed=False
        self.next_capture_restart=time.monotonic()+0.5
        self.status.set(reason)

    def should_archive_frame(self,stamp):
        min_interval=1.0 if self.archive_quality_var.get()=="1 FPS" else 0.0
        if min_interval and stamp-self.dvr_last_saved_ts<min_interval:
            return False
        self.dvr_last_saved_ts=stamp
        return True

    def current_live_fps(self):
        cutoff=time.time()-self.fps_window_seconds
        while self.frame_times and self.frame_times[0]<cutoff:
            self.frame_times.popleft()
        if len(self.frame_times)>1:
            return (len(self.frame_times)-1)/max(.001,self.frame_times[-1]-self.frame_times[0])
        return 3.4

    def update_archive_size_label(self):
        fps=self.current_live_fps() if self.archive_quality_var.get()=="Max FPS" else 1.0
        raw_mb_min=(38400.0*fps*60.0)/(1024.0*1024.0)
        if self.dvr_frames_written>10:
            avg_bytes=self.dvr_bytes_written/max(1,self.dvr_frames_written)
            mb_min=(avg_bytes*fps*60.0)/(1024.0*1024.0)
            self.archive_size_var.set(f"≈ {mb_min:.1f} MB/min • {mb_min*60:.0f} MB/h")
        else:
            self.archive_size_var.set(f"≤ {raw_mb_min:.1f} MB/min • ≤ {raw_mb_min*60:.0f} MB/h raw")

    def init_dvr_database(self):
        con=sqlite3.connect(self.dvr_db)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            con.execute("""CREATE TABLE IF NOT EXISTS frames(
                ts REAL PRIMARY KEY,
                file TEXT NOT NULL,
                offset INTEGER NOT NULL,
                raw_size INTEGER NOT NULL,
                comp_size INTEGER NOT NULL
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS point_samples(
                ts REAL NOT NULL,
                point_name TEXT NOT NULL,
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                temp_c REAL,
                PRIMARY KEY(ts,point_name)
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS scene_samples(
                ts REAL PRIMARY KEY,
                min_c REAL,
                center_c REAL,
                max_c REAL,
                emissivity REAL,
                reflected_c REAL,
                calibration_offset_c REAL
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS favorite_ranges(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_ts REAL NOT NULL,
                end_ts REAL NOT NULL,
                label TEXT DEFAULT ''
            )""")
            con.commit()
        finally:
            con.close()

    def load_storage_settings(self):
        try:
            data=json.loads(STORAGE_SETTINGS.read_text(encoding="utf-8"))
            folder=data.get("folder")
            if folder:
                p=pathlib.Path(folder)
                p.mkdir(parents=True,exist_ok=True)
                self.dvr_dir=p
                self.dvr_db=p/"history.sqlite3"
            self.storage_max_gb=max(0.5,float(data.get("max_gb",20.0)))
            mode=data.get("recording_speed","Max FPS")
            if mode in ("Max FPS","1 FPS"):
                self._pending_archive_quality=mode
        except (OSError,ValueError,json.JSONDecodeError):
            pass

    def save_storage_settings(self):
        try:
            STORAGE_SETTINGS.parent.mkdir(parents=True,exist_ok=True)
            STORAGE_SETTINGS.write_text(json.dumps({
                "folder":str(self.dvr_dir),
                "max_gb":float(self.storage_max_gb),
                "recording_speed":self.archive_quality_var.get(),
            },indent=2),encoding="utf-8")
        except OSError:
            pass

    def folder_size_bytes(self,root=None):
        root=pathlib.Path(root or self.dvr_dir)
        total=0
        try:
            for p in root.rglob("*"):
                if p.is_file():
                    try: total+=p.stat().st_size
                    except OSError: pass
        except OSError:
            pass
        return total

    def archive_usage_bytes(self):
        """Fast archive-size estimate from the DVR index; never walks the folder tree."""
        total=0
        try:
            con=sqlite3.connect(self.dvr_db,timeout=2)
            try:
                row=con.execute(
                    "SELECT COUNT(*),COALESCE(SUM(comp_size),0) FROM frames"
                ).fetchone()
                if row:
                    count,comp_bytes=row
                    total=int(comp_bytes or 0)+int(count or 0)*DVR_HEADER.size
            finally:
                con.close()
        except (sqlite3.Error,OSError):
            # Writer counters are session-local but still better than blocking
            # the UI with a recursive filesystem walk.
            total=int(self.dvr_bytes_written)

        # Include SQLite bookkeeping files cheaply by stat'ing known paths only.
        for p in (
            self.dvr_db,
            pathlib.Path(str(self.dvr_db)+"-wal"),
            pathlib.Path(str(self.dvr_db)+"-shm"),
        ):
            try: total+=p.stat().st_size
            except OSError: pass
        return total

    def storage_stats(self):
        """Cheap periodic health check: O(1) disk_usage + indexed DB aggregate."""
        import shutil
        du=shutil.disk_usage(self.dvr_dir)
        return du.total,du.free,self.archive_usage_bytes()

    def open_storage_settings(self):
        win=tk.Toplevel(self.root)
        win.title("FLIR DVR Storage")
        win.configure(bg="#111923")
        win.transient(self.root); win.grab_set(); win.resizable(False,False)
        folder_var=tk.StringVar(value=str(self.dvr_dir))
        max_var=tk.StringVar(value=f"{self.storage_max_gb:g}")
        speed_var=tk.StringVar(value=self.archive_quality_var.get())
        info_var=tk.StringVar(value="")

        def update_info(*_):
            try:
                import shutil
                folder=pathlib.Path(folder_var.get())
                folder.mkdir(parents=True,exist_ok=True)
                du=shutil.disk_usage(folder)
                free_gb=du.free/(1024**3)
                max_gb=float(max_var.get())
                suffix="  ⚠ limit exceeds currently free space" if max_gb>free_gb else ""
                info_var.set(f"Disk free: {free_gb:.1f} GB{suffix}")
            except Exception:
                info_var.set("Select a valid writable folder.")

        def browse():
            p=filedialog.askdirectory(initialdir=folder_var.get() or str(self.dvr_dir))
            if p: folder_var.set(p)

        def apply():
            try:
                import shutil
                folder=pathlib.Path(folder_var.get())
                folder.mkdir(parents=True,exist_ok=True)
                max_gb=max(0.5,float(max_var.get()))
                du=shutil.disk_usage(folder)
            except Exception as exc:
                messagebox.showerror("FLIR",f"Invalid storage settings: {exc}",parent=win); return

            # If the user keeps the current archive folder, existing DVR data
            # can be reclaimed by the configured cleanup policy.  For a new
            # folder, compare only with actual free disk space.  No recursive
            # directory scan is performed on the UI thread.
            existing_reclaimable=self.archive_usage_bytes() if folder.resolve()==self.dvr_dir.resolve() else 0
            if max_gb*1024**3 > du.free + existing_reclaimable:
                if not messagebox.askyesno(
                    "FLIR storage",
                    "The configured maximum is larger than the space currently available. "
                    "Recording can continue, but the real disk-space limit may be reached first. Continue?",
                    parent=win
                ): return

            changed=folder.resolve()!=self.dvr_dir.resolve()
            self.storage_max_gb=max_gb
            self.archive_quality_var.set(speed_var.get())

            if changed:
                self.dvr_stop.set()
                try:self.dvr_thread.join(timeout=4.0)
                except Exception:pass
                self.dvr_dir=folder
                self.dvr_db=folder/"history.sqlite3"
                self.dvr_queue=queue.Queue(maxsize=256)
                self.dvr_stop=threading.Event()
                self.init_dvr_database()
                self.dvr_thread=threading.Thread(target=self.dvr_writer_loop,daemon=True)
                self.dvr_thread.start()
                self.dvr_frames_written=0; self.dvr_bytes_written=0

            self.save_storage_settings()
            self.storage_warned_near_limit=False
            self.storage_warned_disk_low=False
            self.storage_delete_warned=False
            self.update_archive_size_label()
            win.destroy()

        frm=ttk.Frame(win,style="Panel.TFrame",padding=12); frm.pack(fill="both",expand=True)
        ttk.Label(frm,text="Recording folder").grid(row=0,column=0,sticky="w",pady=5)
        ttk.Entry(frm,textvariable=folder_var,width=55).grid(row=0,column=1,sticky="ew",padx=(8,4))
        ttk.Button(frm,text="Browse…",command=browse).grid(row=0,column=2)
        ttk.Label(frm,text="Max storage").grid(row=1,column=0,sticky="w",pady=5)
        ttk.Entry(frm,textvariable=max_var,width=10).grid(row=1,column=1,sticky="w",padx=(8,0))
        ttk.Label(frm,text="GB").grid(row=1,column=1,sticky="w",padx=(82,0))
        ttk.Label(frm,text="Recording speed").grid(row=2,column=0,sticky="w",pady=5)
        ttk.Combobox(frm,textvariable=speed_var,values=["Max FPS","1 FPS"],
                     state="readonly",width=12).grid(row=2,column=1,sticky="w",padx=(8,0))
        tk.Label(frm,textvariable=info_var,bg="#111923",fg="#98adb9",
                 font=("Segoe UI",9),anchor="w").grid(row=3,column=0,columnspan=3,sticky="ew",pady=(8,10))
        btns=ttk.Frame(frm,style="Panel.TFrame"); btns.grid(row=4,column=0,columnspan=3,sticky="e")
        ttk.Button(btns,text="Cancel",command=win.destroy).pack(side="right")
        ttk.Button(btns,text="Apply",command=apply).pack(side="right",padx=(0,6))
        max_var.trace_add("write",update_info); folder_var.trace_add("write",update_info); update_info()

    def favorite_ranges(self):
        con=sqlite3.connect(self.dvr_db)
        try:
            return [(float(a),float(b),label or "") for a,b,label in
                    con.execute("SELECT start_ts,end_ts,label FROM favorite_ranges ORDER BY start_ts")]
        finally: con.close()

    def session_is_favorite(self,start_ts,end_ts):
        con=sqlite3.connect(self.dvr_db)
        try:
            return bool(con.execute(
                "SELECT 1 FROM favorite_ranges WHERE NOT(end_ts<? OR start_ts>?) LIMIT 1",
                (start_ts,end_ts)).fetchone())
        finally: con.close()

    def toggle_selected_history_favorite(self):
        idx=self.history_selected_session_index
        if idx is None or idx>=len(self.history_sessions):
            if self.history_status_var:self.history_status_var.set("Select a recording/session first.")
            return
        s=self.history_sessions[idx]
        con=sqlite3.connect(self.dvr_db)
        try:
            row=con.execute(
                "SELECT id FROM favorite_ranges WHERE NOT(end_ts<? OR start_ts>?) LIMIT 1",
                (s["start"],s["end"])).fetchone()
            if row:
                con.execute("DELETE FROM favorite_ranges WHERE id=?",(row[0],)); fav=False
            else:
                label=dt.datetime.fromtimestamp(s["start"]).strftime("%Y-%m-%d %H:%M:%S")
                con.execute("INSERT INTO favorite_ranges(start_ts,end_ts,label) VALUES(?,?,?)",
                            (s["start"],s["end"],label)); fav=True
            con.commit()
        finally: con.close()
        self.history_favorite_button.configure(text="★ Favorited — keep" if fav else "☆ Favorite recording")
        self.refresh_history_graph()

    def update_history_favorite_button(self):
        if not hasattr(self,"history_favorite_button"): return
        idx=self.history_selected_session_index
        if idx is None or idx>=len(self.history_sessions):
            self.history_favorite_button.configure(text="☆ Favorite recording"); return
        s=self.history_sessions[idx]
        fav=self.session_is_favorite(s["start"],s["end"])
        self.history_favorite_button.configure(text="★ Favorited — keep" if fav else "☆ Favorite recording")

    def prune_storage_if_needed(self):
        limit=int(self.storage_max_gb*1024**3)
        import shutil
        du=shutil.disk_usage(self.dvr_dir)
        free=du.free
        used=self.archive_usage_bytes()
        reserve=512*1024**2
        if used<=limit and free>=reserve:return 0
        favorites=self.favorite_ranges()
        con=sqlite3.connect(self.dvr_db)
        deleted=0
        try:
            rows=con.execute(
                "SELECT file,MIN(ts),MAX(ts) FROM frames GROUP BY file ORDER BY MIN(ts)"
            ).fetchall()
            for rel,start_ts,end_ts in rows:
                if any(not (end_ts<a or start_ts>b) for a,b,_ in favorites): continue
                path=self.dvr_dir/rel
                try:size=path.stat().st_size
                except OSError:size=0
                try:path.unlink(missing_ok=True)
                except OSError:continue
                con.execute("DELETE FROM frames WHERE file=?",(rel,))
                con.execute("DELETE FROM point_samples WHERE ts BETWEEN ? AND ?",(start_ts,end_ts))
                con.execute("DELETE FROM scene_samples WHERE ts BETWEEN ? AND ?",(start_ts,end_ts))
                deleted+=size; used=max(0,used-size); free+=size
                if used<=limit and free>=reserve:break
            con.commit()
        finally:con.close()
        return deleted

    def check_storage_health(self):
        now=time.monotonic()
        if now-self.storage_check_last<30.0:return
        self.storage_check_last=now
        try:_total,free,used=self.storage_stats()
        except Exception:return
        limit=max(1,int(self.storage_max_gb*1024**3))
        used_gb=used/(1024**3); free_gb=free/(1024**3)

        if used/limit>=0.90 and not self.storage_warned_near_limit:
            self.storage_warned_near_limit=True
            messagebox.showwarning(
                "FLIR DVR storage",
                f"Archive usage is {used_gb:.1f} GB of the {self.storage_max_gb:g} GB limit.\n"
                "At the limit, oldest non-favorite recordings are deleted automatically.\n"
                "Favorites are protected."
            )
        if free_gb<1.0 and not self.storage_warned_disk_low:
            self.storage_warned_disk_low=True
            messagebox.showwarning(
                "FLIR DVR disk space",
                f"Only {free_gb:.2f} GB remains free on the recording disk.\n"
                "Old non-favorite recordings will be removed if necessary."
            )
        if used>limit or free<512*1024**2:
            if not self.storage_delete_warned:
                self.storage_delete_warned=True
                messagebox.showwarning(
                    "FLIR DVR automatic cleanup",
                    "Storage cleanup is starting. Oldest non-favorite recordings are deleted first; favorites are protected."
                )
            removed=self.prune_storage_if_needed()
            if removed:
                self.dvr_time_var.set(f"Cleanup removed {removed/(1024**2):.0f} MB • favorites protected")

    def dvr_hour_file(self,stamp):
        d=dt.datetime.fromtimestamp(stamp)
        folder=self.dvr_dir / d.strftime("%Y-%m-%d")
        folder.mkdir(exist_ok=True)
        return folder / f"{d.strftime('%Y-%m-%d_%H')}.f1dvr"

    def queue_dvr_frame(self,stamp,blob):
        try:
            self.dvr_queue.put_nowait(("frame",stamp,bytes(blob)))
        except queue.Full:
            # Never silently downsample; flag overflow loudly instead.
            self.status.set("DVR buffer overflow — archive cannot keep up with capture")

    def queue_dvr_measurements(self,stamp,temperatures=None,max_info=None):
        """Archive scene, automatic MAX and manual point temperatures."""
        temps=self.temperatures if temperatures is None else temperatures
        scene=None
        valid=[t for t in temps if math.isfinite(t)]
        if valid:
            try:
                e,tr,off=map(float,self.radiometry_settings(live=True))
            except ValueError:
                e,tr,off=.95,20.,0.
            scene=(min(valid),self.sample_temp_from(temps,VIEW_W//2,VIEW_H//2,live=True),max(valid),e,tr,off)

        pts=[]
        if max_info is None and valid:
            i=max(range(len(temps)),key=lambda k: temps[k] if math.isfinite(temps[k]) else -float("inf"))
            max_info=(i%VIEW_W,i//VIEW_W,temps[i])
        if max_info is not None:
            mx,my,mt=max_info
            if math.isfinite(mt):pts.append(("MAX",mx,my,mt))

        live_points=self._live_analysis['points'] if self.playback_mode and self._live_analysis else self.points
        for p in live_points:
            pts.append((p["name"],p["x"],p["y"],self.sample_temp_from(temps,p["x"],p["y"],live=True)))
        try:
            self.dvr_queue.put_nowait(("measure",stamp,scene,pts))
        except queue.Full:
            self.status.set("DVR buffer overflow — measurement archive delayed")

    def archive_live_measurements_from_blob(self,stamp,blob):
        """Archive live measurements while an old DVR frame owns the main viewer."""
        decoded=self.decode_raw_blob(blob,live=True)
        if decoded is None:return
        _sensor,_values,temps=decoded
        valid=[(t,i) for i,t in enumerate(temps) if math.isfinite(t)]
        max_info=None
        if valid:
            mt,mi=max(valid)
            max_info=(mi%VIEW_W,mi//VIEW_W,mt)
        self.queue_dvr_measurements(stamp,temperatures=temps,max_info=max_info)
        names=('points','max_point','graph_filter_state','temperatures')
        saved={name:getattr(self,name) for name in names}
        try:
            for name in names[:-1]:setattr(self,name,self._live_analysis[name])
            self.temperatures=temps
            self.update_max_point(stamp)
            for p in self.points:
                value=self.filter_graph_sample(p['name'],self.sample_temp_from(temps,p['x'],p['y'],live=True))
                if value is not None:p['history'].append((stamp,value))
                while p['history'] and p['history'][0][0]<stamp-self.history_retention_seconds:p['history'].popleft()
            if self.recording:self.write_csv(stamp)
        finally:
            for name,value in saved.items():setattr(self,name,value)

    def dvr_writer_loop(self):
        con=sqlite3.connect(self.dvr_db,timeout=30)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        pending=0; last_commit=time.monotonic()
        handles={}
        try:
            while not self.dvr_stop.is_set() or not self.dvr_queue.empty():
                try:
                    item=self.dvr_queue.get(timeout=.25)
                except queue.Empty:
                    item=None
                if item:
                    kind=item[0]
                    if kind=="frame":
                        _,stamp,blob=item
                        path=self.dvr_hour_file(stamp)
                        key=str(path)
                        fh=handles.get(key)
                        if fh is None:
                            fh=open(path,"ab",buffering=1024*1024); handles[key]=fh
                        comp=zlib.compress(blob,level=3)  # lossless; no frame-rate reduction
                        offset=fh.tell()
                        header=DVR_HEADER.pack(DVR_MAGIC,int(stamp*1_000_000_000),len(blob),len(comp))
                        fh.write(header); fh.write(comp)
                        rel=str(path.relative_to(self.dvr_dir))
                        con.execute("INSERT OR REPLACE INTO frames(ts,file,offset,raw_size,comp_size) VALUES(?,?,?,?,?)",
                                    (stamp,rel,offset,len(blob),len(comp)))
                        self.dvr_frames_written+=1; self.dvr_bytes_written+=len(header)+len(comp)
                        pending+=1
                    elif kind=="measure":
                        _,stamp,scene,pts=item
                        if scene is not None:
                            con.execute("""INSERT OR REPLACE INTO scene_samples
                                (ts,min_c,center_c,max_c,emissivity,reflected_c,calibration_offset_c)
                                VALUES(?,?,?,?,?,?,?)""",(stamp,*scene))
                        for name,x,y,temp in pts:
                            con.execute("""INSERT OR REPLACE INTO point_samples
                                (ts,point_name,x,y,temp_c) VALUES(?,?,?,?,?)""",(stamp,name,x,y,temp))
                        pending+=1
                if pending>=32 or (pending and time.monotonic()-last_commit>=1.0):
                    for fh in handles.values(): fh.flush()
                    con.commit(); pending=0; last_commit=time.monotonic()
            for fh in handles.values(): fh.flush()
            con.commit()
        finally:
            for fh in handles.values():
                try: fh.close()
                except Exception: pass
            con.close()

    def dvr_bounds(self):
        con=sqlite3.connect(self.dvr_db)
        try:
            row=con.execute("SELECT MIN(ts),MAX(ts) FROM frames").fetchone()
            return row if row and row[0] is not None else (None,None)
        finally:
            con.close()

    def dvr_nearest_frame(self,stamp):
        con=sqlite3.connect(self.dvr_db)
        try:
            row=con.execute("""SELECT ts,file,offset,raw_size,comp_size FROM frames
                               ORDER BY ABS(ts-?) LIMIT 1""",(stamp,)).fetchone()
        finally:
            con.close()
        if not row:return None
        ts,rel,offset,raw_size,comp_size=row
        path=self.dvr_dir/rel
        try:
            with path.open("rb") as fh:
                fh.seek(offset)
                hdr=fh.read(DVR_HEADER.size)
                magic,ts_ns,rs,cs=DVR_HEADER.unpack(hdr)
                if magic!=DVR_MAGIC:return None
                comp=fh.read(cs)
            blob=zlib.decompress(comp)
            if len(blob)!=rs:return None
            return float(ts),blob
        except (OSError,zlib.error,struct.error):
            return None

    @staticmethod
    def _median(values):
        if not values:
            return float("nan")
        vals=sorted(values)
        n=len(vals)
        mid=n//2
        return vals[mid] if n & 1 else (vals[mid-1]+vals[mid])*0.5

    def frame_guard_samples(self,blob):
        """Return sparse radiometric samples in sensor order for FFC guarding."""
        if len(blob)!=38400:
            return None
        try:
            sensor=struct.unpack("<19200H",blob)
        except struct.error:
            return None
        samples=[]
        for i in range(0,19200,32):
            t=self.raw_to_c(sensor[i],live=True)
            if math.isfinite(t):
                samples.append(t)
        return samples if len(samples)>=100 else None

    def frame_is_acceptable(self,blob):
        """Reject FFC/shutter settling frames before they reach DVR or graphs."""
        cur=self.frame_guard_samples(blob)
        if cur is None:
            return False,"invalid radiometric frame"
        prev=self.frame_guard_prev_samples
        if prev is None or len(prev)!=len(cur):
            self.frame_guard_prev_samples=cur
            self.frame_guard_candidate_samples=None
            self.frame_guard_candidate_count=0
            return True,""

        deltas=[b-a for a,b in zip(prev,cur)]
        med=self._median(deltas)
        mad=self._median([abs(d-med) for d in deltas])

        cur_sorted=sorted(cur); prev_sorted=sorted(prev)
        q05=cur_sorted[int((len(cur_sorted)-1)*0.05)]
        q95=cur_sorted[int((len(cur_sorted)-1)*0.95)]
        p05=prev_sorted[int((len(prev_sorted)-1)*0.05)]
        p95=prev_sorted[int((len(prev_sorted)-1)*0.95)]
        cur_span=q95-q05; prev_span=p95-p05

        global_shift=abs(med)>=3.0 and mad<=0.85
        shutter_like=cur_span<=0.65 and prev_span>=2.0

        if global_shift or shutter_like:
            reason=(
                f"FFC/settling suppressed (global shift {med:+.1f} °C, MAD {mad:.2f} °C)"
                if global_shift else
                f"FFC/shutter suppressed (scene span {cur_span:.2f} °C)"
            )
            cand=self.frame_guard_candidate_samples
            if cand is not None and len(cand)==len(cur):
                cd=[b-a for a,b in zip(cand,cur)]
                cand_med=self._median(cd)
                cand_mad=self._median([abs(d-cand_med) for d in cd])
                if abs(cand_med)<=0.75 and cand_mad<=0.50:
                    self.frame_guard_candidate_count+=1
                else:
                    self.frame_guard_candidate_samples=cur
                    self.frame_guard_candidate_count=1
            else:
                self.frame_guard_candidate_samples=cur
                self.frame_guard_candidate_count=1

            if self.frame_guard_candidate_count>=4:
                self.frame_guard_prev_samples=cur
                self.frame_guard_candidate_samples=None
                self.frame_guard_candidate_count=0
                return True,"new stable radiometric baseline accepted"

            self.frame_guard_rejected+=1
            self.frame_guard_last_reason=reason
            return False,reason

        self.frame_guard_prev_samples=cur
        self.frame_guard_candidate_samples=None
        self.frame_guard_candidate_count=0
        return True,""

    def decode_raw_blob(self,blob,live=False):
        """Decode one 160×120 sensor RAW16 frame to the rotated 120×160 view."""
        if len(blob)!=38400:
            return None
        try:
            sensor=struct.unpack("<19200H",blob)
        except struct.error:
            return None
        out=[0]*19200
        for sy in range(SRC_H):
            row=sy*SRC_W
            for sx in range(SRC_W):
                out[(SRC_W-1-sx)*VIEW_W+sy]=sensor[row+sx]
        temps=self.frame_temperatures(out,live=live)
        return sensor,out,temps

    def load_raw_blob(self,blob,update_background=True):
        decoded=self.decode_raw_blob(blob)
        if decoded is None:
            return False
        self.raw,self.display_values,self.temperatures=decoded
        if update_background:
            self.update_background_model(time.monotonic())
        return True

    def history_sessions_from_db(self, gap_threshold=12.0):
        con=sqlite3.connect(self.dvr_db)
        try:
            rows=con.execute("SELECT ts FROM frames ORDER BY ts").fetchall()
        finally:
            con.close()
        if not rows:
            return []
        sessions=[]
        start=prev=float(rows[0][0]); count=1
        for (raw_ts,) in rows[1:]:
            ts=float(raw_ts)
            if ts-prev>gap_threshold:
                sessions.append({"start":start,"end":prev,"count":count})
                start=ts; count=1
            else:
                count+=1
            prev=ts
        sessions.append({"start":start,"end":prev,"count":count})
        return sessions

    def history_point_names(self):
        con=sqlite3.connect(self.dvr_db)
        try:
            return [r[0] for r in con.execute(
                "SELECT DISTINCT point_name FROM point_samples ORDER BY point_name"
            ).fetchall()]
        finally:
            con.close()

    def open_history_window(self):
        self.open_gallery()

    def _legacy_history_window(self):
        if self.history_window is not None and self.history_window.winfo_exists():
            self.history_window.deiconify()
            self.history_window.lift()
            self.refresh_history_graph()
            return

        win=tk.Toplevel(self.root)
        self.history_window=win
        win.title("FLIR ONE Gen 2 — History")
        win.configure(bg="#050609")
        win.geometry("1180x760")
        win.minsize(900,600)

        header=ttk.Frame(win,style="Panel.TFrame")
        header.pack(fill="x",padx=10,pady=(10,6))
        ttk.Label(header,text="HISTORY",style="Title.TLabel").pack(side="left")

        ttk.Label(header,textvariable=self.history_selected_var,style="Panel.TLabel").pack(side="left",padx=(18,10))

        self.history_play_button=ttk.Button(header,text="▶ Playback",command=self.play_selected_history)
        self.history_play_button.pack(side="left",padx=(0,8))
        self.history_favorite_button=ttk.Button(
            header,text="☆ Favorite recording",command=self.toggle_selected_history_favorite
        )
        self.history_favorite_button.pack(side="left",padx=(0,8))

        ttk.Label(header,text="Speed",style="Panel.TLabel").pack(side="left",padx=(0,5))
        self.history_speed_combo=ttk.Combobox(
            header,textvariable=self.history_speed_var,
            values=["1×","3×","5×","10×","20×"],
            state="readonly",width=6
        )
        self.history_speed_combo.pack(side="left")
        self.history_speed_combo.bind("<<ComboboxSelected>>",self.on_history_speed_changed)

        ttk.Label(header,text="Graph point:",style="Panel.TLabel").pack(side="left",padx=(18,6))
        self.history_point_combo=ttk.Combobox(
            header,textvariable=self.history_point_var,state="readonly",width=10
        )
        self.history_point_combo.pack(side="left")
        self.history_point_combo.bind("<<ComboboxSelected>>",lambda _e:self.refresh_history_graph())

        ttk.Button(header,text="Refresh",command=self.refresh_history_graph).pack(side="right")
        ttk.Button(header,text="Close",command=win.withdraw).pack(side="right",padx=(0,6))

        preview_frame=ttk.Frame(win,style="Dark.TFrame")
        preview_frame.pack(fill="both",expand=True,padx=10,pady=(0,8))
        self.history_preview=tk.Canvas(
            preview_frame,bg="#050609",highlightthickness=1,highlightbackground="#263545"
        )
        self.history_preview.pack(fill="both",expand=True)
        self.history_preview.create_text(
            430,220,text="Select a time below — the main viewer becomes the history viewer",
            fill="#8ba1b5",font=("Segoe UI",14),tags="placeholder"
        )

        self.history_status_var=tk.StringVar(
            value="Click the graph to select a time, then press Playback."
        )
        tk.Label(
            win,textvariable=self.history_status_var,bg="#111923",fg="#eff5ff",
            font=("Segoe UI",10),anchor="w",padx=10
        ).pack(fill="x",padx=10,pady=(0,5))

        graph_frame=ttk.Frame(win,style="Panel.TFrame")
        graph_frame.pack(fill="x",padx=10,pady=(0,10))
        self.history_graph=tk.Canvas(
            graph_frame,height=190,bg="#0d141e",
            highlightthickness=1,highlightbackground="#263545",cursor="crosshair"
        )
        self.history_scroll=ttk.Scrollbar(
            graph_frame,orient="horizontal",command=self.history_graph.xview
        )
        self.history_graph.configure(xscrollcommand=self.history_scroll.set)
        self.history_graph.pack(fill="x",expand=True)
        self.history_scroll.pack(fill="x")

        self.history_graph.bind("<Motion>",self.on_history_motion)
        self.history_graph.bind("<Button-1>",self.on_history_click)
        self.history_graph.bind("<MouseWheel>",self.on_history_wheel)

        win.protocol("WM_DELETE_WINDOW",win.withdraw)

        names=self.history_point_names()
        self.history_point_combo["values"]=names
        if names and self.history_point_var.get() not in names:
            self.history_point_var.set(names[0])

        self.refresh_history_graph()
        self.update_history_favorite_button()

    def refresh_history_graph(self):
        g=self.history_graph
        if g is None:
            return

        names=self.history_point_names()
        self.history_point_combo["values"]=names
        if names and self.history_point_var.get() not in names:
            self.history_point_var.set(names[0])

        self.history_sessions=self.history_sessions_from_db()
        self.history_map=[]
        g.delete("all")

        if not self.history_sessions:
            g.create_text(24,85,text="No archived frames yet.",fill="#8ba1b5",
                          anchor="w",font=("Segoe UI",11))
            g.configure(scrollregion=(0,0,900,190))
            return

        point_name=self.history_point_var.get()
        con=sqlite3.connect(self.dvr_db)
        try:
            samples=con.execute(
                "SELECT ts,temp_c FROM point_samples WHERE point_name=? ORDER BY ts",
                (point_name,)
            ).fetchall() if point_name else []
        finally:
            con.close()

        samples=[(float(t),float(v)) for t,v in samples if v is not None and math.isfinite(v)]
        vals=[v for _,v in samples]
        if vals:
            ymin,ymax=min(vals),max(vals)
            pad=max(.5,(ymax-ymin)*.10)
            ymin-=pad; ymax+=pad
        else:
            ymin,ymax=0.0,1.0

        px_per_second=0.75
        min_session_width=100
        gap_width=24
        left=58; top=28; bottom=154
        x=left

        for n in range(5):
            y=top+n*(bottom-top)/4
            temp=ymax-n*(ymax-ymin)/4
            g.create_line(left,y,1200,y,fill="#263545")
            g.create_text(50,y,text=f"{self.shown_temp(temp):.1f}",
                          fill="#98adb9",anchor="e",font=("Segoe UI",8))

        for idx,s in enumerate(self.history_sessions):
            duration=max(.001,s["end"]-s["start"])
            sw=max(min_session_width,duration*px_per_second)
            x0,x1=x,x+sw
            self.history_map.append((x0,x1,idx,s))

            fav=self.session_is_favorite(s["start"],s["end"])
            g.create_rectangle(x0,top,x1,bottom,fill="#15202c",
                               outline="#7fded2" if fav else "#263545",
                               width=2 if fav else 1)
            g.create_text(
                x0+6,top+5,
                text=("★ " if fav else "") + dt.datetime.fromtimestamp(s["start"]).strftime("%d %b %H:%M:%S"),
                fill="#98adb9",anchor="nw",font=("Segoe UI",8)
            )

            seg=[(t,v) for t,v in samples if s["start"]<=t<=s["end"]]
            coords=[]
            for t,v in seg:
                xx=x0+(t-s["start"])/duration*(x1-x0)
                yy=top+(ymax-v)/(ymax-ymin)*(bottom-top)
                coords.extend((xx,yy))
            if len(coords)>=4:
                g.create_line(*coords,fill="#ffe45e",width=2,smooth=True)

            g.create_line(x1,top,x1,bottom,fill="#506777")
            x=x1

            if idx < len(self.history_sessions)-1:
                real_gap=self.history_sessions[idx+1]["start"]-s["end"]
                g.create_line(x,bottom-9,x+gap_width,bottom-9,fill="#506777",dash=(3,3))
                g.create_text(
                    x+gap_width/2,bottom-17,
                    text=self.format_span(real_gap),
                    fill="#8ba1b5",anchor="s",font=("Segoe UI",7)
                )
                x+=gap_width

        g.create_line(left,bottom,x,bottom,fill="#506777")
        g.create_text(
            left,10,
            text=f"All recorded time • graph: {point_name or 'no point data'} • gaps compressed",
            fill="#d8e8ef",anchor="w",font=("Segoe UI Semibold",9)
        )
        g.configure(scrollregion=(0,0,max(980,x+50),190))
        self.draw_history_selection_marker()

    def history_position_to_time(self,canvas_x):
        for x0,x1,idx,s in self.history_map:
            if x0<=canvas_x<=x1:
                f=clamp((canvas_x-x0)/max(1,x1-x0),0.0,1.0)
                ts=s["start"]+f*(s["end"]-s["start"])
                return idx,s,ts
        return None,None,None

    def on_history_motion(self,e):
        if self.history_graph is None:
            return
        cx=self.history_graph.canvasx(e.x)
        idx,s,ts=self.history_position_to_time(cx)
        if s is None:
            return

        self.history_graph.delete("history_cursor")
        self.history_graph.create_line(
            cx,22,cx,160,fill="#ffffff",dash=(3,3),tags="history_cursor"
        )

        if self.history_status_var:
            self.history_status_var.set(
                f"{dt.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')}  •  "
                f"session {idx+1}/{len(self.history_sessions)}"
            )

        # Hover only previews the timestamp/cursor. Playback starts explicitly.

    def on_history_click(self,e):
        if self.history_graph is None:
            return
        cx=self.history_graph.canvasx(e.x)
        idx,s,ts=self.history_position_to_time(cx)
        if s is None:
            return
        self.history_selected_ts=ts
        self.history_selected_session_index=idx
        self.history_selected_var.set(
            "Selected: " + dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        )
        self.update_history_favorite_button()
        self.draw_history_selection_marker()
        # Show the selected frame immediately but do not start playback yet.
        hit=self.dvr_nearest_frame(ts)
        if hit:
            frame_ts,blob=hit
            self.history_play_ts=frame_ts
            self.history_session_index=idx
            self.show_history_frame(frame_ts,blob)

    def draw_history_selection_marker(self):
        if self.history_graph is None:
            return
        self.history_graph.delete("history_selected")
        ts=self.history_selected_ts
        idx=self.history_selected_session_index
        if ts is None or idx is None or idx>=len(self.history_sessions):
            return
        s=self.history_sessions[idx]
        mapping=None
        for x0,x1,i,ss in self.history_map:
            if i==idx:
                mapping=(x0,x1,ss); break
        if mapping is None:
            return
        x0,x1,ss=mapping
        duration=max(.001,ss["end"]-ss["start"])
        x=x0+(ts-ss["start"])/duration*(x1-x0)
        self.history_graph.create_polygon(
            x-5,18,x+5,18,x,27,
            fill="#7fded2",outline="#7fded2",tags="history_selected"
        )
        self.history_graph.create_line(
            x,27,x,158,fill="#7fded2",width=2,tags="history_selected"
        )

    def on_history_speed_changed(self,_=None):
        raw=self.history_speed_var.get().replace("×","").strip()
        try:self.history_speed=max(0.1,float(raw))
        except ValueError:self.history_speed=1.0

    def play_selected_history(self):
        if self.history_playing:
            self.history_playing=False
            if self.history_play_after:
                try:self.root.after_cancel(self.history_play_after)
                except Exception:pass
                self.history_play_after=None
            self.history_play_button.configure(text="▶ Playback")
            return
        if self.history_selected_ts is None or self.history_selected_session_index is None:
            if self.history_status_var:
                self.history_status_var.set("Select a time on the history graph first.")
            return
        self.on_history_speed_changed()
        self.start_history_playback(
            self.history_selected_ts,
            self.history_selected_session_index
        )

    def on_history_wheel(self,e):
        if self.history_graph is not None:
            self.history_graph.xview_scroll(-4 if getattr(e,"delta",0)>0 else 4,"units")
        return "break"

    def start_history_playback(self,stamp,session_index):
        self.history_playing=False
        if self.history_play_after:
            try:self.root.after_cancel(self.history_play_after)
            except Exception:pass
            self.history_play_after=None

        hit=self.dvr_nearest_frame(stamp)
        if not hit:
            return

        ts,blob=hit
        self.history_session_index=session_index
        self.history_play_ts=ts
        self.show_history_frame(ts,blob)
        self.history_playing=True
        if hasattr(self,"history_play_button"):
            self.history_play_button.configure(text="⏸ Playing")
        self.schedule_history_next()

    def schedule_history_next(self):
        if not self.history_playing or self.history_session_index is None:
            return

        s=self.history_sessions[self.history_session_index]
        con=sqlite3.connect(self.dvr_db)
        try:
            row=con.execute(
                "SELECT ts FROM frames WHERE ts>? AND ts<=? ORDER BY ts LIMIT 1",
                (self.history_play_ts,s["end"])
            ).fetchone()
        finally:
            con.close()

        if not row:
            self.history_playing=False
            if hasattr(self,"history_play_button"):
                self.history_play_button.configure(text="▶ Playback")
            return

        next_ts=float(row[0])
        delay=max(1,int((next_ts-self.history_play_ts)*1000/max(.1,self.history_speed)))
        self.history_play_after=self.root.after(
            delay,lambda t=next_ts:self.advance_history_frame(t)
        )

    def advance_history_frame(self,stamp):
        if not self.history_playing:
            return
        hit=self.dvr_nearest_frame(stamp)
        if not hit:
            self.history_playing=False
            return

        ts,blob=hit
        self.history_play_ts=ts
        self.show_history_frame(ts,blob)
        self.schedule_history_next()

    def history_measurements_at(self,stamp,tolerance=1.0):
        con=sqlite3.connect(self.dvr_db)
        try:
            rows=con.execute(
                """SELECT point_name,x,y,temp_c,ABS(ts-?) AS d
                   FROM point_samples
                   WHERE ts BETWEEN ? AND ?
                   ORDER BY point_name,d""",
                (stamp,stamp-tolerance,stamp+tolerance)
            ).fetchall()

            nearest={}
            for name,x,y,temp,d in rows:
                if name not in nearest:
                    nearest[name]=(name,x,y,temp)

            scene=con.execute(
                """SELECT min_c,center_c,max_c
                   FROM scene_samples
                   WHERE ts BETWEEN ? AND ?
                   ORDER BY ABS(ts-?) LIMIT 1""",
                (stamp-tolerance,stamp+tolerance,stamp)
            ).fetchone()
        finally:
            con.close()

        return list(nearest.values()),scene

    def show_history_frame(self,stamp,blob):
        """Archived RAW16 becomes the active frame in the main viewer."""
        if not self.load_raw_blob(blob,update_background=False):return
        self.playback_mode=True
        self.frozen=True
        self.freeze_button.configure(text="▶ Return to live")
        self.status.set("HISTORY • "+dt.datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3])
        self.render()

        if self.history_preview is not None and self.rendered_image is not None:
            try:
                self.history_preview.update_idletasks()
                cw=max(520,self.history_preview.winfo_width()); ch=max(340,self.history_preview.winfo_height())
                im=self.rendered_image.copy()
                scale=min(cw/im.width,ch/im.height)
                target=(max(1,int(im.width*scale)),max(1,int(im.height*scale)))
                scaled=im.resize(target,Image.Resampling.NEAREST)
                self.history_preview_photo=ImageTk.PhotoImage(scaled)
                self.history_preview.delete("all")
                self.history_preview.create_image(cw//2,ch//2,image=self.history_preview_photo,anchor="center")
                self.history_preview.create_text(
                    14,14,text=dt.datetime.fromtimestamp(stamp).strftime("%Y-%m-%d  %H:%M:%S.%f")[:-3],
                    fill="#f0f2f5",anchor="nw",font=("Segoe UI Semibold",11))
            except tk.TclError:pass

        valid=[t for t in self.temperatures if math.isfinite(t)]
        if valid and self.history_status_var:
            self.history_status_var.set(
                f"{dt.datetime.fromtimestamp(stamp).strftime('%Y-%m-%d %H:%M:%S')} • "
                f"Min {min(valid):.1f} °C • Center {self.sample_temp(VIEW_W//2,VIEW_H//2):.1f} °C • "
                f"Max {max(valid):.1f} °C • main viewer active"
            )

    def radiometry_settings(self,live=False):
        if live and self.playback_mode and self._live_analysis:return self._live_radiometry
        return (self.emissivity_var.get(),self.reflected_var.get(),self.temp_offset_var.get())

    def frame_temperatures(self,values,live=False):
        # Cache exact conversions across frames; invalidate on any calibration
        # edit. RAW16 bounds this cache to at most 65,536 sensor values.
        key=self.radiometry_settings(live)
        if (getattr(self,"_temperature_frame_values",None) is values
                and getattr(self,"_temperature_cache_key",None)==key):
            return self._temperature_frame_result
        if getattr(self,"_temperature_cache_key",None)!=key:
            self._temperature_cache_key=key
            self._temperature_cache={}
        converted=self._temperature_cache
        for v in set(values):
            if v not in converted:converted[v]=self.raw_to_c(v,live=live)
        result=[converted[v] for v in values]
        self._temperature_frame_values=values
        self._temperature_frame_result=result
        return result

    def raw_to_c(self,raw14,live=False):
        try:
            e,tr,offset=map(float,self.radiometry_settings(live))
            e=clamp(e,.01,1.0)
        except ValueError:
            e,tr,offset=.95,20.,0.0
        try:
            zn=R2*(math.exp(B/(tr+273.15))-F); raw_refl=R1/zn-O; raw_obj=(raw14*4-(1-e)*raw_refl)/e
            lg=R1/(R2*(raw_obj+O)+F)
            base=B/math.log(lg)-273.15 if lg>1 else float("nan")
            return base+offset if math.isfinite(base) else base
        except (ValueError,ZeroDivisionError,OverflowError): return float("nan")

    def shown_temp(self,c): return c*9/5+32 if self.unit_var.get()=="°F" else c
    def fmt_temp(self,c): return f"{self.shown_temp(c):.1f} {self.unit_var.get()}" if math.isfinite(c) else "—"
    def fmt_delta(self,c_delta):
        if not math.isfinite(c_delta):return "—"
        factor=9/5 if self.unit_var.get()=="°F" else 1.0
        return f"{c_delta*factor:+.1f} {self.unit_var.get()}"

    def sample_temp_from(self,temperatures,x,y,live=False):
        if not temperatures:return float("nan")
        average=self._live_average if live and self.playback_mode and self._live_analysis else self.smooth_var.get()
        r=1 if average else 0; vals=[]
        for yy in range(max(0,y-r),min(VIEW_H,y+r+1)):
            for xx in range(max(0,x-r),min(VIEW_W,x+r+1)):
                v=temperatures[yy*VIEW_W+xx]
                if math.isfinite(v):vals.append(v)
        return statistics.fmean(vals) if vals else float("nan")

    def sample_temp(self,x,y):
        return self.sample_temp_from(self.temperatures,x,y)

    def load_raw(self):
        try:
            blob=LIVE_RAW.read_bytes()
            if len(blob)!=38400:return False
            sensor=struct.unpack("<19200H",blob)
        except (OSError,struct.error):return False
        out=[0]*19200
        for sy in range(SRC_H):
            for sx in range(SRC_W):out[(SRC_W-1-sx)*VIEW_W+sy]=sensor[sy*SRC_W+sx]
        self.raw=sensor; self.display_values=out; self.temperatures=[self.raw_to_c(v) for v in out]
        self.update_background_model(time.monotonic())
        return True

    def visual_stream_is_fresh(self):
        """Only advertise Visible/MSX when a visual frame is actually live and synced."""
        try:
            vst=LIVE_VISUAL.stat()
            rst=LIVE_RAW.stat()
            if vst.st_size<=0:
                return False
            # Prevent an old JPEG from a previous experiment being mistaken for
            # a live optical stream. Two seconds is generous at Gen2 frame rates.
            return abs(vst.st_mtime-rst.st_mtime)<=2.0
        except OSError:
            return False

    def update_visible_controls(self,force=False):
        available=self.visual_stream_is_fresh()
        if not force and available==self.visual_available:
            return
        self.visual_available=available
        if available:
            # Reveal the view selector and optical alignment controls only when
            # an actual synchronized optical stream has been detected.
            self.view_label.grid(row=3,column=0,sticky="w",padx=(8,6),pady=5)
            self.view_combo.grid(row=3,column=1,sticky="ew",padx=(0,12),pady=5)
            if not self.visible_box.winfo_manager():
                self.visible_box.pack(fill="x",pady=(0,7))
            self.view_combo.configure(values=["Thermal","Visible","Overlay","MSX edges"])
        else:
            if self.view_mode.get()!="Thermal":
                self.view_mode.set("Thermal")
            try:self.view_label.grid_remove()
            except Exception:pass
            try:self.view_combo.grid_remove()
            except Exception:pass
            try:self.visible_box.pack_forget()
            except Exception:pass
            self.view_combo.configure(values=["Thermal"])

    def load_visual(self):
        if not self.visual_stream_is_fresh():
            return False
        try:
            mtime=LIVE_VISUAL.stat().st_mtime_ns
            if self.visible_image is not None and mtime==self.visual_mtime:
                if not self.visual_available:self.update_visible_controls(force=True)
                return True
            with Image.open(LIVE_VISUAL) as im:self.visible_image=im.convert("RGB").copy()
            self.visual_mtime=mtime
            if not self.visual_available:self.update_visible_controls(force=True)
            return True
        except (OSError, ValueError):
            if self.visual_available:
                self.visible_image=None
                self.update_visible_controls(force=True)
            return False

    def aligned_visual(self):
        if not self.load_visual():return None
        im=self.visible_image
        if im.width>im.height:im=im.transpose(Image.Transpose.ROTATE_270)
        zoom=max(.6,min(1.8,self.visual_zoom.get()/100))
        target=(max(1,int(VIEW_W*zoom)),max(1,int(VIEW_H*zoom)))
        im=ImageOps.fit(im,target,method=Image.Resampling.LANCZOS)
        layer=Image.new("RGB",(VIEW_W,VIEW_H),(0,0,0))
        layer.paste(im,((VIEW_W-im.width)//2+self.visual_x.get(),(VIEW_H-im.height)//2+self.visual_y.get()))
        return layer

    @staticmethod
    def _percentile_sorted(values,q):
        if not values:
            return float("nan")
        q=clamp(float(q),0.0,1.0)
        pos=(len(values)-1)*q
        i=int(pos)
        j=min(i+1,len(values)-1)
        f=pos-i
        return values[i]*(1.0-f)+values[j]*f

    def _radiometry_key(self):
        try:
            return (
                round(clamp(float(self.emissivity_var.get()),.01,1.0),6),
                round(float(self.reflected_var.get()),4),
                round(float(self.temp_offset_var.get()),4),
            )
        except ValueError:
            return None

    def reset_background_model(self,temperatures=None,stamp=None):
        """Reset the temporal scene model without changing radiometric data."""
        if temperatures is None:
            temperatures=self.temperatures
        if stamp is None:
            stamp=time.monotonic()
        if not temperatures:
            self.background_mean=None
            self.background_var=None
            self.background_last_update=stamp
            self.background_age=0.0
            self.background_center=None
            self.background_low=None
            self.background_high=None
            return

        self.background_mean=[float(t) if math.isfinite(t) else float("nan") for t in temperatures]
        self.background_var=[0.0]*len(temperatures)
        self.background_last_update=stamp
        self.background_age=0.0
        self.background_key=self._radiometry_key()
        self._recompute_background_band()

    def _recompute_background_band(self):
        """Estimate the ordinary/stable scene-temperature band.

        Only low-temporal-variance pixels are preferred.  Their long-term EWMA
        temperatures are then reduced to a robust spatial band, so a small,
        stationary hot component does not become 'background' just because it
        is thermally stable.
        """
        means=self.background_mean
        variances=self.background_var
        if not means or not variances:
            self.background_center=self.background_low=self.background_high=None
            return

        candidates=[]
        # 1/4 of the 160x120 image is plenty for robust statistics and keeps
        # this cheap even if capture FPS increases later.
        for i in range(0,min(len(means),len(variances)),4):
            m=means[i]
            if not math.isfinite(m):
                continue
            sigma=math.sqrt(max(0.0,variances[i]))
            if self.background_age<4.0 or sigma<=self.background_stability_sigma:
                candidates.append(m)

        if len(candidates)<250:
            candidates=[m for m in means[::4] if math.isfinite(m)]
        if not candidates:
            self.background_center=self.background_low=self.background_high=None
            return

        candidates.sort()
        center=self._percentile_sorted(candidates,0.50)
        q10=self._percentile_sorted(candidates,0.10)
        q90=self._percentile_sorted(candidates,0.90)

        # Background should occupy only the dark end of the palette.  Give the
        # ordinary scene a minimum 0.7 °C dark band, but cap each side at
        # roughly 0.85 °C so a genuinely hot object cannot widen it forever.
        low=center-max(0.35,min(0.85,(center-q10)+0.12))
        high=center+max(0.35,min(0.85,(q90-center)+0.12))

        self.background_center=center
        self.background_low=low
        self.background_high=high

    def update_background_model(self,stamp=None):
        """Update per-pixel temporal mean/variance and the robust background band."""
        temps=self.temperatures
        if not temps:
            return
        if stamp is None:
            stamp=time.monotonic()

        key=self._radiometry_key()
        if (self.background_mean is None or self.background_var is None or
                len(self.background_mean)!=len(temps) or key!=self.background_key):
            self.reset_background_model(temps,stamp)
            return

        last=self.background_last_update
        dt=0.5 if last is None else max(0.01,min(10.0,stamp-last))

        # Scene-change guard: if most of the image suddenly no longer matches
        # the learned per-pixel baseline, assume the camera was moved and learn
        # the new scene immediately instead of spending two minutes dragging the
        # old baseline toward it.
        if self.background_age>=4.0:
            diffs=[]
            big=0
            total=0
            for i in range(0,len(temps),16):
                t=temps[i]; m=self.background_mean[i]
                if not (math.isfinite(t) and math.isfinite(m)):
                    continue
                d=abs(t-m)
                diffs.append(d)
                total+=1
                if d>=0.80:
                    big+=1
            if diffs and total:
                diffs.sort()
                med=self._percentile_sorted(diffs,0.50)
                if med>=0.70 and big/total>=0.65:
                    self.background_scene_resets+=1
                    self.reset_background_model(temps,stamp)
                    return

        alpha_mean=1.0-math.exp(-dt/self.background_learning_seconds())
        alpha_var=1.0-math.exp(-dt/max(1.0,self.background_variance_tau))
        # Avoid a numerically frozen model at unusually high FPS.
        alpha_mean=max(0.001,min(0.20,alpha_mean))
        alpha_var=max(0.003,min(0.35,alpha_var))

        means=self.background_mean
        variances=self.background_var
        for i,t in enumerate(temps):
            if not math.isfinite(t):
                continue
            m=means[i]
            if not math.isfinite(m):
                means[i]=t
                variances[i]=0.0
                continue
            delta=t-m
            means[i]=m+alpha_mean*delta
            # Exponentially weighted variance; faster than the mean so moving
            # or changing regions stop qualifying as stable background quickly.
            variances[i]=(1.0-alpha_var)*(variances[i]+alpha_var*delta*delta)

        self.background_last_update=stamp
        self.background_age+=dt
        self.background_key=key
        self._recompute_background_band()

    def background_display_params(self,temperatures,use_temporal=True):
        """Return dark-background band and upper hot-tone limit in °C."""
        sample=[t for t in temperatures[::4] if math.isfinite(t)]
        if not sample:
            return {"center":0.0,"low":-0.35,"high":0.35,"deadband":0.25,"hot":3.6}
        sample.sort()

        if (use_temporal and self.background_key==self._radiometry_key() and
                self.background_center is not None and self.background_low is not None and
                self.background_high is not None):
            center=self.background_center
            low=self.background_low
            high=self.background_high
        else:
            # History/single-frame fallback: no temporal model is available,
            # so use robust spatial percentiles and the same capped dark band.
            center=self._percentile_sorted(sample,0.50)
            q10=self._percentile_sorted(sample,0.10)
            q90=self._percentile_sorted(sample,0.90)
            low=center-max(0.35,min(0.85,(center-q10)+0.12))
            high=center+max(0.35,min(0.85,(q90-center)+0.12))

        try: deadband=clamp(float(self.background_deadband_var.get()),0.0,2.0)
        except ValueError: deadband=0.25
        try: min_hot_span=clamp(float(self.background_hot_span_var.get()),0.5,20.0)
        except ValueError: min_hot_span=3.0

        p995=self._percentile_sorted(sample,0.995)
        hot=max(high+deadband+min_hot_span,p995+0.10)
        return {"center":center,"low":low,"high":high,
                "deadband":deadband,"hot":hot}

    @staticmethod
    def background_palette_index(temp,params):
        """Map °C to palette index while keeping ordinary surfaces dark."""
        if not math.isfinite(temp):
            return 0
        low=params["low"]; high=params["high"]
        deadband=params["deadband"]; hot=params["hot"]

        if temp<=low:
            # Colder-than-background remains dark blue/black; never bright.
            cold=clamp((low-temp)/2.0,0.0,1.0)
            return int(round(10.0*(1.0-cold)))
        if temp<=high:
            # Entire ordinary/stable surface band gets only the first ~11% of
            # the palette: navy -> very dark purple in the Iron palette.
            f=(temp-low)/max(0.05,high-low)
            return int(round(10.0+18.0*f))
        if temp<=high+deadband:
            return 28

        start=high+deadband
        u=clamp((temp-start)/max(0.10,hot-start),0.0,1.0)
        # Slightly concave curve makes a real warm spot become visible early,
        # without stretching tiny background noise across the full palette.
        u=u**0.65
        return int(round(34.0+221.0*u))

    def reset_heq_state(self):
        self.tone_mapper.reset()


    def normalize_rotation(self,angle):
        angle=float(angle)%360.0
        if abs(angle-360.0)<1e-6:angle=0.0
        return angle

    def set_rotation(self,angle):
        self.rotation_angle=self.normalize_rotation(angle)
        shown=int(round(self.rotation_angle)) if abs(self.rotation_angle-round(self.rotation_angle))<0.05 else round(self.rotation_angle,1)
        self.rotation_angle_label.configure(text=f"{shown}°")
        self.schedule_save_viewer_settings()
        self.render()

    def reset_view(self):
        self.rotation_angle=0.0
        self.mirror_var.set(False)
        self.rotation_angle_label.configure(text="0°")
        self.set_viewport_scale(1.0)

    def set_viewport_scale(self,scale):
        self.viewport_scale=max(0.60,min(1.60,float(scale)))
        new_w=max(240,int(round(self.base_canvas_w*self.viewport_scale)))
        new_h=max(320,int(round(self.base_canvas_h*self.viewport_scale)))

        # Resize the actual thermal viewport/canvas, not the image inside it.
        self.canvas.configure(width=new_w,height=new_h)
        self.canvas.coords(self.placeholder_id,new_w//2,new_h//2)
        self.viewport_scale_label.configure(text=f"{int(round(self.viewport_scale*100))}%")
        self.schedule_save_viewer_settings()

        # Grow/shrink the toplevel along with the viewport while preserving
        # the rest of the UI.  Geometry is adjusted by the exact canvas delta.
        self.root.update_idletasks()
        cur_w=max(1,self.root.winfo_width())
        cur_h=max(1,self.root.winfo_height())
        old_w=getattr(self,"_last_canvas_w",self.base_canvas_w)
        old_h=getattr(self,"_last_canvas_h",self.base_canvas_h)
        self._last_canvas_w=new_w
        self._last_canvas_h=new_h

        target_w=max(self.root.winfo_reqwidth(),cur_w+(new_w-old_w))
        target_h=max(self.root.winfo_reqheight(),cur_h+(new_h-old_h))
        self.root.geometry(f"{target_w}x{target_h}")
        self.render()

    def adjust_viewport_scale(self,delta):
        self.set_viewport_scale(self.viewport_scale+delta)

    def rotation_press(self,e):
        self.rotation_drag_start_x=e.x_root
        self.rotation_drag_start_angle=self.rotation_angle
        self.rotation_dragged=False

    def rotation_drag(self,e):
        dx=e.x_root-self.rotation_drag_start_x
        if abs(dx)>=3:
            self.rotation_dragged=True
        # 0.35° per mouse pixel gives useful fine control without being twitchy.
        self.rotation_angle=self.normalize_rotation(self.rotation_drag_start_angle + dx*0.35)
        shown=int(round(self.rotation_angle)) if abs(self.rotation_angle-round(self.rotation_angle))<0.05 else round(self.rotation_angle,1)
        self.rotation_angle_label.configure(text=f"{shown}°")
        self.schedule_save_viewer_settings()
        self.render()

    def rotation_release(self,_e):
        if not self.rotation_dragged:
            self.set_rotation(self.rotation_angle+90.0)

    def sensor_to_base_canvas(self,x,y):
        cw=max(1,int(self.canvas.cget("width")))
        ch=max(1,int(self.canvas.cget("height")))
        return ((x+0.5)*cw/VIEW_W, (y+0.5)*ch/VIEW_H)

    def base_canvas_to_sensor(self,x,y):
        cw=max(1,int(self.canvas.cget("width")))
        ch=max(1,int(self.canvas.cget("height")))
        return (x*VIEW_W/cw, y*VIEW_H/ch)

    def image_to_canvas(self,x,y):
        """Map unrotated canvas-pixel coordinates into the displayed rotated image."""
        tr=self.rotation_transform
        if not tr:
            return x,y
        a=math.radians(tr["angle"])
        c,s=math.cos(a),math.sin(a)
        cw=max(1,int(self.canvas.cget("width"))); ch=max(1,int(self.canvas.cget("height")))
        dx=x-cw/2.0
        dy=y-ch/2.0
        rx=c*dx-s*dy + tr["rw"]/2.0
        ry=s*dx+c*dy + tr["rh"]/2.0
        cx,cy=tr["ox"]+rx*tr["scale"], tr["oy"]+ry*tr["scale"]
        if self.mirror_var.get():cx=cw-1-cx
        return cx,cy

    def canvas_to_image(self,x,y):
        """Inverse of image_to_canvas(); returns original unrotated canvas pixels."""
        tr=self.rotation_transform
        if not tr:
            return x,y
        if self.mirror_var.get():x=int(self.canvas.cget("width"))-1-x
        rx=(x-tr["ox"])/tr["scale"]-tr["rw"]/2.0
        ry=(y-tr["oy"])/tr["scale"]-tr["rh"]/2.0
        a=math.radians(tr["angle"])
        c,s=math.cos(a),math.sin(a)
        dx=c*rx+s*ry
        dy=-s*rx+c*ry
        cw=max(1,int(self.canvas.cget("width"))); ch=max(1,int(self.canvas.cget("height")))
        return dx+cw/2.0,dy+ch/2.0

    def render(self):
        if not self.display_values:return
        self.temperatures=self.frame_temperatures(self.display_values)
        rgb=bytearray(57600); pal=self.palette_var.get(); bg_params=None
        # Reuse palette results within this render (settings cannot change
        # during this synchronous callback). Preserve fractional level inputs.
        color_cache={}
        def color(level):
            if level not in color_cache:
                color_cache[level]=bytes(palette_color(pal,int(level)))
            return color_cache[level]

        mode_scale=self.scale_mode.get()

        if mode_scale=="Background relative":
            # Archived frames must not borrow the live scene's temporal model.
            bg_params=self.background_display_params(
                self.temperatures,use_temporal=not self.playback_mode
            )
            for i,temp in enumerate(self.temperatures):
                level=self.background_palette_index(temp,bg_params)
                rgb[i*3:i*3+3]=color(self.adjusted_palette_level(level))
            display_lo_c=bg_params["low"]
            display_hi_c=bg_params["hot"]

        else:
            levels,display_lo_c,display_hi_c=self.display_levels(self.temperatures)
            # Pillow's LUT conversion avoids a Python loop over every pixel.
            indexed=Image.frombytes("P",(VIEW_W,VIEW_H),levels.tobytes())
            indexed.putpalette([channel for level in range(256) for channel in palette_color(pal,level)])
            rgb=indexed.convert("RGB").tobytes()

        thermal=Image.frombytes("RGB",(VIEW_W,VIEW_H),bytes(rgb))
        visual=None if self.playback_mode else self.aligned_visual(); mode=self.view_mode.get(); alpha=clamp(self.overlay_alpha.get()/100,0,1); self.alpha_label.configure(text=f"{int(alpha*100)}%")
        if mode=="Visible" and visual is not None:shown=visual
        elif mode=="Overlay" and visual is not None:shown=Image.blend(thermal,visual,alpha)
        elif mode=="MSX edges" and visual is not None:
            edges=ImageOps.grayscale(visual).filter(ImageFilter.FIND_EDGES); edges=ImageEnhance.Contrast(edges).enhance(3.0).point(lambda p:255 if p>42 else 0)
            lines=Image.new("RGB",thermal.size,(235,235,235)); shown=Image.composite(lines,thermal,edges)
        else:shown=thermal
        cw=max(1,int(self.canvas.cget("width")))
        ch=max(1,int(self.canvas.cget("height")))
        resample_display=Image.Resampling.BILINEAR if self.interpolation_var.get()=="Smooth" else Image.Resampling.NEAREST
        base_image=shown.resize((cw,ch),resample_display)

        # Positive UI angle means clockwise. PIL uses positive=counter-clockwise,
        # hence the negative sign.
        angle=self.rotation_angle
        if abs(angle)%360.0 < 1e-9:
            rotated=base_image
        else:
            resample=Image.Resampling.NEAREST if abs(angle%90.0)<1e-6 else Image.Resampling.BICUBIC
            rotated=base_image.rotate(-angle,expand=True,resample=resample,fillcolor=(5,6,9))

        rw,rh=rotated.size
        fit_scale=min(cw/rw,ch/rh)
        fw=max(1,int(round(rw*fit_scale))); fh=max(1,int(round(rh*fit_scale)))
        if (fw,fh)!=(rw,rh):
            rotated=rotated.resize(
                (fw,fh),
                Image.Resampling.NEAREST if abs(angle%90.0)<1e-6 else Image.Resampling.BICUBIC
            )
        ox=(cw-fw)//2; oy=(ch-fh)//2
        composed=Image.new("RGB",(cw,ch),(5,6,9))
        composed.paste(rotated,(ox,oy))
        if self.mirror_var.get():composed=ImageOps.mirror(composed)
        self.rendered_image=composed
        self.rotation_transform={
            "angle":angle,
            "rw":rw,"rh":rh,
            "scale":fit_scale,
            "ox":ox,"oy":oy,
        }
        self.photo=ImageTk.PhotoImage(self.rendered_image)
        self.canvas.itemconfigure(self.image_id,image=self.photo)
        self.canvas.itemconfigure(self.placeholder_id,state="hidden")
        self.canvas.delete("overlay")
        valid=[(t,i) for i,t in enumerate(self.temperatures) if math.isfinite(t)]
        if valid:
            tmin,imin=min(valid); tmax,imax=max(valid); center=self.sample_temp(VIEW_W//2,VIEW_H//2)
            now_mono=time.monotonic()
            if now_mono-self.last_text_update>=0.20:
                self.scene_text.set(f"Min {self.fmt_temp(tmin)}   •   Center {self.fmt_temp(center)}   •   Max {self.fmt_temp(tmax)}")
                if bg_params is not None:
                    self.range_text.set(
                        f"Background {self.fmt_temp(bg_params['center'])}  •  "
                        f"dark band {self.fmt_temp(bg_params['low'])}–{self.fmt_temp(bg_params['high'])}  •  "
                        f"hot scale → {self.fmt_temp(bg_params['hot'])}"
                    )
                elif mode_scale in ("Auto","Detail"):
                    self.range_text.set(
                        f"{mode_scale} • nonlinear AGC domain {self.fmt_temp(display_lo_c)} – {self.fmt_temp(display_hi_c)}"
                    )
                else:
                    self.range_text.set(f"Display range {self.fmt_temp(display_lo_c)} – {self.fmt_temp(display_hi_c)}")
                self.last_text_update=now_mono
            self.draw_scene_marker(imin,"C","#64b5ff")
            self.draw_scene_marker(imax,"MAX","#ff574d")
        for p in self.points:
            bx,by=self.sensor_to_base_canvas(p["x"],p["y"])
            cx,cy=self.image_to_canvas(bx,by); color=p["color"]
            self.canvas.create_line(cx-8,cy,cx+8,cy,fill=color,width=2,tags="overlay"); self.canvas.create_line(cx,cy-8,cx,cy+8,fill=color,width=2,tags="overlay")
            self.canvas.create_text(cx+8,cy-12,text=f'{p["name"]}  {self.fmt_temp(self.sample_temp(p["x"],p["y"]))}',fill="white",anchor="sw",font=("Segoe UI Semibold",10),tags="overlay")

    def draw_scene_marker(self,index,label,color):
        x,y=index%VIEW_W,index//VIEW_W
        bx,by=self.sensor_to_base_canvas(x,y)
        cx,cy=self.image_to_canvas(bx,by)
        self.canvas.create_oval(cx-6,cy-6,cx+6,cy+6,outline=color,width=2,tags="overlay"); self.canvas.create_text(cx+11,cy-9,text=label,fill=color,font=("Segoe UI Semibold",8),tags="overlay")

    def filter_graph_sample(self,key,value):
        """Reject isolated one-frame jumps without suppressing sustained real changes.

        A jump larger than the adaptive threshold is held as a candidate.
        If the next frame is close to that candidate, the new level is accepted;
        if it snaps back, the single bad frame never enters the graph.
        """
        if not math.isfinite(value):
            return None
        st=self.graph_filter_state.get(key)
        if st is None:
            self.graph_filter_state[key]={
                "last":value,"candidate":None,"count":0,
                "recent":deque([value],maxlen=9)
            }
            return value

        recent=list(st["recent"])
        center=statistics.median(recent) if recent else st["last"]
        deviations=[abs(v-center) for v in recent]
        mad=statistics.median(deviations) if deviations else 0.0
        threshold=max(2.5,6.0*mad+0.6)

        if abs(value-st["last"])<=threshold:
            st["last"]=value
            st["candidate"]=None
            st["count"]=0
            st["recent"].append(value)
            return value

        cand=st["candidate"]
        if cand is not None and abs(value-cand)<=1.2:
            st["count"]+=1
        else:
            st["candidate"]=value
            st["count"]=1

        if st["count"]>=2:
            # Sustained step = real scene change; accept the new level.
            st["last"]=value
            st["candidate"]=None
            st["count"]=0
            st["recent"].clear()
            st["recent"].append(value)
            return value

        self.graph_transient_rejected+=1
        return None

    def hottest_pixel(self):
        if not self.temperatures:
            return None
        best_i=None; best_t=-float("inf")
        for i,t in enumerate(self.temperatures):
            if math.isfinite(t) and t>best_t:
                best_t=t; best_i=i
        if best_i is None:return None
        return best_i%VIEW_W,best_i//VIEW_W,best_t

    def update_max_point(self,stamp):
        hot=self.hottest_pixel()
        if hot is None:
            return
        x,y,temp=hot
        self.max_point["x"]=x
        self.max_point["y"]=y
        v=self.filter_graph_sample("MAX",temp)
        if v is not None:
            self.max_point["history"].append((stamp,v))
            cutoff=stamp-self.history_retention_seconds
            while self.max_point["history"] and self.max_point["history"][0][0]<cutoff:
                self.max_point["history"].popleft()

    def update_points(self,stamp):
        self.update_max_point(stamp)
        cutoff=stamp-self.history_retention_seconds

        for p in self.points:
            raw_v=self.sample_temp(p["x"],p["y"])
            v=self.filter_graph_sample(p["name"],raw_v)
            if v is not None:
                p["history"].append((stamp,v))
                while p["history"] and p["history"][0][0]<cutoff:
                    p["history"].popleft()

        if self.recording:self.write_csv(stamp)
        self.graph_dirty=True
        now_mono=time.monotonic()
        if now_mono-self.last_point_list_update>=0.25:
            self.refresh_point_list()
            self.last_point_list_update=now_mono

    def measurement_rows(self):
        """Rows shown in MEASUREMENT POINTS: one automatic MAX plus manual points."""
        return [("auto",self.max_point)] + [("manual",p) for p in self.points]

    def on_point_list_select(self,_e=None):
        sel=self.point_list.curselection()
        rows=self.measurement_rows()
        if sel and 0<=sel[0]<len(rows):
            self.graph_selected_series=rows[sel[0]][1]["name"]
            self.update_graph_detail()
        self.request_graph_redraw(force=True)

    def on_point_list_click(self,e):
        """Toggle graph visibility from the checkbox area at the row start."""
        rows=self.measurement_rows()
        if not rows:
            return
        idx=self.point_list.nearest(e.y)
        if not (0<=idx<len(rows)):
            return
        kind,p=rows[idx]
        if e.x<=34:
            p["graph"]=not p.get("graph",True)
            if kind=="auto":self.schedule_save_viewer_settings()
            self.refresh_point_list()
            self.request_graph_redraw(force=True)
            return "break"

        # Normal row click selects that graph series too.
        self.graph_selected_series=p["name"]
        self.update_graph_detail()
        self.request_graph_redraw(force=True)

    def refresh_point_list(self):
        rows_data=self.measurement_rows()
        sel=self.point_list.curselection()
        selected=sel[0] if sel else 0
        rows=[]

        for kind,p in rows_data:
            temp=(self.sample_temp(p["x"],p["y"]) if kind!='auto' else max(self.temperatures,default=float('nan'))) if self.playback_mode else (p["history"][-1][1] if p["history"] else float("nan"))
            vals=[v for _,v in p["history"] if math.isfinite(v)]
            delta=vals[-1]-vals[0] if len(vals)>1 else 0
            mark="☑" if p.get("graph",True) else "☐"
            prefix="A" if kind=="auto" else " "
            rows.append(
                f'{mark}{prefix} {p["name"]:<5} ({p["x"]:3},{p["y"]:3})  '
                f'{self.fmt_temp(temp):>9}   Δ {self.fmt_delta(delta)}'
            )

        current=list(self.point_list.get(0,"end"))
        if current!=rows:
            self.point_list.delete(0,"end")
            for row in rows:
                self.point_list.insert("end",row)
            if rows:
                self.point_list.selection_set(min(selected,len(rows)-1))

    def on_motion(self,e):
        bx,by=self.canvas_to_image(e.x,e.y)
        sx,sy=self.base_canvas_to_sensor(bx,by)
        x,y=int(sx),int(sy)
        self.canvas.delete("hover_temp")
        if 0<=x<VIEW_W and 0<=y<VIEW_H and self.temperatures:
            temp=self.sample_temp(x,y)
            self.hover_text.set(f"X {x:3}  Y {y:3}   •   {self.fmt_temp(temp)}")
            # Small, regular-weight label with no opaque background.
            tx=min(max(8,e.x+10),max(8,int(self.canvas.cget("width"))-58))
            ty=max(10,e.y-10)
            self.canvas.create_text(
                tx,ty,text=self.fmt_temp(temp),fill="#f4f5f7",
                anchor="w",font=("Segoe UI",7),tags="hover_temp"
            )

    def on_leave(self,_):
        self.hover_text.set("Move the pointer over the thermal image")
        self.canvas.delete("hover_temp")

    def add_point(self,e):
        bx,by=self.canvas_to_image(e.x,e.y)
        sx,sy=self.base_canvas_to_sensor(bx,by)
        x,y=int(sx),int(sy)
        if not(0<=x<VIEW_W and 0<=y<VIEW_H):return
        colors=["#ffe45e","#4dd6ff","#ff72d2","#82ff72","#ff9b54","#b69cff","#ffffff","#55ffd3"]
        self.points.append({
            "name":f"P{self.next_point}","x":x,"y":y,
            "color":colors[(self.next_point-1)%len(colors)],
            "history":deque(maxlen=self.history_max_samples),
            "graph":True
        }); self.next_point+=1
        # Seed only the newly created point. Calling update_points() here would
        # duplicate the automatic MAX and every existing point at the same frame.
        p=self.points[-1]
        v=self.filter_graph_sample(p["name"],self.sample_temp(p["x"],p["y"]))
        if v is not None and not self.playback_mode:p["history"].append((time.time(),v))
        self.request_recording_analysis()
        self.refresh_point_list()
        self.point_list.selection_clear(0,"end")
        self.point_list.selection_set(1+len(self.points)-1)
        self.graph_selected_series=p["name"]
        self.render(); self.request_graph_redraw(force=True)
    def remove_nearest(self,e):
        if not self.points:return
        bx,by=self.canvas_to_image(e.x,e.y)
        sx,sy=self.base_canvas_to_sensor(bx,by)
        x,y=int(sx),int(sy)
        i=min(range(len(self.points)),key=lambda n:(self.points[n]["x"]-x)**2+(self.points[n]["y"]-y)**2)
        if (self.points[i]["x"]-x)**2+(self.points[i]["y"]-y)**2<=100:
            removed_name=self.points[i]["name"]
            del self.points[i]
            self.request_recording_analysis()
            if self.graph_selected_series==removed_name:
                self.graph_selected_series="MAX"
            self.refresh_point_list(); self.render(); self.request_graph_redraw(force=True)
    def clear_points(self):
        self.points.clear()
        self.request_recording_analysis()
        self.graph_selected_series="MAX"
        self.refresh_point_list()
        self.graph_dirty=True
        self.draw_graph(force=True)
        self.render()

    def graph_window_seconds(self):
        return self.graph_windows[self.graph_window_index]

    @staticmethod
    def format_span(seconds):
        seconds=max(0,int(round(seconds)))
        h,rem=divmod(seconds,3600); m,s=divmod(rem,60)
        if h:return f"{h}h {m:02d}m {s:02d}s"
        if m:return f"{m}m {s:02d}s"
        return f"{s}s"

    def request_graph_redraw(self,force=False):
        self.graph_dirty=True
        if force:self.draw_graph(force=True)

    def toggle_graph_pause(self):
        self.graph.delete("graph_hover"); self.graph_hover_stamp=None
        if self.graph_paused:
            self.resume_graph_live()
        else:
            self.graph_paused=True
            state=self.graph_render_state
            self.graph_paused_page_start=state["t0"] if state else None
            self.graph_pause_anchor=time.time()
            self.graph_pause_button.configure(text="▶ Play graph")
            self.graph_range_text.set(self.graph_range_text.get().replace(" • paused","") + " • paused")
            self.status.set("Graph view paused; measurements continue in the background")
            self.draw_graph(force=True)

    def resume_graph_live(self):
        self.graph.delete("graph_hover"); self.graph_hover_stamp=None
        self.graph_paused=False
        self.graph_pause_anchor=None
        self.graph_paused_page_start=None
        self.graph_view_t0_override=None
        self.graph_y_pan_c=0.0
        self.graph_pause_button.configure(text="⏸ Pause graph")
        if self.playback_mode:
            self.graph_view_t0_override=max(self.recording_session['start'],self.playback_time-self.graph_window_seconds()/2)
            self.request_recording_analysis()
        self.graph_dirty=True
        self.draw_graph(force=True)

    def zoom_graph(self,direction):
        # Backward-compatible centered zoom.
        self.zoom_graph_at(direction,None)

    def zoom_graph_at(self,direction,cursor_x=None):
        state=self.graph_render_state
        old_span=float(self.graph_window_seconds())
        old_t0=state["t0"] if state else None

        self.graph_window_index=int(clamp(
            self.graph_window_index+direction,0,len(self.graph_windows)-1
        ))
        new_span=float(self.graph_window_seconds())

        label=f"{int(new_span)//60} min" if new_span>=60 else f"{int(new_span)} s"
        if new_span>=3600:label=f"{new_span/3600:g} h"
        self.graph_range_text.set(
            f"History: {label}" + (" • paused" if self.graph_paused else "")
        )

        if state and old_t0 is not None:
            ml,mr,w=state["ml"],state["mr"],state["w"]
            if cursor_x is None:
                frac=0.5
            else:
                frac=clamp((cursor_x-ml)/max(1,w-ml-mr),0.0,1.0)
            anchor=old_t0+frac*old_span
            self.graph_view_t0_override=anchor-frac*new_span
            if self.graph_paused:
                self.graph_paused_page_start=self.graph_view_t0_override

        self.schedule_save_viewer_settings()
        self.draw_graph(force=True)

    def _graph_page_start(self, latest_stamp, span):
        """Return a fixed timeline page start so the trace grows left-to-right."""
        if self.graph_origin is None:
            self.graph_origin=latest_stamp
        if self.graph_paused and self.graph_paused_page_start is not None:
            return self.graph_paused_page_start
        elapsed=max(0.0,latest_stamp-self.graph_origin)
        page_index=int(elapsed//span)
        return self.graph_origin+page_index*span

    @staticmethod
    def _draw_dashed_polyline(draw,coords,fill,width=2,dash=7,gap=5):
        if len(coords)<2:
            return
        for (x1,y1),(x2,y2) in zip(coords,coords[1:]):
            dx=x2-x1; dy=y2-y1
            dist=math.hypot(dx,dy)
            if dist<=0:
                continue
            ux=dx/dist; uy=dy/dist
            pos=0.0
            while pos<dist:
                end=min(dist,pos+dash)
                draw.line((x1+ux*pos,y1+uy*pos,x1+ux*end,y1+uy*end),
                          fill=fill,width=width)
                pos=end+gap

    def graph_series_by_name(self,name,state=None):
        state=state or self.graph_render_state or {}
        for s in state.get("series",[]):
            if s.get("name")==name:
                return s
        return None

    def update_graph_detail(self,series=None):
        if series is None:
            series=self.graph_series_by_name(self.graph_selected_series)
        if not series or not series.get("data"):
            self.graph_detail_text.set(f"Selected: {self.graph_selected_series} • no data in this view")
            return

        vals=[v for _,v in series["data"] if math.isfinite(v)]
        if not vals:
            self.graph_detail_text.set(f"Selected: {series['name']} • no valid data")
            return

        latest=vals[-1]
        minimum=min(vals); maximum=max(vals)
        average=statistics.fmean(vals)
        delta=latest-vals[0] if len(vals)>1 else 0.0

        extra=""
        if series.get("auto_hot"):
            extra=f" • X {series['x']} Y {series['y']}"
        else:
            p=next((p for p in self.points if p["name"]==series["name"]),None)
            if p is not None:
                extra=f" • X {p['x']} Y {p['y']}"

        self.graph_detail_text.set(
            f"Selected: {series['name']}{extra}   •   "
            f"Now {self.fmt_temp(latest)}   •   "
            f"Min {self.fmt_temp(minimum)}   •   "
            f"Max {self.fmt_temp(maximum)}   •   "
            f"Avg {self.fmt_temp(average)}   •   "
            f"Δ {self.fmt_delta(delta)}"
        )

    @staticmethod
    def _point_segment_distance(px,py,x1,y1,x2,y2):
        vx=x2-x1; vy=y2-y1
        wx=px-x1; wy=py-y1
        vv=vx*vx+vy*vy
        if vv<=1e-12:
            return math.hypot(px-x1,py-y1)
        t=max(0.0,min(1.0,(wx*vx+wy*vy)/vv))
        qx=x1+t*vx; qy=y1+t*vy
        return math.hypot(px-qx,py-qy)

    def select_graph_series(self,name):
        self.graph_selected_series=name
        self.update_graph_detail()
        self.request_graph_redraw(force=True)

    def _select_graph_series_at(self,e):
        state=self.graph_render_state
        if not state:return

        for box in state.get("legend_boxes",[]):
            x0,y0,x1,y1,name=box
            if x0<=e.x<=x1 and y0<=e.y<=y1:
                self.select_graph_series(name)
                return

        best=None
        for s in state.get("series",[]):
            coords=s.get("coords",[])
            if len(coords)==1:
                dist=math.hypot(e.x-coords[0][0],e.y-coords[0][1])
            elif len(coords)>=2:
                dist=min(
                    self._point_segment_distance(
                        e.x,e.y,
                        coords[i][0],coords[i][1],
                        coords[i+1][0],coords[i+1][1]
                    )
                    for i in range(len(coords)-1)
                )
            else:
                continue
            if best is None or dist<best[0]:
                best=(dist,s["name"])
        if best:self.select_graph_series(best[1])

    def on_graph_press(self,e):
        state=self.graph_render_state
        self.graph_dragging=False
        if not state:
            self.graph_drag_start=None
            return
        self.graph_drag_start={
            "x":e.x,"y":e.y,
            "t0":state["t0"],
            "y_pan":self.graph_y_pan_c,
            "span":state["t1"]-state["t0"],
            "ymin":state["ymin"],"ymax":state["ymax"],
            "w":state["w"],"h":state["h"],
            "ml":state["ml"],"mr":state["mr"],
            "mt":state["mt"],"mb":state["mb"],
        }

    def on_graph_drag(self,e):
        st=self.graph_drag_start
        if not st:return
        dx=e.x-st["x"]; dy=e.y-st["y"]
        if not self.graph_dragging and math.hypot(dx,dy)<self.graph_drag_threshold:
            return
        self.graph_dragging=True

        plot_w=max(1,st["w"]-st["ml"]-st["mr"])
        plot_h=max(1,st["h"]-st["mt"]-st["mb"])
        seconds_per_px=st["span"]/plot_w
        degrees_per_px=(st["ymax"]-st["ymin"])/plot_h

        # "Grab" interaction: drag right -> older time comes into view;
        # drag down -> traces move down with the pointer.
        self.graph_view_t0_override=st["t0"]-dx*seconds_per_px
        self.graph_y_pan_c=st["y_pan"]+dy*degrees_per_px
        if self.graph_paused:
            self.graph_paused_page_start=self.graph_view_t0_override

        self.graph_dirty=True
        self.draw_graph(force=True)

    def on_graph_release(self,e):
        if not self.graph_drag_start:
            return
        was_drag=self.graph_dragging
        self.graph_drag_start=None
        self.graph_dragging=False
        if not was_drag:
            self._select_graph_series_at(e)

    def remove_periodic_graph_pattern(self,data,period=75.0):
        """Remove only the repeating ~75 s graph pattern.

        The raw/DVR history is untouched.  We learn a phase-locked additive
        template from several cycles and subtract that template only for display.

        Steps:
          1) estimate a slow local trend with a robust moving median,
          2) fold residuals into 1-second phase bins over a 75 s period,
          3) take the median residual in each phase bin across cycles,
          4) remove the template DC component,
          5) subtract the learned phase template from the graph samples.

        Non-repeating thermal events do not reinforce at the same phase and
        therefore mostly disappear from the median template.
        """
        if len(data) < 30:
            return data

        pts=[(float(t),float(v)) for t,v in data if math.isfinite(v)]
        if len(pts)<30:
            return data

        duration=pts[-1][0]-pts[0][0]
        # Need at least ~3 complete repetitions before learning anything.
        if duration < period*2.8:
            return pts

        # Estimate cadence for a reasonable trend window.
        dts=[pts[i][0]-pts[i-1][0] for i in range(1,len(pts))
             if 0 < pts[i][0]-pts[i-1][0] < 5.0]
        cadence=statistics.median(dts) if dts else 0.33
        cadence=max(0.05,min(2.0,cadence))

        # A ~25 s robust trend window is deliberately much slower than the
        # sharp FFC-like waveform but still follows genuine long-term drift.
        half_window=max(3,int(round(12.5/cadence)))

        times=[t for t,_ in pts]
        values=[v for _,v in pts]
        trend=[0.0]*len(pts)

        # Maintain the same median window incrementally instead of sorting
        # an overlapping window for every historical sample on every redraw.
        window=[]
        window_a=window_b=0
        for i in range(len(pts)):
            a=max(0,i-half_window)
            b=min(len(pts),i+half_window+1)
            while window_b<b:
                bisect.insort(window,values[window_b]); window_b+=1
            while window_a<a:
                del window[bisect.bisect_left(window,values[window_a])]; window_a+=1
            middle=len(window)//2
            trend[i]=(window[middle] if len(window)%2 else
                      (window[middle-1]+window[middle])/2)

        residual=[values[i]-trend[i] for i in range(len(pts))]

        # 1-second phase bins are plenty at ~3 FPS and avoid overfitting noise.
        bin_width=1.0
        bins=max(8,int(round(period/bin_width)))
        phase_bins=[[] for _ in range(bins)]
        origin=times[0]

        for t,r in zip(times,residual):
            phase=(t-origin)%period
            idx=min(bins-1,int(phase/bin_width))
            phase_bins[idx].append(r)

        # Need repeated support for most bins. Sparse bins are interpolated.
        template=[None]*bins
        supported=0
        for i,vals in enumerate(phase_bins):
            if len(vals)>=3:
                template[i]=statistics.median(vals)
                supported+=1

        if supported < int(bins*0.60):
            return pts

        # Circular interpolation across unsupported bins.
        known=[i for i,v in enumerate(template) if v is not None]
        if len(known)<4:
            return pts

        for i in range(bins):
            if template[i] is not None:
                continue
            left=None
            right=None
            for step in range(1,bins+1):
                j=(i-step)%bins
                if template[j] is not None:
                    left=j; break
            for step in range(1,bins+1):
                j=(i+step)%bins
                if template[j] is not None:
                    right=j; break
            if left is None or right is None:
                template[i]=0.0
            elif left==right:
                template[i]=template[left]
            else:
                dl=(i-left)%bins
                dr=(right-i)%bins
                frac=dl/max(1,dl+dr)
                template[i]=template[left]*(1-frac)+template[right]*frac

        # Remove DC so the correction changes shape, not absolute level.
        dc=statistics.median(template)
        template=[v-dc for v in template]

        # Conservative amplitude clamp: we only want to remove the recurring
        # wiggle, never multi-degree real events.
        template=[max(-1.5,min(1.5,v)) for v in template]

        corrected=[]
        for t,v in pts:
            phase=(t-origin)%period
            pos=phase/bin_width
            i0=int(pos)%bins
            i1=(i0+1)%bins
            f=pos-int(pos)
            corr=template[i0]*(1-f)+template[i1]*f
            corrected.append((t,v-corr))

        return corrected

    def draw_graph(self,force=False):
        self.request_recording_analysis()
        if self.graph_paused and not force:return
        now_mono=time.monotonic()
        if not force and (not self.graph_dirty or now_mono-self.graph_last_draw<0.20):return
        self.graph_dirty=False; self.graph_last_draw=now_mono
        g=self.graph; g.update_idletasks()
        g.delete("graph_hover"); self.graph_hover_stamp=None
        w,h=max(380,g.winfo_width()),max(200,g.winfo_height())
        ml,mr,mt,mb=52,14,20,32
        img=Image.new("RGB",(w,h),(13,20,30)); d=ImageDraw.Draw(img)
        d.line((ml,mt,ml,h-mb),fill=(80,103,119))
        d.line((ml,h-mb,w-mr,h-mb),fill=(80,103,119))

        series=[]
        if self.max_point.get("graph",True):
            data=[(t,v) for t,v in self.max_point["history"] if math.isfinite(v)]
            if data:
                series.append({
                    "name":"MAX","color":self.max_point["color"],"data":data,
                    "dashed":True,"auto_hot":True,
                    "x":self.max_point["x"],"y":self.max_point["y"]
                })

        for p in self.points:
            if p.get("graph",True):
                pdata=[(t,v) for t,v in p["history"] if math.isfinite(v)]
                if pdata:
                    series.append({"name":p["name"],"color":p["color"],"data":pdata,"dashed":False})

        if not series:
            d.text((w//2-88,h//2-6),"Waiting for thermal graph data…",fill=(102,112,128))
            self.graph_render_state=None
        else:
            span=float(self.graph_window_seconds())
            latest=self.playback_time if self.playback_mode else max(s["data"][-1][0] for s in series)

            if self.graph_view_t0_override is not None:
                t0=float(self.graph_view_t0_override)
                # Do not let a live zoom/pan window get stranded forever while
                # new samples move beyond it.
                if (not self.playback_mode and not self.graph_paused and
                        (latest < t0-0.001 or latest > t0+span+0.001)):
                    self.graph_view_t0_override=None
                    self.graph_y_pan_c=0.0
                    t0=self._graph_page_start(latest,span)
            else:
                t0=self._graph_page_start(latest,span)

            def collect_visible(view_t0):
                view_t1=view_t0+span
                vis=[]; yvals=[]
                for s in series:
                    cleaned_full=s['data'] if self.playback_mode else self.remove_periodic_graph_pattern(s["data"],75.0)
                    data=[(t,v) for t,v in cleaned_full if view_t0<=t<=view_t1]
                    if data:
                        ns=dict(s); ns["data"]=data
                        vis.append(ns)
                        yvals.extend(v for _,v in data)
                return view_t1,vis,yvals

            t1,visible,vals=collect_visible(t0)

            if not vals and not self.graph_paused and not self.playback_mode:
                # Hard recovery for any stale timeline state: if live samples
                # exist, the live graph must display them.
                self.graph_view_t0_override=None
                self.graph_y_pan_c=0.0
                self.graph_origin=latest
                t0=latest
                t1,visible,vals=collect_visible(t0)
                if len(vals)<=1:
                    earliest=min(s["data"][0][0] for s in series)
                    t0=max(earliest,latest-span)
                    t1,visible,vals=collect_visible(t0)

            if not vals:
                d.text((w//2-82,h//2-6),"Waiting for samples in this view…",fill=(102,112,128))
                self.graph_render_state=None
            else:
                ymin,ymax=min(vals),max(vals)
                pad=max(.5,(ymax-ymin)*.12)
                ymin-=pad; ymax+=pad
                if self.graph_y_pan_c:
                    ymin+=self.graph_y_pan_c
                    ymax+=self.graph_y_pan_c
                yr=max(1e-9,ymax-ymin)

                for n in range(5):
                    y=mt+n*(h-mt-mb)/4
                    val=ymax-n*(ymax-ymin)/4
                    d.line((ml,y,w-mr,y),fill=(38,53,69))
                    d.text((4,y-6),f"{self.shown_temp(val):.1f}",fill=(152,173,185))

                render_series=[]
                legend_x=ml
                legend_boxes=[]
                for s in visible:
                    coords=[]
                    for stamp,v in s["data"]:
                        x=ml+(stamp-t0)/span*(w-ml-mr)
                        y=mt+(ymax-v)/yr*(h-mt-mb)
                        coords.append((x,y))

                    selected=(s["name"]==self.graph_selected_series)
                    line_width=2 if selected else 1
                    if len(coords)==1:
                        x0,y0=coords[0]
                        d.ellipse((x0-2,y0-2,x0+2,y0+2),fill=s["color"])
                    elif s["dashed"]:
                        self._draw_dashed_polyline(
                            d,coords,fill=s["color"],width=line_width,dash=7,gap=5
                        )
                    elif len(coords)>=2:
                        d.line(coords,fill=s["color"],width=line_width)

                    render_series.append({**s,"coords":coords})
                    label=f'{s["name"]} {self.fmt_temp(s["data"][-1][1])}'
                    label_w=max(78,len(label)*7+14)
                    if selected:
                        d.rectangle(
                            (legend_x-4,1,legend_x+label_w-4,17),
                            outline=(95,103,116)
                        )
                    d.text((legend_x,4),label,fill=s["color"])
                    legend_boxes.append((legend_x-5,0,legend_x+label_w,20,s["name"]))
                    legend_x+=label_w+8

                marker_stamp=min(max(latest,t0),t1)
                marker_x=ml+(marker_stamp-t0)/span*(w-ml-mr)
                d.line((marker_x,mt,marker_x,h-mb),fill=(70,75,84),width=1)

                d.text((ml,h-20),dt.datetime.fromtimestamp(t0).strftime("%H:%M:%S"),fill=(146,154,170))
                end_label=dt.datetime.fromtimestamp(t1).strftime("%H:%M:%S")
                d.text((w-mr-52,h-20),end_label,fill=(146,154,170))
                elapsed=max(0.0,min(span,latest-t0))
                page_label=(dt.datetime.fromtimestamp(t0).strftime('%Y-%m-%d') if self.playback_mode else f"{self.format_span(elapsed)} / {self.format_span(span)}")
                d.text((max(ml,w//2-35),h-20),page_label,fill=(120,128,140))

                self.graph_render_state={
                    "series":render_series,"legend_boxes":legend_boxes,
                    "t0":t0,"t1":t1,
                    "ml":ml,"mr":mr,"mt":mt,"mb":mb,
                    "w":w,"h":h,"ymin":ymin,"ymax":ymax,"latest":latest
                }
                self.update_graph_detail()

        self.graph_photo=ImageTk.PhotoImage(img)
        g.itemconfigure(self.graph_image_id,image=self.graph_photo)
        g.tag_lower(self.graph_image_id)

    def on_graph_wheel(self,e):
        if getattr(e,"delta",0)>0:
            self.zoom_graph_at(-1,e.x)
        elif getattr(e,"delta",0)<0:
            self.zoom_graph_at(+1,e.x)
        return "break"

    def on_graph_motion(self,e):
        if self.graph_dragging:
            return
        state=self.graph_render_state
        if not state:return
        ml,mr,w=state["ml"],state["mr"],state["w"]
        if e.x<ml or e.x>w-mr:
            return self.on_graph_leave(None)

        t=state["t0"]+(e.x-ml)/max(1,w-ml-mr)*(state["t1"]-state["t0"])

        # Hover follows only the currently selected series.  All richer
        # statistics stay in the detail row below the graph.
        series=self.graph_series_by_name(self.graph_selected_series,state)
        if series is None:
            candidates=[s for s in state.get("series",[]) if s.get("data")]
            if not candidates:
                return self.on_graph_leave(None)
            series=candidates[0]

        data=series.get("data",[])
        if not data:
            return self.on_graph_leave(None)

        stamps=[row[0] for row in data]
        i=bisect.bisect_left(stamps,t)
        if i<=0:i=0
        elif i>=len(data):i=len(data)-1
        elif abs(stamps[i-1]-t)<=abs(stamps[i]-t):i-=1

        stamp,temp=data[i]
        self.graph_hover_stamp=stamp
        x=ml+(stamp-state["t0"])/max(.001,state["t1"]-state["t0"])*(w-ml-mr)
        y=state["mt"]+(state["ymax"]-temp)/max(1e-9,state["ymax"]-state["ymin"])*(state["h"]-state["mt"]-state["mb"])

        self.graph.delete("graph_hover")
        self.graph.create_line(x,state['mt'],x,state['h']-state['mb'],fill='#d8e8ef',dash=(3,3),tags='graph_hover')
        self.graph.create_oval(
            x-2,y-2,x+2,y+2,
            fill=series["color"],outline="",tags="graph_hover"
        )
        tx=min(max(state["ml"]+4,x+7),state["w"]-160)
        ty=max(state["mt"]+4,y-14)
        self.graph.create_text(
            tx,ty,
            text=f'{self.fmt_temp(temp)}\n{timestamp_label(stamp)}\n{age_label(stamp)}',
            fill=series["color"],
            anchor="nw",
            font=("Segoe UI",8),
            tags="graph_hover"
        )

    def on_graph_leave(self,_):
        # Intentionally keep the last graph tooltip visible. It is replaced
        # only when the pointer selects another sample or the graph page changes.
        pass

    def toggle_freeze(self):
        if self.playback_mode:
            self.return_to_live(); return
        self.frozen=not self.frozen
        self.freeze_button.configure(text="▶ Resume image" if self.frozen else "⏸ Freeze image")
        self.status.set("Thermal image frozen" if self.frozen else "Live stream")
    def snapshot(self):
        if not self.rendered_image:messagebox.showinfo("FLIR","No image is available yet."); return
        name=f'FLIR_{dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.png'; path=filedialog.asksaveasfilename(initialfile=name,initialdir=str(CAPTURE_DIR),defaultextension=".png",filetypes=[("PNG image","*.png")])
        if not path:return
        try:self.rendered_image.save(path,"PNG"); self.status.set(f"PNG saved: {pathlib.Path(path).name}")
        except OSError as exc:messagebox.showerror("FLIR",str(exc))
    def toggle_record(self):
        if self.recording:
            self.recording=False
            self.record_text.set("● Start logging")
            if self.csv_file:self.csv_file.close()
            self.csv_file=None; self.csv_writer=None; self.csv_series_names=[]
            self.status.set("Temperature logging stopped")
            return
        path=CAPTURE_DIR/f'temperature_{dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.csv'
        self.csv_file=path.open("w",newline="",encoding="utf-8-sig")
        self.csv_writer=csv.writer(self.csv_file,delimiter=";")
        # Freeze the CSV schema for the whole recording. Points created/deleted
        # mid-recording cannot shift the columns under existing data.
        live_points=self._live_analysis['points'] if self.playback_mode and self._live_analysis else self.points
        self.csv_series_names=["MAX"]+[p["name"] for p in live_points]
        self.csv_writer.writerow(["Timestamp","Elapsed (s)"]+[f'{name} (°C)' for name in self.csv_series_names])
        self.record_start=time.time(); self.recording=True
        self.record_text.set("■ Stop logging")
        self.status.set(f"CSV logging: {path.name}")

    def write_csv(self,stamp):
        if not self.csv_writer:return
        values=[]
        for name in self.csv_series_names:
            if name=="MAX":
                hist=self.max_point["history"]
            else:
                p=next((p for p in self.points if p["name"]==name),None)
                hist=p["history"] if p is not None else None
            values.append(f'{hist[-1][1]:.3f}' if hist else "")
        self.csv_writer.writerow([
            dt.datetime.fromtimestamp(stamp).isoformat(timespec="milliseconds"),
            f"{stamp-self.record_start:.3f}",*values
        ])
        self.csv_file.flush()

    def refresh(self):
        refresh_started=time.perf_counter()
        rendered_age_ms=None
        try:
            while True:
                line=self.messages.get_nowait()
                if "LIVE frame=" in line:self.status.set(line.split("] ",1)[-1])
                elif "Disconnected/error" in line:self.status.set("Disconnected; reconnecting automatically…")
                elif "CONFIG SESSION ALIVE" in line or "polling EP85" in line:self.status.set("Connected; waiting for thermal frames…")
                elif "Connected" in line:self.status.set("USB found; establishing iAP2 session…")
        except queue.Empty:pass
        try:
            stat=LIVE_RAW.stat()
            stream_mtime=stat.st_mtime_ns
            if stream_mtime!=self.stream_mtime:
                self.stream_mtime=stream_mtime
                if stat.st_mtime>=self.capture_start_wall-0.25:
                    self.capture_has_streamed=True
                    self.last_live_monotonic=time.monotonic()
        except OSError:pass

        try:
            mtime=LIVE_RAW.stat().st_mtime_ns
            if mtime!=self.last_mtime:
                blob=LIVE_RAW.read_bytes()
                self.last_mtime=mtime
                if len(blob)==38400:
                    accepted,guard_reason=self.frame_is_acceptable(blob)
                    if not accepted:
                        # Rejected frames do NOT enter display, point histories,
                        # CSV, scene_samples or the RAW DVR.
                        self.status.set(guard_reason)
                    else:
                        now=time.time(); self.frame_times.append(now)
                        cutoff=now-self.fps_window_seconds
                        while self.frame_times and self.frame_times[0]<cutoff:
                            self.frame_times.popleft()
                        if self.should_archive_frame(now):
                            self.queue_dvr_frame(now,blob)
                        if not self.playback_mode:
                            if self.load_raw_blob(blob,update_background=True):
                                # MAX history starts automatically on the very
                                # first accepted frame, before any manual point.
                                self.update_points(now)
                                self.queue_dvr_measurements(
                                    now,
                                    max_info=(self.max_point["x"],self.max_point["y"],
                                              self.max_point["history"][-1][1] if self.max_point["history"] else float("nan"))
                                )
                                if not self.frozen:
                                    self.render()
                                    rendered_age_ms=max(0.0,(time.time()-mtime/1e9)*1000)
                        else:
                            # Keep the archived frame authoritative in the UI,
                            # while still recording live scene/MAX/manual data.
                            self.archive_live_measurements_from_blob(now,blob)
                if len(self.frame_times)>1:
                    extra=""
                    try:
                        state=json.loads(LIVE_STATUS.read_text(encoding="utf-8")); bv=state.get("batteryVoltageUpdate",{}); bs=state.get("batteryChargingStateUpdate",{}).get("chargingState","")
                        pct=bv.get("percentage"); charging="charging" if bs!="stateNoCharging" else "not charging"
                        extra=f" • Battery {pct}% • {charging}" if pct is not None else f" • {charging}"
                    except (OSError,json.JSONDecodeError):pass
                    self.load_visual()
                    self.update_archive_size_label()
                    suppressed=self.frame_guard_rejected+self.graph_transient_rejected
                    if suppressed:
                        self.dvr_time_var.set(
                            f"Continuous archive: active  •  {suppressed} transient sample(s) suppressed"
                        )
                    self.status.set(f"{self.current_live_fps():.1f} FPS{extra}")
        except OSError:pass

        self.update_visible_controls()
        # Cheap disk_usage + SQLite aggregate only; never recursively scan DVR here.
        self.check_storage_health()
        if not self.graph_paused:
            self.draw_graph()

        if not self.external_capture:
            now_mono=time.monotonic()
            if self.process is not None and self.process.poll() is not None:
                code=self.process.returncode
                self.process=None; self.capture_has_streamed=False
                self.next_capture_restart=now_mono+0.5
                self.status.set(f"Capture exited (code {code}); restarting automatically…")
            elif self.process is not None and self.capture_has_streamed and now_mono-self.last_live_monotonic>20.0:
                self.restart_capture("Stream stalled; renewing USB session automatically…")
            if self.process is None and now_mono>=self.next_capture_restart:
                try:self.start_capture(); self.status.set("Capture restarted; looking for camera…")
                except OSError as exc:self.next_capture_restart=now_mono+2.; self.status.set(f"Could not start capture: {exc}")
        if rendered_age_ms is not None:
            if not hasattr(self,"_latency_samples"):
                self._latency_samples=deque(maxlen=90)
                self._last_performance_report=0.0
            self._latency_samples.append((rendered_age_ms,(time.perf_counter()-refresh_started)*1000))
            if time.monotonic()-self._last_performance_report>=2.0:
                self._last_performance_report=time.monotonic()
                samples=list(self._latency_samples)
                try:
                    (ROOT/"outputs"/"flir-performance.json").write_text(json.dumps({
                        "updated":time.time(),"viewer_fps":self.current_live_fps(),
                        "samples":len(samples),
                        "file_to_render_median_ms":statistics.median(s[0] for s in samples),
                        "file_to_render_max_ms":max(s[0] for s in samples),
                        "refresh_median_ms":statistics.median(s[1] for s in samples),
                        "note":"Host file publication to Tk image submission; excludes sensor/USB/display latency"
                    }),encoding="utf-8")
                except OSError:pass
        self.root.after(5,self.refresh)

    def close(self):
        self.close_playback()
        self.save_viewer_settings()
        self.save_storage_settings()
        if self.csv_file:self.csv_file.close()
        self.playback_running=False
        if self.playback_after_id:
            try:self.root.after_cancel(self.playback_after_id)
            except Exception:pass
        if self.process is not None and self.process.poll() is None:self.process.terminate()
        self.dvr_stop.set()
        try:self.dvr_thread.join(timeout=3.0)
        except Exception:pass
        self.root.destroy()
    def run(self):self.root.mainloop()

if __name__=="__main__":Viewer().run()
