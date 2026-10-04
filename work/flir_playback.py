"""Viewer recording controls. Shares rendering, keeps live/analysis histories separate."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import threading
import time
import tkinter as tk
from tkinter import ttk
from flir_gallery import ArchiveStore, GalleryWindow, timestamp_label


class PlaybackMixin:
    def init_playback(self):
        self.gallery=None; self.recording_session=None; self._live_analysis=None
        self._analysis_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='flir-analysis')
        self._analysis_cancel=threading.Event(); self._analysis_generation=0
        self._analysis_key=None; self._analysis_after=None; self._seek_after=None
        self._player_after=None; self._player_running=False; self._closed=False
        self._playback_skipped=0
        self.player_status=tk.StringVar(value='Live camera')
        self.player_speed=tk.StringVar(value='1×')
        self.player_position=tk.DoubleVar(value=0.)

    def build_playback_controls(self,parent):
        nav=ttk.Frame(parent); nav.pack(fill='x',pady=(0,6))
        ttk.Button(nav,text='● Live',command=self.return_to_live).pack(side='left')
        ttk.Button(nav,text='▦ Recordings',command=self.open_history_window).pack(side='left',padx=6)
        self.player_label=ttk.Label(nav,textvariable=self.player_status,font=('Segoe UI',9))
        self.player_label.pack(side='left',padx=4)
        self.player_bar=ttk.Frame(parent)
        buttons=ttk.Frame(self.player_bar); buttons.pack(fill='x')
        ttk.Button(buttons,text='‹ Previous',command=lambda:self.adjacent_recording(-1)).pack(side='left')
        self.player_button=ttk.Button(buttons,text='▶ Play',command=self.toggle_playback); self.player_button.pack(side='left',padx=5)
        ttk.Button(buttons,text='Next ›',command=lambda:self.adjacent_recording(1)).pack(side='left')
        speed=ttk.Combobox(buttons,textvariable=self.player_speed,values=('0.25×','0.5×','1×','2×','4×'),state='readonly',width=6)
        speed.pack(side='left',padx=5); speed.bind('<<ComboboxSelected>>',self.playback_speed_changed)
        ttk.Button(buttons,text='☆ Keep',command=self.keep_recording).pack(side='right')
        self.player_scale=ttk.Scale(self.player_bar,variable=self.player_position,from_=0,to=1,command=self.seek_recording)
        self.player_scale.pack(fill='x',pady=(3,6))
        self._player_parent=parent

    def archive_store(self):return ArchiveStore(self.dvr_dir,self.dvr_db)

    def open_gallery(self):
        if self.gallery is None or self.gallery.closed:self.gallery=GalleryWindow(self)
        else:
            self.gallery.store=self.archive_store(); self.gallery.show()

    def open_recording(self,session,stamp=None):
        hit=self.archive_store().nearest(session['start'] if stamp is None else stamp,session['start'],session['end'])
        if not hit:self.player_status.set('Recording missing or damaged'); return
        self.stop_playback()
        if not self.playback_mode:
            names=('points','max_point','next_point','graph_origin','graph_view_t0_override','graph_paused',
                   'graph_pause_anchor','graph_paused_page_start','graph_y_pan_c','graph_selected_series','graph_filter_state')
            self._live_analysis={name:getattr(self,name) for name in names}
            self._live_radiometry=tuple(v.get() for v in (self.emissivity_var,self.reflected_var,self.temp_offset_var))
            self._live_average=self.smooth_var.get()
            self.points=[]; self.next_point=1
            self.max_point={**self.max_point,'history':deque(),'x':0,'y':0}
            self.graph_filter_state={}; self.graph_selected_series='MAX'
        self.recording_session=dict(session); self.playback_mode=True; self.frozen=True
        self.graph_origin=session['start']; self.graph_view_t0_override=session['start']
        self.graph_paused=False; self.graph_paused_page_start=None; self.graph_y_pan_c=0.
        self.graph_pause_button.configure(text='⏸ Pause graph')
        self.player_bar.pack(fill='x',before=self.canvas)
        self.player_scale.configure(to=max(.001,session['end']-session['start']))
        self.freeze_button.configure(text='▶ Return to live')
        self._analysis_key=None
        self.display_recording_frame(*hit)
        self.request_recording_analysis()

    def display_recording_frame(self,stamp,blob):
        if not self.load_raw_blob(blob,update_background=False):return False
        self.playback_time=stamp
        start=self.graph_view_t0_override
        if not self.graph_paused and start is not None and stamp>start+self.graph_window_seconds():
            self.graph_view_t0_override=stamp
            self.request_recording_analysis()
        self.player_position.set(max(0.,stamp-self.recording_session['start']))
        self.player_status.set(timestamp_label(stamp))
        self.status.set('RECORDING • '+timestamp_label(stamp)+' • live capture continues')
        hot=self.hottest_pixel()
        if hot:self.max_point['x'],self.max_point['y'],_=hot
        self.render(); self.refresh_point_list()
        self.graph_dirty=True
        return True

    def stop_playback(self):
        self._player_running=False
        if self._player_after is not None:
            self.root.after_cancel(self._player_after); self._player_after=None
        if self._seek_after is not None:
            self.root.after_cancel(self._seek_after); self._seek_after=None
        if hasattr(self,'player_button'):self.player_button.configure(text='▶ Play')

    def toggle_playback(self):
        if not self.playback_mode:return
        if self._player_running:self.stop_playback(); return
        if self.playback_time>=self.recording_session['end']:
            self.seek_recording_now(self.recording_session['start'])
        self._player_running=True; self.player_button.configure(text='⏸ Pause')
        self._player_wall=time.monotonic(); self._player_stamp=self.playback_time
        self.schedule_playback()

    def playback_speed_changed(self,_=None):
        if self._player_running:
            self.stop_playback(); self.toggle_playback()

    def schedule_playback(self):
        if not self._player_running or self._closed:return
        next_ts=self.archive_store().next_stamp(self.playback_time,self.recording_session['end'])
        if next_ts is None:self.stop_playback(); return
        speed=float(self.player_speed.get().replace('×',''))
        due=self._player_wall+(next_ts-self._player_stamp)/speed
        delay=max(1,int((due-time.monotonic())*1000))
        self._player_after=self.root.after(delay,lambda:self.advance_recording(next_ts))

    def advance_recording(self,stamp):
        self._player_after=None
        if not self._player_running:return
        hit=self.archive_store().nearest(stamp,self.recording_session['start'],self.recording_session['end'])
        if not hit:
            self.stop_playback(); self.player_status.set('Recording missing or damaged'); return
        self.display_recording_frame(*hit); self.schedule_playback()

    def seek_recording(self,value):
        if not self.playback_mode:return
        # Scale callbacks come only from user interaction, not DoubleVar.set().
        self.stop_playback()
        stamp=self.recording_session['start']+float(value)
        self._seek_after=self.root.after(45,lambda:self.seek_recording_now(stamp))

    def seek_recording_now(self,stamp):
        self._seek_after=None
        if not self.playback_mode:return
        hit=self.archive_store().nearest(stamp,self.recording_session['start'],self.recording_session['end'])
        if hit:
            self.display_recording_frame(*hit)
            if not self.graph_paused:
                self.graph_view_t0_override=max(self.recording_session['start'],hit[0]-self.graph_window_seconds()/2)
            self.request_recording_analysis(); self.request_graph_redraw(force=True)

    def adjacent_recording(self,direction):
        if not self.recording_session:return
        selected=self.recording_session['start']
        future=self._analysis_pool.submit(self.archive_store().sessions)
        self.player_status.set('Finding recording…')
        def ready():
            if self._closed or not self.recording_session or self.recording_session['start']!=selected:return
            if not future.done():self.root.after(40,ready); return
            try:sessions=future.result()
            except Exception as exc:self.player_status.set(f'Archive unavailable: {exc}'); return
            index=next((i for i,s in enumerate(sessions) if s['start']==selected),None)
            if index is not None and 0<=index+direction<len(sessions):self.open_recording(sessions[index+direction])
            else:self.player_status.set('No more recordings in this direction')
        ready()

    def keep_recording(self):
        if not self.recording_session:return
        import sqlite3
        s=self.recording_session
        con=sqlite3.connect(self.dvr_db)
        try:
            con.execute('INSERT INTO favorite_ranges(start_ts,end_ts,label) VALUES(?,?,?)',(s['start'],s['end'],'Kept from gallery'))
            con.commit()
        finally:con.close()
        self.player_status.set('★ Recording protected from automatic cleanup')

    def return_to_live(self):
        self.stop_playback()
        self._analysis_cancel.set(); self._analysis_generation+=1; self._analysis_key=None
        if not self.playback_mode:return
        self.playback_mode=False; self.frozen=False
        for var,value in zip((self.emissivity_var,self.reflected_var,self.temp_offset_var),self._live_radiometry):var.set(value)
        self.smooth_var.set(self._live_average)
        if self._live_analysis:
            for name,value in self._live_analysis.items():setattr(self,name,value)
        self._live_analysis=None; self.recording_session=None
        self.player_bar.pack_forget(); self.player_status.set('Live camera')
        self.freeze_button.configure(text='⏸ Freeze image')
        self.graph_pause_button.configure(text='▶ Play graph' if self.graph_paused else '⏸ Pause graph')
        self.visible_image=None
        # Force the next live refresh to consume the current frame, even if frozen.
        self.last_mtime=0
        self.load_raw(); self.render(); self.refresh_point_list(); self.request_graph_redraw(force=True)
        self.status.set('Live stream')

    def request_recording_analysis(self,*_):
        if not self.playback_mode or not self.recording_session or self._closed:return
        try:settings=(float(self.emissivity_var.get()),float(self.reflected_var.get()),float(self.temp_offset_var.get()))
        except ValueError:return
        if not all(__import__('math').isfinite(v) for v in settings):return
        points=tuple((p['name'],p['x'],p['y']) for p in self.points)
        s=self.recording_session
        start=max(s['start'],self.graph_view_t0_override if self.graph_view_t0_override is not None else s['start'])
        end=min(s['end'],start+self.graph_window_seconds())
        key=(s['start'],start,end,points,settings,self.smooth_var.get())
        if key==self._analysis_key:return
        self._analysis_key=key; self._analysis_cancel.set(); self._analysis_cancel=threading.Event()
        self.max_point['history'].clear()
        for p in self.points:p['history'].clear()
        self._analysis_generation+=1; generation=self._analysis_generation
        if self._analysis_after is not None:self.root.after_cancel(self._analysis_after)
        self.graph_detail_text.set('Analyzing saved RAW frames… live recording continues')
        # Debounce repeated edits and drags; only the latest requested view is read.
        self._analysis_after=self.root.after(150,lambda:self._start_analysis(generation,key,self._analysis_cancel))

    def _start_analysis(self,generation,key,cancel):
        self._analysis_after=None
        if self._closed or generation!=self._analysis_generation:return
        _,start,end,points,settings,average=key
        future=self._analysis_pool.submit(self.archive_store().analyze,start,end,points,settings,average,cancel)
        self._poll_analysis(future,generation)

    def _poll_analysis(self,future,generation):
        if self._closed or generation!=self._analysis_generation or not self.playback_mode:return
        if not future.done():
            self.root.after(40,lambda:self._poll_analysis(future,generation)); return
        try:series=future.result()
        except Exception as exc:self.graph_detail_text.set(f'Archive analysis failed: {exc}'); return
        if series is None:return
        self.max_point['history']=deque(series['MAX'])
        for p in self.points:p['history']=deque(series.get(p['name'],[]))
        self.refresh_point_list(); self.request_graph_redraw(force=True)

    def close_playback(self):
        self._closed=True; self.stop_playback(); self._analysis_cancel.set()
        self._analysis_pool.shutdown(wait=True,cancel_futures=True)
        if self.gallery:self.gallery.close()
