#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spin Helper – Slots auto + Roulette tools + Autoclicker (manual/auto)
v1.13.0
- Target Calculator embedded as a sub-tab inside Autoclicker (Manual / Automatic / Calculator).
- "Target Calculator…" buttons in Slots/Roulette now navigate to that sub-tab (no popup).
- Preserves all existing behavior and UI flows; no removals of working code.
- Minor fix: corrected sleep jitter in Autoclicker loop.
"""
import os; os.environ.setdefault("TK_SILENCE_DEPRECATION","1")
import sys, time, math, csv, random, threading, re, json, queue, datetime as dt
from dataclasses import dataclass
from typing import Optional, Tuple, List

import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont

import pyautogui
from PIL import Image, ImageChops, ImageStat, ImageTk, ImageOps
import pytesseract
from mss import mss

APP_TITLE="Spin Helper"; VERSION="1.13.0"
CFG_PATH=os.path.expanduser("~/.spin_helper.json")
pyautogui.FAILSAFE=False

SPIN_SAMPLE_BOX=60
PIX_DIFF_READY=8.0
MOTION_RMS_THRESH=3.2
BRIGHT_READY_TOL=0.18
NOTREADY_RMS_HARD=22.0
SPIN_CHANGE_TIMEOUT=25.0
CHANGE_STICK_MS=160
SETTLE_GUARD_SECS=0.60
MIN_VALID_SPIN_MS=2000
MAX_CONSECUTIVE_BLIPS=3
JITTER_PX=2
DELAY_MIN,DELAY_MAX=0.35,0.75
MAX_MOUSE_DRIFT_PX=60
MOUSE_DRIFT_STICK_MS=450

FS_INIT_SAMPLES=5
FS_POLL_SAMPLES=3
FS_SAMPLE_GAP=0.12
FS_MAX_REASONABLE=200
FS_COUNTER_POLL=0.30
FS_EXIT_CLICK_GRACE=1.0
FS_TESS_DIGITS=r"--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
FS_TESS_BANNER=r"--oem 3 --psm 6"

ROUL_BANNER_DEFAULT=(0.15,0.10,0.70,0.12)

LOG_DIR_SLOTS="spin_logs"; LOG_DIR_ROULETTE="roulette_logs"

def ensure_dir(p): os.makedirs(p, exist_ok=True)
def timestamp(): return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _norm_box(*args)->Tuple[int,int,int,int]:
    if len(args)==1 and isinstance(args[0],(tuple,list)): args=tuple(args[0])  # type: ignore
    x1,y1,x2,y2=[int(v) for v in args]
    if x2>x1 and y2>y1: x,y,w,h=x1,y1,x2-x1,y2-y1
    else:               x,y,w,h=x1,y1,x2,y2
    return (x,y,max(1,w),max(1,h))

def grab_region(*box):
    x,y,w,h=_norm_box(*box)
    with mss() as sct:
        shot=sct.grab({"left":x,"top":y,"width":w,"height":h})
    return Image.frombytes("RGB", shot.size, shot.rgb)

def rms_diff(a:Image.Image,b:Image.Image)->float:
    A=a.convert("L"); B=b.convert("L"); diff=ImageChops.difference(A,B); stat=ImageStat.Stat(diff); return stat.mean[0]

def _binarize(img:Image.Image)->Image.Image:
    g=img.convert("L").resize((int(img.width*1.8),int(img.height*1.8)), Image.NEAREST)
    return g.point(lambda p: 255 if p>160 else 0)

def load_cfg()->dict:
    try:
        with open(CFG_PATH,"r",encoding="utf-8") as f: return json.load(f)
    except Exception: return {}
def save_cfg(d:dict):
    try:
        with open(CFG_PATH,"w",encoding="utf-8") as f: json.dump(d,f,indent=2)
    except Exception: pass

@dataclass
class SessionStateSlots:
    spinner_xy: Optional[Tuple[int,int]]=None
    spinner_roi: Optional[Tuple[int,int,int,int]]=None
    spinner_baseline: Optional[Image.Image]=None
    spinner_ready_brightness: Optional[float]=None
    last_spinner_sample: Optional[Image.Image]=None
    last_motion_seen: Optional[float]=None

    fs_counter_roi: Optional[Tuple[int,int,int,int]]=None
    fs_banner_roi: Optional[Tuple[int,int,int,int]]=None
    detect_fs: bool=True
    free_spins_mode: bool=False
    target_spins:int=0
    spin_count:int=0
    running:bool=False; paused:bool=False; abort:bool=False
    log_file_path:str=""
    spin_started_at: Optional[float]=None
    bound_monitor: Optional[dict]=None
    movement_guard_active:bool=False
    mouse_breach_since: Optional[float]=None
    stop_after_current_spin:bool=False

@dataclass
class SessionStateRoulette:
    armed:bool=False
    wager_amount:float=0.0
    target_wager:float=0.0
    explicit_wagers: Optional[int]=None
    wagers_done:int=0
    total_wagered:float=0.0
    click_xy: Optional[Tuple[int,int]]=None
    next_btn_autoclick:bool=False
    autobanner_enabled:bool=False
    autobanner_clicks:int=1
    autobanner_gap:float=0.20
    loop_running:bool=False
    banner_roi: Optional[Tuple[int,int,int,int]]=None
    log_file_path:str=""

# ---------- UI scaffolding (scrollable left so nothing truncates) ----------
class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self.columnconfigure(0, weight=1)
        self.canvas=tk.Canvas(self, highlightthickness=0)
        self.vsb=ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.grid(row=0,column=0,sticky="nsew")
        self.vsb.grid(row=0,column=1,sticky="ns")
        self.rowconfigure(0,weight=1)
        self.inner=ttk.Frame(self.canvas)
        self.inner.columnconfigure(0,weight=1)
        self._win=self.canvas.create_window((0,0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
    def _on_frame_configure(self,_evt=None): self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    def _on_canvas_configure(self,evt): self.canvas.itemconfig(self._win, width=evt.width)

class SpinHelperApp:
    def __init__(self, root: tk.Tk):
        self.root=root; self.root.title(f"{APP_TITLE} v{VERSION}")
        self._cfg=load_cfg(); self.root.geometry(f"{self._cfg.get('w',1120)}x{self._cfg.get('h',820)}+60+60")
        self.root.minsize(860,620); self.root.attributes("-topmost",True)
        self.state_slots=SessionStateSlots(); self.state_roul=SessionStateRoulette()
        self._uiq: "queue.Queue[tuple]"=queue.Queue(); self._after_ids={}; self._closing=False
        self._log_buffer: List[tuple]=[]; self._blip_count=0
        self.ui_font=tkfont.nametofont("TkDefaultFont"); self.text_font=tkfont.nametofont("TkTextFont")
        self._build_ui()
        ensure_dir(LOG_DIR_SLOTS); ensure_dir(LOG_DIR_ROULETTE)
        self._log("Ready. If macOS prompts, allow Accessibility, Input Monitoring, and Screen Recording.")
        self._after("ui_tick",80,self._ui_tick); self._after("drain_uiq",16,self._drain_uiq)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._resize_debounce=None; self.root.bind("<Configure>", self._on_configure)

    # ---------- timer/ui queue ----------
    def _after(self,key,ms,fn):
        if self._closing: return
        def wrap():
            if self._closing: return
            try: fn()
            finally: pass
        aid=self.root.after(ms, wrap); self._after_ids[key]=aid
    def _cancel_all_after(self):
        for aid in list(self._after_ids.values()):
            try: self.root.after_cancel(aid)
            except Exception: pass
        self._after_ids.clear()
    def _ui(self,fn,*a,**kw):
        try: self._uiq.put((fn,a,kw))
        except Exception as e: self._log(f"UI queue error: {e}","warn")
    def _drain_uiq(self):
        try:
            while True:
                fn,a,kw=self._uiq.get_nowait()
                try: fn(*a,**kw)
                except Exception as e: self._log(f"UI task error: {e}","warn")
        except queue.Empty: pass
        self._after("drain_uiq",16,self._drain_uiq)

    def _build_ui(self):
        root=self.root
        root.columnconfigure(0,weight=1); root.rowconfigure(0,weight=1)
        self.paned=ttk.Panedwindow(root, orient="horizontal"); self.paned.grid(row=0,column=0,sticky="nsew")
        self.left_wrap=ScrollableFrame(self.paned); self.left=self.left_wrap.inner; self.left.columnconfigure(0,weight=1)
        self.right=ttk.Frame(self.paned,padding=(8,10,10,10)); self.right.columnconfigure(0,weight=1); self.right.rowconfigure(1,weight=1)
        self.paned.add(self.left_wrap,weight=3); self.paned.add(self.right,weight=2)
        header=ttk.Frame(self.left); header.grid(row=0,column=0,sticky="ew",pady=(6,6)); header.columnconfigure(0,weight=1)
        ttk.Label(header,text=f"{APP_TITLE} v{VERSION}",foreground="#555").grid(row=0,column=0,sticky="e")

        self.nb=ttk.Notebook(self.left); self.nb.grid(row=1,column=0,sticky="nsew"); self.left.rowconfigure(1,weight=1)
        self.slots_tab=ttk.Frame(self.nb); self.roul_tab=ttk.Frame(self.nb); self.clicker_tab=ttk.Frame(self.nb)
        for t in (self.slots_tab,self.roul_tab,self.clicker_tab): t.columnconfigure(0,weight=1)

        self._build_slots_tab(self.slots_tab)
        self._build_roulette_tab(self.roul_tab)
        self._build_autoclicker_tab(self.clicker_tab)

        self.nb.add(self.slots_tab,text="Slots (auto)")
        self.nb.add(self.roul_tab,text="Roulette (manual/auto)")
        self.nb.add(self.clicker_tab,text="Autoclicker")

        ttk.Label(self.right,text="Notification Centre").grid(row=0,column=0,sticky="w")
        self.log_txt=tk.Text(self.right,wrap="word",state="disabled")
        vs=ttk.Scrollbar(self.right,orient="vertical",command=self.log_txt.yview)
        self.log_txt.configure(yscrollcommand=vs.set)
        self.log_txt.grid(row=1,column=0,sticky="nsew",pady=(6,6)); vs.grid(row=1,column=1,sticky="ns",pady=(6,6))
        self.log_txt.tag_configure("action",foreground="#0a7a0a",font=(self.text_font.actual("family"), self.text_font.actual("size"), "bold"))
        self.log_txt.tag_configure("ok",foreground="#0a7a0a")
        self.log_txt.tag_configure("warn",foreground="#cc7a00")
        self.log_txt.tag_configure("err",foreground="#bb2d3b")
        ctrl=ttk.Frame(self.right); ctrl.grid(row=2,column=0,sticky="w")
        ttk.Button(ctrl,text="Clear log",command=self._clear_log).grid(row=0,column=0)

        try:
            sash=self._cfg.get("sash", None)
            if sash is not None: self.root.after(50, lambda: self.paned.sashpos(0, int(sash)))
        except Exception: pass

    def _clear_log(self):
        self.log_txt.config(state="normal"); self.log_txt.delete("1.0","end")
        self.log_txt.insert("end", f"[{timestamp()}] Log cleared.\n", ("ok",)); self.log_txt.config(state="disabled")

    def _log(self,msg,tag=None): 
        self._log_buffer.append((f"[{timestamp()}] {msg}",tag))
    def _flush_log(self):
        if not self._log_buffer: return
        self.log_txt.config(state="normal")
        for line,tag in self._log_buffer:
            if tag: self.log_txt.insert("end", line+"\n", (tag,))
            else:   self.log_txt.insert("end", line+"\n")
            self.log_txt.see("end")
        self._log_buffer.clear(); self.log_txt.config(state="disabled")
    def _ui_tick(self): self._flush_log(); self._after("ui_tick",80,self._ui_tick)

    def _on_configure(self, evt):
        if hasattr(self,"_resize_debounce") and self._resize_debounce:
            try: self.root.after_cancel(self._resize_debounce)
            except Exception: pass
        def save():
            try:
                self._cfg["w"]=self.root.winfo_width(); self._cfg["h"]=self.root.winfo_height()
                try: self._cfg["sash"]=self.paned.sashpos(0)
                except Exception: pass
                save_cfg(self._cfg)
            except Exception: pass
        self._resize_debounce=self.root.after(400, save)

    # ===================== TARGET CALCULATOR (embedded) =====================
    def _open_target_calc(self, mode:str):
        """Navigate to the embedded calculator tab and set apply target."""
        try:
            self.nb.select(self.clicker_tab)
            self.ac_nb.select(self.calc_tab)
            self.calc_apply_var.set(mode)  # "slots" | "roulette" | "autoclicker"
            self._update_calc_labels()
            self._log(f"Calculator opened for {mode}.","ok")
        except Exception:
            pass

    # ===================== SLOTS UI =====================
    def _build_slots_tab(self, parent: ttk.Frame):
        parent.columnconfigure(0,weight=1)
        self.cfg=ttk.Labelframe(parent,text="Configuration"); self.cfg.grid(row=0,column=0,sticky="ew",padx=2,pady=(6,8))
        for i in range(10): self.cfg.columnconfigure(i,weight=1)

        self.mode_var=tk.StringVar(value="standard")
        ttk.Label(self.cfg,text="Mode:").grid(row=0,column=0,sticky="w")
        ttk.Radiobutton(self.cfg,text="Standard",value="standard",variable=self.mode_var,command=self._on_mode_change).grid(row=0,column=1,sticky="w")
        ttk.Radiobutton(self.cfg,text="Free-Spins only",value="fs_only",variable=self.mode_var,command=self._on_mode_change).grid(row=0,column=2,sticky="w")

        ttk.Label(self.cfg,text="No. of spins:").grid(row=1,column=0,sticky="w")
        self.spins_var=tk.StringVar(value="0"); ttk.Entry(self.cfg,textvariable=self.spins_var,width=10).grid(row=1,column=1,sticky="ew")

        ttk.Label(self.cfg,text="£ per spin:").grid(row=1,column=2,sticky="e")
        self.stake_var=tk.StringVar(value=""); ttk.Entry(self.cfg,textvariable=self.stake_var,width=10).grid(row=1,column=3,sticky="ew")

        ttk.Label(self.cfg,text="Total wagering £ (optional):").grid(row=1,column=4,sticky="e")
        self.target_wager_var=tk.StringVar(value=""); ttk.Entry(self.cfg,textvariable=self.target_wager_var,width=12).grid(row=1,column=5,sticky="ew")

        ttk.Button(self.cfg,text="Calc spins",command=self._calc_spins).grid(row=1,column=6,sticky="w")
        ttk.Button(self.cfg,text="Target Calculator…",command=lambda:self._open_target_calc("slots")).grid(row=1,column=7,sticky="w")

        self.fs_toggle_var=tk.BooleanVar(value=True)
        ttk.Checkbutton(self.cfg,text="Detect Free Spins",variable=self.fs_toggle_var,command=self._toggle_fs).grid(row=1,column=8,sticky="e")

        self.pick=ttk.Labelframe(parent,text="Detection & Selection"); self.pick.grid(row=1,column=0,sticky="ew",padx=2,pady=(0,8))
        for i in range(5): self.pick.columnconfigure(i,weight=1)
        ttk.Button(self.pick,text="Capture Spinner",command=self._countdown_capture_spinner).grid(row=0,column=0,sticky="w")
        self.spinner_preview=ttk.Label(self.pick,text="(spinner preview)"); self.spinner_preview.grid(row=0,column=1,sticky="w",padx=(10,0))
        ttk.Button(self.pick,text="Bind to this display",command=self._bind_display_button).grid(row=0,column=2,sticky="w",padx=(10,0))
        ttk.Button(self.pick,text="Select FS Counter ROI",command=lambda:self._pick_two_corner_roi("fs_counter")).grid(row=1,column=0,sticky="w",pady=(6,0))
        ttk.Button(self.pick,text="Select FS Banner ROI", command=lambda:self._pick_two_corner_roi("fs_banner")).grid(row=1,column=1,sticky="w",pady=(6,0))
        self.fs_status=ttk.Label(self.pick,text="FS: counter preferred; banner is fallback")
        self.fs_status.grid(row=1,column=2,columnspan=2,sticky="w",padx=(10,0),pady=(6,0))

        self.run=ttk.Labelframe(parent,text="Run"); self.run.grid(row=2,column=0,sticky="ew",padx=2,pady=(0,8))
        for i in range(5): self.run.columnconfigure(i,weight=1)
        ttk.Label(self.run,text="Spin Count:").grid(row=0,column=0,sticky="w")
        self.count_var=tk.IntVar(value=0)
        ttk.Label(self.run,textvariable=self.count_var,font=("TkDefaultFont",14,"bold")).grid(row=0,column=1,sticky="w",padx=(6,12))
        tk.Button(self.run,text="Reset",command=self._reset_count,bg="#bb2d3b",fg="white",activebackground="#a42734",activeforeground="white",highlightbackground="#bb2d3b",bd=0,relief="raised",padx=12,pady=2).grid(row=0,column=2,sticky="w")
        btns=ttk.Frame(self.run); btns.grid(row=0,column=4,sticky="e")
        ttk.Button(btns,text="Start",command=self.start_slots).grid(row=0,column=0,padx=(0,8))
        ttk.Button(btns,text="Pause (safe)",command=self.pause_slots).grid(row=0,column=1,padx=(0,8))
        ttk.Button(btns,text="Stop",command=self.stop_slots).grid(row=0,column=2)

    # ===================== ROULETTE UI =====================
    def _build_roulette_tab(self, parent: ttk.Frame):
        parent.columnconfigure(0,weight=1)
        cfg=ttk.Labelframe(parent,text="Configuration"); cfg.grid(row=0,column=0,sticky="ew",padx=2,pady=(6,8))
        for i in range(10): cfg.columnconfigure(i,weight=1)
        ttk.Label(cfg,text="£ per wager:").grid(row=0,column=0,sticky="w")
        self.r_amount_var=tk.StringVar(value=""); ttk.Entry(cfg,textvariable=self.r_amount_var,width=10).grid(row=0,column=1,sticky="ew")
        ttk.Label(cfg,text="Target wagering £ (optional):").grid(row=0,column=2,sticky="e")
        self.r_target_var=tk.StringVar(value=""); ttk.Entry(cfg,textvariable=self.r_target_var,width=12).grid(row=0,column=3,sticky="ew")
        ttk.Label(cfg,text="# of wagers (optional):").grid(row=0,column=4,sticky="e")
        self.r_explicit_n_var=tk.StringVar(value=""); ttk.Entry(cfg,textvariable=self.r_explicit_n_var,width=10).grid(row=0,column=5,sticky="ew")
        ttk.Button(cfg,text="Target Calculator…",command=lambda:self._open_target_calc("roulette")).grid(row=0,column=6,sticky="w")

        pick=ttk.Labelframe(parent,text="Selection & Overlay"); pick.grid(row=1,column=0,sticky="ew",padx=2,pady=(0,8))
        for i in range(4): pick.columnconfigure(i,weight=1)
        ttk.Button(pick,text="Capture Wager Button",command=self._roulette_capture_click_point).grid(row=0,column=0,sticky="w")
        self.r_click_preview=ttk.Label(pick,text="(wager button preview)"); self.r_click_preview.grid(row=0,column=1,sticky="w",padx=(10,0))
        ttk.Button(pick,text="Select Betting Banner ROI",command=self._roulette_pick_banner_roi).grid(row=1,column=0,sticky="w",pady=(6,0))
        self.r_banner_status=ttk.Label(pick,text="Banner ROI: default (top green bar)"); self.r_banner_status.grid(row=1,column=1,sticky="w",padx=(10,0))

        ctl=ttk.Labelframe(parent,text="Controls"); ctl.grid(row=2,column=0,sticky="ew",padx=2,pady=(0,8))
        for i in range(6): ctl.columnconfigure(i,weight=1)
        self.r_stats_var=tk.StringVar(value="Wagers done: 0 • Left: 0 • £ remaining: 0.00")
        ttk.Label(ctl,textvariable=self.r_stats_var,font=("TkDefaultFont",12,"bold")).grid(row=0,column=0,columnspan=6,sticky="w",pady=(0,8))
        self.r_autoclick_var=tk.BooleanVar(value=False)
        ttk.Checkbutton(ctl,text="Auto-click on Next Wager (one-shot)",variable=self.r_autoclick_var,command=self._toggle_roul_next_autoclick).grid(row=1,column=0,sticky="w")
        self.r_autobanner_var=tk.BooleanVar(value=False)
        ttk.Checkbutton(ctl,text="Auto-bet while 'Place Your Bets' visible",variable=self.r_autobanner_var).grid(row=2,column=0,sticky="w",pady=(6,0))
        ttk.Label(ctl,text="Chips per wager:").grid(row=2,column=1,sticky="e")
        self.r_chips_per_var=tk.StringVar(value="1"); ttk.Entry(ctl,textvariable=self.r_chips_per_var,width=6).grid(row=2,column=2,sticky="w",padx=(4,8))
        ttk.Label(ctl,text="Click gap (s):").grid(row=2,column=3,sticky="e")
        self.r_gap_var=tk.StringVar(value="0.20"); ttk.Entry(ctl,textvariable=self.r_gap_var,width=6).grid(row=2,column=4,sticky="w",padx=(4,8))
        btns=ttk.Frame(ctl); btns.grid(row=3,column=0,columnspan=6,sticky="w",pady=(6,0))
        ttk.Button(btns,text="Start / Arm",command=self._roulette_arm).grid(row=0,column=0,padx=(0,8))
        ttk.Button(btns,text="Next Wager",command=self._roulette_next).grid(row=0,column=1,padx=(0,8))
        ttk.Button(btns,text="Undo Last",command=self._roulette_undo).grid(row=0,column=2,padx=(0,8))
        ttk.Button(btns,text="Finish",command=self._roulette_finish).grid(row=0,column=3)

    # ===================== AUTCLICKER UI (with sub-tabs) =====================
    def _build_autoclicker_tab(self, parent: ttk.Frame):
        parent.columnconfigure(0,weight=1)

        pick=ttk.Labelframe(parent,text="Pointer Target"); pick.grid(row=0,column=0,sticky="ew",padx=2,pady=(6,8))
        for i in range(4): pick.columnconfigure(i,weight=1)
        ttk.Button(pick,text="Capture Click Point (required)",command=self._countdown_capture_spinner).grid(row=0,column=0,sticky="w")
        self.clicker_preview=ttk.Label(pick,text="(click target preview)"); self.clicker_preview.grid(row=0,column=1,sticky="w",padx=(10,0))
        ttk.Button(pick,text="Bind to this display",command=self._bind_display_button).grid(row=0,column=2,sticky="w",padx=(10,0))
        ttk.Label(pick,text="Uses the same spinner/click point as Slots.").grid(row=1,column=0,columnspan=3,sticky="w",pady=(6,0))

        # Sub-tabs: Manual / Automatic / Calculator
        self.ac_nb=ttk.Notebook(parent); self.ac_nb.grid(row=1,column=0,sticky="nsew",padx=2,pady=(0,8))
        parent.rowconfigure(1,weight=1)
        self.ac_manual_tab=ttk.Frame(self.ac_nb); self.ac_auto_tab=ttk.Frame(self.ac_nb); self.calc_tab=ttk.Frame(self.ac_nb)
        for t in (self.ac_manual_tab,self.ac_auto_tab,self.calc_tab): t.columnconfigure(0,weight=1)
        self.ac_nb.add(self.ac_manual_tab,text="Manual")
        self.ac_nb.add(self.ac_auto_tab,text="Automatic")
        self.ac_nb.add(self.calc_tab,text="Calculator")

        # ---- Manual tab
        manA=ttk.Labelframe(self.ac_manual_tab,text="Targeted manual clicking"); manA.grid(row=0,column=0,sticky="ew",pady=(6,8))
        for i in range(8): manA.columnconfigure(i,weight=1)
        ttk.Label(manA,text="Target clicks:").grid(row=0,column=0,sticky="w")
        self.ck_target_var=tk.IntVar(value=0)
        ttk.Label(manA,textvariable=self.ck_target_var,font=("TkDefaultFont",12,"bold")).grid(row=0,column=1,sticky="w")
        ttk.Label(manA,text="Progress:").grid(row=0,column=2,sticky="e")
        self.ck_progress_var=tk.IntVar(value=0)
        ttk.Label(manA,textvariable=self.ck_progress_var,font=("TkDefaultFont",12,"bold")).grid(row=0,column=3,sticky="w")
        self.ck_click_btn=ttk.Button(manA,text="Click (target)",command=lambda:self._clicker_target_click(self.ck_click_btn))
        self.ck_click_btn.grid(row=0,column=4,sticky="w",padx=(8,8))
        ttk.Button(manA,text="Reset target",command=self._clicker_target_reset).grid(row=0,column=5,sticky="w")
        ttk.Button(manA,text="Open Calculator tab",command=lambda:self._open_target_calc("autoclicker")).grid(row=0,column=6,sticky="w")

        manB=ttk.Labelframe(self.ac_manual_tab,text="Free manual clicking"); manB.grid(row=1,column=0,sticky="ew",pady=(0,8))
        for i in range(8): manB.columnconfigure(i,weight=1)
        ttk.Label(manB,text="Count:").grid(row=0,column=0,sticky="w")
        self.free_count_var=tk.IntVar(value=0); ttk.Label(manB,textvariable=self.free_count_var,font=("TkDefaultFont",12,"bold")).grid(row=0,column=1,sticky="w")
        self.free_click_btn=ttk.Button(manB,text="Click (manual)",command=lambda:self._clicker_free_click(self.free_click_btn))
        self.free_click_btn.grid(row=0,column=2,sticky="w",padx=(8,8))
        ttk.Button(manB,text="Reset",command=self._clicker_free_reset).grid(row=0,column=3,sticky="w")
        ttk.Label(manB,text="Target (optional):").grid(row=0,column=4,sticky="e")
        self.free_target_var=tk.StringVar(value=""); self.free_target_entry=ttk.Entry(manB,textvariable=self.free_target_var,width=8)
        self.free_target_entry.grid(row=0,column=5,sticky="w",padx=(4,12)); self.free_target_var.trace_add("write", lambda *_: self._free_target_changed())

        # ---- Automatic tab
        auto=ttk.Labelframe(self.ac_auto_tab,text="Autoclicker"); auto.grid(row=0,column=0,sticky="ew",pady=(6,8))
        for i in range(8): auto.columnconfigure(i,weight=1)
        ttk.Label(auto,text="Count:").grid(row=0,column=0,sticky="w")
        # reuse free_count_var for auto progress (keeps previous design)
        ttk.Label(auto,textvariable=self.free_count_var,font=("TkDefaultFont",12,"bold")).grid(row=0,column=1,sticky="w")
        ttk.Label(auto,text="Target (optional):").grid(row=0,column=2,sticky="e")
        # reuse free_target_var for auto target as before
        ttk.Entry(auto,textvariable=self.free_target_var,width=8).grid(row=0,column=3,sticky="w",padx=(4,12))
        self.ac_start_btn=ttk.Button(auto,text="Start (auto)",command=self._ac_start)
        self.ac_stop_btn =ttk.Button(auto,text="Stop (auto)",command=self._ac_stop)
        self.ac_start_btn.grid(row=0,column=4,sticky="w"); self.ac_stop_btn.grid(row=0,column=5,sticky="w",padx=(8,0))

        # ---- Calculator sub-tab
        self._build_embedded_calculator(self.calc_tab)

    def _build_embedded_calculator(self, parent: ttk.Frame):
        parent.columnconfigure(0,weight=1)
        frm=ttk.Labelframe(parent,text="Target Calculator"); frm.grid(row=0,column=0,sticky="ew",pady=(6,8))
        for i in range(10): frm.columnconfigure(i,weight=1)

        ttk.Label(frm,text="Amount £ (cash/bonus):").grid(row=0,column=0,sticky="w")
        self.calc_amount=tk.StringVar(value="")
        ttk.Entry(frm,textvariable=self.calc_amount,width=12).grid(row=0,column=1,sticky="w",padx=(4,12))

        ttk.Label(frm,text="Wagering ×:").grid(row=0,column=2,sticky="e")
        self.calc_mult=tk.StringVar(value="")
        ttk.Entry(frm,textvariable=self.calc_mult,width=8).grid(row=0,column=3,sticky="w",padx=(4,12))

        self.calc_unit_lbl=tk.StringVar(value="£ per click:")
        ttk.Label(frm,textvariable=self.calc_unit_lbl).grid(row=0,column=4,sticky="e")
        self.calc_unit=tk.StringVar(value="")
        ttk.Entry(frm,textvariable=self.calc_unit,width=10).grid(row=0,column=5,sticky="w")

        ttk.Separator(frm,orient="horizontal").grid(row=1,column=0,columnspan=10,sticky="ew",pady=(6,6))

        self.calc_total_lbl=tk.StringVar(value="Total to wager £: —")
        self.calc_target_lbl=tk.StringVar(value="Target count: —")
        ttk.Label(frm,textvariable=self.calc_total_lbl,font=("TkDefaultFont",11,"bold")).grid(row=2,column=0,columnspan=3,sticky="w")
        ttk.Label(frm,textvariable=self.calc_target_lbl,font=("TkDefaultFont",11,"bold")).grid(row=2,column=3,columnspan=3,sticky="e")

        # Apply destination
        dest=ttk.Labelframe(parent,text="Apply result to"); dest.grid(row=1,column=0,sticky="ew",pady=(0,8))
        for i in range(8): dest.columnconfigure(i,weight=1)
        self.calc_apply_var=tk.StringVar(value="autoclicker")  # "slots" | "roulette" | "autoclicker"
        ttk.Radiobutton(dest,text="Autoclicker",value="autoclicker",variable=self.calc_apply_var,command=self._update_calc_labels).grid(row=0,column=0,sticky="w")
        ttk.Radiobutton(dest,text="Slots",value="slots",variable=self.calc_apply_var,command=self._update_calc_labels).grid(row=0,column=1,sticky="w")
        ttk.Radiobutton(dest,text="Roulette",value="roulette",variable=self.calc_apply_var,command=self._update_calc_labels).grid(row=0,column=2,sticky="w")

        btns=ttk.Frame(parent); btns.grid(row=2,column=0,sticky="e")
        ttk.Button(btns,text="Compute",command=self._calc_compute).grid(row=0,column=0,padx=(0,8))
        ttk.Button(btns,text="Apply",command=self._calc_apply).grid(row=0,column=1)

        # live compute
        for v in (self.calc_amount,self.calc_mult,self.calc_unit):
            v.trace_add("write", lambda *_: self._calc_compute())

        self._calc_compute(); self._update_calc_labels()

    def _update_calc_labels(self):
        m=self.calc_apply_var.get()
        self.calc_unit_lbl.set({"slots":"£ per spin:","roulette":"£ per wager:","autoclicker":"£ per click:"}[m])

    def _calc_compute(self):
        try:
            amt=float((self.calc_amount.get() or "").strip())
            mult=float((self.calc_mult.get() or "").strip())
            unit=float((self.calc_unit.get() or "").strip())
            if amt<=0 or mult<=0 or unit<=0: raise ValueError
            total=amt*mult
            target=math.ceil(total/unit)
            self.calc_total_lbl.set(f"Total to wager £: {total:.2f}")
            self.calc_target_lbl.set(f"Target count: {target}")
            self._calc_last=(total,target)
        except Exception:
            self.calc_total_lbl.set("Total to wager £: —")
            self.calc_target_lbl.set("Target count: —")
            self._calc_last=None

    def _calc_apply(self):
        if not getattr(self,"_calc_last",None):
            self._log("Calculator: enter valid numbers first.","warn"); return
        total,target=self._calc_last
        mode=self.calc_apply_var.get()
        if mode=="slots":
            try: self.spins_var.set(str(int(target))); self._log(f"Slots: calculated spins = {int(target)} (total £{total:.2f}).","ok")
            except Exception: pass
        elif mode=="roulette":
            try: self.r_explicit_n_var.set(str(int(target))); self._log(f"Roulette: target wagers = {int(target)} (total £{total:.2f}).","ok"); self._update_roul_stats()
            except Exception: pass
        else:
            try: self.ck_target_var.set(int(target)); self.ck_progress_var.set(0); self._log(f"Autoclicker: target clicks = {int(target)} (total £{total:.2f}).","ok")
            except Exception: pass

    # ---------- shared capture/bind ----------
    def _virtual_bounds(self)->Tuple[int,int,int,int]:
        try:
            if self.state_slots.bound_monitor is not None:
                m=self.state_slots.bound_monitor; return m["left"],m["top"],m["width"],m["height"]
            with mss() as sct:
                m=sct.monitors[0]; return m["left"],m["top"],m["width"],m["height"]
        except Exception:
            sw,sh=pyautogui.size(); return 0,0,sw,sh
    def _bind_monitor_from_cursor(self):
        x,y=pyautogui.position()
        try:
            with mss() as sct:
                chosen=None
                for m in sct.monitors[1:]:
                    if m["left"]<=x<m["left"]+m["width"] and m["top"]<=y<m["top"]+m["height"]:
                        chosen=m; break
                self.state_slots.bound_monitor=chosen or sct.monitors[0]
                if chosen: self._log(f"Bound scans to display at {chosen['left']},{chosen['top']} {chosen['width']}x{chosen['height']}.","ok")
                else:      self._log("Bound scans to virtual desktop (all displays).","ok")
        except Exception as e: self._log(f"Bind monitor failed: {e}","warn")
    def _bind_display_button(self): self._countdown("Binding to this display",3,self._bind_monitor_from_cursor)
    def _countdown(self,label,secs,on_done):
        def tick(n):
            if n==0: on_done(); return
            self._log(f"{label} in {n}…","action"); self.root.after(1000, lambda: tick(n-1))
        tick(secs)
    def _countdown_capture_spinner(self):
        self._bind_monitor_from_cursor()
        self._countdown("Capturing spinner",3,self._capture_spinner_from_cursor)
    def _capture_spinner_from_cursor(self):
        try:
            x,y=pyautogui.position(); half=SPIN_SAMPLE_BOX//2; roi=(x-half,y-half,SPIN_SAMPLE_BOX,SPIN_SAMPLE_BOX)
            img=grab_region(roi); s=self.state_slots; s.spinner_xy=(x,y); s.spinner_roi=roi; s.spinner_baseline=img
            s.spinner_ready_brightness=ImageStat.Stat(img.convert("L")).mean[0]
            s.last_spinner_sample=None; s.last_motion_seen=None; s.mouse_breach_since=None; s.stop_after_current_spin=False; s.movement_guard_active=False
            self._log(f"Spinner captured at XY=({x},{y}).","ok")
            tkimg=ImageTk.PhotoImage(img.resize((80,80)))
            for lab in ("spinner_preview","clicker_preview","r_click_preview"):
                try:
                    lbl=getattr(self,lab); 
                    if lbl and isinstance(lbl, ttk.Label): 
                        lbl.configure(image=tkimg); lbl.image=tkimg
                except Exception: pass
        except Exception as ex: self._log(f"Spinner capture failed: {ex}","err")

    # ---------- ROI pickers ----------
    def _pick_two_corner_roi(self,which:str):
        title={"fs_counter":"Free-Spins Counter ROI","fs_banner":"Free-Spins Banner ROI"}[which]
        def after_tl():
            x1,y1=pyautogui.position(); self._log(f"{title}: TOP-LEFT captured at ({x1},{y1}).","ok")
            self._countdown(f"{title}: move to BOTTOM-RIGHT. Capturing",3,lambda: after_br(x1,y1))
        def after_br(x1,y1):
            x2,y2=pyautogui.position()
            if x2<=x1 or y2<=y1: self._log("Invalid region (bottom-right must be larger).","warn"); return
            roi=(x1,y1,x2-x1,y2-y1)
            if which=="fs_counter": self.state_slots.fs_counter_roi=roi; self._ui(self.fs_status.config,text="FS: counter ROI set (preferred)")
            else: self.state_slots.fs_banner_roi=roi; self._ui(self.fs_status.config,text="FS: banner ROI set (fallback)")
            self._log(f"{title} set: {roi}","ok")
        self._countdown(f"{title}: move mouse to TOP-LEFT. Capturing",3,after_tl)

    # ---------- spinner readiness ----------
    def _measure_spinner(self)->Tuple[float,float,float]:
        s=self.state_slots; cur=grab_region(s.spinner_roi)  # type: ignore
        diff=rms_diff(cur, s.spinner_baseline)  # type: ignore
        bright=ImageStat.Stat(cur.convert("L")).mean[0]
        motion=0.0 if s.last_spinner_sample is None else rms_diff(cur, s.last_spinner_sample)
        s.last_spinner_sample=cur; return diff, bright, motion
    def _is_ready(self)->bool:
        s=self.state_slots
        if not s.spinner_baseline: return False
        diff, bright, motion=self._measure_spinner()
        b0=s.spinner_ready_brightness or 200.0; rel_dark=(b0 - bright)/max(1.0,b0)
        if diff<=PIX_DIFF_READY and rel_dark<=BRIGHT_READY_TOL and motion<MOTION_RMS_THRESH: return True
        if diff>=NOTREADY_RMS_HARD and motion<MOTION_RMS_THRESH*0.8: return False
        return (motion<2.0 and rel_dark<=0.22 and diff<=12.0)
    def _wait_change_sticky(self, min_stick_ms:int, timeout:float)->bool:
        t0=time.time(); changed_at=None
        while time.time()-t0<timeout:
            if self._check_mouse_drift_sticky(): self.state_slots.stop_after_current_spin=True
            if not self._is_ready():
                if changed_at is None: changed_at=time.time()
                elif (time.time()-changed_at)*1000.0>=min_stick_ms: return True
            else: changed_at=None
            time.sleep(0.04)
        return False
    def _wait_until_ready(self, timeout:float)->bool:
        t0=time.time()
        while time.time()-t0<timeout:
            if self._is_ready(): return True
            time.sleep(0.06)
        return False
    def _guard_settle_ready(self, seconds:float)->bool:
        t0=time.time()
        while time.time()-t0<seconds:
            if not self._is_ready(): return False
            time.sleep(0.08)
        return True
    def _check_mouse_drift_sticky(self)->bool:
        s=self.state_slots
        if not (s.spinner_xy and s.movement_guard_active): return False
        sx,sy=s.spinner_xy; cx,cy=pyautogui.position(); dx=cx-sx; dy=cy-sy
        far=(dx*dx+dy*dy)**0.5>MAX_MOUSE_DRIFT_PX; now=time.time()
        if far:
            if s.mouse_breach_since is None: s.mouse_breach_since=now
            elif (now - s.mouse_breach_since)*1000.0>=MOUSE_DRIFT_STICK_MS:
                if not s.stop_after_current_spin: self._log("Too much mouse movement detected — finishing current spin and pausing.","warn")
                return True
        else: s.mouse_breach_since=None
        return False

    # ---------- FS detection ----------
    def _stable_fs_value(self,samples:int)->Optional[int]:
        s=self.state_slots
        if not (s.detect_fs and s.fs_counter_roi): return None
        vals=[]
        for _ in range(samples):
            try:
                txt=pytesseract.image_to_string(_binarize(grab_region(s.fs_counter_roi)),config=FS_TESS_DIGITS)  # type: ignore
                m=re.search(r"\d+", txt or "");  vals.append(int(m.group(0))) if m else None
            except Exception: pass
            time.sleep(FS_SAMPLE_GAP)
        return sorted(vals)[len(vals)//2] if vals else None
    def _scan_fs_bottom_text(self)->Tuple[bool, Optional[int]]:
        if not self.state_slots.detect_fs: return (False,None)
        try:
            vx,vy,vw,vh=self._virtual_bounds()
            x=vx+int(vw*((1.0-0.60)/2.0)); y=vy+int(vh*(1.0-0.22))
            img=grab_region((x,y,int(vw*0.60),int(vh*0.22)))
            g=img.convert("L").point(lambda p:255 if p>150 else 0)
            txt=(pytesseract.image_to_string(g,config=FS_TESS_BANNER) or "").upper().replace("£"," ")
            m=re.search(r"FREE\s+SPINS\s+LEFT\s+(\d+)", txt)
            if m: return True,int(m.group(1))
            if ("FREE" in txt and "SPINS" in txt): return True,None
            return False,None
        except Exception: return False,None
    def _is_fs_present_quick(self)->bool:
        if not self.state_slots.detect_fs: return False
        try:
            if self.state_slots.fs_counter_roi:
                s=pytesseract.image_to_string(_binarize(grab_region(self.state_slots.fs_counter_roi)),config=FS_TESS_DIGITS)  # type: ignore
                if re.search(r"\d+", s or ""): return True
        except Exception: pass
        present,_=self._scan_fs_bottom_text()
        return present
    def _await_free_spins_end(self)->bool:
        if not self.state_slots.detect_fs: return False
        v=self._stable_fs_value(FS_INIT_SAMPLES)
        if v is not None and 0<=v<=FS_MAX_REASONABLE:
            last=v; self._log(f"Free-Spins counter: {last}")
            while True:
                cur=self._stable_fs_value(FS_POLL_SAMPLES)
                if cur is None: break
                if 0<=cur<=last and cur!=last:
                    self._log(f"Free-Spins progress: {cur} left."); last=cur
                if cur<=0: break
                time.sleep(FS_COUNTER_POLL)
            time.sleep(FS_EXIT_CLICK_GRACE); return True
        present,_=self._scan_fs_bottom_text()
        if present:
            last_seen=time.time()
            while True:
                p,n=self._scan_fs_bottom_text()
                if p:
                    last_seen=time.time()
                    if n is not None: self._log(f"Free-Spins progress: {n} left.")
                    time.sleep(0.5); continue
                if time.time()-last_seen>12: break
                time.sleep(0.4)
            return True
        return False

    # ---------- readiness helpers ----------
    def _rescue_once_then_wait_ready(self, wait_after_click:float=SPIN_CHANGE_TIMEOUT)->bool:
        x,y=self.state_slots.spinner_xy  # type: ignore
        pyautogui.moveTo(x+random.randint(-JITTER_PX,JITTER_PX), y+random.randint(-JITTER_PX,JITTER_PX), duration=0.06)
        pyautogui.click(); self._log("Rescue click #1.")
        if self._is_fs_present_quick():
            if self._await_free_spins_end():
                return self._guard_settle_ready(SETTLE_GUARD_SECS)
        return self._wait_until_ready(wait_after_click)
    def _ensure_ready_before_click(self)->bool:
        if self._wait_until_ready(3.0): return True
        if self._is_fs_present_quick():
            if self._await_free_spins_end():
                return self._guard_settle_ready(SETTLE_GUARD_SECS)
        if self._rescue_once_then_wait_ready(wait_after_click=SPIN_CHANGE_TIMEOUT): return True
        return False

    # ---------- Slots run ----------
    def _on_mode_change(self):
        fs_only=(self.mode_var.get()=="fs_only"); self.state_slots.free_spins_mode=fs_only
        for child in self.cfg.grid_slaves():
            if isinstance(child, ttk.Entry):
                child.configure(state=("disabled" if fs_only else "normal"))
        self._log(f"Mode: {'Free-Spins only' if fs_only else 'Standard'}","ok")
    def _toggle_fs(self):
        self.state_slots.detect_fs=bool(self.fs_toggle_var.get())
        self._log(f"Detect Free Spins: {'ON' if self.state_slots.detect_fs else 'OFF'}", "ok" if self.state_slots.detect_fs else "warn")
    def _calc_spins(self):
        try:
            stake=float(self.stake_var.get()); total=float(self.target_wager_var.get())
            if stake<=0 or total<=0: raise ValueError
            spins=math.ceil(total/stake); self.spins_var.set(str(spins)); self._log(f"Calculated spins = {spins} (from total £{total:.2f} ÷ £{stake:.2f}).","ok")
        except Exception:
            self._log("Enter valid '£ per spin' and 'Total wagering £' or open the Calculator tab.","warn")
    def _reset_count(self):
        s=self.state_slots; s.spin_count=0; s.stop_after_current_spin=False; s.mouse_breach_since=None
        self._ui(self.count_var.set,0); self._log("Spin counter reset.","ok")

    def _open_slots_logfile(self):
        ensure_dir(LOG_DIR_SLOTS); day=dt.datetime.now().strftime("%Y-%m-%d")
        path=os.path.join(LOG_DIR_SLOTS, f"{day}_session.csv")
        if not os.path.exists(path):
            with open(path,"w",newline="",encoding="utf-8") as f: csv.writer(f).writerow(["timestamp","spin_count","x","y","balance"])
        self.state_slots.log_file_path=path; return path

    def start_slots(self):
        s=self.state_slots
        if not (s.spinner_roi and s.spinner_xy and s.spinner_baseline):
            self._log("Please capture the SPINNER first.","warn"); return
        fs_only=(self.mode_var.get()=="fs_only")
        if fs_only:
            try: s.target_spins=int(self.spins_var.get() or "0")
            except Exception: s.target_spins=0
        else:
            try: spins=int(self.spins_var.get() or "0")
            except Exception: spins=0
            if spins<=0:
                try:
                    stake=float(self.stake_var.get()); total=float(self.target_wager_var.get())
                    if stake>0 and total>0: spins=math.ceil(total/stake)
                except Exception: pass
            s.target_spins=max(0,spins)
        self._open_slots_logfile()
        if s.running: self._log("Already running.","warn"); return
        s.running=True; s.paused=False; s.abort=False; s.stop_after_current_spin=False; s.mouse_breach_since=None; s.movement_guard_active=False
        self._log("Starting…","ok"); threading.Thread(target=self._spin_loop,daemon=True).start()

    def pause_slots(self): self.state_slots.abort=True; self._log("PAUSED (will take effect at a safe point).","warn")
    def stop_slots (self): self.state_slots.abort=True; self.state_slots.running=False; self.state_slots.paused=False; self._log("Stopped.","warn")
    def _target_reached(self)->bool:
        t=self.state_slots.target_spins; return t>0 and self.state_slots.spin_count>=t

    def _spin_loop(self):
        s=self.state_slots
        while s.running and not s.abort:
            if self._target_reached():
                self._log(f"Target reached ({s.spin_count}/{s.target_spins}). Stopping.","ok"); break
            if s.stop_after_current_spin:
                self._log("Movement latch is set — pausing safely (won't start a new spin).","warn"); break
            if not self._ensure_ready_before_click():
                self._log("Timeout waiting READY.","warn"); s.paused=True; break
            self._log("Ready confirmed.","ok")
            if self._target_reached() or s.stop_after_current_spin:
                self._log("Safe-check blocked new spin (target reached or movement).","warn"); break
            next_idx=s.spin_count+1; self._log(f"Spin #{next_idx} starting…","action")
            s.spin_started_at=time.time()
            x,y=s.spinner_xy  # type: ignore
            time.sleep(DELAY_MIN + random.random()*(DELAY_MAX-DELAY_MIN))
            pyautogui.moveTo(x+random.randint(-JITTER_PX,JITTER_PX), y+random.randint(-JITTER_PX,JITTER_PX), duration=0.08); pyautogui.click()
            s.movement_guard_active=True
            if not self._wait_change_sticky(CHANGE_STICK_MS, timeout=1.2):
                if not self._rescue_once_then_wait_ready(wait_after_click=3.0):
                    if self._await_free_spins_end():
                        s.movement_guard_active=False; continue
                    self._log("No visual change after click. Pausing.","warn")
                    s.paused=True; s.movement_guard_active=False; break
            t0=time.time()
            while time.time()-t0<SPIN_CHANGE_TIMEOUT:
                if self._is_fs_present_quick():
                    if self._await_free_spins_end(): self._guard_settle_ready(SETTLE_GUARD_SECS); break
                if self._is_ready(): break
                time.sleep(0.20)
            if not self._is_ready():
                if not self._rescue_once_then_wait_ready(wait_after_click=SPIN_CHANGE_TIMEOUT/2):
                    self._log("Did not return to READY. Pausing.","warn"); s.paused=True; s.movement_guard_active=False; break
            dur_ms=int((time.time()-s.spin_started_at)*1000)
            if dur_ms<MIN_VALID_SPIN_MS:
                self._blip_count+=1
                if self._blip_count>=MAX_CONSECUTIVE_BLIPS:
                    self._log("Too many short blips — pausing.","warn"); s.paused=True; self._blip_count=0; s.movement_guard_active=False; break
                self._log(f"Ignored short blip ({dur_ms} ms)."); time.sleep(0.12); s.movement_guard_active=False; continue
            self._blip_count=0
            s.spin_count+=1; self._ui(self.count_var.set,s.spin_count)
            try:
                path=self._open_slots_logfile(); xx,yy=s.spinner_xy  # type: ignore
                with open(path,"a",newline="",encoding="utf-8") as f: csv.writer(f).writerow([timestamp(), s.spin_count, xx, yy, ""])
            except Exception: pass
            self._log(f"Spin #{s.spin_count} complete in {dur_ms} ms.","ok")
            if s.stop_after_current_spin:
                self._log("Paused after finishing spin due to mouse movement.","warn"); s.movement_guard_active=False; break
            if self._target_reached():
                self._log(f"Target reached ({s.spin_count}/{s.target_spins}). Stopping.","ok"); s.movement_guard_active=False; break
            s.movement_guard_active=False
            time.sleep(DELAY_MIN + random.random()*(DELAY_MAX-DELAY_MIN))
        s.running=False; s.paused=False; s.abort=False; self._log("Stopped.")

    # ---------- Roulette logic ----------
    def _roulette_capture_click_point(self):
        self._countdown("Roulette: capture wager button",3,self._roulette_capture_click_now)
    def _roulette_capture_click_now(self):
        self._log("Capturing wager button…","action"); xy=pyautogui.position(); self.state_roul.click_xy=xy; self._log(f"Roulette click point set at {xy}.","ok")
        try:
            half=30; img=grab_region(xy[0]-half,xy[1]-half,xy[0]+half,xy[1]+half)
            tkimg=ImageTk.PhotoImage(img.resize((80,80))); self.r_click_preview.configure(image=tkimg); self.r_click_preview.image=tkimg
        except Exception: pass
    def _roulette_pick_banner_roi(self):
        self._countdown("Banner ROI: move to TOP-LEFT",3,self._roulette_banner_top_left)
    def _roulette_banner_top_left(self):
        x1,y1=pyautogui.position(); self._log(f"Banner ROI top-left at ({x1},{y1}).","ok")
        self._countdown("Now move to BOTTOM-RIGHT",3,lambda:self._roulette_banner_bottom_right(x1,y1))
    def _roulette_banner_bottom_right(self,x1,y1):
        x2,y2=pyautogui.position()
        if x2<=x1 or y2<=y1: self._log("Invalid region.","warn"); return
        self.state_roul.banner_roi=(x1,y1,x2-x1,y2-y1); self._ui(self.r_banner_status.config,text=f"Banner ROI: {self.state_roul.banner_roi}")
        self._log(f"Banner ROI set: {self.state_roul.banner_roi}","ok")
    def _roulette_get_banner_box(self)->Tuple[int,int,int,int]:
        if self.state_roul.banner_roi: return self.state_roul.banner_roi
        vx,vy,vw,vh=self._virtual_bounds(); rx,ry,rw,rh=ROUL_BANNER_DEFAULT
        return (vx+int(vw*rx), vy+int(vh*ry), int(vw*rw), int(vh*rh))
    def _roulette_banner_present(self)->bool:
        x,y,w,h=self._roulette_get_banner_box(); img=grab_region((x,y,w,h)); rgb=img.convert("RGB"); px=rgb.load(); W,H=rgb.size
        greenish=0
        for yy in range(0,H,max(1,H//40)):
            for xx in range(0,W,max(1,W//60)):
                r,g,b=px[xx,yy]
                if g-r>50 and g-b>50 and (r+g+b)>360: greenish+=1
        denom=max(1,(H//max(1,H//40))*(W//max(1,W//60)))
        if greenish/denom>=0.10: return True
        try:
            g=ImageOps.autocontrast(img.convert("L")); txt=(pytesseract.image_to_string(g,config="--oem 3 --psm 6") or "").upper()
            return "PLACE YOUR BETS" in txt
        except Exception: return False
    def _roulette_no_more_bets(self)->bool:
        x,y,w,h=self._roulette_get_banner_box(); img=grab_region((x,y,w,h)).convert("L")
        try:
            txt=(pytesseract.image_to_string(ImageOps.autocontrast(img),config="--oem 3 --psm 6") or "").upper()
            return any(kw in txt for kw in ("NO MORE BETS","BETS APPROVED","BETTING HAS STARTED"))
        except Exception: return False
    def _toggle_roul_next_autoclick(self):
        self.state_roul.next_btn_autoclick=True if self.r_autoclick_var.get() else False
        self._log(f"Manual one-shot autoclick is {'ON' if self.state_roul.next_btn_autoclick else 'OFF'}.","ok")
    def _open_roulette_logfile(self):
        ensure_dir(LOG_DIR_ROULETTE); day=dt.datetime.now().strftime("%Y-%m-%d")
        path=os.path.join(LOG_DIR_ROULETTE, f"{day}_session.csv")
        if not os.path.exists(path):
            with open(path,"w",newline="",encoding="utf-8") as f: csv.writer(f).writerow(["timestamp","wager_index","amount","cumulative_amount","remaining_amount","note"])
        self.state_roul.log_file_path=path; return path
    def _update_roul_stats(self):
        left=self._roul_wagers_left() or 0
        remaining=max(0.0,(self.state_roul.target_wager or 0.0)-self.state_roul.total_wagered)
        self.r_stats_var.set(f"Wagers done: {self.state_roul.wagers_done} • Left: {left} • £ remaining: {remaining:.2f}")
    def _roul_wagers_left(self)->Optional[int]:
        s=self.state_roul
        if s.explicit_wagers: return max(0, s.explicit_wagers - s.wagers_done)
        if s.target_wager>0 and s.wager_amount>0: return max(0, math.ceil(s.target_wager/s.wager_amount) - s.wagers_done)
        return None
    def _roul_reached_goal(self)->bool:
        s=self.state_roul
        if s.explicit_wagers and s.wagers_done>=s.explicit_wagers: return True
        if s.target_wager>0 and s.total_wagered>=s.target_wager: return True
        return False
    def _roulette_arm(self):
        try:
            amt=float(self.r_amount_var.get() or "0")
            tgt=float(self.r_target_var.get() or "0")
            n=int(self.r_explicit_n_var.get()) if (self.r_explicit_n_var.get() or "").strip() else None
            if amt<=0: raise ValueError
            if not n and tgt<=0: raise ValueError
        except Exception:
            self._log("Enter valid Roulette inputs (amount and either target £ or # wagers).","warn"); return
        s=self.state_roul; s.wager_amount=amt; s.target_wager=tgt; s.explicit_wagers=n
        s.wagers_done=0; s.total_wagered=0.0; s.armed=True
        s.autobanner_enabled=bool(self.r_autobanner_var.get())
        try: s.autobanner_clicks=max(1,int(self.r_chips_per_var.get() or "1")); s.autobanner_gap=max(0.05,float(self.r_gap_var.get() or "0.20"))
        except Exception: s.autobanner_clicks, s.autobanner_gap=1,0.20
        self._open_roulette_logfile(); self._update_roul_stats(); self._log("Roulette session armed.","ok")
        if s.autobanner_enabled and s.click_xy:
            self._log("Auto-bet loop enabled (clicks only while 'Place Your Bets' is visible).","ok")
            s.loop_running=True; threading.Thread(target=self._roulette_loop,daemon=True).start()
        elif s.autobanner_enabled and not s.click_xy:
            self._log("Set the wager button first (Capture Wager Button).","warn")
    def _roulette_loop(self):
        s=self.state_roul
        while s.armed and s.loop_running:
            if self._roul_reached_goal(): break
            if not self._roulette_banner_present(): time.sleep(0.20); continue
            if s.click_xy:
                x,y=s.click_xy
                for _ in range(s.autobanner_clicks):
                    pyautogui.moveTo(x,y,duration=0.06); pyautogui.click(); time.sleep(s.autobanner_gap)
            s.wagers_done+=1; s.total_wagered+=s.wager_amount; self._update_roul_stats(); self._log_roulette_row("auto")
            t0=time.time()
            while self._roulette_banner_present() and time.time()-t0<10: time.sleep(0.15)
            if self._roulette_no_more_bets(): time.sleep(0.5)
            if self._roul_reached_goal(): break
        s.loop_running=False
        if self._roul_reached_goal(): self._log("Roulette target reached. Disarming.","ok"); s.armed=False
    def _log_roulette_row(self,note:str):
        try:
            path=self._open_roulette_logfile(); remaining=max(0.0,(self.state_roul.target_wager or 0.0)-self.state_roul.total_wagered)
            with open(path,"a",newline="",encoding="utf-8") as f:
                csv.writer(f).writerow([timestamp(), self.state_roul.wagers_done, f"{self.state_roul.wager_amount:.2f}", f"{self.state_roul.total_wagered:.2f}", f"{remaining:.2f}", note])
        except Exception: pass
    def _roulette_next(self):
        s=self.state_roul
        if not s.armed: self._log("Roulette is not armed. Click 'Start / Arm' first.","warn"); return
        if s.next_btn_autoclick and s.click_xy:
            x,y=s.click_xy; pyautogui.moveTo(x,y,duration=0.06); pyautogui.click()
        s.wagers_done+=1; s.total_wagered+=s.wager_amount; self._update_roul_stats(); self._log_roulette_row("manual")
    def _roulette_undo(self):
        s=self.state_roul
        if s.wagers_done<=0: self._log("Nothing to undo.","warn"); return
        s.wagers_done-=1; s.total_wagered=max(0.0, s.total_wagered - s.wager_amount); self._update_roul_stats(); self._log_roulette_row("undo")
    def _roulette_finish(self):
        s=self.state_roul; s.armed=False; s.loop_running=False; self._log("Roulette session finished.","ok")

    # ---------- Autoclicker logic ----------
    def _click_at_spinner_then_return(self, source_button: tk.Widget)->bool:
        if self.state_slots.running:
            self._log("Stop Slots auto before using the Autoclicker.","warn"); return False
        if not self.state_slots.spinner_xy:
            self._log("Capture Click Point / Spinner first.","warn"); return False
        try:
            bx=source_button.winfo_rootx()+source_button.winfo_width()//2
            by=source_button.winfo_rooty()+source_button.winfo_height()//2
        except Exception:
            bx,by=self.root.winfo_rootx()+40,self.root.winfo_rooty()+40
        sx,sy=self.state_slots.spinner_xy
        pyautogui.moveTo(sx+random.randint(-JITTER_PX,JITTER_PX), sy+random.randint(-JITTER_PX,JITTER_PX), duration=0.06)
        pyautogui.click()
        pyautogui.moveTo(bx,by,duration=0.06)
        return True
    def _clicker_target_click(self, btn: tk.Widget):
        if not self._click_at_spinner_then_return(btn): return
        cur=self.ck_progress_var.get()+1; self.ck_progress_var.set(cur)
        tgt=self.ck_target_var.get()
        self._log(f"Autoclicker (manual/target): shot #{cur}")
        if tgt>0 and cur>=tgt:
            try: self.ck_click_btn.configure(state="disabled")
            except Exception: pass
            self._log("Clicker target reached; button disabled.","ok")
    def _clicker_target_reset(self):
        self.ck_progress_var.set(0)
        if self.ck_target_var.get()>0: self.ck_click_btn.configure(state="normal")
        self._log("Clicker target progress reset.","ok")
    def _free_target_changed(self):
        try: tgt=int(self.free_target_var.get() or "0")
        except Exception: tgt=0
        # Manual free-click button is always enabled; disable only when target achieved
        if tgt==0 or self.free_count_var.get()<tgt:
            try: self.free_click_btn.configure(state="normal")
            except Exception: pass
    def _clicker_free_click(self, btn: tk.Widget):
        if not self._click_at_spinner_then_return(btn): return
        cur=self.free_count_var.get()+1; self.free_count_var.set(cur)
        self._log(f"Autoclicker (manual/free): shot #{cur}")
        try: tgt=int(self.free_target_var.get() or "0")
        except Exception: tgt=0
        if tgt>0 and cur>=tgt:
            try: self.free_click_btn.configure(state="disabled")
            except Exception: pass
            self._log("Free clicker target reached; button disabled.","ok")
    def _clicker_free_reset(self):
        self.free_count_var.set(0)
        try: self.free_click_btn.configure(state="normal")
        except Exception: pass
        self._log("Autoclicker (free) counter reset.","ok")
    def _ac_start(self):
        if self.state_slots.running:
            self._log("Stop Slots auto before using the Autoclicker.","warn"); return
        if not (self.state_slots.spinner_roi and self.state_slots.spinner_xy and self.state_slots.spinner_baseline):
            self._log("Capture the spinner/click point first.","warn"); return
        if getattr(self,"ac_running",False):
            self._log("Autoclicker already running.","warn"); return
        self.ac_running=True; self.ac_abort=False
        self._log("Autoclicker (auto) starting…","ok")
        threading.Thread(target=self._ac_loop,daemon=True).start()
    def _ac_stop(self):
        if not getattr(self,"ac_running",False):
            self._log("Autoclicker is not running.","warn"); return
        self.ac_abort=True; self.ac_running=False
        self._log("Autoclicker (auto) stopped.","warn")
    def _ac_target_reached(self)->bool:
        try: tgt=int(self.free_target_var.get() or "0")
        except Exception: tgt=0
        return (tgt>0 and self.free_count_var.get()>=tgt)
    def _ac_loop(self):
        btn_xy=self.state_slots.spinner_xy  # type: ignore
        while getattr(self,"ac_running",False) and not getattr(self,"ac_abort",False):
            if self._ac_target_reached():
                self._log("Autoclicker target reached; disabling Start.","ok")
                try: self.ac_start_btn.configure(state="disabled")
                except Exception: pass
                break
            if not self._ensure_ready_before_click():
                self._log("Autoclicker: timeout waiting READY. Pausing.","warn"); break
            time.sleep(DELAY_MIN + random.random()*(DELAY_MAX-DELAY_MIN))
            x,y=btn_xy
            pyautogui.moveTo(x+random.randint(-JITTER_PX,JITTER_PX), y+random.randint(-JITTER_PX,JITTER_PX), duration=0.08); pyautogui.click()
            if not self._wait_change_sticky(CHANGE_STICK_MS, timeout=1.2):
                if not self._rescue_once_then_wait_ready(wait_after_click=3.0):
                    if self._await_free_spins_end(): continue
                    self._log("Autoclicker: no visual change after click; pausing.","warn"); break
            t0=time.time()
            while time.time()-t0<SPIN_CHANGE_TIMEOUT and not self._is_ready():
                if self._is_fs_present_quick():
                    if self._await_free_spins_end(): self._guard_settle_ready(SETTLE_GUARD_SECS); break
                time.sleep(0.20)
            cur=self.free_count_var.get()+1; self._ui(self.free_count_var.set,cur)
            self._log(f"Autoclicker (auto): shot #{cur}")
            if self._ac_target_reached():
                self._log("Autoclicker target reached; stopping.","ok")
                try: self.ac_start_btn.configure(state="disabled")
                except Exception: pass
                break
            time.sleep(DELAY_MIN + random.random()*(DELAY_MAX-DELAY_MIN))
        self.ac_running=False; self.ac_abort=False

    # ---------- housekeeping ----------
    def _open_roulette_logfile(self): # duplicate guard
        ensure_dir(LOG_DIR_ROULETTE); day=dt.datetime.now().strftime("%Y-%m-%d")
        path=os.path.join(LOG_DIR_ROULETTE, f"{day}_session.csv")
        if not os.path.exists(path):
            with open(path,"w",newline="",encoding="utf-8") as f: csv.writer(f).writerow(["timestamp","wager_index","amount","cumulative_amount","remaining_amount","note"])
        self.state_roul.log_file_path=path; return path

    def _on_close(self):
        try:
            self.state_slots.abort=True; self.state_slots.running=False; self.state_slots.paused=False
            self.state_roul.loop_running=False; self.state_roul.armed=False
            self.ac_abort=True; self.ac_running=False
        except Exception: pass
        self._closing=True; self._cancel_all_after()
        try: self.root.quit()
        except Exception: pass
        try: self.root.destroy()
        except Exception: pass

def main():
    root=tk.Tk(); app=SpinHelperApp(root); root.mainloop()
if __name__=="__main__": main()





# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-
# """
# Spin Helper – Slots auto + Roulette tools + Clicker (manual)

