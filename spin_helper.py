# spin_helper.py — v1.18.0
from __future__ import annotations
# FIXED: Counter mode click detection, cross-contamination, consistent button behavior
# FIXED: Slots mouse positioning, proper state isolation between modes

import os
import sys
import time
import json
import queue
import threading
import subprocess
import random
import math
from dataclasses import dataclass
from typing import Optional, Tuple, List
from enum import Enum

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

# Import checks
PIL_AVAILABLE = False
PYAUTOGUI_AVAILABLE = False
PYNPUT_AVAILABLE = False

try:
    from PIL import Image, ImageGrab, ImageChops, ImageStat, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    print("WARNING: PIL (Pillow) not available - image processing disabled")

try:
    import pyautogui as pg
    pg.FAILSAFE = False
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    print("WARNING: PyAutoGUI not available - automation disabled")

try:
    from pynput import mouse, keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    print("INFO: pynput not available - click detection disabled")

# --------------- Constants ---------------

APP_VERSION = "1.18.2"
UI_FLUSH_MS = 60
SESSIONS_DIR = os.path.join(os.path.expanduser("~"), "spin_helper_sessions")

# Spin detection thresholds
PIX_DIFF_READY = 4.0
PIX_DIFF_CHANGED = 10.0
SPIN_CHANGE_TIMEOUT = 25.0
CHANGE_STICK_MS = 180
# Minimum spin duration heuristic (for logging only). Spins shorter than this
# will be flagged as "short" but still counted to avoid false negatives.
MIN_VALID_SPIN_MS = 2500
MAX_CONSECUTIVE_BLIPS = 3

# Long-spin handling (avoid premature rescues on long wins/anticipation)
LONG_SPIN_GRACE_SEC = 4.0

# Pre-click readiness handling (Automatic/Slots): allow multiple grace clicks
PRE_READY_INITIAL_WAIT = 4.0
PRE_READY_GRACE_CLICKS = 3
PRE_READY_WAIT_AFTER_CLICK = 10.0
PRE_READY_MAX_TIMEOUT = 45.0

# Free-Spins animation heuristics (optional; only if FS ROI is set)
FS_ANIM_RMS_ACTIVE = 5.0  # average RMS threshold to consider area "active"

# Mouse movement pause detection
MOUSE_PAUSE_THRESHOLD = 80
MOUSE_CHECK_INTERVAL = 0.5

# Click timing
JITTER_PX = 2
DELAY_MIN, DELAY_MAX = 0.35, 0.75
GRACE_PERIOD_SECS = 1.0

# Defaults
AC_DEFAULT_WAGGLE_ON = False
AC_DEFAULT_WAGGLE_SECS = 25
AC_DEFAULT_WAGGLE_AMP = 10

# --------------- Enums ---------------

class SpinState(Enum):
    READY = "ready"
    NOT_READY = "not_ready"
    UNKNOWN = "unknown"

class AutomationMode(Enum):
    STOPPED = "stopped"
    READY = "ready"
    RUNNING = "running" 
    PAUSED = "paused"

class PreClickPhase(Enum):
    INITIAL_WAIT = "initial_wait"
    OVERLAY_PROGRESS = "overlay_progress"
    FS_HOLD = "fs_hold"
    READY = "ready"
    TIMEOUT = "timeout"

# --------------- Utility Functions ---------------

def now_ts():
    return time.strftime("[%Y-%m-%d %H:%M:%S]")

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def _avg_rgb(img: Image.Image) -> Tuple[float, float, float]:
    if not PIL_AVAILABLE:
        return (0.0, 0.0, 0.0)
    stat = ImageStat.Stat(img)
    if len(stat.mean) >= 3:
        return (stat.mean[0], stat.mean[1], stat.mean[2])
    return (stat.mean[0], stat.mean[0], stat.mean[0])

def _rms(img_a: Image.Image, img_b: Image.Image) -> float:
    if not PIL_AVAILABLE:
        return 0.0
    diff = ImageChops.difference(img_a, img_b)
    stat = ImageStat.Stat(diff)
    return stat.mean[0] if stat.mean else 0.0

def _brightness(img: Image.Image) -> float:
    if not PIL_AVAILABLE:
        return 0.5
    stat = ImageStat.Stat(img.convert("L"))
    return (stat.mean[0] if stat.mean else 0.0) / 255.0

# --------------- Data Models ---------------

@dataclass
class SpinnerROI:
    x: int
    y: int
    w: int
    h: int

@dataclass
class SpinnerCapture:
    roi: Optional[SpinnerROI] = None
    baseline_ready: Optional[Image.Image] = None
    aux_roi: Optional[SpinnerROI] = None
    aux_baseline_ready: Optional[Image.Image] = None
    ready_color: Optional[Tuple[float, float, float]] = None
    ready_brightness: Optional[float] = None
    center_xy: Optional[Tuple[int, int]] = None
    capture_time: Optional[float] = None
    is_valid: bool = False
    thumbnail: Optional[ImageTk.PhotoImage] = None

@dataclass
class AutomationState:
    mode: AutomationMode = AutomationMode.STOPPED
    total_done: int = 0
    target_count: int = 0
    paused_by_mouse: bool = False
    paused_manually: bool = False
    stop_requested: bool = False
    last_mouse_pos: Optional[Tuple[int,int]] = None
    actual_clicks: int = 0
    suppress_mouse_pause_until: float = 0.0
    
@dataclass
class SessionStateSlots:
    spinner: SpinnerCapture = None
    fs_roi: Optional[SpinnerROI] = None
    detect_fs: bool = True
    automation: AutomationState = None
    suppress_overlay_pause: bool = True
    suppress_overlay_secs: float = 11.0
    
    def __post_init__(self):
        if self.spinner is None:
            self.spinner = SpinnerCapture()
        if self.automation is None:
            self.automation = AutomationState()

@dataclass
class WindowInfo:
    title: str
    app_name: str
    window_id: Optional[str] = None

# --------------- Click Detection for Counter Mode ---------------

class ClickDetector:
    def __init__(self, app_instance):
        self.app = app_instance
        self.monitoring = False
        self.mouse_listener = None
        self.last_click_ts: Optional[float] = None
        
    def start_monitoring(self):
        if self.monitoring or not PYNPUT_AVAILABLE:
            return
        self.monitoring = True
        try:
            self.mouse_listener = mouse.Listener(on_click=self._on_click)
            self.mouse_listener.daemon = True
            self.mouse_listener.start()
            self.app._log("Click detection started for Counter mode")
        except Exception as e:
            self.app._log(f"Click detection failed to start: {e}")
            
    def stop_monitoring(self):
        if self.mouse_listener:
            try:
                self.mouse_listener.stop()
            except:
                pass
            self.mouse_listener = None
        self.monitoring = False
        
    def _on_click(self, x, y, button, pressed):
        # Only count left button press (not release)
        if button == mouse.Button.left and pressed:
            # Check if click is near spinner location and Counter mode is active
            if hasattr(self.app, 'counter_mode_active') and self.app.counter_mode_active:
                if self.app.state_slots.spinner.center_xy:
                    sx, sy = self.app.state_slots.spinner.center_xy
                    distance = math.sqrt((x - sx)**2 + (y - sy)**2)
                    if distance <= 50:  # Click within 50px of spinner
                        # Log interval between clicks as an approximation of spin duration
                        now_t = time.time()
                        if self.last_click_ts is not None:
                            dt_ms = (now_t - self.last_click_ts) * 1000.0
                            self.app._log(f"Counter: ~{dt_ms:.0f} ms since last click")
                        self.last_click_ts = now_t
                        # Increment Actual Clicks for Counter mode (guarded)
                        try:
                            self.app._inc_actual_clicks(x, y)
                        except Exception:
                            pass
                        current = self.app.clicker_manual_done.get()
                        target = self.app.clicker_manual_target.get()
                        if target == 0 or current < target:
                            self.app.clicker_manual_done.set(current + 1)
                            self.app._log(f"Counter: Click #{current + 1} detected", green=True)
                            if target > 0 and current + 1 >= target:
                                self.app._log("Counter target reached", green=True)

# --------------- Mouse Movement Monitor ---------------

class MouseMonitor:
    def __init__(self, state: SessionStateSlots, log_func):
        self.state = state
        self.log = log_func
        self.monitoring = False
        self.monitor_thread = None
        
    def start_monitoring(self):
        if self.monitoring or not self.state.spinner.is_valid:
            return
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        
    def stop_monitoring(self):
        self.monitoring = False
        
    def _monitor_loop(self):
        while self.monitoring and PYAUTOGUI_AVAILABLE:
            try:
                if (self.state.automation.mode == AutomationMode.RUNNING and 
                    self.state.spinner.center_xy):
                    current_pos = pg.position()
                    sx, sy = self.state.spinner.center_xy
                    distance = math.sqrt((current_pos[0] - sx)**2 + (current_pos[1] - sy)**2)
                    
                    # Suppress auto-pause during intentional away-from-spin overlay clicks
                    if time.time() < getattr(self.state.automation, 'suppress_mouse_pause_until', 0):
                        time.sleep(MOUSE_CHECK_INTERVAL)
                        continue

                    if distance > MOUSE_PAUSE_THRESHOLD and not self.state.automation.paused_by_mouse:
                        self.state.automation.paused_by_mouse = True
                        self.log(f"Auto-paused: mouse moved {distance:.0f}px from spinner", bright_blue=True)
                    elif distance <= MOUSE_PAUSE_THRESHOLD and self.state.automation.paused_by_mouse:
                        self.state.automation.paused_by_mouse = False
                        self.log("Auto-resume: mouse returned to spinner area")
                        
            except Exception:
                pass
            time.sleep(MOUSE_CHECK_INTERVAL)

# --------------- Browser Detection ---------------

class BrowserDetector:
    def __init__(self):
        self.detected_windows = []
        self.selected_window = None
    
    def _run_applescript(self, script: str) -> str:
        try:
            result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""
    
    def detect_browser_windows(self) -> List[WindowInfo]:
        detected = []
        browser_apps = ["Google Chrome", "Safari", "Firefox", "Microsoft Edge"]
        
        for app_name in browser_apps:
            try:
                check_script = f'tell application "System Events" to return name of every application process whose name is "{app_name}"'
                if not self._run_applescript(check_script):
                    continue
                
                window_script = f'''
                tell application "{app_name}"
                    set windowList to {{}}
                    repeat with w in windows
                        if name of w is not "" then
                            set end of windowList to name of w
                        end if
                    end repeat
                    return windowList
                end tell
                '''
                
                windows_output = self._run_applescript(window_script)
                if windows_output:
                    titles = [t.strip().strip('"') for t in windows_output.split(",") if t.strip()]
                    for i, title in enumerate(titles):
                        if title:
                            detected.append(WindowInfo(
                                title=title,
                                app_name=app_name,
                                window_id=f"{app_name.lower().replace(' ', '_')}_{i}"
                            ))
            except Exception:
                continue
        
        if not detected:
            detected.extend([
                WindowInfo(title="Chrome - Manual Mode", app_name="Google Chrome (Manual)", window_id="manual_chrome"),
                WindowInfo(title="Safari - Manual Mode", app_name="Safari (Manual)", window_id="manual_safari")
            ])
        
        self.detected_windows = detected
        return detected
    
    def show_selection_dialog(self, parent, auto_toggle_topmost=True):
        # Disable stay-on-top during dialog
        parent_was_topmost = False
        try:
            parent_was_topmost = parent.attributes("-topmost")
            if parent_was_topmost and auto_toggle_topmost:
                parent.attributes("-topmost", False)
                parent.update()
                parent._log("Stay-on-top temporarily disabled for dialog")
        except Exception:
            pass
        
        dialog = tk.Toplevel(parent)
        dialog.title("Select Browser Window") 
        dialog.geometry("700x500")
        dialog.transient(parent)
        dialog.grab_set()
        dialog.lift()
        dialog.focus_force()
        
        # Center on parent
        parent.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 350
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 250
        dialog.geometry(f"700x500+{x}+{y}")
        
        selected_window = None
        
        # Instructions
        ttk.Label(dialog, text=(
            "Step 1: Click 'Detect Windows' to scan for open browsers\n"
            "Step 2: Select your casino game tab from the list\n"
            "Step 3: Click 'Confirm Selection' to complete setup"
        ), justify=tk.LEFT).pack(pady=15, padx=20)
        
        # Detection controls
        detect_frame = ttk.Frame(dialog)
        detect_frame.pack(fill=tk.X, padx=20)
        
        def detect_windows():
            status_label.config(text="Scanning for browser windows...")
            dialog.update()
            windows = self.detect_browser_windows()
            window_listbox.delete(0, tk.END)
            for window in windows:
                window_listbox.insert(tk.END, f"{window.app_name}: {window.title}")
            status_label.config(text=f"Found {len(windows)} browser windows")
        
        ttk.Button(detect_frame, text="Detect Windows", command=detect_windows).pack(side=tk.LEFT)
        ttk.Button(detect_frame, text="Refresh", command=detect_windows).pack(side=tk.LEFT, padx=(10, 0))
        
        # Window list
        ttk.Label(dialog, text="Select your casino game window:").pack(anchor='w', padx=20, pady=(15, 5))
        
        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))
        
        window_listbox = tk.Listbox(list_frame, font=('Monaco', 10))
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=window_listbox.yview)
        window_listbox.configure(yscrollcommand=scrollbar.set)
        window_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Auto-detect on open
        dialog.after(200, detect_windows)
        
        # Status and buttons
        status_label = ttk.Label(dialog, text="Preparing to scan...")
        status_label.pack(pady=10)
        
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=15)
        
        def confirm_selection():
            nonlocal selected_window
            selection = window_listbox.curselection()
            if not selection:
                messagebox.showwarning("No Selection", "Please select a browser window first.")
                return
            selected_window = self.detected_windows[selection[0]]
            dialog.destroy()
        
        ttk.Button(button_frame, text="Confirm Selection", command=confirm_selection).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=10)
        
        dialog.bind('<Return>', lambda e: confirm_selection())
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        
        dialog.wait_window()
        
        # Restore stay-on-top
        try:
            if parent_was_topmost and auto_toggle_topmost:
                parent.attributes("-topmost", True)
                parent.update()
                parent._log("Stay-on-top restored after dialog")
        except Exception:
            pass
        
        if selected_window:
            self.selected_window = selected_window
        return selected_window

