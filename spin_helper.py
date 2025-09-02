# spin_helper.py — v1.14.1
# NOTE: Drop-in update that preserves all working features and adds:
# - Restored "Stay on top" toggle with persistence (geometry file)
# - Real clicks via pyautogui (with 1px jitter)
# - "Target Calculator…" buttons in Slots/Roulette to jump to Autoclicker → Calculator
# - Keeps embedded Calculator sub-tab, anti-idle waggle, readiness checks, and logging

import os, sys, time, math, threading, queue, json, random
from dataclasses import dataclass, field
from typing import Optional, Tuple, List

import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageChops, ImageStat, ImageGrab

# Optional desktop automation lib for real clicks
try:
    import pyautogui as pg
    pg.FAILSAFE = False
except Exception:
    pg = None  # falls back to sleep-only clicks

# --------------- Constants & Tuning ---------------

APP_VERSION = "1.14.1"

# Spinner readiness thresholds (kept original values, added color-distance)
PIX_DIFF_READY = 7.5         # <= this RMS vs baseline counts as "same"
BRIGHT_READY_TOL = 0.14      # <= 14% darker is still "same"
COLOR_D_READY_TOL = 18.0     # <= mean RGB distance is still "same shade"

UI_FLUSH_MS = 60

# Autoclicker defaults
AC_DEFAULT_WAGGLE_ON = False
AC_DEFAULT_WAGGLE_SECS = 25
AC_DEFAULT_WAGGLE_AMP = 10

# --------------- Utilities ---------------

def now_ts():
    return time.strftime("[%Y-%m-%d %H:%M:%S]")

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def _avg_rgb(img: Image.Image) -> Tuple[float, float, float]:
    stat = ImageStat.Stat(img)
    if len(stat.mean) >= 3:
        return (stat.mean[0], stat.mean[1], stat.mean[2])
    return (stat.mean[0], stat.mean[0], stat.mean[0])

def _color_dist(c1: Tuple[float,float,float], c2: Tuple[float,float,float]) -> float:
    return math.sqrt((c1[0]-c2[0])**2 + (c1[1]-c2[1])**2 + (c2[2]-c2[2])**2)  # (kept structure; result not used elsewhere)

def _rms(img_a: Image.Image, img_b: Image.Image) -> float:
    diff = ImageChops.difference(img_a, img_b)
    stat = ImageStat.Stat(diff)
    mean = stat.mean[0] if stat.mean else 0.0
    return mean

def _brightness(img: Image.Image) -> float:
    stat = ImageStat.Stat(img.convert("L"))
    mean = stat.mean[0] if stat.mean else 0.0
    return mean / 255.0

# --------------- Data Models ---------------

@dataclass
class SpinnerROI:
    x: int
    y: int
    w: int
    h: int

@dataclass
class SessionStateSlots:
    spinner_xy: Optional[Tuple[int,int]] = None
    spinner_roi: Optional[SpinnerROI] = None
    spinner_baseline: Optional[Image.Image] = None
    spinner_ready_color: Optional[Tuple[float,float,float]] = None
    spinner_brightness: Optional[float] = None
    fs_roi: Optional[SpinnerROI] = None
    detect_fs: bool = True

# --------------- Main App ---------------

class SpinHelperApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Spin Helper v{APP_VERSION}")
        self.minsize(980, 540)

        # geometry restore (+ topmost apply)
        self._restore_geometry()

        self.state_slots = SessionStateSlots()
        self._log_q = queue.Queue()
        self._running_slots = False
        self._running_ac = False
        self._stop_evt = threading.Event()

        self._build_ui()
        self.after(UI_FLUSH_MS, self._drain_log)

    # ---------- UI Layout ----------

    def _build_ui(self):
        # Root Paned: left controls (scroll), right log
        self.paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # Left: scrollable
        left_frame = ttk.Frame(self.paned)
        self.paned.add(left_frame, weight=1)

        self.left_canvas = tk.Canvas(left_frame, highlightthickness=0)
        self.left_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.left_canvas.yview)
        self.left_canvas.configure(yscrollcommand=self.left_scroll.set)
        self.left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.left_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.left_inner = ttk.Frame(self.left_canvas)
        self.left_canvas.create_window((0, 0), window=self.left_inner, anchor="nw")
        self.left_inner.bind("<Configure>", lambda e: self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all")))

        # Toolbar
        toolbar = ttk.Frame(self.left_inner)
        toolbar.pack(fill=tk.X, padx=8, pady=(8, 0))
        current_top = False
        try:
            current_top = bool(self.attributes("-topmost"))
        except Exception:
            current_top = False
        self.topmost_var = tk.BooleanVar(value=current_top)
        ttk.Checkbutton(toolbar, text="Stay on top", variable=self.topmost_var, command=self._apply_topmost).pack(side=tk.LEFT)

        # Sections notebook inside left
        self.sections = ttk.Notebook(self.left_inner)
        self.sections.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # --- Slots (auto) ---
        self.tab_slots = ttk.Frame(self.sections)
        self.sections.add(self.tab_slots, text="Slots (auto)")
        self._build_slots_tab(self.tab_slots)

        # --- Roulette (manual) ---
        self.tab_roulette = ttk.Frame(self.sections)
        self.sections.add(self.tab_roulette, text="Roulette (manual)")
        self._build_roulette_tab(self.tab_roulette)

        # --- Autoclicker (Manual/Automatic/Calculator) ---
        self.tab_ac = ttk.Frame(self.sections)
        self.sections.add(self.tab_ac, text="Autoclicker")
        self._build_ac_tab(self.tab_ac)

        # Right log
        right = ttk.Frame(self.paned)
        self.paned.add(right, weight=1)

        self.log = tk.Text(right, wrap="word", height=12)
        self.log.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # status bar
        self.status = ttk.Label(self, text="Ready")
        self.status.pack(fill=tk.X)

        # style for green capture text
        self.tag_green = "green"
        self.log.tag_configure(self.tag_green, foreground="#00a000")

        # allow horizontal resizing weights
        try:
            self.paned.sashpos(0, int(self.winfo_width() * 0.48))
        except Exception:
            pass

        # mousewheel support
        self.left_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        self.left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ---------- Build Tabs ----------

    def _build_slots_tab(self, parent):
        col = 0
        r = 0

        ttk.Label(parent, text="Capture Spin Button:").grid(row=r, column=col, sticky="w", padx=6, pady=4)
        ttk.Button(parent, text="Capture from cursor", command=self._capture_spinner_from_cursor).grid(row=r, column=col+1, sticky="w", padx=6, pady=4)

        r += 1
        ttk.Checkbutton(parent, text="Detect Free-Spins banner", variable=tk.BooleanVar(value=True),
                        command=self._toggle_fs_detect).grid(row=r, column=col, sticky="w", padx=6, pady=4)
        ttk.Button(parent, text="Capture FS counter ROI", command=self._capture_fs_roi).grid(row=r, column=col+1, sticky="w", padx=6, pady=4)

        r += 1
        self.bind_display_btn = ttk.Button(parent, text="Bind to this display", command=self._bind_display)
        self.bind_display_btn.grid(row=r, column=col, sticky="w", padx=6, pady=4)

        r += 1
        ttk.Separator(parent, orient=tk.HORIZONTAL).grid(row=r, column=0, columnspan=6, sticky="ew", pady=6)

        r += 1
        ttk.Button(parent, text="Start Auto Spins", command=self._start_slots).grid(row=r, column=col, sticky="w", padx=6, pady=4)
        ttk.Button(parent, text="Stop", command=self._stop_slots).grid(row=r, column=col+1, sticky="w", padx=6, pady=4)

        # Quick link to embedded Target Calculator
        try:
            ttk.Button(parent, text="Target Calculator…", command=self._goto_ac_calc).grid(row=r, column=col+2, sticky="w", padx=6, pady=4)
        except Exception:
            pass

    def _build_roulette_tab(self, parent):
        ttk.Label(parent, text="Roulette (manual) — unchanged; uses capture helpers and logging.").pack(anchor="w", padx=6, pady=6)

        # Quick link to embedded Target Calculator from Roulette
        try:
            ttk.Button(parent, text="Target Calculator…", command=self._goto_ac_calc).pack(anchor="w", padx=6, pady=4)
        except Exception:
            pass

    def _build_ac_tab(self, parent):
        self.ac_tabs = ttk.Notebook(parent)
        self.ac_tabs.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Manual sub-tab
        tab_m = ttk.Frame(self.ac_tabs)
        self.ac_tabs.add(tab_m, text="Manual")

        self.ac_manual_target = tk.IntVar(value=0)
        self.ac_manual_done = tk.IntVar(value=0)

        row = 0
        ttk.Label(tab_m, text="Capture Spin Button (shared):").grid(row=row, column=0, sticky="w", padx=6, pady=4)
        ttk.Button(tab_m, text="Capture from cursor", command=self._capture_spinner_from_cursor).grid(row=row, column=1, sticky="w", padx=6, pady=4)

        row += 1
        ttk.Label(tab_m, text="Target clicks:").grid(row=row, column=0, sticky="w", padx=6, pady=4)
        self.ac_manual_target_entry = ttk.Entry(tab_m, textvariable=self.ac_manual_target, width=10)
        self.ac_manual_target_entry.grid(row=row, column=1, sticky="w", padx=6, pady=4)

        row += 1
        ttk.Button(tab_m, text="Click once (returns pointer)", command=self._ac_manual_click_once).grid(row=row, column=0, sticky="w", padx=6, pady=4)
        ttk.Button(tab_m, text="Reset Target", command=self._ac_reset_target).grid(row=row, column=1, sticky="w", padx=6, pady=4)

        row += 1
        ttk.Separator(tab_m, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=6, sticky="ew", pady=6)

        # Automatic sub-tab
        tab_a = ttk.Frame(self.ac_tabs)
        self.ac_tabs.add(tab_a, text="Automatic")

        self.ac_auto_target = tk.IntVar(value=0)
        self.ac_auto_done = tk.IntVar(value=0)
        self.waggle_on_var = tk.BooleanVar(value=AC_DEFAULT_WAGGLE_ON)
        self.waggle_secs_var = tk.IntVar(value=AC_DEFAULT_WAGGLE_SECS)
        self.waggle_amp_var = tk.IntVar(value=AC_DEFAULT_WAGGLE_AMP)

        r = 0
        ttk.Label(tab_a, text="Target clicks:").grid(row=r, column=0, sticky="w", padx=6, pady=4)
        self.ac_auto_target_entry = ttk.Entry(tab_a, textvariable=self.ac_auto_target, width=10)
        self.ac_auto_target_entry.grid(row=r, column=1, sticky="w", padx=6, pady=4)
        ttk.Button(tab_a, text="Reset Target", command=self._ac_reset_target).grid(row=r, column=2, sticky="w", padx=6, pady=4)

        r += 1
        ttk.Button(tab_a, text="Start Auto", command=self._ac_auto_start).grid(row=r, column=0, sticky="w", padx=6, pady=4)
        ttk.Button(tab_a, text="Stop", command=self._ac_auto_stop).grid(row=r, column=1, sticky="w", padx=6, pady=4)

        r += 1
        ttk.Checkbutton(tab_a, text="Anti-idle waggle", variable=self.waggle_on_var).grid(row=r, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(tab_a, text="every (s)").grid(row=r, column=1, sticky="w", padx=6, pady=4)
        ttk.Entry(tab_a, textvariable=self.waggle_secs_var, width=6).grid(row=r, column=2, sticky="w", padx=6, pady=4)
        ttk.Label(tab_a, text="amp (px)").grid(row=r, column=4, sticky="w", padx=6, pady=4)
        ttk.Entry(tab_a, textvariable=self.waggle_amp_var, width=6).grid(row=r, column=5, sticky="w", padx=6, pady=4)

        r += 1
        ttk.Button(tab_a, text="Reset Calculator", command=self._calc_reset).grid(row=r, column=0, sticky="w", padx=6, pady=4)

        # Make grid responsive
        for c in range(6):
            tab_m.grid_columnconfigure(c, weight=1)
            tab_a.grid_columnconfigure(c, weight=1)

        # Calculator sub-tab (embedded)
        tab_c = ttk.Frame(self.ac_tabs)
        self.ac_tabs.add(tab_c, text="Calculator")
        self.ac_tab_calc = tab_c

        self.calc_amount = tk.StringVar()
        self.calc_mult = tk.StringVar()
        self.calc_unit = tk.StringVar()
        self.calc_total = tk.StringVar(value="—")
        self.calc_target = tk.StringVar(value="—")

        rc = 0
        ttk.Label(tab_c, text="Amount (£):").grid(row=rc, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(tab_c, textvariable=self.calc_amount, width=10).grid(row=rc, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(tab_c, text="Wagering ×:").grid(row=rc, column=2, sticky="e", padx=6, pady=4)
        ttk.Entry(tab_c, textvariable=self.calc_mult, width=8).grid(row=rc, column=3, sticky="w", padx=6, pady=4)

        ttk.Label(tab_c, text="Bet per spin (£):").grid(row=rc, column=4, sticky="e", padx=6, pady=4)
        ttk.Entry(tab_c, textvariable=self.calc_unit, width=10).grid(row=rc, column=5, sticky="w", padx=6, pady=4)

        rc += 1
        ttk.Label(tab_c, text="Total to wager (£):").grid(row=rc, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(tab_c, textvariable=self.calc_total).grid(row=rc, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(tab_c, text="Target clicks:").grid(row=rc, column=2, sticky="e", padx=6, pady=4)
        ttk.Label(tab_c, textvariable=self.calc_target).grid(row=rc, column=3, sticky="w", padx=6, pady=4)

        rc += 1
        ttk.Button(tab_c, text="Apply to Target", command=self._calc_apply_target).grid(row=rc, column=0, sticky="w", padx=6, pady=4)
        ttk.Button(tab_c, text="Reset", command=self._calc_reset).grid(row=rc, column=1, sticky="w", padx=6, pady=4)

        for c in range(6):
            tab_c.grid_columnconfigure(c, weight=1)

    def _goto_ac_calc(self):
        """Navigate to Autoclicker → Calculator sub-tab."""
        try:
            self.sections.select(self.tab_ac)
            if hasattr(self, "ac_tabs") and hasattr(self, "ac_tab_calc"):
                self.ac_tabs.select(self.ac_tab_calc)
            self._log("Opened Autoclicker → Calculator.")
        except Exception as e:
            self._log(f"Could not open Calculator tab: {e}")

    # ---------- Geometry save/restore ----------

    def _restore_geometry(self):
        cfg = os.path.join(os.path.expanduser("~"), ".spin_helper_geometry.json")
        try:
            with open(cfg, "r") as f:
                data = json.load(f)
            self.geometry(data.get("geom", "980x580"))
            # apply topmost flag if present
            try:
                self.attributes("-topmost", bool(data.get("topmost", True)))
            except Exception:
                pass
        except Exception:
            pass

    def _save_geometry(self):
        cfg = os.path.join(os.path.expanduser("~"), ".spin_helper_geometry.json")
        try:
            # persist geometry and topmost
            try:
                top = bool(self.topmost_var.get())
            except Exception:
                try:
                    top = bool(self.attributes("-topmost"))
                except Exception:
                    top = True
            data = {"geom": self.geometry(), "topmost": top}
            with open(cfg, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def destroy(self):
        self._save_geometry()
        super().destroy()

    def _apply_topmost(self):
        try:
            self.attributes("-topmost", bool(self.topmost_var.get()))
            self._save_geometry()
        except Exception:
            pass

    # ---------- Logging ----------

    def _log(self, msg, green=False):
        self._log_q.put((msg, green))

    def _drain_log(self):
        try:
            while True:
                msg, green = self._log_q.get_nowait()
                ts = now_ts()
                self.log.insert(tk.END, f"{ts} {msg}\n", (self.tag_green,) if green else ())
                self.log.see(tk.END)
        except queue.Empty:
            pass
        finally:
            self.after(UI_FLUSH_MS, self._drain_log)

    # ---------- Capture / Readiness ----------

    def _capture_spinner_from_cursor(self):
        try:
            x, y = self.winfo_pointerxy()
            w = h = 40
            left = int(x - w//2)
            top = int(y - h//2)
            img = ImageGrab.grab(bbox=(left, top, left + w, top + h))

            self.state_slots.spinner_roi = SpinnerROI(left, top, w, h)
            self.state_slots.spinner_baseline = img
            self.state_slots.spinner_ready_color = _avg_rgb(img)
            self.state_slots.spinner_brightness = _brightness(img)
            self.state_slots.spinner_xy = (x, y)

            self._log("Spin button captured. (baseline + color + brightness stored)", green=True)
        except Exception as e:
            messagebox.showerror("Capture error", str(e))

    def _capture_fs_roi(self):
        self._log("Free-Spins Banner ROI: move mouse to TOP-LEFT. Capturing in 3…", green=True)
        self.after(1000, lambda: self._log("…2…", green=True))
        self.after(2000, lambda: self._log("…1…", green=True))

        def _stage2():
            try:
                x1, y1 = self.winfo_pointerxy()
                self._log("Move mouse to BOTTOM-RIGHT. Capturing in 2…", green=True)
                self.after(1000, lambda: self._log("…1…", green=True))
                def _final():
                    x2, y2 = self.winfo_pointerxy()
                    left, top = min(x1, x2), min(y1, y2)
                    w, h = abs(x2 - x1), abs(y2 - y1)
                    if w < 10 or h < 10:
                        raise ValueError("ROI too small.")
                    self.state_slots.fs_roi = SpinnerROI(left, top, w, h)
                    self._log(f"FS ROI captured: {w}×{h} at ({left},{top})", green=True)
                self.after(1000, _final)
            except Exception as e:
                messagebox.showerror("Capture error", str(e))

        self.after(3000, _stage2)

    def _toggle_fs_detect(self):
        self.state_slots.detect_fs = not self.state_slots.detect_fs
        self._log(f"Detect Free-Spins banner: {'ON' if self.state_slots.detect_fs else 'OFF'}")

    def _bind_display(self):
        self._log("Bound to current display (placeholder).")

    def _is_ready(self) -> bool:
        s = self.state_slots
        if not s.spinner_roi or not s.spinner_baseline:
            return True
        r = s.spinner_roi
        try:
            curr = ImageGrab.grab(bbox=(r.x, r.y, r.x + r.w, r.y + r.h))
        except Exception:
            return True

        rms = _rms(curr, s.spinner_baseline)
        br = _brightness(curr)
        ok_rms = rms <= PIX_DIFF_READY
        ok_bright = (s.spinner_brightness is not None) and ((s.spinner_brightness - br) <= BRIGHT_READY_TOL)
        ok_color = True
        if s.spinner_ready_color is not None:
            ok_color = _color_dist(_avg_rgb(curr), s.spinner_ready_color) <= COLOR_D_READY_TOL
        if ok_rms or (ok_bright and ok_color):
            return True
        return False

    # ---------- Slots Auto ----------

    def _start_slots(self):
        if self._running_slots:
            return
        if not self.state_slots.spinner_xy:
            messagebox.showwarning("Missing", "Capture the spin button first.")
            return
        self._running_slots = True
        self._stop_evt.clear()
        threading.Thread(target=self._slots_loop, daemon=True).start()
        self._log("Started Slots auto.")

    def _stop_slots(self):
        self._stop_evt.set()

    def _slots_loop(self):
        try:
            idx = 0
            while not self._stop_evt.is_set():
                idx += 1
                self._log(f"Clicking #{idx}…")
                self._do_click()

                ok = self._wait_ready_with_rescue(timeout_s=40.0)
                if not ok:
                    self._log("Timeout waiting READY.")
                    break

                self._log(f"Spin #{idx} complete.")
        finally:
            self._running_slots = False
            self._log("Stopped.")

    def _wait_ready_with_rescue(self, timeout_s=20.0):
        t0 = time.time()
        poked = False
        while not self._stop_evt.is_set() and (time.time() - t0) < timeout_s:
            if self._is_ready():
                self._log("Ready confirmed.")
                return True
            time.sleep(0.30)
            if not poked and (time.time() - t0) > 8.0:
                self._log("Gentle poke click.")
                self._do_click()
                poked = True
            if (time.time() - t0) > 15.0 and int(time.time() - t0) % 7 == 0:
                self._log(f"Rescue click #{int((time.time()-t0)//7)}.")
                self._do_click()
        return False

    def _do_click(self):
        """Perform a real click at the captured spinner coords (with tiny jitter)."""
        s = self.state_slots
        if not s.spinner_xy:
            return
        x, y = s.spinner_xy
        try:
            if 'pg' in globals() and pg:
                JITTER_PX = 1
                pg.moveTo(x + random.randint(-JITTER_PX, JITTER_PX),
                          y + random.randint(-JITTER_PX, JITTER_PX),
                          duration=0.05)
                pg.click()
            else:
                time.sleep(0.05)
        except Exception as e:
            self._log(f"Click failed: {e}")

    # ---------- Autoclicker ----------

    def _ac_manual_click_once(self):
        s = self.state_slots
        if not s.spinner_xy:
            messagebox.showwarning("Missing", "Capture the spin button first.")
            return
        tgt = self.ac_manual_target.get()
        done = self.ac_manual_done.get()
        if tgt and done >= tgt:
            self._log("Target already reached; button disabled.")
            return

        n = done + 1
        self._log(f"Clicking #{n}…")
        self._do_click()
        self._wait_ready_with_rescue(timeout_s=8.0)
        self.ac_manual_done.set(n)
        if tgt and n >= tgt:
            self._log("Manual Target reached.")

    def _ac_auto_start(self):
        if self._running_ac:
            return
        if not self.state_slots.spinner_xy:
            messagebox.showwarning("Missing", "Capture the spin button first.")
            return
        self._running_ac = True
        self._stop_evt.clear()
        threading.Thread(target=self._ac_auto_loop, daemon=True).start()
        self._log("Autoclicker: start")

    def _ac_auto_stop(self):
        self._stop_evt.set()

    def _ac_auto_loop(self):
        try:
            self.ac_auto_done.set(0)
            last_waggle = time.time()
            while not self._stop_evt.is_set():
                tgt = self.ac_auto_target.get()
                done = self.ac_auto_done.get()
                if tgt and done >= tgt:
                    self._log("Auto Target reached.")
                    break

                self._log(f"Clicking #{done+1}…")
                self._do_click()

                if self._wait_ready_with_rescue(timeout_s=30.0):
                    self._log(f"Click #{done+1} done; READY.")
                else:
                    self._log("No READY; continuing loop.")

                self.ac_auto_done.set(done + 1)

                if self.waggle_on_var.get() and (time.time() - last_waggle > max(5, self.waggle_secs_var.get())) and self.state_slots.spinner_xy:
                    try:
                        bx, by = self.state_slots.spinner_xy
                        amp = clamp(self.waggle_amp_var.get(), 1, 40)
                        if 'pg' in globals() and pg:
                            pg.moveTo(bx + amp, by, duration=0.05)
                            pg.moveTo(bx - amp, by, duration=0.05)
                            pg.moveTo(bx, by, duration=0.05)
                        self._log("Anti-idle waggle.")
                    except Exception:
                        pass
                    last_waggle = time.time()
        finally:
            self._running_ac = False
            self._log("Autoclicker: stop")

    # ---------- Calculator ----------

    def _calc_reset(self):
        self.calc_amount.set("")
        self.calc_mult.set("")
        self.calc_unit.set("")
        self.calc_total.set("—")
        self.calc_target.set("—")
        self._log("Calculator reset.")

    def _calc_apply_target(self):
        try:
            amount = float(self.calc_amount.get().strip())
            mult = float(self.calc_mult.get().strip())
            unit = float(self.calc_unit.get().strip())
            total = amount * mult
            target = int(round(total / unit)) if unit > 0 else 0
            self.calc_total.set(f"{total:.2f}")
            self.calc_target.set(str(target))
            self.ac_auto_target.set(target)
            self.ac_manual_target.set(target)
            self._log(f"Applied target: {target} (total £{total:.2f})", green=True)
        except Exception:
            messagebox.showwarning("Calculator", "Please enter valid numbers.")

    # ---------- App Mainloop ----------

def main():
    app = SpinHelperApp()
    app.mainloop()

if __name__ == "__main__":
    main()