# v1.10.1
# - Clicker (manual) gets an OPTIONAL "Target count" in the Free clicker subsection.
#   When set (>0), the Click button disables at target; Reset re-enables it.
# - No changes to Slots/Roulette behaviour or settings; all previous functionality preserved.
# """
# import os; os.environ.setdefault("TK_SILENCE_DEPRECATION","1")
# import sys, time, math, csv, random, threading, re, queue, datetime as dt
# from dataclasses import dataclass
# from typing import Optional, Tuple, List

# import tkinter as tk
# from tkinter import ttk
# import tkinter.font as tkfont

# import pyautogui
# from PIL import Image, ImageChops, ImageStat, ImageTk, ImageOps
# import pytesseract
# from mss import mss

# APP_TITLE="Spin Helper"; VERSION="1.10.1"

# # ---- tuning (unchanged) ----
# SPIN_SAMPLE_BOX=60
# PIX_DIFF_READY=4.0
# PIX_DIFF_CHANGED=10.0
# SPIN_CHANGE_TIMEOUT=25.0
# JITTER_PX=2
# DELAY_MIN,DELAY_MAX=0.35,0.75
# CHANGE_STICK_MS=180
# MIN_VALID_SPIN_MS=2000
# MAX_CONSECUTIVE_BLIPS=3