# --------------- ROI Selection ---------------

class ROISelector:
    @staticmethod
    def select_roi_overlay(parent, auto_toggle_topmost=True) -> Optional[SpinnerROI]:
        """Simple in-app ROI selector using a fullscreen translucent overlay.

        Returns SpinnerROI or None if cancelled.
        """
        parent_was_topmost = False
        try:
            parent_was_topmost = parent.attributes("-topmost")
            if parent_was_topmost and auto_toggle_topmost:
                parent.attributes("-topmost", False)
                parent.update()
        except Exception:
            pass

        roi = {"x": None, "y": None, "w": None, "h": None}
        start = {"x": 0, "y": 0}
        rect_id = {"id": None}

        overlay = tk.Toplevel(parent)
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-topmost", True)
        try:
            overlay.overrideredirect(True)
        except Exception:
            pass

        canvas = tk.Canvas(overlay, cursor="crosshair", bg="black")
        canvas.pack(fill=tk.BOTH, expand=True)
        try:
            canvas.configure(highlightthickness=0)
        except Exception:
            pass
        canvas.configure(background="#000000")
        canvas.attributes = getattr(canvas, 'attributes', None)

        w = overlay.winfo_screenwidth()
        h = overlay.winfo_screenheight()
        # Semi-transparent veil effect
        try:
            overlay.attributes("-alpha", 0.25)
        except Exception:
            pass

        def on_press(event):
            start["x"], start["y"] = event.x, event.y
            if rect_id["id"] is not None:
                canvas.delete(rect_id["id"])
            rect_id["id"] = canvas.create_rectangle(start["x"], start["y"], event.x, event.y, outline="#00ff00", width=2)

        def on_drag(event):
            if rect_id["id"] is not None:
                canvas.coords(rect_id["id"], start["x"], start["y"], event.x, event.y)

        def on_release(event):
            x0, y0 = start["x"], start["y"]
            x1, y1 = event.x, event.y
            x, y = min(x0, x1), min(y0, y1)
            rw, rh = abs(x1 - x0), abs(y1 - y0)
            if rw >= 10 and rh >= 10:
                roi.update({"x": x, "y": y, "w": rw, "h": rh})
            overlay.destroy()

        def on_escape(event):
            overlay.destroy()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", on_escape)
        overlay.focus_set()
        overlay.grab_set()
        parent.wait_window(overlay)

        try:
            if parent_was_topmost and auto_toggle_topmost:
                parent.attributes("-topmost", True)
                parent.update()
        except Exception:
            pass

        if None in roi.values():
            return None
        return SpinnerROI(roi["x"], roi["y"], roi["w"], roi["h"])

    @staticmethod
    def select_roi_native(parent, auto_toggle_topmost=True) -> bool:
        """Use macOS native interactive screenshot tool to let user select an area.

        Returns True if user made a selection (image saved), False otherwise.
        Note: This tool does NOT provide coordinates; app will fallback to heuristic ROI.
        """
        parent_was_topmost = False
        try:
            parent_was_topmost = parent.attributes("-topmost") 
            if parent_was_topmost and auto_toggle_topmost:
                parent.attributes("-topmost", False)
                parent.update()
        except Exception:
            pass
        try:
            parent.withdraw()
            messagebox.showinfo("FS Area Selection", 
                "macOS screenshot selection will open.\n"
                "Click and drag over the slots area, then release.\n"
                "Press Escape to cancel.")
            result = subprocess.run(["screencapture", "-i", "-r", "/tmp/spin_helper_fs_area.png"], timeout=120)
        except Exception:
            result = None
        finally:
            try:
                parent.deiconify(); parent.lift()
                if parent_was_topmost and auto_toggle_topmost:
                    parent.attributes("-topmost", True)
                    parent.update()
            except Exception:
                pass
        return bool(result and result.returncode == 0)

# --------------- Enhanced Calculator Component ---------------

class EmbeddedCalculator:
    def __init__(self, parent, app_instance, feature_name):
        self.app = app_instance
        self.feature_name = feature_name
        self.frame = ttk.LabelFrame(parent, text=f"{feature_name} Target Calculator", padding=8, style='Calc.TLabelframe')
        
        self.amount_var = tk.StringVar()
        self.mult_var = tk.StringVar()
        self.bet_var = tk.StringVar()
        # Optional direct input for Scenario 1: Total Wager Target
        self.total_target_input_var = tk.StringVar()
        # Optional policy + balance input
        self.bonus_first_var = tk.BooleanVar(value=True)
        self.balance_var = tk.StringVar()
        self.total_var = tk.StringVar(value="—")
        self.target_var = tk.StringVar(value="—")
        self.current_wager_var = tk.StringVar(value="£0.00")
        
        self._build_ui()
        
        if hasattr(self.app, 'state_slots'):
            self._update_timer()
    
    def _build_ui(self):
        # Input row
        input_frame = ttk.Frame(self.frame)
        input_frame.pack(fill=tk.X)
        
        ttk.Label(input_frame, text="Bonus (£):").grid(row=0, column=0, sticky="w", padx=(0, 5))
        ttk.Entry(input_frame, textvariable=self.amount_var, width=8).grid(row=0, column=1, padx=(0, 10))
        
        ttk.Label(input_frame, text="Wagering ×:").grid(row=0, column=2, sticky="w", padx=(0, 5))
        ttk.Entry(input_frame, textvariable=self.mult_var, width=6).grid(row=0, column=3, padx=(0, 10))
        
        ttk.Label(input_frame, text="Bet/spin (£):").grid(row=0, column=4, sticky="w", padx=(0, 5))
        ttk.Entry(input_frame, textvariable=self.bet_var, width=8).grid(row=0, column=5)

        # Optional total target input for Scenario 1
        ttk.Label(input_frame, text="Total Target (£, optional):").grid(row=1, column=0, sticky="w", padx=(0, 5), pady=(6,0))
        ttk.Entry(input_frame, textvariable=self.total_target_input_var, width=10).grid(row=1, column=1, padx=(0, 10), pady=(6,0))
        ttk.Label(input_frame, text="Tip: Fill Total to compute Wager ×; or leave Total blank to compute Total from Wager ×.")\
            .grid(row=1, column=2, columnspan=4, sticky="w", pady=(6,0))

        # Policy toggle and Balance input
        policy_frame = ttk.Frame(self.frame)
        policy_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Checkbutton(policy_frame, text="Bonus used before cash (stop using cash when bonus exhausted)",
                        variable=self.bonus_first_var).pack(side=tk.LEFT)

        balance_frame = ttk.Frame(self.frame)
        balance_frame.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(balance_frame, text="Balance (£, user-entered):").pack(side=tk.LEFT)
        ttk.Entry(balance_frame, textvariable=self.balance_var, width=10).pack(side=tk.LEFT, padx=(6, 0))
        
        # Results row
        result_frame = ttk.Frame(self.frame)
        result_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(result_frame, text="Total Wager:").grid(row=0, column=0, sticky="w", padx=(0, 5))
        ttk.Label(result_frame, textvariable=self.total_var, font=('Monaco', 9, 'bold')).grid(row=0, column=1, padx=(0, 15))
        
        ttk.Label(result_frame, text="Target Spins:").grid(row=0, column=2, sticky="w", padx=(0, 5))
        ttk.Label(result_frame, textvariable=self.target_var, font=('Monaco', 9, 'bold')).grid(row=0, column=3, padx=(0, 15))
        
        ttk.Label(result_frame, text="Current Wager:").grid(row=0, column=4, sticky="w", padx=(0, 5))
        ttk.Label(result_frame, textvariable=self.current_wager_var, font=('Monaco', 9, 'bold'), 
                 foreground="white").grid(row=0, column=5)
        
        # Buttons
        button_frame = ttk.Frame(self.frame)
        button_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Button(button_frame, text="Calculate", command=self._calculate).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Apply Target", command=self._apply).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Reset", command=self._reset).pack(side=tk.LEFT)
    
    def _update_timer(self):
        """Update current wager display"""
        try:
            bet = float(self.bet_var.get() or "0")
            spins = getattr(self.app.state_slots.automation, 'total_done', 0)
            current_wager = spins * bet
            self.current_wager_var.set(f"£{current_wager:.2f}")
        except:
            pass
        self.app.after(1000, self._update_timer)
    
    def _calculate(self):
        try:
            def parse_money(s: str) -> float:
                s = (s or "").strip().replace("£", "").replace(",", "")
                return float(s or "0")

            amount = parse_money(self.amount_var.get())
            mult_in = float((self.mult_var.get() or "0").strip() or "0")
            bet = parse_money(self.bet_var.get())
            total_in = parse_money(self.total_target_input_var.get())

            if amount <= 0:
                raise ValueError("Amount must be greater than 0")

            used_scenario = None
            # Scenario 1: Total provided -> derive Wager X
            if total_in > 0:
                total = total_in
                mult = total / amount if amount > 0 else 0.0
                self.mult_var.set(f"{mult:.2f}")
                used_scenario = 1
            else:
                # Scenario 2: Wager X provided -> derive Total
                if mult_in <= 0:
                    raise ValueError("Provide either Wagering × or Total Target")
                mult = mult_in
                total = amount * mult
                used_scenario = 2

            # Spins are optional; only compute if bet > 0
            if bet > 0:
                target = int(round(total / bet))
                self.target_var.set(str(target))
            else:
                self.target_var.set("—")

            self.total_var.set(f"£{total:.2f}")

            # Log which formula was applied
            if used_scenario == 1:
                if bet > 0:
                    self.app._log(
                        f"{self.feature_name}: £{total:.2f} ÷ £{amount:.2f} = {mult:.2f}×; ÷ £{bet:.2f} = {self.target_var.get()} spins",
                        green=True,
                    )
                else:
                    self.app._log(
                        f"{self.feature_name}: £{total:.2f} ÷ £{amount:.2f} = {mult:.2f}× (Wager ×)",
                        green=True,
                    )
            else:
                if bet > 0:
                    self.app._log(
                        f"{self.feature_name}: £{amount:.2f} × {mult:.2f} ÷ £{bet:.2f} = {self.target_var.get()} spins",
                        green=True,
                    )
                else:
                    self.app._log(
                        f"{self.feature_name}: £{amount:.2f} × {mult:.2f} = £{total:.2f}",
                        green=True,
                    )
            
        except ValueError as e:
            self.total_var.set("Error")
            self.target_var.set("—")
            messagebox.showwarning("Calculation Error", str(e))
    
    def _apply(self):
        try:
            target_str = self.target_var.get()
            if target_str in ["—", "Error"]:
                messagebox.showwarning("No Target", "Calculate a target first.")
                return
            
            target = int(target_str)
            
            # Apply to appropriate targets
            if hasattr(self.app, 'clicker_manual_target'):
                self.app.clicker_manual_target.set(target)
            if hasattr(self.app, 'clicker_auto_target'):
                self.app.clicker_auto_target.set(target)
            if hasattr(self.app, 'state_slots'):
                self.app.state_slots.automation.target_count = target

            # For Slots: update the applied display values under Automation Controls
            if getattr(self, 'feature_name', '') == 'Slots':
                try:
                    if hasattr(self.app, 'slots_meta_target_var'):
                        self.app.slots_meta_target_var.set(str(target))
                    if hasattr(self.app, 'slots_meta_total_var'):
                        self.app.slots_meta_total_var.set(self.total_var.get())
                except Exception:
                    pass
            
            # Propagate Balance to current feature's balance field if present
            bal = getattr(self, 'balance_var', None)
            if bal is not None:
                bal_str = bal.get()
                if hasattr(self.app, 'clicker_balance_var') and bal_str is not None:
                    self.app.clicker_balance_var.set(bal_str)
            
            self.app._log(f"{self.feature_name} target applied: {target}", green=True)
            
        except Exception as e:
            messagebox.showwarning("Apply Error", str(e))
    
    def _reset(self):
        self.amount_var.set("")
        self.mult_var.set("")
        self.bet_var.set("")
        self.total_target_input_var.set("")
        self.balance_var.set("")
        self.bonus_first_var.set(True)
        self.total_var.set("—")
        self.target_var.set("—")
        self.current_wager_var.set("£0.00")
        self.app._log(f"{self.feature_name} calculator reset")
    
    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

