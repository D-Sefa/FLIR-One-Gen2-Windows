"""Read-only RAW archive access and a date-organized recording gallery.

No USB access, device commands, schema migrations or archive writes live here.
All worker results are delivered to Tk on its owning thread.
"""
from __future__ import annotations
import calendar
import datetime as dt
import math
import pathlib
import sqlite3
import struct
import tkinter as tk
import zlib
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from tkinter import ttk
import numpy as np
from PIL import Image, ImageTk

HEADER = struct.Struct('<4sQII')


def date_bounds(first='', last=''):
    start = dt.date.fromisoformat(first) if first else dt.date.min
    end = dt.date.fromisoformat(last) if last else dt.date.max
    if end < start:
        raise ValueError('End date must not be before start date.')
    return start, end


def timestamp_label(stamp):
    return dt.datetime.fromtimestamp(stamp).strftime('%Y-%m-%d %H:%M:%S')


def age_label(stamp, now=None):
    now = dt.datetime.now().timestamp() if now is None else now
    seconds = max(0, int(now-stamp))
    h, seconds = divmod(seconds, 3600)
    m, s = divmod(seconds, 60)
    return f'{h}h {m}m {s}s ago'


def temperatures(raw, settings):
    """Same legacy radiometry as Viewer.raw_to_c; not a new calibration."""
    e, tr, offset = settings
    e = max(.01, min(1., e))
    with np.errstate(over='ignore', divide='ignore', invalid='ignore'):
        reflected = 16528.178/(.012258549*(np.exp(1427.5/(tr+273.15))-1.0))+1307.0
        obj = (np.asarray(raw, dtype=np.float64)*4-(1-e)*reflected)/e
        lg = 16528.178/(.012258549*(obj-1307.0)+1.0)
        return np.where(lg > 1, 1427.5/np.log(lg)-273.15+offset, np.nan)