# MAX_MOUSE_DRIFT_PX=60
# MOUSE_DRIFT_STICK_MS=450

# FS_INIT_SAMPLES=5
# FS_POLL_SAMPLES=3
# FS_SAMPLE_GAP=0.12
# FS_MAX_REASONABLE=200
# FS_COUNTER_POLL=0.30
# FS_EXIT_CLICK_GRACE=1.0
# FS_TESS_DIGITS=r"--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
# FS_TESS_BANNER=r"--oem 3 --psm 6"

# BAND_W,BAND_H=0.60,0.22
# SETTLE_GUARD_SECS=0.6

# ROUL_BANNER_DEFAULT=(0.15,0.10,0.70,0.12)

# LOG_DIR_SLOTS="spin_logs"; LOG_DIR_ROULETTE="roulette_logs"

# def ensure_dir(p): os.makedirs(p, exist_ok=True)
# def timestamp(): return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# def _norm_box(*args)->Tuple[int,int,int,int]:
#     if len(args)==1 and isinstance(args[0],(tuple,list)): args=tuple(args[0])  # type: ignore
#     x1,y1,x2,y2=[int(v) for v in args]
#     if x2>x1 and y2>y1: x,y,w,h=x1,y1,x2-x1,y2-y1
#     else:               x,y,w,h=x1,y1,x2,y2
#     return (x,y,max(1,w),max(1,h))