# --------------- Enhanced Spin Detection ---------------

class SpinDetector:
    def __init__(self, state: SessionStateSlots, log_func):
        self.state = state
        self.log = log_func
        self.on_actual_click = None  # optional callback to increment app-visible counters
        self.on_overlay_click_start = None
        self.on_overlay_click_end = None
        
    def get_current_state(self) -> SpinState:
        if not PIL_AVAILABLE or not self.state.spinner.is_valid:
            return SpinState.UNKNOWN
            
        spinner = self.state.spinner
        roi = spinner.roi
        
        try:
            current = ImageGrab.grab(bbox=(roi.x, roi.y, roi.x + roi.w, roi.y + roi.h))
            rms = _rms(current, spinner.baseline_ready)
            # Auxiliary check: if aux ROI captured, treat large change as NOT_READY
            if spinner.aux_roi and spinner.aux_baseline_ready is not None:
                aux = ImageGrab.grab(bbox=(spinner.aux_roi.x, spinner.aux_roi.y, spinner.aux_roi.x + spinner.aux_roi.w, spinner.aux_roi.y + spinner.aux_roi.h))
                aux_diff = _rms(aux, spinner.aux_baseline_ready)
                if aux_diff >= PIX_DIFF_CHANGED:
                    return SpinState.NOT_READY
            
            if rms <= PIX_DIFF_READY:
                return SpinState.READY
            elif rms >= PIX_DIFF_CHANGED:
                return SpinState.NOT_READY
            else:
                return SpinState.UNKNOWN
            
        except Exception:
            return SpinState.UNKNOWN

    def _wait_change_sticky(self, baseline: Image.Image, min_stick_ms: int, timeout: float) -> bool:
        t0 = time.time()
        changed_at = None
        
        while time.time() - t0 < timeout:
            if self.state.automation.stop_requested:
                return False
                
            img = ImageGrab.grab(bbox=(self.state.spinner.roi.x, self.state.spinner.roi.y, 
                                     self.state.spinner.roi.x + self.state.spinner.roi.w, 
                                     self.state.spinner.roi.y + self.state.spinner.roi.h))
            diff = _rms(img, baseline)
            
            if diff >= PIX_DIFF_CHANGED:
                if changed_at is None:
                    changed_at = time.time()
                elif (time.time() - changed_at) * 1000.0 >= min_stick_ms:
                    return True
            else:
                changed_at = None
                
            time.sleep(0.04)
            
        return False

    def _wait_for_change(self, baseline: Image.Image, become_changed=True, timeout=SPIN_CHANGE_TIMEOUT) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.state.automation.stop_requested:
                return False
            state = self.get_current_state()
            if become_changed and state == SpinState.NOT_READY:
                return True
            if not become_changed and state == SpinState.READY:
                return True
            time.sleep(0.05)
        return False

    def wait_ready_with_grace(self, baseline: Image.Image,
                               grace_sec: float = LONG_SPIN_GRACE_SEC,
                               max_timeout: float = SPIN_CHANGE_TIMEOUT,
                               allow_grace_click: bool = True) -> bool:
        """Wait for READY state with a grace window before any rescue.

        After grace_sec elapses, optionally perform a single gentle click to
        dismiss potential overlays, then continue waiting up to max_timeout.
        Returns True if READY is observed before timeout.
        """
        t0 = time.time()
        grace_clicked = False
        roi = self.state.spinner.roi
        while time.time() - t0 < max_timeout:
            if self.state.automation.stop_requested:
                return False
            try:
                img = ImageGrab.grab(bbox=(roi.x, roi.y, roi.x + roi.w, roi.y + roi.h))
                diff = _rms(img, baseline)
            except Exception:
                diff = PIX_DIFF_CHANGED + 1.0

            if diff <= PIX_DIFF_READY:
                return True

            elapsed = time.time() - t0
            if elapsed < grace_sec:
                time.sleep(0.05)
                continue

            if (allow_grace_click and not grace_clicked and self.state.spinner.center_xy and PYAUTOGUI_AVAILABLE
                and not self.state.automation.paused_by_mouse and not self.state.automation.paused_manually):
                try:
                    x, y = self.state.spinner.center_xy
                    jx = x + random.randint(-JITTER_PX, JITTER_PX)
                    jy = y + random.randint(-JITTER_PX, JITTER_PX)
                    pg.moveTo(jx, jy, duration=0.06)
                    pg.click()
                    self.log("Grace click after long wait (overlay suspected)")
                except Exception:
                    pass
                grace_clicked = True

            time.sleep(0.06)
        return False

    def _rescue_once_then_wait_ready(self, baseline: Image.Image, wait_after_click: float = SPIN_CHANGE_TIMEOUT) -> bool:
        """Perform a single away-from-spin click to advance overlays, then wait READY.

        Intentionally avoids clicking the spin button to prevent accidental spins.
        """
        try:
            self._click_anywhere_to_continue()
            self.log("Rescue click (away) #1")
            return self._wait_for_change(baseline, become_changed=False, timeout=wait_after_click)
        except Exception as e:
            self.log(f"Rescue click failed: {e}")
            return False

    def _ensure_ready_before_click(self, baseline: Image.Image) -> bool:
        if self._wait_for_change(baseline, become_changed=False, timeout=2.5):
            return True
            
        if self._rescue_once_then_wait_ready(baseline, wait_after_click=SPIN_CHANGE_TIMEOUT):
            return True
            
        return False

    def _fs_area_active(self) -> bool:
        """Heuristic: sample FS ROI quickly to estimate if area is animating.

        Requires: PIL available and detection enabled.
        """
        try:
            if not PIL_AVAILABLE:
                return False
            if not getattr(self.state, 'detect_fs', False):
                return False
            # Build candidate ROIs: user FS ROI, status banner ROI, slots ROI
            rois = []
            r = getattr(self.state, 'fs_roi', None)
            if r:
                rois.append(r)
            sb = self._derive_status_banner_roi()
            if sb:
                rois.append(sb)
            sr = self._derive_slots_roi()
            if sr:
                rois.append(sr)
            if not rois:
                return False
            # Consider active if any candidate shows sufficient activity
            for roi in rois:
                samples = []
                last = ImageGrab.grab(bbox=(roi.x, roi.y, roi.x + roi.w, roi.y + roi.h))
                for _ in range(3):
                    time.sleep(0.06)
                    cur = ImageGrab.grab(bbox=(roi.x, roi.y, roi.x + roi.w, roi.y + roi.h))
                    samples.append(_rms(cur, last))
                    last = cur
                avg = sum(samples) / max(1, len(samples))
                if avg >= FS_ANIM_RMS_ACTIVE:
                    return True
            return False
        except Exception:
            return False

    def _derive_slots_roi(self) -> Optional[SpinnerROI]:
        """Best-effort ROI over the slots area when no explicit FS ROI.

        Heuristic: rectangle up/left of the spinner, sized to typical slots area.
        """
        try:
            if not self.state.spinner.center_xy:
                return None
            sx, sy = self.state.spinner.center_xy
            try:
                sw, sh = pg.size()
            except Exception:
                sw, sh = 1920, 1080
            width = max(200, int(sw * 0.35))
            height = max(180, int(sh * 0.40))
            x = clamp(sx - width - 140, 0, max(0, sw - width))
            y = clamp(sy - height - 120, 0, max(0, sh - height))
            return SpinnerROI(x, y, width, height)
        except Exception:
            return None

    def _derive_status_banner_roi(self) -> Optional[SpinnerROI]:
        """Approximate banner ROI at bottom center (for status text like GOOD LUCK / WIN).

        Best-effort without explicit selection.
        """
        try:
            if not PYAUTOGUI_AVAILABLE:
                return None
            sw, sh = pg.size()
            width = max(220, int(sw * 0.35))
            height = max(60, int(sh * 0.08))
            x = int(sw * 0.5 - width / 2)
            y = int(sh * 0.82)
            y = clamp(y, 0, max(0, sh - height))
            return SpinnerROI(x, y, width, height)
        except Exception:
            return None

    def _click_anywhere_to_continue(self) -> None:
        """Click away from the spin button to advance overlays or prompts.

        Chooses a point up/left from the spinner, jittered slightly, and clicks it.
        Intentionally NOT near the spinner to avoid accidental spins.
        """
        try:
            if not self.state.spinner.center_xy or not PYAUTOGUI_AVAILABLE:
                return
            sx, sy = self.state.spinner.center_xy
            # Prefer a small offset near the spinner to stay on the same screen
            # Click within a ring 70–120px away from center, generally up/left
            dx = -random.randint(70, 120)
            dy = -random.randint(50, 100)
            tx, ty = sx + dx, sy + dy
            # If we can derive a slots ROI and our point is outside it, nudge inside
            roi = self._derive_slots_roi()
            if roi and not (roi.x <= tx <= roi.x + roi.w and roi.y <= ty <= roi.y + roi.h):
                tx = min(max(tx, roi.x + 10), roi.x + max(11, roi.w - 10))
                ty = min(max(ty, roi.y + 10), roi.y + max(11, roi.h - 10))
            # Keep within screen bounds if possible
            try:
                sw, sh = pg.size()
                tx = clamp(tx, 10, sw - 10)
                ty = clamp(ty, 10, sh - 10)
            except Exception:
                pass
            # Suppress auto-pause if enabled
            try:
                if getattr(self.state, 'suppress_overlay_pause', True):
                    secs = float(getattr(self.state, 'suppress_overlay_secs', PRE_READY_WAIT_AFTER_CLICK))
                    self.state.automation.suppress_mouse_pause_until = time.time() + secs
            except Exception:
                pass
            # Temporarily drop app topmost if callback provided
            try:
                if self.on_overlay_click_start:
                    self.on_overlay_click_start()
            except Exception:
                pass
            pg.moveTo(tx, ty, duration=0.08)
            pg.click()
            self.log("Overlay-progress click (away from spin)")
        except Exception:
            pass
        finally:
            try:
                if self.on_overlay_click_end:
                    self.on_overlay_click_end()
            except Exception:
                pass

    def wait_while_fs_active(self, max_seconds: float = 180.0, check_interval: float = 0.5) -> float:
        """Block while FS/animation area is active; returns seconds waited."""
        t0 = time.time()
        try:
            while (time.time() - t0) < max_seconds and not self.state.automation.stop_requested:
                if not self._fs_area_active():
                    break
                time.sleep(check_interval)
        except Exception:
            pass
        return time.time() - t0

    def ensure_ready_multigrace(self, baseline: Image.Image) -> bool:
        """Wait for READY with multiple pre-click grace attempts.

        Strategy:
        1) Wait a short initial period for READY.
        2) If not ready, perform up to N overlay-progress clicks away from the spin
           button, each followed by a wait; after each, re-check READY.
        3) If FS detection is available and area is active, bias towards waiting.
        """
        t0 = time.time()

        phase = PreClickPhase.INITIAL_WAIT
        self.log(f"Pre-click phase: {phase.value}", orange=True)
        # Initial wait
        if self._wait_for_change(baseline, become_changed=False, timeout=PRE_READY_INITIAL_WAIT):
            phase = PreClickPhase.READY
            self.log(f"Pre-click phase: {phase.value}", orange=True)
            return True

        clicks = 0
        while (time.time() - t0) < PRE_READY_MAX_TIMEOUT and clicks < PRE_READY_GRACE_CLICKS:
            if self.state.automation.stop_requested:
                return False
            if self.state.automation.paused_by_mouse or self.state.automation.paused_manually:
                self.log("Pre-click: pause requested; waiting for READY", orange=True)
                self._wait_for_change(baseline, become_changed=False, timeout=SPIN_CHANGE_TIMEOUT*2)
                return False

            # If FS area appears active, wait briefly before attempting a grace click
            if self._fs_area_active():
                self.log("Pre-click: spin NOT READY; slots animations active — waiting briefly", orange=True)
                time.sleep(0.4)
                # quick re-check for ready without clicking
                if self._wait_for_change(baseline, become_changed=False, timeout=0.5):
                    phase = PreClickPhase.READY
                    self.log(f"Pre-click phase: {phase.value}", orange=True)
                    return True
            else:
                # Relaxed READY check: allow small tolerance to break out and click
                try:
                    roi = self.state.spinner.roi
                    cur = ImageGrab.grab(bbox=(roi.x, roi.y, roi.x + roi.w, roi.y + roi.h))
                    if _rms(cur, baseline) <= (PIX_DIFF_READY + 3.0):
                        self.log("Pre-click: relaxed READY satisfied — proceeding", orange=True)
                        return True
                except Exception:
                    pass

            # Perform an away-from-spin click to advance overlays/requests for input
            phase = PreClickPhase.OVERLAY_PROGRESS
            self.log(f"Pre-click: spin NOT READY; overlay suspected — {phase.value} (attempt {clicks + 1})", orange=True)
            self._click_anywhere_to_continue()

            # If paused mid-phase, wait READY and abort
            if self.state.automation.paused_by_mouse or self.state.automation.paused_manually:
                self._wait_for_change(baseline, become_changed=False, timeout=SPIN_CHANGE_TIMEOUT*2)
                return False
            # Wait and check READY after the grace click
            if self._wait_for_change(baseline, become_changed=False, timeout=PRE_READY_WAIT_AFTER_CLICK):
                return True

            # If FS area becomes active, wait until it calms down (free spins, big win, etc.)
            if self._fs_area_active():
                phase = PreClickPhase.FS_HOLD
                self.log(f"Pre-click phase: {phase.value}", orange=True)
                waited = self.wait_while_fs_active()
                self.log(f"Pre-click FS hold waited {waited:.1f}s")
                # After waiting, re-check READY quickly
                if self._wait_for_change(baseline, become_changed=False, timeout=2.0):
                    phase = PreClickPhase.READY
                    self.log(f"Pre-click phase: {phase.value}", orange=True)
                    return True

            clicks += 1

        phase = PreClickPhase.TIMEOUT
        self.log(f"Pre-click phase: {phase.value}", orange=True)
        return False

    def do_click(self, with_jitter: bool = True) -> bool:
        if not self.state.spinner.center_xy:
            return False
            
        x, y = self.state.spinner.center_xy
        try:
            if pg:
                if with_jitter:
                    jx = x + random.randint(-JITTER_PX, JITTER_PX)
                    jy = y + random.randint(-JITTER_PX, JITTER_PX)
                    pg.moveTo(jx, jy, duration=0.08)
                else:
                    pg.moveTo(x, y, duration=0.08)
                pg.click()
                return True
            else:
                time.sleep(0.05)
                return True
        except Exception as e:
            self.log(f"Click failed: {e}")
            return False