class ArchiveStore:
    def __init__(self, folder, database=None):
        self.folder = pathlib.Path(folder).resolve()
        self.database = pathlib.Path(database or self.folder/'history.sqlite3')

    @contextmanager
    def connect(self):
        con=sqlite3.connect(self.database.resolve().as_uri()+'?mode=ro', uri=True, timeout=3)
        try:yield con
        finally:con.close()

    def sessions(self, first='', last='', gap=12.):
        start_date, end_date = date_bounds(first, last)
        # Range predicates allow SQLite's timestamp index to exclude other days.
        low = dt.datetime.combine(start_date, dt.time()).timestamp() if first else -1e30
        high = dt.datetime.combine(end_date+dt.timedelta(days=1), dt.time()).timestamp() if last and end_date<dt.date.max else 1e30
        result = []
        with self.connect() as con:
            for (stamp,) in con.execute('SELECT ts FROM frames WHERE ts>=? AND ts<? ORDER BY ts', (low,high)):
                stamp = float(stamp)
                day = dt.datetime.fromtimestamp(stamp).date().isoformat()
                if not result or stamp-result[-1]['end']>gap or day!=result[-1]['date']:
                    result.append(dict(start=stamp,end=stamp,count=1,date=day))
                else:
                    result[-1]['end']=stamp; result[-1]['count']+=1
        return result

    def read(self, row):
        if row is None:return None
        stamp, rel, offset, raw_size, comp_size = row
        try:
            path=(self.folder/rel).resolve()
            if not path.is_relative_to(self.folder) or raw_size!=38400 or not 0<comp_size<=40000:return None
            with path.open('rb') as f:
                f.seek(offset)
                magic, ns, rs, cs = HEADER.unpack(f.read(HEADER.size))
                if magic!=b'F1D1' or rs!=raw_size or cs!=comp_size or abs(ns/1e9-stamp)>.001:return None
                compressed=f.read(cs)
            decompressor=zlib.decompressobj()
            blob=decompressor.decompress(compressed,38401)
            if len(blob)!=38400 or not decompressor.eof:return None
            return float(stamp), blob
        except (OSError,ValueError,zlib.error,struct.error):return None

    def nearest(self, stamp, start=-1e30, end=1e30):
        with self.connect() as con:
            columns='ts,file,offset,raw_size,comp_size'
            before=con.execute(f'SELECT {columns} FROM frames WHERE ts<=? AND ts>=? AND ts<=? ORDER BY ts DESC LIMIT 1',(stamp,start,end)).fetchone()
            after=con.execute(f'SELECT {columns} FROM frames WHERE ts>=? AND ts>=? AND ts<=? ORDER BY ts LIMIT 1',(stamp,start,end)).fetchone()
        rows=[row for row in (before,after) if row]
        return self.read(min(rows,key=lambda row:abs(row[0]-stamp))) if rows else None

    def at_time(self, stamp, tolerance=1.):
        hit=self.nearest(stamp)
        return hit if hit and abs(hit[0]-stamp)<=tolerance else None

    def next_stamp(self, stamp, end):
        with self.connect() as con:
            row=con.execute('SELECT ts FROM frames WHERE ts>? AND ts<=? ORDER BY ts LIMIT 1',(stamp,end)).fetchone()
        return float(row[0]) if row else None

    def analyze(self, start, end, points, settings, average, cancelled=None):
        series={name:[] for name,_,_ in points}; series['MAX']=[]
        indices={}
        radius=1 if average else 0
        for name,x,y in points:
            indices[name]=[xx*160+159-yy for yy in range(max(0,y-radius),min(160,y+radius+1))
                           for xx in range(max(0,x-radius),min(120,x+radius+1))]
        with self.connect() as con:
            rows=con.execute('SELECT ts,file,offset,raw_size,comp_size FROM frames WHERE ts>=? AND ts<=? ORDER BY ts',(start,end))
            for row in rows:
                if cancelled and cancelled.is_set():return None
                hit=self.read(row)
                if not hit:continue
                stamp,blob=hit
                values=temperatures(np.frombuffer(blob,dtype='<u2'),settings)
                valid=values[np.isfinite(values)]
                if valid.size:series['MAX'].append((stamp,float(valid.max())))
                for name,idx in indices.items():
                    vals=values[idx]; vals=vals[np.isfinite(vals)]
                    if vals.size:series[name].append((stamp,float(vals.mean())))
        return series

    def thumbnail(self, session):
        hit=self.nearest(session['start'],session['start'],session['end'])
        if not hit:return None
        values=np.rot90(np.frombuffer(hit[1],dtype='<u2').reshape(120,160))
        lo,hi=np.percentile(values,(2,98)); span=max(1.,hi-lo)
        gray=np.clip((values-lo)*255/span,0,255).astype(np.uint8)
        # Fixed thumbnail palette: previews do not alter the active viewer mapper.
        stops=np.array([[0,0,10],[13,0,118],[72,0,150],[170,28,92],[238,92,18],[255,205,45],[255,255,255]])
        lut=np.stack([np.interp(np.arange(256),np.linspace(0,255,len(stops)),stops[:,c]) for c in range(3)],axis=1).astype(np.uint8)
        im=Image.fromarray(lut[gray]); im.thumbnail((174,180))
        return im