# def grab_region(*box):
#     x,y,w,h=_norm_box(*box)
#     with mss() as sct:
#         shot=sct.grab({"left":x,"top":y,"width":w,"height":h})
#     return Image.frombytes("RGB", shot.size, shot.rgb)

# def rms_diff(a:Image.Image,b:Image.Image)->float:
#     A=a.convert("L"); B=b.convert("L"); diff=ImageChops.difference(A,B); stat=ImageStat.Stat(diff); return stat.mean[0]

# def _binarize(img:Image.Image)->Image.Image:
#     g=img.convert("L").resize((int(img.width*1.8),int(img.height*1.8)), Image.NEAREST)
#     return g.point(lambda p: 255 if p>160 else 0)

# @dataclass
# class SessionStateSlots:
#     spinner_xy: Optional[Tuple[int,int]]=None
#     spinner_roi: Optional[Tuple[int,int,int,int]]=None
#     spinner_baseline: Optional[Image.Image]=None
#     fs_counter_roi: Optional[Tuple[int,int,int,int]]=None
#     fs_banner_roi: Optional[Tuple[int,int,int,int]]=None
#     detect_fs: bool=True
#     free_spins_mode: bool=False
#     target_spins:int=0
#     spin_count:int=0
#     running:bool=False; paused:bool=False; abort:bool=False
#     log_file_path:str=""
#     spin_started_at: Optional[float]=None
#     bound_monitor: Optional[dict]=None
#     movement_guard_active:bool=False
#     mouse_breach_since: Optional[float]=None
#     stop_after_current_spin:bool=False