# --------------- Main Application ---------------

class SpinHelperApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Spin Helper v{APP_VERSION}")
        self.minsize(980, 540)

        # Initialize state
        self.browser_detector = BrowserDetector()
        self.state_slots = SessionStateSlots()
        
        # Enhanced components
        self.spin_detector = SpinDetector(self.state_slots, self._log)
        self.spin_detector.on_actual_click = self._inc_actual_clicks
        # Hooks to avoid clicking the app window during overlay clicks
        try:
            self.spin_detector.on_overlay_click_start = lambda: self.after(0, self._overlay_click_begin)
            self.spin_detector.on_overlay_click_end = lambda: self.after(0, self._overlay_click_end)
        except Exception:
            pass
        self.mouse_monitor = MouseMonitor(self.state_slots, self._log)
        self.click_detector = ClickDetector(self)
        
        self._log_q = queue.Queue()
        self._stop_evt = threading.Event()
        self._blip_count = 0
        
        # Mode tracking for cross-contamination prevention
        self.counter_mode_active = False
        self.automatic_mode_active = False
        self.slots_mode_active = False

        # Shared Anti-idle waggle settings (used by Clicker and Slots)
        self.waggle_on_var = tk.BooleanVar(value=AC_DEFAULT_WAGGLE_ON)
        self.waggle_secs_var = tk.IntVar(value=AC_DEFAULT_WAGGLE_SECS)
        self.waggle_amp_var = tk.IntVar(value=AC_DEFAULT_WAGGLE_AMP)

        # Overlay handling suppression controls (UI vars)
        self.overlay_suppress_var = tk.BooleanVar(value=bool(self.state_slots.suppress_overlay_pause))
        self.overlay_suppress_secs_var = tk.DoubleVar(value=float(self.state_slots.suppress_overlay_secs))

        # Infinite wait (post-click READY) toggle
        self.infinite_wait_var = tk.BooleanVar(value=False)

        # Auto-save on target toggle (default OFF)
        self.auto_save_on_target_var = tk.BooleanVar(value=False)

        # UI counters for Actual Clicks per mode
        self.slots_actual_clicks_var = tk.StringVar(value="0")
        self.clicker_manual_actual_clicks = tk.IntVar(value=0)
        self.clicker_auto_actual_clicks = tk.IntVar(value=0)

        # Build UI and restore
        self._restore_geometry()
        self._build_ui()
        self.after(UI_FLUSH_MS, self._drain_log)
        # Start Clicker Automatic current wager updater
        self.after(1000, self._update_clicker_current_wager)
        
        self._log(f"Spin Helper v{APP_VERSION} initialized", green=True)

    # ---------- UI Building ----------

    def _build_ui(self):
        # Main paned window
        self.paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # Left scrollable controls
        left_frame = ttk.Frame(self.paned)
        self.paned.add(left_frame, weight=1)

        self.left_canvas = tk.Canvas(left_frame, highlightthickness=0)
        left_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.left_canvas.yview)
        self.left_canvas.configure(yscrollcommand=left_scroll.set)
        self.left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        left_inner = ttk.Frame(self.left_canvas)
        self.left_canvas.create_window((0, 0), window=left_inner, anchor="nw")
        left_inner.bind("<Configure>", lambda e: self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all")))

        # Toolbar
        toolbar = ttk.Frame(left_inner)
        toolbar.pack(fill=tk.X, padx=8, pady=(8, 0))
        
        try:
            current_top = bool(self.attributes("-topmost"))
        except Exception:
            current_top = True
        self.topmost_var = tk.BooleanVar(value=current_top)
        ttk.Checkbutton(toolbar, text="Stay on top", variable=self.topmost_var, command=self._apply_topmost).pack(side=tk.LEFT)

        # Session controls
        ttk.Button(toolbar, text="Save Session", command=self._save_session_dialog).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(toolbar, text="Load Session", command=self._load_session_dialog).pack(side=tk.LEFT, padx=(6, 8))
        self.session_name_var = tk.StringVar(value="No session loaded")
        ttk.Label(toolbar, textvariable=self.session_name_var).pack(side=tk.LEFT)

        # Main sections
        self.sections = ttk.Notebook(left_inner)
        self.sections.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Build tabs
        self._build_env_tab()
        self._build_slots_tab()
        self._build_roulette_tab()
        self._build_clicker_tab()

        # Right log panel
        right = ttk.Frame(self.paned)
        self.paned.add(right, weight=1)

        self.log = tk.Text(right, wrap="word", height=12, font=('Monaco', 9))
        self.log.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Status bar
        self.status = ttk.Label(self, text="Ready - Select browser window and capture spinner")
        self.status.pack(fill=tk.X)

        # Widget styles
        style = ttk.Style(self)
        try:
            style.configure('Danger.TButton', foreground='white', background='#cc0000')
            style.map('Danger.TButton', background=[('active', '#b30000')])
            style.configure('Calc.TLabelframe', background='#4a86e8')
            style.configure('Calc.TLabelframe.Label', background='#4a86e8', foreground='white')
        except Exception:
            pass

        # Log styling
        self.tag_green = "green"
        self.tag_blue = "blue"
        self.tag_bright_blue = "bright_blue"
        self.tag_orange = "orange"
        self.tag_red = "red"
        self.log.tag_configure(self.tag_green, foreground="#00a000")
        self.log.tag_configure(self.tag_blue, foreground="#0066cc")
        self.log.tag_configure(self.tag_bright_blue, foreground="#00aaff")
        self.log.tag_configure(self.tag_orange, foreground="#ff8c00")
        self.log.tag_configure(self.tag_red, foreground="#cc0000")

        # Mouse wheel support
        self.left_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        self.left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ---------- Tab Building ----------

    def _build_env_tab(self):
        tab_env = ttk.Frame(self.sections)
        self.sections.add(tab_env, text="Environment Setup")
        
        # Browser selection
        browser_frame = ttk.LabelFrame(tab_env, text="Browser Window Selection", padding=10)
        browser_frame.pack(fill=tk.X, padx=8, pady=8)
        
        ttk.Label(browser_frame, text=(
            "Step 1: Open your casino game in Chrome/Safari/Firefox\n"
            "Step 2: Click 'Select Browser Window' below\n"
            "Step 3: Choose your casino tab from the list\n"
            "Note: Stay-on-top will be temporarily disabled during selection"
        )).pack(anchor='w', pady=(0, 10))
        
        button_frame = ttk.Frame(browser_frame)
        button_frame.pack(fill=tk.X)
        
        ttk.Button(button_frame, text="Select Browser Window", command=self._select_browser).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Refresh List", command=self._refresh_browsers).pack(side=tk.LEFT)
        
        self.browser_status_var = tk.StringVar(value="No browser window selected")
        ttk.Label(browser_frame, textvariable=self.browser_status_var).pack(anchor='w', pady=(10, 0))
        
        # Universal Spinner Capture
        spinner_frame = ttk.LabelFrame(tab_env, text="Universal Spinner Button Capture", padding=10)
        spinner_frame.pack(fill=tk.X, padx=8, pady=8)
        
        ttk.Label(spinner_frame, text=(
            "Position your mouse over the spin button, then click 'Capture Spinner Button'.\n"
            "The app will give you 3 seconds to position your mouse correctly.\n"
            "This capture will be used across all features (Slots, Roulette, Clicker)."
        )).pack(anchor='w', pady=(0, 8))
        
        spinner_controls = ttk.Frame(spinner_frame)
        spinner_controls.pack(fill=tk.X)
        
        ttk.Button(spinner_controls, text="Capture Spinner Button", command=self._capture_spinner_delayed).pack(side=tk.LEFT)
        
        self.spinner_status_var = tk.StringVar(value="No spinner captured")
        ttk.Label(spinner_controls, textvariable=self.spinner_status_var).pack(side=tk.LEFT, padx=(15, 0))
        
        self.spinner_thumb_label = ttk.Label(spinner_controls)
        self.spinner_thumb_label.pack(side=tk.LEFT, padx=(10, 0))
        
        # (System Information panel hidden for now; keep terminal logs via check_dependencies)

        # Overlay handling controls
        overlay_frame = ttk.LabelFrame(tab_env, text="Overlay Handling", padding=10)
        overlay_frame.pack(fill=tk.X, padx=8, pady=8)
        ttk.Checkbutton(overlay_frame, text="Suppress auto-pause during overlay handling",
                        variable=self.overlay_suppress_var, command=self._apply_overlay_settings).pack(side=tk.LEFT)
        ttk.Label(overlay_frame, text="for (sec):").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(overlay_frame, textvariable=self.overlay_suppress_secs_var, width=6).pack(side=tk.LEFT)

        # Waiting/Session controls
        wait_frame = ttk.LabelFrame(tab_env, text="Waiting & Sessions", padding=10)
        wait_frame.pack(fill=tk.X, padx=8, pady=8)
        ttk.Checkbutton(wait_frame, text="Infinite Wait (Manual Mode)",
                        variable=self.infinite_wait_var).pack(side=tk.LEFT)
        ttk.Checkbutton(wait_frame, text="Auto-save session when target reached",
                        variable=self.auto_save_on_target_var).pack(side=tk.LEFT, padx=(12, 0))

    def _build_slots_tab(self):
        tab_slots = ttk.Frame(self.sections)
        self.sections.add(tab_slots, text="Slots (auto)")
        
        # Free-spins detection
        fs_frame = ttk.LabelFrame(tab_slots, text="Free-Spins Detection", padding=8)
        fs_frame.pack(fill=tk.X, padx=8, pady=8)
        
        fs_controls = ttk.Frame(fs_frame)
        fs_controls.pack(fill=tk.X)
        
        self.detect_fs_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(fs_controls, text="Detect Free-Spins banner", variable=self.detect_fs_var, command=self._toggle_fs).pack(side=tk.LEFT)
        ttk.Button(fs_controls, text="Select FS Area (Native)", command=self._capture_fs_native).pack(side=tk.LEFT, padx=(20, 0))
        self.fs_status_var = tk.StringVar(value="No FS ROI selected")
        ttk.Label(fs_frame, textvariable=self.fs_status_var).pack(anchor='w', pady=(6,0))
        
        # FIXED: Consistent automation controls
        auto_frame = ttk.LabelFrame(tab_slots, text="Automation Controls", padding=8)
        auto_frame.pack(fill=tk.X, padx=8, pady=8)
        
        auto_controls = ttk.Frame(auto_frame)
        auto_controls.pack(fill=tk.X)
        
        # Consistent button behavior: Ready/Pause/Stop
        self.slots_ready_btn = ttk.Button(auto_controls, text="Ready", command=self._slots_ready)
        self.slots_ready_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.slots_pause_btn = ttk.Button(auto_controls, text="Pause", command=self._slots_pause, state=tk.DISABLED)
        self.slots_pause_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.slots_stop_btn = ttk.Button(auto_controls, text="Stop/Reset", command=self._slots_stop_reset, style='Danger.TButton')
        self.slots_stop_btn.pack(side=tk.LEFT)
        
        # Spin counter display
        counter_frame = ttk.Frame(auto_frame)
        counter_frame.pack(fill=tk.X, pady=(8, 0))
        
        ttk.Label(counter_frame, text="Spins Completed:").pack(side=tk.LEFT)
        self.slots_counter_var = tk.StringVar(value="0")
        ttk.Label(counter_frame, textvariable=self.slots_counter_var, font=('Monaco', 12, 'bold'), 
                 foreground="white").pack(side=tk.LEFT, padx=(10, 0))

        # Actual clicks display
        actual_frame = ttk.Frame(auto_frame)
        actual_frame.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(actual_frame, text="Actual Clicks:").pack(side=tk.LEFT)
        ttk.Label(actual_frame, textvariable=self.slots_actual_clicks_var, font=('Monaco', 10, 'bold'),
                 foreground="white").pack(side=tk.LEFT, padx=(10, 0))

        # Current Wager (consistent naming)
        self.slots_current_wager_var = tk.StringVar(value="£0.00")
        slots_wager_frame = ttk.Frame(auto_frame)
        slots_wager_frame.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(slots_wager_frame, text="Current Wager:").pack(side=tk.LEFT)
        ttk.Label(slots_wager_frame, textvariable=self.slots_current_wager_var, font=('Monaco', 10, 'bold'),
                 foreground="white").pack(side=tk.LEFT, padx=(10, 0))
        
        # Anti-idle waggle controls for Slots (shared settings with Clicker)
        waggle_frame_slots = ttk.Frame(auto_frame)
        waggle_frame_slots.pack(fill=tk.X, pady=(8, 0))
        ttk.Checkbutton(waggle_frame_slots, text="Anti-idle waggle every", variable=self.waggle_on_var).pack(side=tk.LEFT)
        ttk.Entry(waggle_frame_slots, textvariable=self.waggle_secs_var, width=4).pack(side=tk.LEFT, padx=(5, 5))
        ttk.Label(waggle_frame_slots, text="sec, amplitude").pack(side=tk.LEFT)
        ttk.Entry(waggle_frame_slots, textvariable=self.waggle_amp_var, width=4).pack(side=tk.LEFT, padx=(5, 5))
        ttk.Label(waggle_frame_slots, text="px").pack(side=tk.LEFT)

        # Embedded calculator
        self.slots_calculator = EmbeddedCalculator(tab_slots, self, "Slots")
        self.slots_calculator.pack(fill=tk.X, padx=8, pady=8)

        # Display calculator targets for visibility (under Automation Controls) — bound to applied values only
        slots_meta_frame = ttk.Frame(auto_frame)
        slots_meta_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(slots_meta_frame, text="Target Spins:").pack(side=tk.LEFT)
        self.slots_meta_target_var = tk.StringVar(value="—")
        ttk.Label(slots_meta_frame, textvariable=self.slots_meta_target_var, font=('Monaco', 10, 'bold'),
                  foreground="white").pack(side=tk.LEFT, padx=(6, 15))
        ttk.Label(slots_meta_frame, text="Total Wagering:").pack(side=tk.LEFT)
        self.slots_meta_total_var = tk.StringVar(value="—")
        ttk.Label(slots_meta_frame, textvariable=self.slots_meta_total_var, font=('Monaco', 10, 'bold'),
                  foreground="white").pack(side=tk.LEFT, padx=(6, 0))

    def _build_roulette_tab(self):
        tab_roulette = ttk.Frame(self.sections)
        self.sections.add(tab_roulette, text="Roulette (manual)")
        
        # Manual controls
        manual_frame = ttk.LabelFrame(tab_roulette, text="Manual Roulette Controls", padding=8)
        manual_frame.pack(fill=tk.X, padx=8, pady=8)
        
        ttk.Label(manual_frame, text=(
            "Manual roulette mode uses the universal spinner detection from Environment Setup.\n"
            "Capture the spin button first, then use controls here."
        )).pack(anchor='w')
        
        # Embedded calculator
        self.roulette_calculator = EmbeddedCalculator(tab_roulette, self, "Roulette")
        self.roulette_calculator.pack(fill=tk.X, padx=8, pady=8)

    def _build_clicker_tab(self):
        tab_clicker = ttk.Frame(self.sections)
        self.sections.add(tab_clicker, text="Clicker")
        
        # Sub-notebook
        self.clicker_notebook = ttk.Notebook(tab_clicker)
        self.clicker_notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        # Counter mode (manual click detection)
        counter_tab = ttk.Frame(self.clicker_notebook)
        self.clicker_notebook.add(counter_tab, text="Counter")
        
        counter_frame = ttk.LabelFrame(counter_tab, text="Manual Click Counter", padding=8)
        counter_frame.pack(fill=tk.X, padx=8, pady=8)
        
        ttk.Label(counter_frame, text=(
            "Counter mode: Detects your manual clicks near spinner.\n"
            "'Ready' positions mouse and starts click detection.\n"
            "'Pause' stops detection. 'Stop/Reset' clears counters."
        )).pack(anchor='w', pady=(0, 8))
        
        self.clicker_manual_target = tk.IntVar(value=0)
        self.clicker_manual_done = tk.IntVar(value=0)
        
        counter_controls = ttk.Frame(counter_frame)
        counter_controls.pack(fill=tk.X)
        
        ttk.Label(counter_controls, text="Target:").grid(row=0, column=0, sticky="w")
        ttk.Entry(counter_controls, textvariable=self.clicker_manual_target, width=8).grid(row=0, column=1, padx=(5, 15))
        
        ttk.Label(counter_controls, text="Spins Completed:").grid(row=0, column=2, sticky="w")
        ttk.Label(counter_controls, textvariable=self.clicker_manual_done, font=('Monaco', 10, 'bold'),
                 foreground="white").grid(row=0, column=3, padx=(5, 15))
        
        # FIXED: Consistent button behavior
        self.counter_ready_btn = ttk.Button(counter_controls, text="Ready", command=self._counter_ready)
        self.counter_ready_btn.grid(row=0, column=4, padx=(10, 5))
        
        self.counter_pause_btn = ttk.Button(counter_controls, text="Pause", command=self._counter_pause, state=tk.DISABLED)
        self.counter_pause_btn.grid(row=0, column=5, padx=(0, 5))
        
        self.counter_stop_btn = ttk.Button(counter_controls, text="Stop/Reset", command=self._counter_stop_reset, style='Danger.TButton')
        self.counter_stop_btn.grid(row=0, column=6)

        # Actual clicks under Spins Completed
        ttk.Label(counter_controls, text="Actual Clicks:").grid(row=1, column=2, sticky="w", pady=(4,0))
        ttk.Label(counter_controls, textvariable=self.clicker_manual_actual_clicks, font=('Monaco', 10, 'bold'),
                 foreground="white").grid(row=1, column=3, padx=(5, 15), pady=(4,0))

        # Current Wager (consistent naming/position)
        ttk.Label(counter_controls, text="Current Wager:").grid(row=2, column=2, sticky="w", pady=(4,0))
        # Ensure variable exists regardless of build order
        if not hasattr(self, 'clicker_manual_wager_var'):
            self.clicker_manual_wager_var = tk.StringVar(value="£0.00")
        ttk.Label(counter_controls, textvariable=self.clicker_manual_wager_var, font=('Monaco', 10, 'bold'),
                 foreground="white").grid(row=2, column=3, padx=(5, 15), pady=(4,0))

        # Current Wager for Counter (manual)
        # (Removed separate manual wager frame to keep a single consistent readout)
        
        # Automatic mode
        auto_tab = ttk.Frame(self.clicker_notebook)
        self.clicker_notebook.add(auto_tab, text="Automatic")
        
        auto_frame = ttk.LabelFrame(auto_tab, text="Automatic Click Controls", padding=8)
        auto_frame.pack(fill=tk.X, padx=8, pady=8)
        
        self.clicker_auto_target = tk.IntVar(value=0)
        self.clicker_auto_done = tk.IntVar(value=0)
        
        auto_controls = ttk.Frame(auto_frame)
        auto_controls.pack(fill=tk.X)
        
        ttk.Label(auto_controls, text="Target:").grid(row=0, column=0, sticky="w")
        ttk.Entry(auto_controls, textvariable=self.clicker_auto_target, width=8).grid(row=0, column=1, padx=(5, 15))
        
        ttk.Label(auto_controls, text="Spins Completed:").grid(row=0, column=2, sticky="w")
        ttk.Label(auto_controls, textvariable=self.clicker_auto_done, font=('Monaco', 10, 'bold'),
                 foreground="white").grid(row=0, column=3, padx=(5, 15))
        
        # FIXED: Consistent button behavior
        self.auto_ready_btn = ttk.Button(auto_controls, text="Ready", command=self._auto_ready)
        self.auto_ready_btn.grid(row=0, column=4, padx=(10, 5))
        
        self.auto_pause_btn = ttk.Button(auto_controls, text="Pause", command=self._auto_pause, state=tk.DISABLED)
        self.auto_pause_btn.grid(row=0, column=5, padx=(0, 5))
        
        self.auto_stop_btn = ttk.Button(auto_controls, text="Stop/Reset", command=self._auto_stop_reset, style='Danger.TButton')
        self.auto_stop_btn.grid(row=0, column=6)

        # Actual clicks under Spins Completed
        ttk.Label(auto_controls, text="Actual Clicks:").grid(row=1, column=2, sticky="w", pady=(4,0))
        ttk.Label(auto_controls, textvariable=self.clicker_auto_actual_clicks, font=('Monaco', 10, 'bold'),
                 foreground="white").grid(row=1, column=3, padx=(5, 15), pady=(4,0))
        
        # Current Wager (for Automatic) — shown before waggle controls
        self.clicker_auto_wager_var = tk.StringVar(value="£0.00")
        wager_frame = ttk.Frame(auto_frame)
        wager_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(wager_frame, text="Current Wager:").pack(side=tk.LEFT)
        ttk.Label(wager_frame, textvariable=self.clicker_auto_wager_var, font=('Monaco', 10, 'bold'),
                 foreground="white").pack(side=tk.LEFT, padx=(6, 0))

        # (Removed duplicate manual wager display from Automatic for clarity)

        # User-entered Balance (advisory)
        self.clicker_balance_var = tk.StringVar(value="")
        balance_frame = ttk.Frame(auto_frame)
        balance_frame.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(balance_frame, text="Balance (£, user-entered):").pack(side=tk.LEFT)
        ttk.Entry(balance_frame, textvariable=self.clicker_balance_var, width=10).pack(side=tk.LEFT, padx=(6, 0))

        # Waggle controls (shared settings; ensure initialized)
        if not hasattr(self, 'waggle_on_var'):
            self.waggle_on_var = tk.BooleanVar(value=AC_DEFAULT_WAGGLE_ON)
        if not hasattr(self, 'waggle_secs_var'):
            self.waggle_secs_var = tk.IntVar(value=AC_DEFAULT_WAGGLE_SECS)
        if not hasattr(self, 'waggle_amp_var'):
            self.waggle_amp_var = tk.IntVar(value=AC_DEFAULT_WAGGLE_AMP)
        
        waggle_frame = ttk.Frame(auto_frame)
        waggle_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Checkbutton(waggle_frame, text="Anti-idle waggle every", variable=self.waggle_on_var).pack(side=tk.LEFT)
        ttk.Entry(waggle_frame, textvariable=self.waggle_secs_var, width=4).pack(side=tk.LEFT, padx=(5, 5))
        ttk.Label(waggle_frame, text="sec, amplitude").pack(side=tk.LEFT)
        ttk.Entry(waggle_frame, textvariable=self.waggle_amp_var, width=4).pack(side=tk.LEFT, padx=(5, 5))
        ttk.Label(waggle_frame, text="px").pack(side=tk.LEFT)
        
        # Embedded calculator
        self.clicker_calculator = EmbeddedCalculator(tab_clicker, self, "Clicker")
        self.clicker_calculator.pack(fill=tk.X, padx=8, pady=8)

    # ---------- Browser Selection ----------

    def _select_browser(self):
        self._log("Starting browser window selection...")
        try:
            selected = self.browser_detector.show_selection_dialog(self, auto_toggle_topmost=True)
            if selected:
                self.browser_status_var.set(f"✓ {selected.app_name}: {selected.title}")
                self.status.config(text="Browser selected - Capture spinner next")
                self._log(f"Browser selected: {selected.app_name}", green=True)
            else:
                self._log("Browser selection cancelled")
        except Exception as e:
            self._log(f"Browser selection error: {e}")
            messagebox.showerror("Error", str(e))

    def _refresh_browsers(self):
        self._log("Refreshing browser list...")
        windows = self.browser_detector.detect_browser_windows()
        real_count = len([w for w in windows if not "Manual" in w.app_name])
        self._log(f"Found {real_count} real browser windows")

    # ---------- Spinner Capture ----------

    def _capture_spinner_delayed(self):
        if not PIL_AVAILABLE:
            messagebox.showerror("PIL Required", "PIL is required for spinner capture.")
            return
        
        self.state_slots.spinner = SpinnerCapture()
        self.spinner_status_var.set("Preparing to capture...")
        
        self._log("Spinner capture starting - Move mouse over spin button NOW", green=True)
        self._log("Capturing in 3...", green=True)
        
        self.after(1000, lambda: self._log("Capturing in 2...", green=True))
        self.after(2000, lambda: self._log("Capturing in 1...", green=True))
        self.after(3000, self._execute_spinner_capture)
    
    def _execute_spinner_capture(self):
        try:
            x, y = self.winfo_pointerxy()
            w = h = 60
            left, top = int(x - w//2), int(y - h//2)
            
            baseline = ImageGrab.grab(bbox=(left, top, left + w, top + h))
            # Auxiliary ROI just below the spinner (for games where a sub-button disappears during spin)
            try:
                aux_h = max(10, int(h * 0.25))
                aux_y = top + h + 6
                aux_left = left + int(w * 0.2)
                aux_right = left + int(w * 0.8)
                aux_bbox = (aux_left, aux_y, aux_right, aux_y + aux_h)
                aux_baseline = ImageGrab.grab(bbox=aux_bbox)
            except Exception:
                aux_baseline = None
            
            thumb_img = baseline.copy()
            thumb_img.thumbnail((32, 32))
            thumbnail = ImageTk.PhotoImage(thumb_img)
            
            self.state_slots.spinner.roi = SpinnerROI(left, top, w, h)
            self.state_slots.spinner.baseline_ready = baseline
            if aux_baseline:
                self.state_slots.spinner.aux_roi = SpinnerROI(aux_left, aux_y, aux_right - aux_left, aux_h)
                self.state_slots.spinner.aux_baseline_ready = aux_baseline
            self.state_slots.spinner.ready_color = _avg_rgb(baseline)
            self.state_slots.spinner.ready_brightness = _brightness(baseline)
            self.state_slots.spinner.center_xy = (x, y)
            self.state_slots.spinner.capture_time = time.time()
            self.state_slots.spinner.is_valid = True
            self.state_slots.spinner.thumbnail = thumbnail
            
            self.spinner_status_var.set(f"✓ Captured at ({x},{y}) - Ready for all features")
            self.spinner_thumb_label.config(image=thumbnail)
            self.status.config(text="Universal spinner captured - Ready for automation")
            
            self._log("Universal spinner button READY state captured", green=True)
            self._log(f"Location: ({x},{y}), ROI: {w}x{h}px")
            
        except Exception as e:
            self.spinner_status_var.set("Capture failed")
            self._log(f"Capture error: {e}")
            messagebox.showerror("Capture Error", str(e))

    def _capture_fs_native(self):
        self._log("Starting FS area selection (native)...", green=True)
        try:
            success = ROISelector.select_roi_native(self, auto_toggle_topmost=True)
            if success:
                # We cannot get coordinates from native tool; use heuristic ROI at runtime
                self.state_slots.fs_roi = None
                self.fs_status_var.set("FS area selected (native). Using heuristic ROI at runtime.")
                self._log("FS area selected via native tool (heuristic ROI runtime)", green=True)
                self._save_geometry()
            else:
                self._log("FS area selection cancelled")
        except Exception as e:
            self._log(f"FS selection error: {e}")

    def _toggle_fs(self):
        self.state_slots.detect_fs = self.detect_fs_var.get()
        self._log(f"FS detection: {'ON' if self.state_slots.detect_fs else 'OFF'}")

    # ---------- State Management Helpers ----------

    def _stop_all_modes(self):
        """Stop all running modes to prevent cross-contamination"""
        self.counter_mode_active = False
        self.automatic_mode_active = False
        self.slots_mode_active = False
        
        self.state_slots.automation.mode = AutomationMode.STOPPED
        self.state_slots.automation.stop_requested = True
        
        self.click_detector.stop_monitoring()
        self.mouse_monitor.stop_monitoring()
        
        self._log("All automation modes stopped", bright_blue=True)

    def _position_mouse_with_grace(self, mode_name: str) -> bool:
        """Common function to position mouse and apply grace period"""
        if not self.state_slots.spinner.is_valid:
            messagebox.showwarning("Setup Required", "Capture spinner button first.")
            return False
        
        if not self.state_slots.spinner.center_xy:
            return False
            
        x, y = self.state_slots.spinner.center_xy
        
        try:
            if pg:
                # FIXED: Actually move the mouse to spinner position
                pg.moveTo(x, y, duration=0.2)
                self._log(f"{mode_name}: Mouse positioned at spinner ({x},{y})")
                
                # NEW: Focus click slightly above the spin button to bring browser to front
                try:
                    focus_x = x + random.randint(-6, 6)
                    focus_y = y - random.randint(15, 25)
                    pg.moveTo(focus_x, focus_y, duration=0.05)
                    pg.click()
                    self._log(f"{mode_name}: Focus click to bring browser to front")
                except Exception:
                    pass
                
                # Grace period
                self._log(f"{mode_name}: Grace period ({GRACE_PERIOD_SECS}s)...")
                time.sleep(GRACE_PERIOD_SECS)
                
                return True
        except Exception as e:
            self._log(f"{mode_name}: Mouse positioning failed: {e}")
            return False
        
        return False

    # ---------- FIXED: Slots Automation ----------

    def _slots_ready(self):
        """FIXED: Slots Ready - positions mouse and starts automation"""
        self._stop_all_modes()
        
        if not self.browser_detector.selected_window:
            messagebox.showwarning("Setup Required", "Select browser window first.")
            return
        
        if not self._position_mouse_with_grace("Slots"):
            return
        
        self.slots_mode_active = True
        self.state_slots.automation.mode = AutomationMode.RUNNING
        self.state_slots.automation.stop_requested = False
        # Reset pause flags to avoid sticky paused state from previous runs
        self.state_slots.automation.paused_by_mouse = False
        self.state_slots.automation.paused_manually = False
        # Reset Actual Clicks counter
        self.state_slots.automation.actual_clicks = 0
        self.slots_actual_clicks_var.set("0")
        
        # Update UI
        self.slots_ready_btn.config(state=tk.DISABLED, text="Running...")
        self.slots_pause_btn.config(state=tk.NORMAL)
        
        # Start monitoring and automation
        self.mouse_monitor.start_monitoring()
        threading.Thread(target=self._slots_automation_loop, daemon=True).start()
        
        self._log("Slots: Ready - automation started with spin detection", green=True)

    def _slots_pause(self):
        """Pause slots at next ready position"""
        self.state_slots.automation.paused_manually = True
        self.slots_ready_btn.config(state=tk.NORMAL, text="Ready")
        self._log("Slots: Pause requested - will pause at next ready position", bright_blue=True)

    def _slots_stop_reset(self):
        """Stop slots and reset counters (not calculator)"""
        self._stop_all_modes()
        
        # Reset counters but NOT calculator
        self.state_slots.automation.total_done = 0
        self.state_slots.automation.target_count = 0
        self.state_slots.automation.actual_clicks = 0
        self.slots_counter_var.set("0")
        self.slots_actual_clicks_var.set("0")
        
        # Reset UI
        self.slots_ready_btn.config(state=tk.NORMAL, text="Ready")
        self.slots_pause_btn.config(state=tk.DISABLED)
        
        self._log("Slots: Stop/Reset - counters cleared, calculator preserved", bright_blue=True)

    def _slots_automation_loop(self):
        """Slots automation loop with robust detection"""
        try:
            baseline = self.state_slots.spinner.baseline_ready
            last_waggle = time.time()
            
            while (self.slots_mode_active and 
                   self.state_slots.automation.mode != AutomationMode.STOPPED and
                   not self.state_slots.automation.stop_requested):
                
                # Check pause states
                if (self.state_slots.automation.paused_by_mouse or 
                    self.state_slots.automation.paused_manually):
                    time.sleep(0.5)
                    continue
                
                # Check targets
                if self._check_targets_reached():
                    break
                
                spin_num = self.state_slots.automation.total_done + 1
                self._log(f"Slots: Executing spin #{spin_num}")
                
                # Execute spin with robust detection (multi-grace pre-click)
                if not self.spin_detector.ensure_ready_multigrace(baseline):
                    # If paused, loop until unpaused rather than breaking
                    if (self.state_slots.automation.paused_by_mouse or 
                        self.state_slots.automation.paused_manually):
                        time.sleep(0.5)
                        continue
                    self._log(f"Slots: Spin #{spin_num} - timeout waiting READY")
                    break
                
                t_start = time.time()
                self._log("Slots: Spin button looks READY — clicking", orange=True)
                if not self.spin_detector.do_click():
                    self._log(f"Slots: Spin #{spin_num} - click failed")
                    continue
                
                # REQUIRE: see NOT_READY after click, else consider it a no-op
                if not self.spin_detector._wait_for_change(baseline, become_changed=True, timeout=1.8):
                    self._log(f"Slots: Spin #{spin_num} - no visual change")
                    continue
                # Count the actual click only when NOT_READY follows
                try:
                    self._inc_actual_clicks()
                except Exception:
                    pass
                
                # Then wait until READY (with grace)
                if not self.spin_detector.wait_ready_with_grace(
                        baseline,
                        grace_sec=LONG_SPIN_GRACE_SEC,
                        max_timeout=(999999 if self.infinite_wait_var.get() else SPIN_CHANGE_TIMEOUT),
                        allow_grace_click=True):
                    self._log(f"Slots: Spin #{spin_num} - completion timeout")
                    continue
                
                # Count successful spin and log if short
                elapsed_ms = (time.time() - t_start) * 1000.0
                self.state_slots.automation.total_done += 1
                self.slots_counter_var.set(str(self.state_slots.automation.total_done))
                if elapsed_ms < MIN_VALID_SPIN_MS:
                    self._log(f"Slots: Spin #{spin_num} completed (short: {elapsed_ms:.0f} ms)", orange=True)
                else:
                    self._log(f"Slots: Spin #{spin_num} completed successfully in {elapsed_ms:.0f} ms", green=True)

                # Anti-idle waggle for Slots
                if (self.waggle_on_var.get() and 
                    time.time() - last_waggle > self.waggle_secs_var.get() and
                    self.state_slots.spinner.center_xy):
                    self._perform_waggle()
                    last_waggle = time.time()

                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                    
        except Exception as e:
            self._log(f"Slots automation error: {e}", red=True)
        finally:
            self.slots_mode_active = False
            self.mouse_monitor.stop_monitoring()
            self.slots_ready_btn.config(state=tk.NORMAL, text="Ready")
            self.slots_pause_btn.config(state=tk.DISABLED)
            self._log("Slots automation stopped", bright_blue=True)

    # ---------- FIXED: Counter Mode ----------

    def _counter_ready(self):
        """FIXED: Counter Ready - positions mouse and starts click detection"""
        self._stop_all_modes()
        
        if not self._position_mouse_with_grace("Counter"):
            return
        
        self.counter_mode_active = True
        # Reset Actual Clicks counter for Counter mode
        self.state_slots.automation.actual_clicks = 0
        self.clicker_manual_actual_clicks.set(0)
        
        # Update UI
        self.counter_ready_btn.config(state=tk.DISABLED, text="Detecting...")
        self.counter_pause_btn.config(state=tk.NORMAL)
        
        # Start click detection
        self.click_detector.start_monitoring()
        
        self._log("Counter: Ready - click detection started, YOU must click manually", green=True)

    def _counter_pause(self):
        """Pause counter mode"""
        self.counter_mode_active = False
        self.click_detector.stop_monitoring()
        
        self.counter_ready_btn.config(state=tk.NORMAL, text="Ready")
        self.counter_pause_btn.config(state=tk.DISABLED)
        
        self._log("Counter: Paused - click detection stopped", bright_blue=True)

    def _counter_stop_reset(self):
        """Stop counter and reset counters (not calculator)"""
        self._stop_all_modes()
        
        # Reset counters
        self.clicker_manual_target.set(0)
        self.clicker_manual_done.set(0)
        self.state_slots.automation.actual_clicks = 0
        self.clicker_manual_actual_clicks.set(0)
        
        # Reset UI
        self.counter_ready_btn.config(state=tk.NORMAL, text="Ready")
        self.counter_pause_btn.config(state=tk.DISABLED)
        
        self._log("Counter: Stop/Reset - counters cleared, calculator preserved", bright_blue=True)

    # ---------- FIXED: Automatic Mode ----------

    def _auto_ready(self):
        """FIXED: Automatic Ready - positions mouse and starts automation"""
        self._stop_all_modes()
        
        target = self.clicker_auto_target.get()
        if target <= 0:
            messagebox.showwarning("Invalid Target", "Set target > 0.")
            return
        
        if not self._position_mouse_with_grace("Automatic"):
            return
        
        self.automatic_mode_active = True
        self.state_slots.automation.mode = AutomationMode.RUNNING
        self.state_slots.automation.stop_requested = False
        # Reset pause flags to ensure clean start
        self.state_slots.automation.paused_by_mouse = False
        self.state_slots.automation.paused_manually = False
        # Preserve Actual Clicks across resumes; reset only if starting fresh
        try:
            starting_fresh = int(self.clicker_auto_done.get()) == 0 if hasattr(self, 'clicker_auto_done') else True
        except Exception:
            starting_fresh = True
        if starting_fresh:
            self.state_slots.automation.actual_clicks = 0
            if hasattr(self, 'clicker_auto_actual_clicks'):
                self.clicker_auto_actual_clicks.set(0)
        
        # Update UI
        self.auto_ready_btn.config(state=tk.DISABLED, text="Running...")
        self.auto_pause_btn.config(state=tk.NORMAL)
        
        # Start automation
        self.mouse_monitor.start_monitoring()
        threading.Thread(target=self._auto_automation_loop, daemon=True).start()
        
        self._log(f"Automatic: Ready - automation started with target {target}", green=True)

    def _auto_pause(self):
        """Pause automatic mode"""
        self.state_slots.automation.paused_manually = True
        self.auto_ready_btn.config(state=tk.NORMAL, text="Ready")
        self._log("Automatic: Pause requested - will pause at next ready position", bright_blue=True)

    def _auto_stop_reset(self):
        """Stop automatic and reset counters (not calculator)"""
        self._stop_all_modes()
        
        # Reset counters
        self.clicker_auto_target.set(0)
        self.clicker_auto_done.set(0)
        if hasattr(self, 'clicker_auto_wager_var'):
            self.clicker_auto_wager_var.set("£0.00")
        self.state_slots.automation.actual_clicks = 0
        self.clicker_auto_actual_clicks.set(0)
        
        # Reset UI
        self.auto_ready_btn.config(state=tk.NORMAL, text="Ready")
        self.auto_pause_btn.config(state=tk.DISABLED)
        
        self._log("Automatic: Stop/Reset - counters cleared, calculator preserved", bright_blue=True)

    def _auto_automation_loop(self):
        """Automatic clicker loop"""
        try:
            baseline = self.state_slots.spinner.baseline_ready
            # Preserve progress across resumes (unless Stop/Reset)
            done = int(self.clicker_auto_done.get() if hasattr(self, 'clicker_auto_done') else 0)
            target = self.clicker_auto_target.get()
            last_waggle = time.time()
            
            while (self.automatic_mode_active and done < target and
                   not self.state_slots.automation.stop_requested):
                
                # Check pause states
                if (self.state_slots.automation.paused_by_mouse or
                    self.state_slots.automation.paused_manually):
                    time.sleep(0.5)
                    continue
                
                next_idx = done + 1
                self._log(f"Automatic: Executing click #{next_idx}/{target}")
                
                if not self.spin_detector.ensure_ready_multigrace(baseline):
                    if (self.state_slots.automation.paused_by_mouse or 
                        self.state_slots.automation.paused_manually):
                        time.sleep(0.5)
                        continue
                    self._log(f"Automatic: Click #{done} - timeout waiting READY")
                    break
                
                t_start = time.time()
                self._log("Automatic: Spin button looks READY — clicking", orange=True)
                if not self.spin_detector.do_click():
                    self._log(f"Automatic: Click #{next_idx} - click failed")
                    break
                
                # REQUIRE: see NOT_READY after click, else consider it a no-op
                if not self.spin_detector._wait_for_change(baseline, become_changed=True, timeout=1.8):
                    self._log(f"Automatic: Click #{next_idx} - no visual change")
                    continue
                # Count the actual click only when NOT_READY follows (real spin start)
                try:
                    self._inc_actual_clicks()
                except Exception:
                    pass
                
                if self.spin_detector.wait_ready_with_grace(
                        baseline,
                        grace_sec=LONG_SPIN_GRACE_SEC,
                        max_timeout=(999999 if self.infinite_wait_var.get() else SPIN_CHANGE_TIMEOUT),
                        allow_grace_click=True):
                    elapsed_ms = (time.time() - t_start) * 1000.0
                    if elapsed_ms < MIN_VALID_SPIN_MS:
                        self._log(f"Automatic: Spin #{next_idx} too short ({elapsed_ms:.0f} ms < {MIN_VALID_SPIN_MS} ms) — retrying", orange=True)
                        continue
                    done = next_idx
                    self.clicker_auto_done.set(done)
                    self._log(f"Automatic: Click #{done}/{target} completed in {elapsed_ms:.0f} ms", green=True)
                    # Guardrail: stop at wager target if reached (from Clicker calculator)
                    try:
                        total_str = self.clicker_calculator.total_var.get()
                        bet = float(self.clicker_calculator.bet_var.get() or "0")
                        if total_str and total_str != "—" and bet > 0:
                            total_target = float(total_str.replace("£",""))
                            current = done * bet
                            if total_target > 0 and current >= total_target:
                                self._log(f"Automatic: Wager target reached £{current:.2f}/£{total_target:.2f} — stopping", green=True)
                                break
                    except Exception:
                        pass
                else:
                    self._log(f"Automatic: Click #{done} - completion timeout")
                
                # Anti-idle waggle
                if (self.waggle_on_var.get() and 
                    time.time() - last_waggle > self.waggle_secs_var.get() and
                    self.state_slots.spinner.center_xy):
                    self._perform_waggle()
                    last_waggle = time.time()
                
                time.sleep(random.uniform(0.3, 0.7))
            
            if done >= target:
                self._log(f"Automatic: Target reached - {done} spins completed", green=True)
                try:
                    if bool(self.auto_save_on_target_var.get()):
                        self._auto_save_session("auto_target")
                except Exception:
                    pass
                
        except Exception as e:
            self._log(f"Automatic clicker error: {e}", red=True)
        finally:
            self.automatic_mode_active = False
            self.mouse_monitor.stop_monitoring()
            self.auto_ready_btn.config(state=tk.NORMAL, text="Ready")
            self.auto_pause_btn.config(state=tk.DISABLED)
            self._log("Automatic clicker stopped", bright_blue=True)

    def _perform_waggle(self):
        """Anti-idle waggle movement"""
        if not PYAUTOGUI_AVAILABLE or not self.state_slots.spinner.center_xy:
            return
        try:
            x, y = self.state_slots.spinner.center_xy
            amp = clamp(self.waggle_amp_var.get(), 1, 40)
            pg.moveTo(x + amp, y, duration=0.05)
            pg.moveTo(x - amp, y, duration=0.05)
            pg.moveTo(x, y, duration=0.05)
            self._log("Anti-idle waggle performed")
        except Exception:
            pass

    # ---------- Target Logic ----------

    def _check_targets_reached(self) -> bool:
        """Check if any targets are reached for slots"""
        # Check explicit applied target (not just calculator display)
        target_spins = int(getattr(self.state_slots.automation, 'target_count', 0))
        if target_spins > 0 and self.state_slots.automation.total_done >= target_spins:
            self._log(f"Slots target reached: {self.state_slots.automation.total_done}/{target_spins}", green=True)
            try:
                if bool(self.auto_save_on_target_var.get()):
                    self._auto_save_session("slots_target")
            except Exception:
                pass
            return True
            
            # Check wager target
            total_str = self.slots_calculator.total_var.get()
            bet_str = self.slots_calculator.bet_var.get()
            if total_str != "—" and bet_str:
                try:
                    target_wager = float(total_str.replace("£", ""))
                    bet_per_spin = float(bet_str)
                    current_wager = self.state_slots.automation.total_done * bet_per_spin
                    if target_wager > 0 and current_wager >= target_wager:
                        self._log(f"Slots wager target reached: £{current_wager:.2f}/£{target_wager:.2f}", green=True)
                        try:
                            if bool(self.auto_save_on_target_var.get()):
                                self._auto_save_session("slots_wager")
                        except Exception:
                            pass
                        return True
                except:
                    pass
        
        return False

    # ---------- Geometry ----------

    def _restore_geometry(self):
        cfg = os.path.join(os.path.expanduser("~"), ".spin_helper_geometry.json")
        try:
            with open(cfg, "r") as f:
                data = json.load(f)
            self.geometry(data.get("geom", "1000x600"))
            self.attributes("-topmost", bool(data.get("topmost", True)))
            # Restore FS ROI if present
            fs = data.get("fs_roi")
            if fs and all(k in fs for k in ("x","y","w","h")):
                try:
                    self.state_slots.fs_roi = SpinnerROI(int(fs["x"]), int(fs["y"]), int(fs["w"]), int(fs["h"]))
                    if hasattr(self, 'fs_status_var'):
                        self.fs_status_var.set(f"FS ROI set at ({fs['x']},{fs['y']}) {fs['w']}x{fs['h']}")
                except Exception:
                    pass
            # Overlay suppression
            ov = data.get('overlay', {})
            self.state_slots.suppress_overlay_pause = bool(ov.get('suppress', self.state_slots.suppress_overlay_pause))
            self.state_slots.suppress_overlay_secs = float(ov.get('secs', self.state_slots.suppress_overlay_secs))
            if hasattr(self, 'overlay_suppress_var'):
                self.overlay_suppress_var.set(self.state_slots.suppress_overlay_pause)
            if hasattr(self, 'overlay_suppress_secs_var'):
                self.overlay_suppress_secs_var.set(self.state_slots.suppress_overlay_secs)
            # Optional flags
            self.infinite_wait_var.set(bool(data.get('infinite_wait', False)))
            self.auto_save_on_target_var.set(bool(data.get('auto_save_on_target', False)))
        except Exception:
            pass

    def _save_geometry(self):
        cfg = os.path.join(os.path.expanduser("~"), ".spin_helper_geometry.json")
        try:
            fs_roi = None
            if getattr(self.state_slots, 'fs_roi', None):
                fs = self.state_slots.fs_roi
                fs_roi = {"x": fs.x, "y": fs.y, "w": fs.w, "h": fs.h}
            data = {"geom": self.geometry(), "topmost": bool(self.topmost_var.get()), "fs_roi": fs_roi,
                    "overlay": {"suppress": bool(self.overlay_suppress_var.get()) if hasattr(self, 'overlay_suppress_var') else True,
                                 "secs": float(self.overlay_suppress_secs_var.get()) if hasattr(self, 'overlay_suppress_secs_var') else 11.0},
                    "infinite_wait": bool(self.infinite_wait_var.get()) if hasattr(self, 'infinite_wait_var') else False,
                    "auto_save_on_target": bool(self.auto_save_on_target_var.get()) if hasattr(self, 'auto_save_on_target_var') else False}
            with open(cfg, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _apply_topmost(self):
        try:
            self.attributes("-topmost", bool(self.topmost_var.get()))
            self._save_geometry()
        except Exception:
            pass

    def _apply_overlay_settings(self):
        try:
            self.state_slots.suppress_overlay_pause = bool(self.overlay_suppress_var.get())
            secs = float(self.overlay_suppress_secs_var.get())
            secs = max(0.0, min(60.0, secs))
            self.overlay_suppress_secs_var.set(secs)
            self.state_slots.suppress_overlay_secs = secs
            self._save_geometry()
            self._log(f"Overlay auto-pause suppression: {'ON' if self.state_slots.suppress_overlay_pause else 'OFF'}, {secs:.1f}s")
        except Exception:
            pass

    # Temporarily drop topmost so overlay clicks never hit our window
    def _overlay_click_begin(self):
        try:
            self._overlay_prev_topmost = bool(self.attributes('-topmost'))
            if self._overlay_prev_topmost:
                self.attributes('-topmost', False)
                self.update_idletasks()
        except Exception:
            pass

    def _overlay_click_end(self):
        try:
            if getattr(self, '_overlay_prev_topmost', False):
                self.attributes('-topmost', True)
                self.update_idletasks()
        except Exception:
            pass

    # ---------- Session Save/Load ----------

    def _ensure_sessions_dir(self):
        try:
            os.makedirs(SESSIONS_DIR, exist_ok=True)
        except Exception:
            pass

    def _get_log_tail(self, lines: int = 60) -> list:
        try:
            content = self.log.get("1.0", tk.END)
            arr = [ln for ln in content.splitlines() if ln.strip()]
            return arr[-lines:]
        except Exception:
            return []

    def _calc_to_dict(self, calc) -> dict:
        if not calc:
            return {}
        d = {}
        for name in [
            "amount_var", "mult_var", "bet_var", "total_target_input_var", "total_var",
            "target_var", "current_wager_var", "balance_var", "bonus_first_var",
        ]:
            if hasattr(calc, name):
                var = getattr(calc, name)
                try:
                    d[name] = var.get() if hasattr(var, 'get') else None
                except Exception:
                    d[name] = None
        return d

    def _collect_session(self) -> dict:
        data = {
            "version": APP_VERSION,
            "ts": time.time(),
            "spinner": None,
            "fs_roi": None,
            "detect_fs": bool(getattr(self.state_slots, 'detect_fs', False)),
            "slots": {
                "spins_done": int(getattr(self.state_slots.automation, 'total_done', 0)),
                "target": int(getattr(self.state_slots.automation, 'target_count', 0)),
                "actual_clicks": int(getattr(self.state_slots.automation, 'actual_clicks', 0)),
            },
            "clicker": {
                "manual": {
                    "target": int(getattr(self, 'clicker_manual_target', tk.IntVar(value=0)).get()) if hasattr(self, 'clicker_manual_target') else 0,
                    "done": int(getattr(self, 'clicker_manual_done', tk.IntVar(value=0)).get()) if hasattr(self, 'clicker_manual_done') else 0,
                    "actual_clicks": int(getattr(self, 'clicker_manual_actual_clicks', tk.IntVar(value=0)).get()) if hasattr(self, 'clicker_manual_actual_clicks') else 0,
                },
                "automatic": {
                    "target": int(getattr(self, 'clicker_auto_target', tk.IntVar(value=0)).get()) if hasattr(self, 'clicker_auto_target') else 0,
                    "done": int(getattr(self, 'clicker_auto_done', tk.IntVar(value=0)).get()) if hasattr(self, 'clicker_auto_done') else 0,
                    "actual_clicks": int(getattr(self, 'clicker_auto_actual_clicks', tk.IntVar(value=0)).get()) if hasattr(self, 'clicker_auto_actual_clicks') else 0,
                    "balance": getattr(self, 'clicker_balance_var', tk.StringVar(value="")).get() if hasattr(self, 'clicker_balance_var') else "",
                    "current_wager": getattr(self, 'clicker_auto_wager_var', tk.StringVar(value="£0.00")).get() if hasattr(self, 'clicker_auto_wager_var') else "£0.00",
                },
            },
            "calculators": {
                "slots": self._calc_to_dict(getattr(self, 'slots_calculator', None)),
                "roulette": self._calc_to_dict(getattr(self, 'roulette_calculator', None)),
                "clicker": self._calc_to_dict(getattr(self, 'clicker_calculator', None)),
            },
            "logs_tail": self._get_log_tail(60),
        }
        sp = getattr(self.state_slots, 'spinner', None)
        if sp and sp.center_xy:
            data["spinner"] = {
                "center_xy": list(sp.center_xy),
                "roi": {"x": sp.roi.x, "y": sp.roi.y, "w": sp.roi.w, "h": sp.roi.h} if sp.roi else None,
            }
        if getattr(self.state_slots, 'fs_roi', None):
            r = self.state_slots.fs_roi
            data["fs_roi"] = {"x": r.x, "y": r.y, "w": r.w, "h": r.h}
        return data

    def _apply_session(self, data: dict):
        try:
            # Restore calculators
            def set_var(container, name, value):
                try:
                    if hasattr(container, name) and value is not None:
                        v = getattr(container, name)
                        if hasattr(v, 'set'):
                            v.set(value)
                except Exception:
                    pass

            calcs = data.get("calculators", {})
            if calcs:
                if hasattr(self, 'slots_calculator'):
                    for k, v in calcs.get("slots", {}).items():
                        set_var(self.slots_calculator, k, v)
                if hasattr(self, 'roulette_calculator'):
                    for k, v in calcs.get("roulette", {}).items():
                        set_var(self.roulette_calculator, k, v)
                if hasattr(self, 'clicker_calculator'):
                    for k, v in calcs.get("clicker", {}).items():
                        set_var(self.clicker_calculator, k, v)

            # Restore clicker fields
            cl = data.get("clicker", {})
            if cl:
                man = cl.get("manual", {})
                if hasattr(self, 'clicker_manual_target'): self.clicker_manual_target.set(int(man.get("target", 0)))
                if hasattr(self, 'clicker_manual_done'): self.clicker_manual_done.set(int(man.get("done", 0)))
                if hasattr(self, 'clicker_manual_actual_clicks'): self.clicker_manual_actual_clicks.set(int(man.get("actual_clicks", 0)))
                aut = cl.get("automatic", {})
                if hasattr(self, 'clicker_auto_target'): self.clicker_auto_target.set(int(aut.get("target", 0)))
                if hasattr(self, 'clicker_auto_done'): self.clicker_auto_done.set(int(aut.get("done", 0)))
                if hasattr(self, 'clicker_auto_actual_clicks'): self.clicker_auto_actual_clicks.set(int(aut.get("actual_clicks", 0)))
                if hasattr(self, 'clicker_balance_var'): self.clicker_balance_var.set(aut.get("balance", ""))
                if hasattr(self, 'clicker_auto_wager_var'): self.clicker_auto_wager_var.set(aut.get("current_wager", "£0.00"))

            # Restore slots counters
            slots = data.get("slots", {})
            self.state_slots.automation.total_done = int(slots.get("spins_done", 0))
            self.state_slots.automation.target_count = int(slots.get("target", 0))
            self.state_slots.automation.actual_clicks = int(slots.get("actual_clicks", 0))
            if hasattr(self, 'slots_counter_var'):
                self.slots_counter_var.set(str(self.state_slots.automation.total_done))
            if hasattr(self, 'slots_actual_clicks_var'):
                self.slots_actual_clicks_var.set(str(self.state_slots.automation.actual_clicks))

            # Restore FS detection + ROI
            self.state_slots.detect_fs = bool(data.get("detect_fs", self.state_slots.detect_fs))
            fsr = data.get("fs_roi")
            if fsr and all(k in fsr for k in ("x","y","w","h")):
                try:
                    self.state_slots.fs_roi = SpinnerROI(int(fsr['x']), int(fsr['y']), int(fsr['w']), int(fsr['h']))
                    if hasattr(self, 'fs_status_var'):
                        self.fs_status_var.set(f"FS ROI set at ({fsr['x']},{fsr['y']}) {fsr['w']}x{fsr['h']}")
                except Exception:
                    pass

            # Restore spinner geometry only (force re-capture of baseline)
            sp = data.get("spinner")
            if sp and sp.get('roi') and sp.get('center_xy'):
                try:
                    roi = sp['roi']
                    self.state_slots.spinner.roi = SpinnerROI(int(roi['x']), int(roi['y']), int(roi['w']), int(roi['h']))
                    self.state_slots.spinner.center_xy = tuple(sp['center_xy'])
                    self.state_slots.spinner.is_valid = False
                    self.state_slots.spinner.baseline_ready = None
                    if hasattr(self, 'spinner_status_var'):
                        self.spinner_status_var.set("Spinner geometry loaded — please Capture Spinner before starting")
                except Exception:
                    pass

            # Append last log lines for context
            for ln in data.get("logs_tail", [])[-10:]:
                self._log(f"[session] {ln}", blue=True)

            self._log("Session loaded. Verify spinner capture and browser selection before starting.", bright_blue=True)
        except Exception as e:
            self._log(f"Session load error: {e}", red=True)

    def _save_session_dialog(self):
        try:
            self._ensure_sessions_dir()
            ts = time.strftime("%Y%m%d_%H%M%S")
            default = os.path.join(SESSIONS_DIR, f"session_{ts}.json")
            path = filedialog.asksaveasfilename(initialfile=os.path.basename(default), initialdir=SESSIONS_DIR, defaultextension=".json", filetypes=[["JSON","*.json"]])
            if not path:
                return
            data = self._collect_session()
            # Optional friendly session name
            try:
                name = simpledialog.askstring("Session Name (optional)", "Enter a friendly session name:", parent=self)
            except Exception:
                name = None
            if name:
                try:
                    data["name"] = name.strip()
                except Exception:
                    pass
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            self._log(f"Session saved to {path}", bright_blue=True)
            try:
                self.session_name_var.set((name.strip() if name else None) or os.path.basename(path))
            except Exception:
                pass
        except Exception as e:
            self._log(f"Session save error: {e}", red=True)

    def _load_session_dialog(self):
        try:
            self._ensure_sessions_dir()
            path = filedialog.askopenfilename(initialdir=SESSIONS_DIR, filetypes=[["JSON","*.json"]])
            if not path:
                return
            with open(path, 'r') as f:
                data = json.load(f)
            self._apply_session(data)
            self._log(f"Loaded session from {path}", bright_blue=True)
            try:
                name = data.get('name') if isinstance(data, dict) else None
                self.session_name_var.set(name or os.path.basename(path))
            except Exception:
                pass
        except Exception as e:
            self._log(f"Session load error: {e}", red=True)

    def _auto_save_session(self, reason: str = ""):
        try:
            self._ensure_sessions_dir()
            ts = time.strftime("%Y%m%d_%H%M%S")
            suffix = f"_{reason}" if reason else ""
            path = os.path.join(SESSIONS_DIR, f"autosave_{ts}{suffix}.json")
            data = self._collect_session()
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            self._log(f"Session auto-saved: {path}", bright_blue=True)
        except Exception:
            pass

    # ---------- Logging ----------

    def _log(self, msg, green=False, blue=False, red=False, orange=False, bright_blue=False):
        if orange:
            color = self.tag_orange
        elif bright_blue:
            color = self.tag_bright_blue
        elif green:
            color = self.tag_green
        elif blue:
            color = self.tag_blue
        elif red:
            color = self.tag_red
        else:
            color = None
        self._log_q.put((msg, color))

    def _drain_log(self):
        try:
            while True:
                msg, color = self._log_q.get_nowait()
                ts = now_ts()
                tags = (color,) if color else ()
                self.log.insert(tk.END, f"{ts} {msg}\n", tags)
                self.log.see(tk.END)
        except queue.Empty:
            pass
        finally:
            self.after(UI_FLUSH_MS, self._drain_log)

    # ---------- Actual Clicks Counter Updater ----------
    def _inc_actual_clicks(self, x: Optional[int]=None, y: Optional[int]=None):
        try:
            if not self._counting_allowed(x, y):
                return
            self.state_slots.automation.actual_clicks += 1
            if self.slots_mode_active:
                self.slots_actual_clicks_var.set(str(self.state_slots.automation.actual_clicks))
            elif self.automatic_mode_active:
                self.clicker_auto_actual_clicks.set(self.state_slots.automation.actual_clicks)
            elif self.counter_mode_active:
                self.clicker_manual_actual_clicks.set(self.state_slots.automation.actual_clicks)
        except Exception:
            pass

    def _counting_allowed(self, x: Optional[int]=None, y: Optional[int]=None) -> bool:
        try:
            # Spinner must be captured
            sp = self.state_slots.spinner
            if not sp or not sp.is_valid or not sp.center_xy:
                return False
            # Ready must be engaged in one of the modes
            ready_any = self.counter_mode_active or self.automatic_mode_active or self.slots_mode_active
            if not ready_any:
                return False
            # If automation paused due to mouse movement, do not count
            if getattr(self.state_slots.automation, 'paused_by_mouse', False):
                return False
            # Verify mouse is near/within spinner region
            mx, my = (None, None)
            if x is not None and y is not None:
                mx, my = x, y
            elif PYAUTOGUI_AVAILABLE:
                try:
                    mx, my = pg.position()
                except Exception:
                    mx, my = None, None
            # If we cannot read mouse, be conservative and do not count
            if mx is None or my is None:
                return False
            # Prefer ROI containment, else distance from center
            if sp.roi:
                if not (sp.roi.x <= mx <= sp.roi.x + sp.roi.w and sp.roi.y <= my <= sp.roi.y + sp.roi.h):
                    return False
            else:
                sx, sy = sp.center_xy
                distance = math.sqrt((mx - sx)**2 + (my - sy)**2)
                if distance > MOUSE_PAUSE_THRESHOLD:
                    return False
            return True
        except Exception:
            return False

    # ---------- Clicker Automatic Current Wager Updater ----------
    def _update_clicker_current_wager(self):
        try:
            # Uses Clicker calculator Bet/spin and Automatic Done count
            bet = 0.0
            if hasattr(self, 'clicker_calculator'):
                bet = float(self.clicker_calculator.bet_var.get() or "0")
            auto_done = int(self.clicker_auto_done.get() if hasattr(self, 'clicker_auto_done') else 0)
            current = auto_done * bet
            if hasattr(self, 'clicker_auto_wager_var'):
                self.clicker_auto_wager_var.set(f"£{current:.2f}")
            # Also update Counter (manual) current wager
            manual_done = int(self.clicker_manual_done.get() if hasattr(self, 'clicker_manual_done') else 0)
            manual_current = manual_done * bet
            if hasattr(self, 'clicker_manual_wager_var'):
                self.clicker_manual_wager_var.set(f"£{manual_current:.2f}")
            # Update Slots current wager based on Slots calculator bet/spin × slots spins completed
            slots_bet = 0.0
            if hasattr(self, 'slots_calculator'):
                try:
                    slots_bet = float(self.slots_calculator.bet_var.get() or "0")
                except Exception:
                    slots_bet = 0.0
            slots_spins = int(getattr(self.state_slots.automation, 'total_done', 0))
            slots_current = slots_spins * slots_bet
            if hasattr(self, 'slots_current_wager_var'):
                self.slots_current_wager_var.set(f"£{slots_current:.2f}")
        except Exception:
            pass
        finally:
            self.after(1000, self._update_clicker_current_wager)

    def destroy(self):
        try:
            if hasattr(self, 'click_detector'):
                self.click_detector.stop_monitoring()
        except Exception:
            pass
        self._save_geometry()
        super().destroy()

# --------------- Main Entry Point ---------------

def check_dependencies():
    missing = []
    
    if not PIL_AVAILABLE:
        missing.append("Pillow (PIL)")
    if not PYAUTOGUI_AVAILABLE:
        missing.append("pyautogui")
    
    if missing:
        print(f"ERROR: Missing dependencies: {', '.join(missing)}")
        return False
    
    if not PYNPUT_AVAILABLE:
        print("INFO: pynput not available - click detection disabled")
    
    return True

def main():
    print(f"Starting Spin Helper v{APP_VERSION}")
    print(f"Platform: {sys.platform}")
    
    if not check_dependencies():
        return 1
    
    try:
        app = SpinHelperApp()
        app.mainloop()
    except Exception as e:
        print(f"Fatal error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