class GalleryWindow:
    PAGE_SIZE=24

    def __init__(self, viewer):
        self.viewer=viewer
        self.store=ArchiveStore(viewer.dvr_dir,viewer.dvr_db)
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='flir-gallery')
        self.closed=False; self.generation=0; self.page=0; self.sessions=[]; self.photos=[]
        self.window=tk.Toplevel(viewer.root); self.window.title('Recordings — FLIR ONE')
        self.window.geometry('940x720'); self.window.minsize(680,480); self.window.configure(bg='#050609')
        self.window.protocol('WM_DELETE_WINDOW',self.hide)
        top=ttk.Frame(self.window); top.pack(fill='x',padx=16,pady=12)
        ttk.Label(top,text='Recordings',font=('Segoe UI',18,'bold')).pack(side='left')
        ttk.Button(top,text='Live camera',command=self.live).pack(side='right')
        filters=ttk.Frame(self.window); filters.pack(fill='x',padx=16)
        self.first=tk.StringVar(); self.last=tk.StringVar(); self.seek_text=tk.StringVar()
        for label,var in (('From',self.first),('To',self.last)):
            ttk.Label(filters,text=label).pack(side='left',padx=(0,4))
            ttk.Entry(filters,textvariable=var,width=11).pack(side='left')
            ttk.Button(filters,text='Calendar',command=lambda v=var:self.calendar(v),width=9).pack(side='left',padx=(3,12))
        ttk.Button(filters,text='Apply',command=self.reload).pack(side='left')
        ttk.Button(filters,text='All dates',command=self.all_dates).pack(side='left',padx=6)
        jump=ttk.Frame(self.window); jump.pack(fill='x',padx=16,pady=8)
        ttk.Label(jump,text='Go to date / time').pack(side='left',padx=(0,8))
        ttk.Entry(jump,textvariable=self.seek_text,width=23).pack(side='left')
        ttk.Button(jump,text='Go',command=self.go_to_time).pack(side='left',padx=6)
        ttk.Label(jump,text='YYYY-MM-DD HH:MM:SS  •  local time').pack(side='left')
        self.message=tk.StringVar(value='Loading recordings…')
        ttk.Label(self.window,textvariable=self.message).pack(fill='x',padx=16,pady=(0,8))
        body=ttk.Frame(self.window); body.pack(fill='both',expand=True,padx=16)
        self.canvas=tk.Canvas(body,bg='#050609',highlightthickness=0)
        scroll=ttk.Scrollbar(body,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set); scroll.pack(side='right',fill='y'); self.canvas.pack(fill='both',expand=True)
        self.cards=ttk.Frame(self.canvas); self.cards_id=self.canvas.create_window(0,0,window=self.cards,anchor='nw')
        self.cards.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.cards_id,width=e.width))
        self.window.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-3 if e.delta>0 else 3,'units'))
        bottom=ttk.Frame(self.window); bottom.pack(fill='x',padx=16,pady=10)
        ttk.Button(bottom,text='‹ Newer',command=lambda:self.change_page(-1)).pack(side='left')
        self.page_label=ttk.Label(bottom); self.page_label.pack(side='left',padx=10)
        ttk.Button(bottom,text='Older ›',command=lambda:self.change_page(1)).pack(side='left')
        ttk.Button(bottom,text='Refresh',command=self.reload).pack(side='right')
        self.reload()

    def hide(self):self.window.withdraw()

    def live(self):self.viewer.return_to_live(); self.hide()

    def show(self):
        self.window.deiconify(); self.window.lift(); self.reload()

    def all_dates(self):self.first.set(''); self.last.set(''); self.reload()

    def reload(self):
        try:date_bounds(self.first.get(),self.last.get())
        except ValueError as exc:self.message.set(f'Invalid date range: {exc}'); return
        self.generation+=1; generation=self.generation
        self.message.set('Loading recordings…')
        self._poll(self.pool.submit(self.store.sessions,self.first.get(),self.last.get()),generation,self._loaded)

    def _poll(self,future,generation,callback):
        if self.closed or generation!=self.generation:return
        if not future.done():
            self.window.after(40,lambda:self._poll(future,generation,callback)); return
        try:result=future.result()
        except Exception as exc:self.message.set(f'Could not read recording: {exc}'); return
        callback(result)

    def _loaded(self,sessions):
        self.sessions=list(reversed(sessions)); self.page=0; self.draw_cards()

    def change_page(self,delta):
        self.page=max(0,min(max(0,(len(self.sessions)-1)//self.PAGE_SIZE),self.page+delta)); self.draw_cards()

    def draw_cards(self):
        for child in self.cards.winfo_children():child.destroy()
        self.photos=[]; self.generation+=1; generation=self.generation
        self.canvas.yview_moveto(0)
        subset=self.sessions[self.page*self.PAGE_SIZE:(self.page+1)*self.PAGE_SIZE]
        self.message.set(f'{len(self.sessions)} recordings • click a preview to analyze RAW data' if subset else 'No recordings in this date range.')
        self.page_label.configure(text=f'{self.page+1} / {max(1,math.ceil(len(self.sessions)/self.PAGE_SIZE))}')
        row=0; col=0; day=None
        for session in subset:
            if session['date']!=day:
                if col:row+=1; col=0
                day=session['date']
                ttk.Label(self.cards,text=day,font=('Segoe UI',13,'bold')).grid(row=row,column=0,columnspan=3,sticky='w',pady=(14,8)); row+=1
            card=ttk.Frame(self.cards,padding=8); card.grid(row=row,column=col,sticky='nsew',padx=5,pady=5)
            preview=tk.Label(card,text='Loading…',bg='#111923',fg='#98adb9',width=23,height=10,cursor='hand2')
            preview.pack(fill='both')
            start=dt.datetime.fromtimestamp(session['start']).strftime('%H:%M:%S')
            end=dt.datetime.fromtimestamp(session['end']).strftime('%H:%M:%S')
            label=ttk.Label(card,text=f'{start} – {end}\n{self.viewer.format_span(session["end"]-session["start"])} • {session["count"]} frames',cursor='hand2')
            label.pack(pady=(6,0))
            for widget in (card,preview,label):widget.bind('<Button-1>',lambda e,s=session:self.open(s))
            self._poll(self.pool.submit(self.store.thumbnail,session),generation,lambda im,w=preview:self._thumbnail(w,im))
            col+=1
            if col==3:row+=1; col=0
        for c in range(3):self.cards.columnconfigure(c,weight=1,uniform='cards')

    def _thumbnail(self,widget,im):
        if im is None:widget.configure(text='Preview unavailable'); return
        photo=ImageTk.PhotoImage(im); self.photos.append(photo)
        widget.configure(image=photo,text='',width=174,height=180)

    def open(self,session,stamp=None):
        self.viewer.open_recording(session,stamp)
        self.hide(); self.viewer.root.deiconify(); self.viewer.root.lift()

    def go_to_time(self):
        try:stamp=dt.datetime.fromisoformat(self.seek_text.get().strip()).timestamp()
        except ValueError:self.message.set('Enter YYYY-MM-DD HH:MM:SS.'); return
        generation=self.generation
        def found(hit):
            if hit is None:self.message.set('No recorded frame at that time (within 1 second).'); return
            day=dt.datetime.fromtimestamp(hit[0]).date().isoformat()
            def opened(sessions):
                session=next((s for s in sessions if s['start']<=hit[0]<=s['end']),None)
                if session:self.open(session,hit[0])
            self._poll(self.pool.submit(self.store.sessions,day,day),generation,opened)
        self._poll(self.pool.submit(self.store.at_time,stamp),generation,found)

    def calendar(self,target):
        win=tk.Toplevel(self.window); win.title('Choose date'); win.resizable(False,False)
        try:chosen=dt.date.fromisoformat(target.get())
        except ValueError:chosen=dt.date.today()
        state=[chosen.year,chosen.month]
        heading=ttk.Frame(win); heading.pack(fill='x',padx=8,pady=8)
        title=ttk.Label(heading,width=20,anchor='center')
        grid=ttk.Frame(win); grid.pack(padx=8,pady=8)
        def choose(day):target.set(dt.date(*state,day).isoformat()); win.destroy()
        def draw(delta=0):
            month=state[0]*12+state[1]-1+delta; state[:]=[month//12,month%12+1]
            title.configure(text=f'{calendar.month_name[state[1]]} {state[0]}')
            for child in grid.winfo_children():child.destroy()
            for i,name in enumerate(('Mo','Tu','We','Th','Fr','Sa','Su')):ttk.Label(grid,text=name,anchor='center').grid(row=0,column=i)
            for r,week in enumerate(calendar.monthcalendar(*state),1):
                for c,day in enumerate(week):
                    if day:ttk.Button(grid,text=str(day),width=4,command=lambda d=day:choose(d)).grid(row=r,column=c,padx=1,pady=1)
        ttk.Button(heading,text='‹',width=3,command=lambda:draw(-1)).pack(side='left'); title.pack(side='left')
        ttk.Button(heading,text='›',width=3,command=lambda:draw(1)).pack(side='left'); draw()

    def close(self):
        self.closed=True; self.generation+=1; self.pool.shutdown(wait=False,cancel_futures=True)
        try:self.window.destroy()
        except tk.TclError:pass