# @dataclass
# class SessionStateRoulette:
#     armed:bool=False
#     wager_amount:float=0.0
#     target_wager:float=0.0
#     explicit_wagers: Optional[int]=None
#     wagers_done:int=0
#     total_wagered:float=0.0
#     click_xy: Optional[Tuple[int,int]]=None
#     next_btn_autoclick:bool=False
#     autobanner_enabled:bool=False
#     autobanner_clicks:int=1
#     autobanner_gap:float=0.20
#     loop_running:bool=False
#     banner_roi: Optional[Tuple[int,int,int,int]]=None
#     log_file_path:str=""

# class SpinHelperApp:
#     def __init__(self, root: tk.Tk):
#         self.root=root; self.root.title(f"{APP_TITLE} v{VERSION}")
#         self.root.geometry("1120x800+60+60"); self.root.minsize(920,680); self.root.attributes("-topmost",True)
#         self.state_slots=SessionStateSlots(); self.state_roul=SessionStateRoulette()
#         self._uiq: "queue.Queue[tuple]"=queue.Queue(); self._after_ids={}; self._closing=False
#         self._log_buffer: List[tuple]=[]; self._blip_count=0
#         self.ui_font=tkfont.nametofont("TkDefaultFont"); self.text_font=tkfont.nametofont("TkTextFont")
#         self._build_ui(); ensure_dir(LOG_DIR_SLOTS); ensure_dir(LOG_DIR_ROULETTE)
#         self._log("Ready. Grant Accessibility / Input Monitoring / Screen Recording if prompted.")
#         self._after("ui_tick",80,self._ui_tick); self._after("drain_uiq",16,self._drain_uiq)
#         self.root.protocol("WM_DELETE_WINDOW", self._on_close); self.root.bind("<Configure>", self._on_resize)

#     # ---------- misc ui helpers ----------
#     def _after(self,key,ms,fn):
#         if self._closing: return
#         def wrap():
#             if self._closing: return
#             try: fn()
#             finally: pass
#         aid=self.root.after(ms, wrap); self._after_ids[key]=aid
#     def _cancel_all_after(self):
#         for aid in list(self._after_ids.values()):
#             try: self.root.after_cancel(aid)
#             except Exception: pass
#         self._after_ids.clear()
#     def _ui(self,fn,*a,**kw):
#         try: self._uiq.put((fn,a,kw))
#         except Exception as e: self._log(f"UI queue error: {e}","warn")
#     def _drain_uiq(self):
#         try:
#             while True:
#                 fn,a,kw=self._uiq.get_nowait()
#                 try: fn(*a,**kw)
#                 except Exception as e: self._log(f"UI task error: {e}","warn")
#         except queue.Empty: pass
#         self._after("drain_uiq",16,self._drain_uiq)

#     def _build_ui(self):
#         root=self.root
#         root.columnconfigure(0,weight=1); root.rowconfigure(0,weight=1)
#         self.paned=ttk.Panedwindow(root, orient="horizontal"); self.paned.grid(row=0,column=0,sticky="nsew")
#         self.left=ttk.Frame(self.paned,padding=10); self.left.columnconfigure(0,weight=1); self.left.rowconfigure(1,weight=1)
#         self.right=ttk.Frame(self.paned,padding=(8,10,10,10)); self.right.columnconfigure(0,weight=1); self.right.rowconfigure(1,weight=1)
#         self.paned.add(self.left,weight=3); self.paned.add(self.right,weight=2)

#         header=ttk.Frame(self.left); header.grid(row=0,column=0,sticky="ew",pady=(0,8)); header.columnconfigure(0,weight=1)
#         ttk.Label(header,text=f"{APP_TITLE} v{VERSION}",foreground="#555").grid(row=0,column=0,sticky="e")

#         self.nb=ttk.Notebook(self.left); self.nb.grid(row=1,column=0,sticky="nsew")
#         self.slots_tab=ttk.Frame(self.nb); self.roul_tab=ttk.Frame(self.nb); self.clicker_tab=ttk.Frame(self.nb)
#         for t in (self.slots_tab,self.roul_tab,self.clicker_tab): t.columnconfigure(0,weight=1)
#         self._build_slots_tab(self.slots_tab); self._build_roulette_tab(self.roul_tab); self._build_clicker_tab(self.clicker_tab)
#         self.nb.add(self.slots_tab,text="Slots (auto)"); self.nb.add(self.roul_tab,text="Roulette (manual/auto)"); self.nb.add(self.clicker_tab,text="Clicker (manual)")

#         ttk.Label(self.right,text="Notification Centre").grid(row=0,column=0,sticky="w")
#         self.log_txt=tk.Text(self.right,wrap="word",state="disabled")
#         vs=ttk.Scrollbar(self.right,orient="vertical",command=self.log_txt.yview); self.log_txt.configure(yscrollcommand=vs.set)
#         self.log_txt.grid(row=1,column=0,sticky="nsew",pady=(6,6)); vs.grid(row=1,column=1,sticky="ns",pady=(6,6))
#         self.log_txt.tag_configure("action",foreground="#0a7a0a",font=(self.text_font.actual("family"), self.text_font.actual("size"), "bold"))
#         self.log_txt.tag_configure("ok",foreground="#0a7a0a")
#         self.log_txt.tag_configure("warn",foreground="#cc7a00")
#         self.log_txt.tag_configure("err",foreground="#bb2d3b")
#         ttk.Button(ttk.Frame(self.right),text="Clear log",command=self._clear_log).grid(row=0,column=0)

#     def _layout_refresh(self):
#         try: Lw=max(1,self.left.winfo_width())
#         except Exception: return
#         mode="narrow" if Lw<680 else "wide"
#         if getattr(self,"_layout_mode",None)==mode: return
#         self._layout_mode=mode
#         for w in (self.cfg_grid+self.cfg_grid2+self.run_grid+self.pick_grid): w.grid_forget()
#         if mode=="wide":
#             r=0
#             self.mode_box.grid(row=r,column=0,sticky="w",padx=(0,16))
#             self.lbl_spins.grid(row=r,column=1,sticky="w"); self.spins_entry.grid(row=r,column=2,sticky="w",padx=(4,12))
#             self.lbl_stake.grid(row=r,column=3,sticky="e"); self.stake_entry.grid(row=r,column=4,sticky="w",padx=(4,12))
#             self.lbl_target.grid(row=r,column=5,sticky="e"); self.target_entry.grid(row=r,column=6,sticky="w",padx=(4,12))
#             self.calc_btn.grid(row=r,column=7,sticky="w",padx=(0,12)); self.fs_chk.grid(row=r,column=8,sticky="w")
#             for i in range(9): self.cfg.columnconfigure(i,weight=0)
#             self.cfg.columnconfigure(2,weight=1); self.cfg.columnconfigure(4,weight=1); self.cfg.columnconfigure(6,weight=1)
#         else:
#             r=0; self.mode_box.grid(row=r,column=0,columnspan=5,sticky="w",pady=(0,4)); r+=1
#             self.lbl_spins.grid(row=r,column=0,sticky="w"); self.spins_entry.grid(row=r,column=1,sticky="ew",padx=(4,12))
#             self.lbl_stake.grid(row=r,column=2,sticky="e"); self.stake_entry.grid(row=r,column=3,sticky="ew",padx=(4,12)); r+=1
#             self.lbl_target.grid(row=r,column=0,sticky="w"); self.target_entry.grid(row=r,column=1,sticky="ew",padx=(4,12))
#             self.calc_btn.grid(row=r,column=2,sticky="w",padx=(0,12)); self.fs_chk.grid(row=r,column=3,sticky="e")
#             for i in range(4): self.cfg.columnconfigure(i,weight=1)

#         # pick
#         self.capture_spinner_btn.grid(row=0,column=0,sticky="w")
#         self.spinner_preview.grid(row=0,column=1,sticky="w",padx=(10,0))
#         self.bind_display_btn.grid(row=0,column=2,sticky="w",padx=(10,0))
#         self.fs_counter_btn.grid(row=1,column=0,sticky="w",pady=(6,0))
#         self.fs_banner_btn.grid(row=1,column=1,sticky="w",pady=(6,0))
#         self.fs_status.grid(row=1,column=2,columnspan=2,sticky="w",padx=(10,0),pady=(6,0))
#         for i in range(4): self.pick.columnconfigure(i,weight=(1 if i==2 else 0))

