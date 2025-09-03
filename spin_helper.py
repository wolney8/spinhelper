# spin_helper.py — v1.17.5
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
from tkinter import ttk, messagebox

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

APP_VERSION = "1.17.5"
UI_FLUSH_MS = 60

# Spin detection thresholds
PIX_DIFF_READY = 4.0
PIX_DIFF_CHANGED = 10.0
SPIN_CHANGE_TIMEOUT = 25.0
CHANGE_STICK_MS = 180
MIN_VALID_SPIN_MS = 2000
MAX_CONSECUTIVE_BLIPS = 3

# Long-spin handling (avoid premature rescues on long wins/anticipation)
LONG_SPIN_GRACE_SEC = 4.0

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
    
@dataclass
class SessionStateSlots:
    spinner: SpinnerCapture = None
    fs_roi: Optional[SpinnerROI] = None
    detect_fs: bool = True
    automation: AutomationState = None
    
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
                    
                    if distance > MOUSE_PAUSE_THRESHOLD and not self.state.automation.paused_by_mouse:
                        self.state.automation.paused_by_mouse = True
                        self.log(f"Auto-paused: mouse moved {distance:.0f}px from spinner")
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
    def select_roi_native(parent, auto_toggle_topmost=True):
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
            
            messagebox.showinfo("ROI Selection", 
                "macOS screenshot selection will open.\n"
                "Click and drag to select the Free-Spins banner area.\n"
                "Press Escape to cancel selection.")
            
            result = subprocess.run([
                "screencapture", "-i", "-r", "/tmp/spin_helper_roi_selection.png"
            ], timeout=60)
            
            parent.deiconify()
            parent.lift()
            
            try:
                if parent_was_topmost and auto_toggle_topmost:
                    parent.attributes("-topmost", True)
                    parent.update()
            except Exception:
                pass
            
            return result.returncode == 0
            
        except Exception:
            parent.deiconify()
            try:
                if parent_was_topmost and auto_toggle_topmost:
                    parent.attributes("-topmost", True)
                    parent.update()
            except Exception:
                pass
            return False

# --------------- Enhanced Calculator Component ---------------