#         # run
#         self.lbl_count.grid(row=0,column=0,sticky="w"); self.count_val.grid(row=0,column=1,sticky="w",padx=(6,12))
#         self.reset_btn.grid(row=0,column=2,sticky="w"); self.run_buttons.grid(row=0,column=4,sticky="e")
#         for i in range(5): self.run.columnconfigure(i,weight=(1 if i==3 else 0))

#     def _on_resize(self,_=None):
#         try:
#             total=self.root.winfo_width()
#             if total<1200: self.paned.sashpos(0,int(total*0.62))
#         except Exception: pass
#         self._layout_refresh()

#     def _log(self,msg,tag=None): self._log_buffer.append((f"[{timestamp()}] {msg}",tag))
#     def _flush_log(self):
#         if not self._log_buffer: return
#         self.log_txt.config(state="normal")
#         for line,tag in self._log_buffer:
#             if tag: self.log_txt.insert("end", line+"\n", (tag,))
#             else:   self.log_txt.insert("end", line+"\n")
#             self.log_txt.see("end")
#         self._log_buffer.clear(); self.log_txt.config(state="disabled")
#     def _clear_log(self):
#         self.log_txt.config(state="normal"); self.log_txt.delete("1.0","end")
#         self.log_txt.insert("end", f"[{timestamp()}] Log cleared.\n", ("ok",)); self.log_txt.config(state="disabled")
#     def _ui_tick(self): self._flush_log(); self._after("ui_tick",80,self._ui_tick)

#     # ---------- Slots UI ----------
#     def _build_slots_tab(self, parent: ttk.Frame):
#         parent.columnconfigure(0,weight=1)
#         self.cfg=ttk.Labelframe(parent,text="Configuration"); self.cfg.grid(row=0,column=0,sticky="ew",padx=2,pady=(6,8))
#         self.mode_var=tk.StringVar(value="standard")
#         self.mode_box=ttk.Frame(self.cfg)
#         ttk.Label(self.mode_box,text="Mode:").pack(side="left")
#         ttk.Radiobutton(self.mode_box,text="Standard",value="standard",variable=self.mode_var,command=self._on_mode_change).pack(side="left",padx=(6,8))
#         ttk.Radiobutton(self.mode_box,text="Free-Spins only",value="fs_only",variable=self.mode_var,command=self._on_mode_change).pack(side="left")

#         self.lbl_spins=ttk.Label(self.cfg,text="No. of spins:")
#         self.spins_var=tk.StringVar(value="0"); self.spins_entry=ttk.Entry(self.cfg,textvariable=self.spins_var,width=10)
#         self.lbl_stake=ttk.Label(self.cfg,text="£ per spin:"); self.stake_var=tk.StringVar(value=""); self.stake_entry=ttk.Entry(self.cfg,textvariable=self.stake_var,width=9)
#         self.lbl_target=ttk.Label(self.cfg,text="Total wagering £:"); self.target_wager_var=tk.StringVar(value=""); self.target_entry=ttk.Entry(self.cfg,textvariable=self.target_wager_var,width=9)
#         self.calc_btn=ttk.Button(self.cfg,text="Calc spins",command=self._calc_spins)
#         self.fs_toggle_var=tk.BooleanVar(value=True)
#         self.fs_chk=ttk.Checkbutton(self.cfg,text="Detect Free Spins",variable=self.fs_toggle_var,command=self._toggle_fs)

#         self.cfg_grid=[self.mode_box,self.lbl_spins,self.spins_entry,self.lbl_stake,self.stake_entry]
#         self.cfg_grid2=[self.lbl_target,self.target_entry,self.calc_btn,self.fs_chk]

#         self.pick=ttk.Labelframe(parent,text="Detection & Selection"); self.pick.grid(row=1,column=0,sticky="ew",padx=2,pady=(0,8))
#         self.capture_spinner_btn=ttk.Button(self.pick,text="Capture Spinner",command=self._countdown_capture_spinner)
#         self.spinner_preview=ttk.Label(self.pick,text="(spinner preview)")
#         self.bind_display_btn=ttk.Button(self.pick,text="Bind to this display",command=self._bind_display_button)
#         self.fs_counter_btn=ttk.Button(self.pick,text="Select FS Counter ROI",command=lambda:self._pick_two_corner_roi("fs_counter"))
#         self.fs_banner_btn =ttk.Button(self.pick,text="Select FS Banner ROI", command=lambda:self._pick_two_corner_roi("fs_banner"))
#         self.fs_status=ttk.Label(self.pick,text="FS: counter preferred; banner is fallback")
#         self.pick_grid=[self.capture_spinner_btn,self.spinner_preview,self.bind_display_btn,self.fs_counter_btn,self.fs_banner_btn,self.fs_status]

#         self.run=ttk.Labelframe(parent,text="Run"); self.run.grid(row=2,column=0,sticky="ew",padx=2,pady=(0,8))
#         self.lbl_count=ttk.Label(self.run,text="Spin Count:"); self.count_var=tk.IntVar(value=0)
#         self.count_val=ttk.Label(self.run,textvariable=self.count_var,font=("TkDefaultFont",14,"bold"))
#         self.reset_btn=tk.Button(self.run,text="Reset",command=self._reset_count,bg="#bb2d3b",fg="white",activebackground="#a42734",activeforeground="white",highlightbackground="#bb2d3b",bd=0,relief="raised",padx=12,pady=2)
#         self.run_buttons=ttk.Frame(self.run)
#         ttk.Button(self.run_buttons,text="Start",command=self.start_slots).grid(row=0,column=0,padx=(0,8))
#         ttk.Button(self.run_buttons,text="Pause (safe)",command=self.pause_slots).grid(row=0,column=1,padx=(0,8))
#         ttk.Button(self.run_buttons,text="Stop",command=self.stop_slots).grid(row=0,column=2)
#         self.run_grid=[self.lbl_count,self.count_val,self.reset_btn,self.run_buttons]
#         self._layout_refresh()

#     # ---------- Roulette UI ----------
#     def _build_roulette_tab(self, parent: ttk.Frame):
#         parent.columnconfigure(0,weight=1)
#         cfg=ttk.Labelframe(parent,text="Configuration"); cfg.grid(row=0,column=0,sticky="ew",padx=2,pady=(6,8)); cfg.columnconfigure(7,weight=1)
#         ttk.Label(cfg,text="£ per wager:").grid(row=0,column=0,sticky="w")
#         self.r_amount_var=tk.StringVar(value=""); ttk.Entry(cfg,textvariable=self.r_amount_var,width=10).grid(row=0,column=1,sticky="w",padx=(4,8))
#         ttk.Label(cfg,text="Target wagering £:").grid(row=0,column=2,sticky="e")
#         self.r_target_var=tk.StringVar(value=""); ttk.Entry(cfg,textvariable=self.r_target_var,width=10).grid(row=0,column=3,sticky="w",padx=(4,12))
#         ttk.Label(cfg,text="# of wagers (optional):").grid(row=0,column=4,sticky="e")
#         self.r_explicit_n_var=tk.StringVar(value=""); ttk.Entry(cfg,textvariable=self.r_explicit_n_var,width=10).grid(row=0,column=5,sticky="w")

#         pick=ttk.Labelframe(parent,text="Selection & Overlay"); pick.grid(row=1,column=0,sticky="ew",padx=2,pady=(0,8))
#         ttk.Button(pick,text="Capture Wager Button",command=self._roulette_capture_click_point).grid(row=0,column=0,sticky="w")
#         self.r_click_preview=ttk.Label(pick,text="(wager button preview)"); self.r_click_preview.grid(row=0,column=1,sticky="w",padx=(10,0))
#         ttk.Button(pick,text="Select Betting Banner ROI",command=self._roulette_pick_banner_roi).grid(row=1,column=0,sticky="w",pady=(6,0))
#         self.r_banner_status=ttk.Label(pick,text="Banner ROI: default (top green bar)"); self.r_banner_status.grid(row=1,column=1,sticky="w",padx=(10,0))

#         ctl=ttk.Labelframe(parent,text="Controls"); ctl.grid(row=2,column=0,sticky="ew",padx=2,pady=(0,8))
#         self.r_stats_var=tk.StringVar(value="Wagers done: 0 • Left: 0 • £ remaining: 0.00")
#         ttk.Label(ctl,textvariable=self.r_stats_var,font=("TkDefaultFont",12,"bold")).grid(row=0,column=0,columnspan=6,sticky="w",pady=(0,8))
#         self.r_autoclick_var=tk.BooleanVar(value=False)
#         ttk.Checkbutton(ctl,text="Auto-click on Next Wager (one-shot)",variable=self.r_autoclick_var,command=self._toggle_roul_next_autoclick).grid(row=1,column=0,sticky="w")
#         self.r_autobanner_var=tk.BooleanVar(value=False)
#         ttk.Checkbutton(ctl,text="Auto-bet while 'Place Your Bets' visible",variable=self.r_autobanner_var).grid(row=2,column=0,sticky="w",pady=(6,0))
#         ttk.Label(ctl,text="Chips per wager:").grid(row=2,column=1,sticky="e")
#         self.r_chips_per_var=tk.StringVar(value="1"); ttk.Entry(ctl,textvariable=self.r_chips_per_var,width=6).grid(row=2,column=2,sticky="w",padx=(4,8))
#         ttk.Label(ctl,text="Click gap (s):").grid(row=2,column=3,sticky="e")
#         self.r_gap_var=tk.StringVar(value="0.20"); ttk.Entry(ctl,textvariable=self.r_gap_var,width=6).grid(row=2,column=4,sticky="w",padx=(4,8))

#         btns=ttk.Frame(ctl); btns.grid(row=3,column=0,columnspan=6,sticky="w",pady=(6,0))
#         ttk.Button(btns,text="Start / Arm",command=self._roulette_arm).grid(row=0,column=0,padx=(0,8))
#         ttk.Button(btns,text="Next Wager",command=self._roulette_next).grid(row=0,column=1,padx=(0,8))
#         ttk.Button(btns,text="Undo Last",command=self._roulette_undo).grid(row=0,column=2,padx=(0,8))
#         ttk.Button(btns,text="Finish",command=self._roulette_finish).grid(row=0,column=3)

#     # ---------- Clicker (manual) UI ----------
#     def _build_clicker_tab(self, parent: ttk.Frame):
#         parent.columnconfigure(0,weight=1)
#         pick=ttk.Labelframe(parent,text="Pointer Target"); pick.grid(row=0,column=0,sticky="ew",padx=2,pady=(6,8))
#         ttk.Button(pick,text="Capture Click Point (required)",command=self._countdown_capture_spinner).grid(row=0,column=0,sticky="w")
#         self.clicker_preview=ttk.Label(pick,text="(click target preview)"); self.clicker_preview.grid(row=0,column=1,sticky="w",padx=(10,0))
#         ttk.Button(pick,text="Bind to this display",command=self._bind_display_button).grid(row=0,column=2,sticky="w",padx=(10,0))
#         self.clicker_status=ttk.Label(pick,text="Use the same spinner/click point as Slots.")
#         self.clicker_status.grid(row=1,column=0,columnspan=3,sticky="w",pady=(6,0))

#         # A) Target calculator (unchanged)
#         calc=ttk.Labelframe(parent,text="A) Target calculator"); calc.grid(row=1,column=0,sticky="ew",padx=2,pady=(0,8))
#         ttk.Label(calc,text="Reward £:").grid(row=0,column=0,sticky="w"); self.ck_reward_var=tk.StringVar(value="")
#         ttk.Entry(calc,textvariable=self.ck_reward_var,width=10).grid(row=0,column=1,sticky="w",padx=(4,12))
#         ttk.Label(calc,text="Wagering ×:").grid(row=0,column=2,sticky="e"); self.ck_wagerx_var=tk.StringVar(value="")
#         ttk.Entry(calc,textvariable=self.ck_wagerx_var,width=8).grid(row=0,column=3,sticky="w",padx=(4,12))
#         ttk.Label(calc,text="£ per click:").grid(row=0,column=4,sticky="e"); self.ck_perclick_var=tk.StringVar(value="")
#         ttk.Entry(calc,textvariable=self.ck_perclick_var,width=10).grid(row=0,column=5,sticky="w",padx=(4,12))
#         ttk.Button(calc,text="Compute target",command=self._clicker_compute).grid(row=0,column=6,sticky="w")

#         ttk.Label(calc,text="Target clicks:").grid(row=1,column=0,sticky="w",pady=(6,0))
#         self.ck_target_var=tk.IntVar(value=0); ttk.Label(calc,textvariable=self.ck_target_var,font=("TkDefaultFont",12,"bold")).grid(row=1,column=1,sticky="w",pady=(6,0))
#         ttk.Label(calc,text="Progress:").grid(row=1,column=2,sticky="e",pady=(6,0))
#         self.ck_progress_var=tk.IntVar(value=0); ttk.Label(calc,textvariable=self.ck_progress_var,font=("TkDefaultFont",12,"bold")).grid(row=1,column=3,sticky="w",pady=(6,0))
#         self.ck_click_btn=ttk.Button(calc,text="Click (target)",command=lambda:self._clicker_target_click(self.ck_click_btn))
#         self.ck_click_btn.grid(row=1,column=4,sticky="w",padx=(8,8),pady=(6,0))
#         ttk.Button(calc,text="Reset target",command=self._clicker_target_reset).grid(row=1,column=5,sticky="w",pady=(6,0))
#         calc.columnconfigure(6,weight=1)

#         # B) Free clicker (now with optional target)
#         free=ttk.Labelframe(parent,text="B) Free clicker"); free.grid(row=2,column=0,sticky="ew",padx=2,pady=(0,8))
#         ttk.Label(free,text="Count:").grid(row=0,column=0,sticky="w")
#         self.free_count_var=tk.IntVar(value=0); ttk.Label(free,textvariable=self.free_count_var,font=("TkDefaultFont",12,"bold")).grid(row=0,column=1,sticky="w")
#         self.free_click_btn=ttk.Button(free,text="Click",command=lambda:self._clicker_free_click(self.free_click_btn))
#         self.free_click_btn.grid(row=0,column=2,sticky="w",padx=(8,8))
#         ttk.Button(free,text="Reset",command=self._clicker_free_reset).grid(row=0,column=3,sticky="w")

#         ttk.Label(free,text="Target (optional):").grid(row=0,column=4,sticky="e")
#         self.free_target_var=tk.StringVar(value="")
#         self.free_target_entry=ttk.Entry(free,textvariable=self.free_target_var,width=8)
#         self.free_target_entry.grid(row=0,column=5,sticky="w",padx=(4,12))
#         # When user changes target, re-enable the click button if appropriate
#         self.free_target_var.trace_add("write", lambda *_: self._free_target_changed())
#         free.columnconfigure(6,weight=1)

#     # ---------- common ----------
#     def _virtual_bounds(self)->Tuple[int,int,int,int]:
#         try:
#             if self.state_slots.bound_monitor is not None:
#                 m=self.state_slots.bound_monitor; return m["left"],m["top"],m["width"],m["height"]
#             with mss() as sct:
#                 m=sct.monitors[0]; return m["left"],m["top"],m["width"],m["height"]
#         except Exception:
#             sw,sh=pyautogui.size(); return 0,0,sw,sh

#     def _bind_monitor_from_cursor(self):
#         x,y=pyautogui.position()
#         try:
#             with mss() as sct:
#                 chosen=None
#                 for m in sct.monitors[1:]:
#                     if m["left"]<=x<m["left"]+m["width"] and m["top"]<=y<m["top"]+m["height"]:
#                         chosen=m; break
#                 self.state_slots.bound_monitor=chosen or sct.monitors[0]
#                 if chosen: self._log(f"Bound FS/overlay scans to display at {chosen['left']},{chosen['top']} {chosen['width']}x{chosen['height']}.","ok")
#                 else:      self._log("Bound scans to virtual desktop (all displays).","ok")
#         except Exception as e: self._log(f"Bind monitor failed: {e}","warn")

#     def _bind_display_button(self):
#         self._countdown("Binding to this display",3,self._bind_monitor_from_cursor)

#     def _countdown(self,label,secs,on_done):
#         def tick(n):
#             if n==0: on_done(); return
#             self._log(f"{label} in {n}…","action"); self.root.after(1000, lambda: tick(n-1))
#         tick(secs)

#     # ---------- capture ----------
#     def _countdown_capture_spinner(self):
#         self._bind_monitor_from_cursor()
#         self._countdown("Capturing spinner",3,self._capture_spinner_from_cursor)

#     def _capture_spinner_from_cursor(self):
#         try:
#             x,y=pyautogui.position(); half=SPIN_SAMPLE_BOX//2; roi=(x-half,y-half,SPIN_SAMPLE_BOX,SPIN_SAMPLE_BOX)
#             img=grab_region(roi)
#             s=self.state_slots; s.spinner_xy=(x,y); s.spinner_roi=roi; s.spinner_baseline=img
#             s.mouse_breach_since=None; s.stop_after_current_spin=False; s.movement_guard_active=False
#             self._log(f"Spinner captured at XY=({x},{y}).","ok")
#             tkimg=ImageTk.PhotoImage(img.resize((80,80)))
#             # Update previews wherever present
#             try: self.spinner_preview.configure(image=tkimg); self.spinner_preview.image=tkimg
#             except Exception: pass
#             try: self.clicker_preview.configure(image=tkimg); self.clicker_preview.image=tkimg
#             except Exception: pass
#         except Exception as ex: self._log(f"Spinner capture failed: {ex}","err")

#     def _pick_two_corner_roi(self,which:str):
#         title={"fs_counter":"Free-Spins Counter ROI","fs_banner":"Free-Spins Banner ROI"}[which]
#         def after_tl():
#             x1,y1=pyautogui.position(); self._log(f"{title}: TOP-LEFT captured at ({x1},{y1}).","ok")
#             self._countdown(f"{title}: move to BOTTOM-RIGHT. Capturing",3,lambda: after_br(x1,y1))
#         def after_br(x1,y1):
#             x2,y2=pyautogui.position()
#             if x2<=x1 or y2<=y1: self._log("Invalid region (bottom-right must be larger).","warn"); return
#             roi=(x1,y1,x2-x1,y2-y1)
#             if which=="fs_counter": self.state_slots.fs_counter_roi=roi; self._ui(self.fs_status.config,text="FS: counter ROI set (preferred)")
#             else: self.state_slots.fs_banner_roi=roi; self._ui(self.fs_status.config,text="FS: banner ROI set (fallback)")
#             self._log(f"{title} set: {roi}","ok")
#         self._countdown(f"{title}: move mouse to TOP-LEFT. Capturing",3,after_tl)

#     # ---------- slots helpers ----------
#     def _is_ready(self)->bool:
#         roi_img=grab_region(self.state_slots.spinner_roi)  # type: ignore
#         return rms_diff(roi_img,self.state_slots.spinner_baseline)<=PIX_DIFF_READY  # type: ignore

#     def _wait_change_sticky(self, baseline:Image.Image, min_stick_ms:int, timeout:float)->bool:
#         t0=time.time(); changed_at=None
#         while time.time()-t0<timeout:
#             if self._check_mouse_drift_sticky(): self.state_slots.stop_after_current_spin=True
#             img=grab_region(self.state_slots.spinner_roi)  # type: ignore
#             if rms_diff(img,baseline)>=PIX_DIFF_CHANGED:
#                 if changed_at is None: changed_at=time.time()
#                 elif (time.time()-changed_at)*1000.0>=min_stick_ms: return True
#             else: changed_at=None
#             time.sleep(0.04)
#         return False

#     def _wait_for_change(self, baseline:Image.Image, become_changed=True, timeout=SPIN_CHANGE_TIMEOUT)->bool:
#         t0=time.time()
#         while time.time()-t0<timeout:
#             if self.state_slots.movement_guard_active and self._check_mouse_drift_sticky():
#                 self.state_slots.stop_after_current_spin=True
#             diff=rms_diff(grab_region(self.state_slots.spinner_roi),baseline)  # type: ignore
#             if  become_changed and diff>=PIX_DIFF_CHANGED: return True
#             if (not become_changed) and diff<=PIX_DIFF_READY: return True
#             time.sleep(0.05)
#         return False

#     def _guard_settle_ready(self, seconds:float)->bool:
#         t0=time.time()
#         while time.time()-t0<seconds:
#             if not self._is_ready(): return False
#             time.sleep(0.08)
#         return True

#     def _check_mouse_drift_sticky(self)->bool:
#         s=self.state_slots
#         if not (s.spinner_xy and s.movement_guard_active): return False
#         sx,sy=s.spinner_xy; cx,cy=pyautogui.position(); dx=cx-sx; dy=cy-sy
#         far=(dx*dx+dy*dy)**0.5>MAX_MOUSE_DRIFT_PX; now=time.time()
#         if far:
#             if s.mouse_breach_since is None: s.mouse_breach_since=now
#             elif (now - s.mouse_breach_since)*1000.0>=MOUSE_DRIFT_STICK_MS:
#                 if not s.stop_after_current_spin: self._log("Too much mouse movement detected — finishing current spin and pausing.","warn")
#                 return True
#         else: s.mouse_breach_since=None
#         return False

#     # ----- Free-Spins detection & handling -----
#     def _stable_fs_value(self,samples:int)->Optional[int]:
#         s=self.state_slots
#         if not (s.detect_fs and s.fs_counter_roi): return None
#         vals=[]
#         for _ in range(samples):
#             try:
#                 txt=pytesseract.image_to_string(_binarize(grab_region(s.fs_counter_roi)),config=FS_TESS_DIGITS)  # type: ignore
#                 m=re.search(r"\d+", txt or "");  vals.append(int(m.group(0))) if m else None
#             except Exception: pass
#             time.sleep(FS_SAMPLE_GAP)
#         return sorted(vals)[len(vals)//2] if vals else None

#     def _scan_fs_bottom_text(self)->Tuple[bool, Optional[int]]:
#         if not self.state_slots.detect_fs: return (False,None)
#         try:
#             vx,vy,vw,vh=self._virtual_bounds()
#             x=vx+int(vw*((1.0-0.60)/2.0)); y=vy+int(vh*(1.0-0.22))
#             img=grab_region((x,y,int(vw*0.60),int(vh*0.22)))
#             g=img.convert("L").point(lambda p:255 if p>150 else 0)
#             txt=(pytesseract.image_to_string(g,config=FS_TESS_BANNER) or "").upper().replace("£"," ")
#             m=re.search(r"FREE\s+SPINS\s+LEFT\s+(\d+)", txt)
#             if m: return True,int(m.group(1))
#             if ("FREE" in txt and "SPINS" in txt): return True,None
#             return False,None
#         except Exception: return False,None

#     def _is_fs_present_quick(self)->bool:
#         if not self.state_slots.detect_fs: return False
#         try:
#             if self.state_slots.fs_counter_roi:
#                 s=pytesseract.image_to_string(_binarize(grab_region(self.state_slots.fs_counter_roi)),config=FS_TESS_DIGITS)  # type: ignore
#                 if re.search(r"\d+", s or ""): return True
#         except Exception: pass
#         present,_=self._scan_fs_bottom_text()
#         return present

#     def _await_free_spins_end(self)->bool:
#         if not self.state_slots.detect_fs: return False
#         v=self._stable_fs_value(FS_INIT_SAMPLES)
#         if v is not None and 0<=v<=FS_MAX_REASONABLE:
#             last=v; self._log(f"Free-Spins counter: {last}")
#             while True:
#                 cur=self._stable_fs_value(FS_POLL_SAMPLES)
#                 if cur is None: break
#                 if 0<=cur<=last and cur!=last:
#                     self._log(f"Free-Spins progress: {cur} left."); last=cur
#                 if cur<=0: break
#                 time.sleep(FS_COUNTER_POLL)
#             time.sleep(FS_EXIT_CLICK_GRACE); return True
#         present,_=self._scan_fs_bottom_text()
#         if present:
#             last_seen=time.time()
#             while True:
#                 p,n=self._scan_fs_bottom_text()
#                 if p:
#                     last_seen=time.time()
#                     if n is not None: self._log(f"Free-Spins progress: {n} left.")
#                     time.sleep(0.5); continue
#                 if time.time()-last_seen>12: break
#                 time.sleep(0.4)
#             return True
#         return False

#     def _rescue_once_then_wait_ready(self, baseline:Image.Image, wait_after_click:float=SPIN_CHANGE_TIMEOUT)->bool:
#         x,y=self.state_slots.spinner_xy  # type: ignore
#         pyautogui.moveTo(x+random.randint(-JITTER_PX,JITTER_PX), y+random.randint(-JITTER_PX,JITTER_PX), duration=0.06)
#         pyautogui.click(); self._log("Rescue click #1.")
#         if self._is_fs_present_quick():
#             if self._await_free_spins_end():
#                 return self._guard_settle_ready(SETTLE_GUARD_SECS)
#         return self._wait_for_change(baseline, become_changed=False, timeout=wait_after_click)

#     def _ensure_ready_before_click(self, baseline:Image.Image)->bool:
#         if self._wait_for_change(baseline, become_changed=False, timeout=2.5): return True
#         if self._is_fs_present_quick():
#             if self._await_free_spins_end():
#                 return self._guard_settle_ready(SETTLE_GUARD_SECS)
#         if self._rescue_once_then_wait_ready(baseline, wait_after_click=SPIN_CHANGE_TIMEOUT): return True
#         return False

#     def _on_mode_change(self):
#         fs_only=(self.mode_var.get()=="fs_only"); self.state_slots.free_spins_mode=fs_only
#         state_money=("disabled" if fs_only else "normal")
#         for w in (self.stake_entry,self.target_entry,self.calc_btn):
#             try: w.configure(state=state_money)
#             except Exception: pass
#         self._log(f"Mode: {'Free-Spins only' if fs_only else 'Standard'}","ok")

#     def _toggle_fs(self):
#         self.state_slots.detect_fs=bool(self.fs_toggle_var.get())
#         self._log(f"Detect Free Spins: {'ON' if self.state_slots.detect_fs else 'OFF'}", "ok" if self.state_slots.detect_fs else "warn")

#     def _calc_spins(self):
#         try:
#             stake=float(self.stake_var.get()); target=float(self.target_wager_var.get())
#             if stake<=0: raise ValueError
#             self.spins_var.set(str(math.ceil(target/stake))); self._log("Calculated spins.","ok")
#         except Exception: self._log("Enter valid '£ per spin' and 'Total wagering £'.","warn")

#     def _reset_count(self):
#         s=self.state_slots; s.spin_count=0; s.stop_after_current_spin=False; s.mouse_breach_since=None
#         self._ui(self.count_var.set,0); self._log("Spin counter reset.","ok")

#     def _open_slots_logfile(self):
#         ensure_dir(LOG_DIR_SLOTS); day=dt.datetime.now().strftime("%Y-%m-%d")
#         path=os.path.join(LOG_DIR_SLOTS, f"{day}_session.csv")
#         if not os.path.exists(path):
#             with open(path,"w",newline="",encoding="utf-8") as f: csv.writer(f).writerow(["timestamp","spin_count","x","y","balance"])
#         self.state_slots.log_file_path=path; return path

#     # ---------- Slots run ----------
#     def start_slots(self):
#         s=self.state_slots
#         if not (s.spinner_roi and s.spinner_xy and s.spinner_baseline):
#             self._log("Please capture the SPINNER first.","warn"); return

#         fs_only=(self.mode_var.get()=="fs_only")
#         if fs_only:
#             try: s.target_spins=int(self.spins_var.get() or "0")
#             except Exception: s.target_spins=0
#         else:
#             try: spins=int(self.spins_var.get() or "0")
#             except Exception: spins=0
#             if spins<=0:
#                 try:
#                     stake=float(self.stake_var.get()); target=float(self.target_wager_var.get())
#                     if stake>0 and target>0: spins=math.ceil(target/stake)
#                 except Exception: pass
#             s.target_spins=max(0,spins)

#         self._open_slots_logfile()
#         if s.running: self._log("Already running.","warn"); return
#         s.running=True; s.paused=False; s.abort=False
#         s.stop_after_current_spin=False; s.mouse_breach_since=None; s.movement_guard_active=False
#         self._log("Starting…","ok")
#         threading.Thread(target=self._spin_loop,daemon=True).start()

#     def pause_slots(self): self.state_slots.abort=True; self._log("PAUSED (will take effect at a safe point).","warn")
#     def stop_slots (self): self.state_slots.abort=True; self.state_slots.running=False; self.state_slots.paused=False; self._log("Stopped.","warn")

#     def _target_reached(self)->bool:
#         t=self.state_slots.target_spins
#         return t>0 and self.state_slots.spin_count>=t

#     def _wait_until_ready_or_fs(self, baseline:Image.Image, timeout:float)->str:
#         t0=time.time()
#         while time.time()-t0<timeout:
#             if self._is_fs_present_quick():
#                 if self._await_free_spins_end():
#                     self._guard_settle_ready(SETTLE_GUARD_SECS)
#                     return "fs"
#             if self._wait_for_change(baseline, become_changed=False, timeout=0.25):
#                 return "ready"
#         return "timeout"

#     def _spin_loop(self):
#         base=self.state_slots.spinner_baseline  # type: ignore
#         while self.state_slots.running:
#             if self._target_reached():
#                 self._log(f"Target reached ({self.state_slots.spin_count}/{self.state_slots.target_spins}). Stopping.","ok"); break
#             if self.state_slots.stop_after_current_spin:
#                 self._log("Movement latch is set — pausing safely (won't start a new spin).","warn"); break

#             if not self._ensure_ready_before_click(base):
#                 self._log("Timeout waiting READY.","warn"); self.state_slots.paused=True; break
#             self._log("Ready confirmed.","ok")

#             if self._target_reached() or self.state_slots.stop_after_current_spin:
#                 self._log("Safe-check blocked new spin (target reached or movement).","warn"); break

#             next_idx=self.state_slots.spin_count+1; self._log(f"Spin #{next_idx} starting…","action")
#             self.state_slots.spin_started_at=time.time()
#             x,y=self.state_slots.spinner_xy  # type: ignore
#             pyautogui.moveTo(x+random.randint(-JITTER_PX,JITTER_PX), y+random.randint(-JITTER_PX,JITTER_PX), duration=0.08); pyautogui.click()
#             self.state_slots.movement_guard_active=True