class EmbeddedCalculator:
    def __init__(self, parent, app_instance, feature_name):
        self.app = app_instance
        self.feature_name = feature_name
        self.frame = ttk.LabelFrame(parent, text=f"{feature_name} Target Calculator", padding=8)
        
        self.amount_var = tk.StringVar()
        self.mult_var = tk.StringVar()
        self.bet_var = tk.StringVar()
        # Optional direct input for Scenario 1: Total Wager Target
        self.total_target_input_var = tk.StringVar()
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
        
        ttk.Label(input_frame, text="Amount (£):").grid(row=0, column=0, sticky="w", padx=(0, 5))
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
            
            self.app._log(f"{self.feature_name} target applied: {target}", green=True)
            
        except Exception as e:
            messagebox.showwarning("Apply Error", str(e))
    
    def _reset(self):
        self.amount_var.set("")
        self.mult_var.set("")
        self.bet_var.set("")
        self.total_target_input_var.set("")
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
        
    def get_current_state(self) -> SpinState:
        if not PIL_AVAILABLE or not self.state.spinner.is_valid:
            return SpinState.UNKNOWN
            
        spinner = self.state.spinner
        roi = spinner.roi
        
        try:
            current = ImageGrab.grab(bbox=(roi.x, roi.y, roi.x + roi.w, roi.y + roi.h))
            rms = _rms(current, spinner.baseline_ready)
            
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
                
            roi = self.state.spinner.roi
            current = ImageGrab.grab(bbox=(roi.x, roi.y, roi.x + roi.w, roi.y + roi.h))
            diff = _rms(current, baseline)
            
            if become_changed and diff >= PIX_DIFF_CHANGED:
                return True
            if not become_changed and diff <= PIX_DIFF_READY:
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

            if allow_grace_click and not grace_clicked and self.state.spinner.center_xy and PYAUTOGUI_AVAILABLE:
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
        if not self.state.spinner.center_xy:
            return False
            
        x, y = self.state.spinner.center_xy
        try:
            jx = x + random.randint(-JITTER_PX, JITTER_PX)
            jy = y + random.randint(-JITTER_PX, JITTER_PX)
            pg.moveTo(jx, jy, duration=0.06)
            pg.click()
            self.log("Rescue click #1")
            
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

        # Log styling
        self.tag_green = "green"
        self.tag_blue = "blue"
        self.tag_red = "red"
        self.log.tag_configure(self.tag_green, foreground="#00a000")
        self.log.tag_configure(self.tag_blue, foreground="#0066cc")
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
        
        # System info
        sys_frame = ttk.LabelFrame(tab_env, text="System Information", padding=10)
        sys_frame.pack(fill=tk.X, padx=8, pady=8)
        
        info_text = f"Python: {sys.version.split()[0]} | Platform: {sys.platform}\n"
        info_text += f"PIL: {PIL_AVAILABLE} | PyAutoGUI: {PYAUTOGUI_AVAILABLE} | Pynput: {PYNPUT_AVAILABLE}\n"
        info_text += "Consistent Ready/Pause/Stop behavior across all features"
        ttk.Label(sys_frame, text=info_text, justify=tk.LEFT).pack(anchor='w')

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
        
        self.slots_stop_btn = ttk.Button(auto_controls, text="Stop/Reset", command=self._slots_stop_reset)
        self.slots_stop_btn.pack(side=tk.LEFT)
        
        # Spin counter display
        counter_frame = ttk.Frame(auto_frame)
        counter_frame.pack(fill=tk.X, pady=(8, 0))
        
        ttk.Label(counter_frame, text="Spins Completed:").pack(side=tk.LEFT)
        self.slots_counter_var = tk.StringVar(value="0")
        ttk.Label(counter_frame, textvariable=self.slots_counter_var, font=('Monaco', 12, 'bold'), 
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

        # Display calculator targets for visibility (under Automation Controls)
        slots_meta_frame = ttk.Frame(auto_frame)
        slots_meta_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(slots_meta_frame, text="Target Spins:").pack(side=tk.LEFT)
        ttk.Label(slots_meta_frame, textvariable=self.slots_calculator.target_var, font=('Monaco', 10, 'bold'),
                  foreground="white").pack(side=tk.LEFT, padx=(6, 15))
        ttk.Label(slots_meta_frame, text="Total Wagering:").pack(side=tk.LEFT)
        ttk.Label(slots_meta_frame, textvariable=self.slots_calculator.total_var, font=('Monaco', 10, 'bold'),
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
        
        ttk.Label(counter_controls, text="Done:").grid(row=0, column=2, sticky="w")
        ttk.Label(counter_controls, textvariable=self.clicker_manual_done, font=('Monaco', 10, 'bold'),
                 foreground="white").grid(row=0, column=3, padx=(5, 15))
        
        # FIXED: Consistent button behavior
        self.counter_ready_btn = ttk.Button(counter_controls, text="Ready", command=self._counter_ready)
        self.counter_ready_btn.grid(row=0, column=4, padx=(10, 5))
        
        self.counter_pause_btn = ttk.Button(counter_controls, text="Pause", command=self._counter_pause, state=tk.DISABLED)
        self.counter_pause_btn.grid(row=0, column=5, padx=(0, 5))
        
        self.counter_stop_btn = ttk.Button(counter_controls, text="Stop/Reset", command=self._counter_stop_reset)
        self.counter_stop_btn.grid(row=0, column=6)
        
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
        
        ttk.Label(auto_controls, text="Done:").grid(row=0, column=2, sticky="w")
        ttk.Label(auto_controls, textvariable=self.clicker_auto_done, font=('Monaco', 10, 'bold'),
                 foreground="white").grid(row=0, column=3, padx=(5, 15))
        
        # FIXED: Consistent button behavior
        self.auto_ready_btn = ttk.Button(auto_controls, text="Ready", command=self._auto_ready)
        self.auto_ready_btn.grid(row=0, column=4, padx=(10, 5))
        
        self.auto_pause_btn = ttk.Button(auto_controls, text="Pause", command=self._auto_pause, state=tk.DISABLED)
        self.auto_pause_btn.grid(row=0, column=5, padx=(0, 5))
        
        self.auto_stop_btn = ttk.Button(auto_controls, text="Stop/Reset", command=self._auto_stop_reset)
        self.auto_stop_btn.grid(row=0, column=6)
        
        # Current Wager (for Automatic) — shown before waggle controls
        self.clicker_auto_wager_var = tk.StringVar(value="£0.00")
        wager_frame = ttk.Frame(auto_frame)
        wager_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(wager_frame, text="Current Wager:").pack(side=tk.LEFT)
        ttk.Label(wager_frame, textvariable=self.clicker_auto_wager_var, font=('Monaco', 10, 'bold'),
                 foreground="white").pack(side=tk.LEFT, padx=(6, 0))

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
            
            thumb_img = baseline.copy()
            thumb_img.thumbnail((32, 32))
            thumbnail = ImageTk.PhotoImage(thumb_img)
            
            self.state_slots.spinner.roi = SpinnerROI(left, top, w, h)
            self.state_slots.spinner.baseline_ready = baseline
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
        self._log("Starting native FS area selection...", green=True)
        
        try:
            proceed = messagebox.askyesno("FS Area Selection", 
                "This will use the native macOS screenshot tool.\n\n"
                "Click YES, then:\n"
                "1. Click and drag to select the Free-Spins banner area\n"
                "2. The selection will be stored for detection\n\n"
                "Click NO to cancel.\n\n"
                "Note: Stay-on-top will be temporarily disabled")
            
            if proceed:
                success = ROISelector.select_roi_native(self, auto_toggle_topmost=True)
                if success:
                    self._log("FS area captured using native selection", green=True)
                else:
                    self._log("FS area selection cancelled")
        except Exception as e:
            self._log(f"Native FS selection error: {e}")

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
        
        self._log("All automation modes stopped")

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
        self._log("Slots: Pause requested - will pause at next ready position")

    def _slots_stop_reset(self):
        """Stop slots and reset counters (not calculator)"""
        self._stop_all_modes()
        
        # Reset counters but NOT calculator
        self.state_slots.automation.total_done = 0
        self.state_slots.automation.target_count = 0
        self.slots_counter_var.set("0")
        
        # Reset UI
        self.slots_ready_btn.config(state=tk.NORMAL, text="Ready")
        self.slots_pause_btn.config(state=tk.DISABLED)
        
        self._log("Slots: Stop/Reset - counters cleared, calculator preserved")

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
                
                # Execute spin with robust detection
                if not self.spin_detector._ensure_ready_before_click(baseline):
                    self._log(f"Slots: Spin #{spin_num} - timeout waiting READY")
                    break
                
                t_start = time.time()
                if not self.spin_detector.do_click():
                    self._log(f"Slots: Spin #{spin_num} - click failed")
                    continue
                
                if not self.spin_detector._wait_change_sticky(baseline, CHANGE_STICK_MS, timeout=0.9):
                    if not self.spin_detector._rescue_once_then_wait_ready(baseline, wait_after_click=3.0):
                        self._log(f"Slots: Spin #{spin_num} - no visual change")
                        continue
                
                if not self.spin_detector.wait_ready_with_grace(baseline, grace_sec=LONG_SPIN_GRACE_SEC, max_timeout=SPIN_CHANGE_TIMEOUT, allow_grace_click=True):
                    if not self.spin_detector._rescue_once_then_wait_ready(baseline, wait_after_click=SPIN_CHANGE_TIMEOUT/2):
                        self._log(f"Slots: Spin #{spin_num} - completion timeout")
                        continue
                
                # Count successful spin
                self.state_slots.automation.total_done += 1
                self.slots_counter_var.set(str(self.state_slots.automation.total_done))
                elapsed_ms = (time.time() - t_start) * 1000.0
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
            self._log("Slots automation stopped")

    # ---------- FIXED: Counter Mode ----------

    def _counter_ready(self):
        """FIXED: Counter Ready - positions mouse and starts click detection"""
        self._stop_all_modes()
        
        if not self._position_mouse_with_grace("Counter"):
            return
        
        self.counter_mode_active = True
        
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
        
        self._log("Counter: Paused - click detection stopped")

    def _counter_stop_reset(self):
        """Stop counter and reset counters (not calculator)"""
        self._stop_all_modes()
        
        # Reset counters
        self.clicker_manual_target.set(0)
        self.clicker_manual_done.set(0)
        
        # Reset UI
        self.counter_ready_btn.config(state=tk.NORMAL, text="Ready")
        self.counter_pause_btn.config(state=tk.DISABLED)
        
        self._log("Counter: Stop/Reset - counters cleared, calculator preserved")

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
        self._log("Automatic: Pause requested - will pause at next ready position")

    def _auto_stop_reset(self):
        """Stop automatic and reset counters (not calculator)"""
        self._stop_all_modes()
        
        # Reset counters
        self.clicker_auto_target.set(0)
        self.clicker_auto_done.set(0)
        if hasattr(self, 'clicker_auto_wager_var'):
            self.clicker_auto_wager_var.set("£0.00")
        
        # Reset UI
        self.auto_ready_btn.config(state=tk.NORMAL, text="Ready")
        self.auto_pause_btn.config(state=tk.DISABLED)
        
        self._log("Automatic: Stop/Reset - counters cleared, calculator preserved")

    def _auto_automation_loop(self):
        """Automatic clicker loop"""
        try:
            baseline = self.state_slots.spinner.baseline_ready
            done = 0
            target = self.clicker_auto_target.get()
            last_waggle = time.time()
            
            while (self.automatic_mode_active and done < target and
                   not self.state_slots.automation.stop_requested):
                
                # Check pause states
                if (self.state_slots.automation.paused_by_mouse or
                    self.state_slots.automation.paused_manually):
                    time.sleep(0.5)
                    continue
                
                done += 1
                self._log(f"Automatic: Executing click #{done}/{target}")
                
                if not self.spin_detector._ensure_ready_before_click(baseline):
                    self._log(f"Automatic: Click #{done} - timeout waiting READY")
                    break
                
                t_start = time.time()
                if not self.spin_detector.do_click():
                    self._log(f"Automatic: Click #{done} - click failed")
                    break
                
                if not self.spin_detector._wait_change_sticky(baseline, CHANGE_STICK_MS, timeout=0.9):
                    if not self.spin_detector._rescue_once_then_wait_ready(baseline, wait_after_click=3.0):
                        self._log(f"Automatic: Click #{done} - no visual change")
                        continue
                
                if self.spin_detector.wait_ready_with_grace(baseline, grace_sec=LONG_SPIN_GRACE_SEC, max_timeout=SPIN_CHANGE_TIMEOUT, allow_grace_click=True):
                    self.clicker_auto_done.set(done)
                    elapsed_ms = (time.time() - t_start) * 1000.0
                    self._log(f"Automatic: Click #{done}/{target} completed in {elapsed_ms:.0f} ms", green=True)
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
                self._log(f"Automatic: Target reached - {done} clicks completed", green=True)
                
        except Exception as e:
            self._log(f"Automatic clicker error: {e}", red=True)
        finally:
            self.automatic_mode_active = False
            self.mouse_monitor.stop_monitoring()
            self.auto_ready_btn.config(state=tk.NORMAL, text="Ready")
            self.auto_pause_btn.config(state=tk.DISABLED)
            self._log("Automatic clicker stopped")

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
        # Check calculator targets
        if hasattr(self, 'slots_calculator'):
            target_str = self.slots_calculator.target_var.get()
            if target_str != "—" and target_str != "Error":
                target_spins = int(target_str)
                if target_spins > 0 and self.state_slots.automation.total_done >= target_spins:
                    self._log(f"Slots target reached: {self.state_slots.automation.total_done}/{target_spins}", green=True)
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
        except Exception:
            pass

    def _save_geometry(self):
        cfg = os.path.join(os.path.expanduser("~"), ".spin_helper_geometry.json")
        try:
            data = {"geom": self.geometry(), "topmost": bool(self.topmost_var.get())}
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

    # ---------- Logging ----------

    def _log(self, msg, green=False, blue=False, red=False):
        color = "green" if green else ("blue" if blue else ("red" if red else None))
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

    # ---------- Clicker Automatic Current Wager Updater ----------
    def _update_clicker_current_wager(self):
        try:
            # Uses Clicker calculator Bet/spin and Automatic Done count
            bet = 0.0
            if hasattr(self, 'clicker_calculator'):
                bet = float(self.clicker_calculator.bet_var.get() or "0")
            done = int(self.clicker_auto_done.get() if hasattr(self, 'clicker_auto_done') else 0)
            current = done * bet
            if hasattr(self, 'clicker_auto_wager_var'):
                self.clicker_auto_wager_var.set(f"£{current:.2f}")
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