#             if not self._wait_change_sticky(base, CHANGE_STICK_MS, timeout=0.9):
#                 if not self._rescue_once_then_wait_ready(base, wait_after_click=3.0):
#                     if self._await_free_spins_end():
#                         self.state_slots.movement_guard_active=False; continue
#                     self._log("No visual change after click. Pausing.","warn")
#                     self.state_slots.paused=True; self.state_slots.movement_guard_active=False; break

#             res=self._wait_until_ready_or_fs(base, timeout=SPIN_CHANGE_TIMEOUT)
#             if res=="timeout":
#                 if self._rescue_once_then_wait_ready(base, wait_after_click=SPIN_CHANGE_TIMEOUT/2):
#                     res="ready"
#                 else:
#                     self._log("Did not return to READY. Pausing.","warn")
#                     self.state_slots.paused=True; self.state_slots.movement_guard_active=False; break

#             if res=="fs":
#                 self.state_slots.movement_guard_active=False
#                 continue

#             dur_ms=int((time.time()-self.state_slots.spin_started_at)*1000)
#             if dur_ms<MIN_VALID_SPIN_MS:
#                 self._blip_count+=1
#                 if self._blip_count>=MAX_CONSECUTIVE_BLIPS:
#                     self._log("Too many short blips — pausing.","warn"); self.state_slots.paused=True; self._blip_count=0; self.state_slots.movement_guard_active=False; break
#                 self._log(f"Ignored short blip ({dur_ms} ms)."); time.sleep(0.12); self.state_slots.movement_guard_active=False; continue
#             self._blip_count=0

#             self.state_slots.spin_count+=1; self._ui(self.count_var.set,self.state_slots.spin_count)
#             try:
#                 path=self._open_slots_logfile(); x,y=self.state_slots.spinner_xy  # type: ignore
#                 with open(path,"a",newline="",encoding="utf-8") as f: csv.writer(f).writerow([timestamp(), self.state_slots.spin_count, x, y, ""])
#             except Exception: pass
#             self._log(f"Spin #{self.state_slots.spin_count} complete in {dur_ms} ms.","ok")

#             if self.state_slots.stop_after_current_spin:
#                 self._log("Paused after finishing spin due to mouse movement.","warn"); self.state_slots.movement_guard_active=False; break
#             if self._target_reached():
#                 self._log(f"Target reached ({self.state_slots.spin_count}/{self.state_slots.target_spins}). Stopping.","ok"); self.state_slots.movement_guard_active=False; break

#             self.state_slots.movement_guard_active=False
#             time.sleep(DELAY_MIN + random.random()*(DELAY_MAX-DELAY_MIN))

#         self.state_slots.running=False; self.state_slots.paused=False; self.state_slots.abort=False; self._log("Stopped.")

#     # ---------- Roulette (unchanged) ----------
#     def _roulette_capture_click_point(self):
#         self._countdown("Roulette: capture wager button",3,self._roulette_capture_click_now)
#     def _roulette_capture_click_now(self):
#         self._log("Capturing wager button…","action"); xy=pyautogui.position(); self.state_roul.click_xy=xy; self._log(f"Roulette click point set at {xy}.","ok")
#         try:
#             half=30; img=grab_region(xy[0]-half,xy[1]-half,xy[0]+half,xy[1]+half)
#             tkimg=ImageTk.PhotoImage(img.resize((80,80))); self.r_click_preview.configure(image=tkimg); self.r_click_preview.image=tkimg
#         except Exception: pass
#     def _roulette_pick_banner_roi(self):
#         self._countdown("Banner ROI: move to TOP-LEFT",3,self._roulette_banner_top_left)
#     def _roulette_banner_top_left(self):
#         x1,y1=pyautogui.position(); self._log(f"Banner ROI top-left at ({x1},{y1}).","ok")
#         self._countdown("Now move to BOTTOM-RIGHT",3,lambda:self._roulette_banner_bottom_right(x1,y1))
#     def _roulette_banner_bottom_right(self,x1,y1):
#         x2,y2=pyautogui.position()
#         if x2<=x1 or y2<=y1: self._log("Invalid region.","warn"); return
#         self.state_roul.banner_roi=(x1,y1,x2-x1,y2-y1); self._ui(self.r_banner_status.config,text=f"Banner ROI: {self.state_roul.banner_roi}")
#         self._log(f"Banner ROI set: {self.state_roul.banner_roi}","ok")
#     def _roulette_get_banner_box(self)->Tuple[int,int,int,int]:
#         if self.state_roul.banner_roi: return self.state_roul.banner_roi
#         vx,vy,vw,vh=self._virtual_bounds(); rx,ry,rw,rh=ROUL_BANNER_DEFAULT
#         return (vx+int(vw*rx), vy+int(vh*ry), int(vw*rw), int(vh*rh))
#     def _roulette_banner_present(self)->bool:
#         x,y,w,h=self._roulette_get_banner_box(); img=grab_region((x,y,w,h)); rgb=img.convert("RGB"); px=rgb.load(); W,H=rgb.size
#         greenish=0
#         for yy in range(0,H,max(1,H//40)):
#             for xx in range(0,W,max(1,W//60)):
#                 r,g,b=px[xx,yy]
#                 if g-r>50 and g-b>50 and (r+g+b)>360: greenish+=1
#         denom=max(1,(H//max(1,H//40))*(W//max(1,W//60)))
#         if greenish/denom>=0.10: return True
#         try:
#             g=ImageOps.autocontrast(img.convert("L")); txt=(pytesseract.image_to_string(g,config="--oem 3 --psm 6") or "").upper()
#             return "PLACE YOUR BETS" in txt
#         except Exception: return False
#     def _roulette_no_more_bets(self)->bool:
#         x,y,w,h=self._roulette_get_banner_box(); img=grab_region((x,y,w,h)).convert("L")
#         try:
#             txt=(pytesseract.image_to_string(ImageOps.autocontrast(img),config="--oem 3 --psm 6") or "").upper()
#             return any(kw in txt for kw in ("NO MORE BETS","BETS APPROVED","BETTING HAS STARTED"))
#         except Exception: return False
#     def _toggle_roul_next_autoclick(self):
#         self.state_roul.next_btn_autoclick=True if self.r_autoclick_var.get() else False
#         self._log(f"Manual one-shot autoclick is {'ON' if self.state_roul.next_btn_autoclick else 'OFF'}.","ok")
#     def _open_roulette_logfile(self):
#         ensure_dir(LOG_DIR_ROULETTE); day=dt.datetime.now().strftime("%Y-%m-%d")
#         path=os.path.join(LOG_DIR_ROULETTE, f"{day}_session.csv")
#         if not os.path.exists(path):
#             with open(path,"w",newline="",encoding="utf-8") as f: csv.writer(f).writerow(["timestamp","wager_index","amount","cumulative_amount","remaining_amount","note"])
#         self.state_roul.log_file_path=path; return path
#     def _update_roul_stats(self):
#         left=self._roul_wagers_left() or 0
#         remaining=max(0.0,(self.state_roul.target_wager or 0.0)-self.state_roul.total_wagered)
#         self.r_stats_var.set(f"Wagers done: {self.state_roul.wagers_done} • Left: {left} • £ remaining: {remaining:.2f}")
#     def _roul_wagers_left(self)->Optional[int]:
#         s=self.state_roul
#         if s.explicit_wagers: return max(0, s.explicit_wagers - s.wagers_done)
#         if s.target_wager>0 and s.wager_amount>0: return max(0, math.ceil(s.target_wager/s.wager_amount) - s.wagers_done)
#         return None
#     def _roul_reached_goal(self)->bool:
#         s=self.state_roul
#         if s.explicit_wagers and s.wagers_done>=s.explicit_wagers: return True
#         if s.target_wager>0 and s.total_wagered>=s.target_wager: return True
#         return False
#     def _roulette_arm(self):
#         try:
#             amt=float(self.r_amount_var.get() or "0"); tgt=float(self.r_target_var.get() or "0")
#             n=int(self.r_explicit_n_var.get()) if (self.r_explicit_n_var.get() or "").strip() else None
#             if amt<=0: raise ValueError
#             if not n and tgt<=0: raise ValueError
#         except Exception: self._log("Enter valid Roulette inputs (amount and either target £ or # wagers).","warn"); return
#         s=self.state_roul; s.wager_amount=amt; s.target_wager=tgt; s.explicit_wagers=n
#         s.wagers_done=0; s.total_wagered=0.0; s.armed=True
#         s.autobanner_enabled=bool(self.r_autobanner_var.get())
#         try: s.autobanner_clicks=max(1,int(self.r_chips_per_var.get() or "1")); s.autobanner_gap=max(0.05,float(self.r_gap_var.get() or "0.20"))
#         except Exception: s.autobanner_clicks, s.autobanner_gap=1,0.20
#         self._open_roulette_logfile(); self._update_roul_stats(); self._log("Roulette session armed.","ok")
#         if s.autobanner_enabled and s.click_xy:
#             self._log("Auto-bet loop enabled (clicks only while 'Place Your Bets' is visible).","ok")
#             s.loop_running=True; threading.Thread(target=self._roulette_loop,daemon=True).start()
#         elif s.autobanner_enabled and not s.click_xy:
#             self._log("Set the wager button first (Capture Wager Button).","warn")
#     def _roulette_loop(self):
#         s=self.state_roul
#         while s.armed and s.loop_running:
#             if self._roul_reached_goal(): break
#             if not self._roulette_banner_present(): time.sleep(0.20); continue
#             if s.click_xy:
#                 x,y=s.click_xy
#                 for _ in range(s.autobanner_clicks):
#                     pyautogui.moveTo(x,y,duration=0.06); pyautogui.click(); time.sleep(s.autobanner_gap)
#             s.wagers_done+=1; s.total_wagered+=s.wager_amount; self._update_roul_stats(); self._log_roulette_row("auto")
#             t0=time.time()
#             while self._roulette_banner_present() and time.time()-t0<10: time.sleep(0.15)
#             if self._roulette_no_more_bets(): time.sleep(0.5)
#             if self._roul_reached_goal(): break
#         s.loop_running=False
#         if self._roul_reached_goal(): self._log("Roulette target reached. Disarming.","ok"); s.armed=False
#     def _log_roulette_row(self,note:str):
#         try:
#             path=self._open_roulette_logfile(); remaining=max(0.0,(self.state_roul.target_wager or 0.0)-self.state_roul.total_wagered)
#             with open(path,"a",newline="",encoding="utf-8") as f:
#                 csv.writer(f).writerow([timestamp(), self.state_roul.wagers_done, f"{self.state_roul.wager_amount:.2f}", f"{self.state_roul.total_wagered:.2f}", f"{remaining:.2f}", note])
#         except Exception: pass
#     def _roulette_next(self):
#         s=self.state_roul
#         if not s.armed: self._log("Roulette is not armed. Click 'Start / Arm' first.","warn"); return
#         if s.next_btn_autoclick and s.click_xy:
#             x,y=s.click_xy; pyautogui.moveTo(x,y,duration=0.06); pyautogui.click()
#         s.wagers_done+=1; s.total_wagered+=s.wager_amount; self._update_roul_stats(); self._log_roulette_row("manual")
#     def _roulette_undo(self):
#         s=self.state_roul
#         if s.wagers_done<=0: self._log("Nothing to undo.","warn"); return
#         s.wagers_done-=1; s.total_wagered=max(0.0, s.total_wagered - s.wager_amount); self._update_roul_stats(); self._log_roulette_row("undo")
#     def _roulette_finish(self):
#         s=self.state_roul; s.armed=False; s.loop_running=False; self._log("Roulette session finished.","ok")

#     # ---------- Clicker (manual) logic ----------
#     def _click_at_spinner_then_return(self, source_button: tk.Widget)->bool:
#         if self.state_slots.running:
#             self._log("Stop Slots auto before using the Clicker.","warn"); return False
#         if not self.state_slots.spinner_xy:
#             self._log("Capture Click Point / Spinner first.","warn"); return False
#         try:
#             bx=source_button.winfo_rootx()+source_button.winfo_width()//2
#             by=source_button.winfo_rooty()+source_button.winfo_height()//2
#         except Exception:
#             bx,by=self.root.winfo_rootx()+40,self.root.winfo_rooty()+40
#         sx,sy=self.state_slots.spinner_xy
#         pyautogui.moveTo(sx+random.randint(-JITTER_PX,JITTER_PX), sy+random.randint(-JITTER_PX,JITTER_PX), duration=0.06)
#         pyautogui.click()
#         pyautogui.moveTo(bx,by,duration=0.06)
#         return True

#     # A) target calculator
#     def _clicker_compute(self):
#         try:
#             reward=float(self.ck_reward_var.get()); mult=float(self.ck_wagerx_var.get()); per=float(self.ck_perclick_var.get())
#             if reward<=0 or mult<=0 or per<=0: raise ValueError
#             total=reward*mult; clicks=math.ceil(total/per)
#             self.ck_target_var.set(clicks); self.ck_progress_var.set(0)
#             self.ck_click_btn.configure(state="normal")
#             self._log(f"Clicker target set: {clicks} clicks (total wagering £{total:.2f}).","ok")
#         except Exception:
#             self._log("Enter valid numbers for Reward £, Wagering ×, and £ per click.","warn")

#     def _clicker_target_click(self, btn: tk.Widget):
#         if not self._click_at_spinner_then_return(btn): return
#         cur=self.ck_progress_var.get()+1; self.ck_progress_var.set(cur)
#         tgt=self.ck_target_var.get()
#         self._log(f"Clicker (target): shot #{cur}")
#         if tgt>0 and cur>=tgt:
#             try: self.ck_click_btn.configure(state="disabled")
#             except Exception: pass
#             self._log("Clicker target reached; button disabled.","ok")

#     def _clicker_target_reset(self):
#         self.ck_progress_var.set(0)
#         if self.ck_target_var.get()>0: self.ck_click_btn.configure(state="normal")
#         self._log("Clicker target progress reset.","ok")

#     # B) free clicker (with optional target)
#     def _free_target_changed(self):
#         """When user edits the optional free target, re-enable the Click if now below target."""
#         try: tgt=int(self.free_target_var.get() or "0")
#         except Exception: tgt=0
#         if tgt==0 or self.free_count_var.get()<tgt:
#             try: self.free_click_btn.configure(state="normal")
#             except Exception: pass

#     def _clicker_free_click(self, btn: tk.Widget):
#         if not self._click_at_spinner_then_return(btn): return
#         cur=self.free_count_var.get()+1; self.free_count_var.set(cur)
#         self._log(f"Clicker (free): shot #{cur}")
#         try: tgt=int(self.free_target_var.get() or "0")
#         except Exception: tgt=0
#         if tgt>0 and cur>=tgt:
#             try: self.free_click_btn.configure(state="disabled")
#             except Exception: pass
#             self._log("Free clicker target reached; button disabled.","ok")

#     def _clicker_free_reset(self):
#         self.free_count_var.set(0)
#         try: self.free_click_btn.configure(state="normal")
#         except Exception: pass
#         self._log("Clicker (free) counter reset.","ok")

#     # ---------- close ----------
#     def _on_close(self):
#         try:
#             self.state_slots.abort=True; self.state_slots.running=False; self.state_slots.paused=False
#             self.state_roul.loop_running=False; self.state_roul.armed=False
#         except Exception: pass
#         self._closing=True; self._cancel_all_after()
#         try: self.root.quit()
#         except Exception: pass
#         try: self.root.destroy()
#         except Exception: pass

# def main():
#     root=tk.Tk(); app=SpinHelperApp(root); root.mainloop()
# if __name__=="__main__": main()












