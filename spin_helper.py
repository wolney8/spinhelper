# spin_helper.py — v1.16.1 HOTFIX
# Fixed regression from v1.15.0 and implemented requested enhancements:
# - Proper spin state cycle detection (ready→not_ready→ready)
# - Mouse movement pause detection with seamless resume
# - Target stopping logic (spins OR wager amount)  
# - Current wager display in calculator
# - Pause button in automation controls
# - Enhanced Environment Setup with universal spinner capture
# - Preserved working delayed capture and embedded calculators

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

# Import checks with proper variable definitions
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
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    print("INFO: pynput not available - keyboard shortcuts disabled")

# --------------- Constants ---------------

APP_VERSION = "1.16.1 HOTFIX"
UI_FLUSH_MS = 60

# Enhanced readiness thresholds
PIX_DIFF_READY = 7.5
BRIGHT_READY_TOL = 0.25
COLOR_D_READY_TOL = 30.0

# NEW: Spin state detection for proper cycle tracking
SPIN_STATE_CHANGE_THRESHOLD = 15.0
SPIN_COMPLETE_TIMEOUT_MS = 45000

# NEW: Mouse movement pause detection
MOUSE_PAUSE_THRESHOLD = 80  # pixels from capture point
MOUSE_CHECK_INTERVAL = 0.5  # seconds

# Defaults
AC_DEFAULT_WAGGLE_ON = False
AC_DEFAULT_WAGGLE_SECS = 25
AC_DEFAULT_WAGGLE_AMP = 10

# --------------- Enums ---------------

class SpinState(Enum):
    READY = "ready"
    NOT_READY = "not_ready"
    UNKNOWN = "unknown"

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

def _color_dist(c1: Tuple[float,float,float], c2: Tuple[float,float,float]) -> float:
    return math.sqrt((c1[0]-c2[0])**2 + (c1[1]-c2[1])**2 + (c1[2]-c2[2])**2)

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
class SessionStateSlots:
    spinner: SpinnerCapture = None
    fs_roi: Optional[SpinnerROI] = None
    detect_fs: bool = True
    # NEW: Enhanced state tracking
    current_spin_state: SpinState = SpinState.UNKNOWN
    total_spins: int = 0
    paused_by_mouse: bool = False
    last_mouse_pos: Optional[Tuple[int,int]] = None
    
    def __post_init__(self):
        if self.spinner is None:
            self.spinner = SpinnerCapture()

@dataclass
class WindowInfo:
    title: str
    app_name: str
    window_id: Optional[str] = None

# --------------- NEW: Mouse Movement Monitor ---------------

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
        self.log("Mouse movement monitoring started")
        
    def stop_monitoring(self):
        self.monitoring = False
        
    def _monitor_loop(self):
        while self.monitoring and PYAUTOGUI_AVAILABLE:
            try:
                current_pos = pg.position()
                if self.state.spinner.center_xy:
                    sx, sy = self.state.spinner.center_xy
                    distance = math.sqrt((current_pos[0] - sx)**2 + (current_pos[1] - sy)**2)
                    
                    if distance > MOUSE_PAUSE_THRESHOLD and not self.state.paused_by_mouse:
                        self.state.paused_by_mouse = True
                        self.log(f"Auto-paused: mouse moved {distance:.0f}px from spinner", green=True)
                    elif distance <= MOUSE_PAUSE_THRESHOLD and self.state.paused_by_mouse:
                        self.state.paused_by_mouse = False
                        self.log("Auto-resume: mouse returned to spinner area", green=True)
                        
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
    
    def show_selection_dialog(self, parent):
        # Store and disable parent topmost temporarily
        parent_was_topmost = False
        try:
            parent_was_topmost = parent.attributes("-topmost")
            if parent_was_topmost:
                parent.attributes("-topmost", False)
                parent.update()
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
        
        # Keyboard shortcuts
        dialog.bind('<Return>', lambda e: confirm_selection())
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        
        # Run modal dialog
        dialog.wait_window()
        
        # Restore parent topmost state
        try:
            if parent_was_topmost:
                parent.attributes("-topmost", True)
                parent.update()
        except Exception:
            pass
        
        if selected_window:
            self.selected_window = selected_window
        return selected_window

# --------------- ROI Selection ---------------

class ROISelector:
    @staticmethod
    def select_roi_native(parent):
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
            
            return result.returncode == 0
            
        except Exception:
            parent.deiconify()
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
        self.total_var = tk.StringVar(value="—")
        self.target_var = tk.StringVar(value="—")
        # NEW: Current wager display
        self.current_wager_var = tk.StringVar(value="£0.00")
        
        self._build_ui()
        
        # NEW: Auto-update current wager when spins change
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
        
        # Results row
        result_frame = ttk.Frame(self.frame)
        result_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(result_frame, text="Total wagering:").grid(row=0, column=0, sticky="w", padx=(0, 5))
        ttk.Label(result_frame, textvariable=self.total_var, font=('Monaco', 9, 'bold')).grid(row=0, column=1, padx=(0, 15))
        
        ttk.Label(result_frame, text="Target spins:").grid(row=0, column=2, sticky="w", padx=(0, 5))
        ttk.Label(result_frame, textvariable=self.target_var, font=('Monaco', 9, 'bold')).grid(row=0, column=3, padx=(0, 15))
        
        # NEW: Current wager display
        ttk.Label(result_frame, text="Current wager:").grid(row=0, column=4, sticky="w", padx=(0, 5))
        ttk.Label(result_frame, textvariable=self.current_wager_var, font=('Monaco', 9, 'bold'), 
                 foreground="blue").grid(row=0, column=5)
        
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
            spins = getattr(self.app.state_slots, 'total_spins', 0)
            current_wager = spins * bet
            self.current_wager_var.set(f"£{current_wager:.2f}")
        except:
            pass
        # Schedule next update
        self.app.after(1000, self._update_timer)
    
    def _calculate(self):
        try:
            amount = float(self.amount_var.get().strip() or "0")
            mult = float(self.mult_var.get().strip() or "0")
            bet = float(self.bet_var.get().strip() or "0")
            
            if amount <= 0 or mult <= 0 or bet <= 0:
                raise ValueError("All values must be greater than 0")
            
            total = amount * mult
            target = int(round(total / bet))
            
            self.total_var.set(f"£{total:.2f}")
            self.target_var.set(str(target))
            
            self.app._log(f"{self.feature_name}: £{amount} × {mult} ÷ £{bet} = {target} spins", green=True)
            
        except ValueError as e:
            self.total_var.set("Error")
            self.target_var.set("Error")
            messagebox.showwarning("Calculation Error", str(e))
    
    def _apply(self):
        try:
            target_str = self.target_var.get()
            if target_str in ["—", "Error"]:
                messagebox.showwarning("No Target", "Calculate a target first.")
                return
            
            target = int(target_str)
            
            # Apply to clicker controls if they exist
            if hasattr(self.app, 'ac_manual_target'):
                self.app.ac_manual_target.set(target)
            if hasattr(self.app, 'ac_auto_target'):
                self.app.ac_auto_target.set(target)
            
            self.app._log(f"{self.feature_name} target applied: {target}", green=True)
            
        except Exception as e:
            messagebox.showwarning("Apply Error", str(e))
    
    def _reset(self):
        self.amount_var.set("")
        self.mult_var.set("")
        self.bet_var.set("")
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
        """Enhanced state detection that ignores 'hey click me' animations"""
        if not PIL_AVAILABLE or not self.state.spinner.is_valid:
            return SpinState.UNKNOWN
            
        spinner = self.state.spinner
        roi = spinner.roi
        
        try:
            current = ImageGrab.grab(bbox=(roi.x, roi.y, roi.x + roi.w, roi.y + roi.h))
            
            # RMS difference check
            rms = _rms(current, spinner.baseline_ready)
            rms_ok = rms <= PIX_DIFF_READY
            
            # Brightness check (more tolerant for shaded buttons)
            curr_brightness = _brightness(current)
            brightness_ok = True
            if spinner.ready_brightness is not None:
                brightness_diff = spinner.ready_brightness - curr_brightness
                brightness_ok = brightness_diff <= BRIGHT_READY_TOL
            
            # Color distance check
            color_ok = True
            if spinner.ready_color:
                curr_color = _avg_rgb(current)
                color_distance = _color_dist(curr_color, spinner.ready_color)
                color_ok = color_distance <= COLOR_D_READY_TOL
            
            return SpinState.READY if (rms_ok or (brightness_ok and color_ok)) else SpinState.NOT_READY
            
        except Exception:
            return SpinState.UNKNOWN
    
    def wait_for_spin_cycle(self, timeout_s: float = 30.0) -> bool:
        """Wait for complete ready→not_ready→ready cycle (ignores animations)"""
        start_time = time.time()
        
        # Phase 1: Ensure we start in ready state
        initial_state = self.get_current_state()
        if initial_state != SpinState.READY:
            self.log("Waiting for initial READY state...")
            while time.time() - start_time < 5.0:
                if self.get_current_state() == SpinState.READY:
                    break
                time.sleep(0.1)
            else:
                self.log("Timeout waiting for initial READY state")
                return False
        
        # Phase 2: Wait for transition to NOT_READY (actual spin started)
        self.log("Waiting for spin to start (READY→NOT_READY)...")
        transition_detected = False
        while time.time() - start_time < timeout_s:
            current_state = self.get_current_state()
            if current_state == SpinState.NOT_READY:
                self.log("Spin transition detected (NOT_READY)")
                transition_detected = True
                break
            time.sleep(0.1)
        
        if not transition_detected:
            self.log("No spin transition detected - may be animation")
            return False
        
        # Phase 3: Wait for return to READY (spin complete)
        self.log("Waiting for spin completion (NOT_READY→READY)...")
        while time.time() - start_time < timeout_s:
            current_state = self.get_current_state()
            if current_state == SpinState.READY:
                self.log("Spin cycle complete (READY detected)")
                return True
            time.sleep(0.1)
                
        self.log("Timeout waiting for spin completion")
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
        
        # NEW: Enhanced components
        self.spin_detector = SpinDetector(self.state_slots, self._log)
        self.mouse_monitor = MouseMonitor(self.state_slots, self._log)
        
        self._log_q = queue.Queue()
        self._running_slots = False
        self._running_ac = False
        self._stop_evt = threading.Event()
        
        # Keyboard listener
        self.keyboard_listener = None
        self._setup_keyboard_shortcuts()

        # Build UI and restore
        self._restore_geometry()
        self._build_ui()
        self.after(UI_FLUSH_MS, self._drain_log)
        
        self._log("Spin Helper v1.16.0 initialized with enhancements", green=True)

    def _setup_keyboard_shortcuts(self):
        if not PYNPUT_AVAILABLE:
            return
        
        def on_key_press(key):
            try:
                if key == keyboard.Key.space:
                    pass  # Space key handling if needed
            except Exception:
                pass
        
        try:
            self.keyboard_listener = keyboard.Listener(on_press=on_key_press)
            self.keyboard_listener.daemon = True
            self.keyboard_listener.start()
        except Exception:
            pass

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
        self._build_autoclicker_tab()

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
        self.log.tag_configure(self.tag_green, foreground="#00a000")
        self.log.tag_configure(self.tag_blue, foreground="#0066cc")

        # Mouse wheel support
        self.left_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        self.left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ---------- Tab Building ----------

    def _build_env_tab(self):
        """Enhanced Environment Setup with universal spinner capture"""
        tab_env = ttk.Frame(self.sections)
        self.sections.add(tab_env, text="Environment Setup")
        
        # Browser selection
        browser_frame = ttk.LabelFrame(tab_env, text="Browser Window Selection", padding=10)
        browser_frame.pack(fill=tk.X, padx=8, pady=8)
        
        ttk.Label(browser_frame, text=(
            "Step 1: Open your casino game in Chrome/Safari/Firefox\n"
            "Step 2: Click 'Select Browser Window' below\n"
            "Step 3: Choose your casino tab from the list"
        )).pack(anchor='w', pady=(0, 10))
        
        button_frame = ttk.Frame(browser_frame)
        button_frame.pack(fill=tk.X)
        
        ttk.Button(button_frame, text="Select Browser Window", command=self._select_browser).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Refresh List", command=self._refresh_browsers).pack(side=tk.LEFT)
        
        self.browser_status_var = tk.StringVar(value="No browser window selected")
        ttk.Label(browser_frame, textvariable=self.browser_status_var).pack(anchor='w', pady=(10, 0))
        
        # NEW: Universal Spinner Capture
        spinner_frame = ttk.LabelFrame(tab_env, text="Universal Spinner Button Capture", padding=10)
        spinner_frame.pack(fill=tk.X, padx=8, pady=8)
        
        ttk.Label(spinner_frame, text=(
            "Position your mouse over the spin button, then click 'Capture Spinner Button'.\n"
            "The app will give you 3 seconds to position your mouse correctly.\n"
            "This capture will be used across all features (Slots, Roulette, Autoclicker)."
        )).pack(anchor='w', pady=(0, 8))
        
        spinner_controls = ttk.Frame(spinner_frame)
        spinner_controls.pack(fill=tk.X)
        
        ttk.Button(spinner_controls, text="Capture Spinner Button", command=self._capture_spinner_delayed).pack(side=tk.LEFT)
        
        self.spinner_status_var = tk.StringVar(value="No spinner captured")
        ttk.Label(spinner_controls, textvariable=self.spinner_status_var).pack(side=tk.LEFT, padx=(15, 0))
        
        # NEW: Spinner preview thumbnail
        self.spinner_thumb_label = ttk.Label(spinner_controls)
        self.spinner_thumb_label.pack(side=tk.LEFT, padx=(10, 0))
        
        # System info
        sys_frame = ttk.LabelFrame(tab_env, text="System Information", padding=10)
        sys_frame.pack(fill=tk.X, padx=8, pady=8)
        
        info_text = f"Python: {sys.version.split()[0]} | Platform: {sys.platform}\n"
        info_text += f"PIL: {PIL_AVAILABLE} | PyAutoGUI: {PYAUTOGUI_AVAILABLE} | Pynput: {PYNPUT_AVAILABLE}"
        ttk.Label(sys_frame, text=info_text, justify=tk.LEFT).pack(anchor='w')

    def _build_slots_tab(self):
        """Enhanced Slots tab with embedded calculator and improved controls"""
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
        
        # NEW: Enhanced automation controls with Pause button
        auto_frame = ttk.LabelFrame(tab_slots, text="Automation Controls", padding=8)
        auto_frame.pack(fill=tk.X, padx=8, pady=8)
        
        auto_controls = ttk.Frame(auto_frame)
        auto_controls.pack(fill=tk.X)
        
        self.slots_start_btn = ttk.Button(auto_controls, text="Start Auto Spins", command=self._start_slots)
        self.slots_start_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        # NEW: Pause button
        self.slots_pause_btn = ttk.Button(auto_controls, text="Pause", command=self._pause_slots, state=tk.DISABLED)
        self.slots_pause_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.slots_stop_btn = ttk.Button(auto_controls, text="Stop", command=self._stop_slots, state=tk.DISABLED)
        self.slots_stop_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        # NEW: Reset button
        self.slots_reset_btn = ttk.Button(auto_controls, text="Reset", command=self._reset_slots)
        self.slots_reset_btn.pack(side=tk.LEFT)
        
        # NEW: Spin counter display
        counter_frame = ttk.Frame(auto_frame)
        counter_frame.pack(fill=tk.X, pady=(8, 0))
        
        ttk.Label(counter_frame, text="Spins Completed:").pack(side=tk.LEFT)
        self.spin_counter_var = tk.StringVar(value="0")
        ttk.Label(counter_frame, textvariable=self.spin_counter_var, font=('Monaco', 12, 'bold'), 
                 foreground="blue").pack(side=tk.LEFT, padx=(10, 0))
        
        # Embedded calculator
        self.slots_calculator = EmbeddedCalculator(tab_slots, self, "Slots")
        self.slots_calculator.pack(fill=tk.X, padx=8, pady=8)

    def _build_roulette_tab(self):
        """Roulette tab with embedded calculator"""
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

    def _build_autoclicker_tab(self):
        """Fixed Autoclicker tab with Manual/Automatic modes and embedded calculator"""
        tab_clicker = ttk.Frame(self.sections)
        self.sections.add(tab_clicker, text="Autoclicker")
        
        # Sub-notebook
        self.clicker_notebook = ttk.Notebook(tab_clicker)
        self.clicker_notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        # Manual mode
        manual_tab = ttk.Frame(self.clicker_notebook)
        self.clicker_notebook.add(manual_tab, text="Manual")
        
        manual_frame = ttk.LabelFrame(manual_tab, text="Manual Click Controls", padding=8)
        manual_frame.pack(fill=tk.X, padx=8, pady=8)
        
        self.ac_manual_target = tk.IntVar(value=0)
        self.ac_manual_done = tk.IntVar(value=0)
        
        manual_controls = ttk.Frame(manual_frame)
        manual_controls.pack(fill=tk.X)
        
        ttk.Label(manual_controls, text="Target:").grid(row=0, column=0, sticky="w")
        ttk.Entry(manual_controls, textvariable=self.ac_manual_target, width=8).grid(row=0, column=1, padx=(5, 15))
        
        ttk.Label(manual_controls, text="Done:").grid(row=0, column=2, sticky="w")
        ttk.Label(manual_controls, textvariable=self.ac_manual_done, font=('Monaco', 10, 'bold')).grid(row=0, column=3, padx=(5, 15))
        
        ttk.Button(manual_controls, text="Single Click", command=self._manual_click).grid(row=0, column=4, padx=(10, 5))
        ttk.Button(manual_controls, text="Reset", command=self._reset_manual).grid(row=0, column=5)
        
        # Automatic mode
        auto_tab = ttk.Frame(self.clicker_notebook)
        self.clicker_notebook.add(auto_tab, text="Automatic")
        
        auto_frame = ttk.LabelFrame(auto_tab, text="Automatic Click Controls", padding=8)
        auto_frame.pack(fill=tk.X, padx=8, pady=8)
        
        self.ac_auto_target = tk.IntVar(value=0)
        self.ac_auto_done = tk.IntVar(value=0)
        
        auto_controls = ttk.Frame(auto_frame)
        auto_controls.pack(fill=tk.X)
        
        ttk.Label(auto_controls, text="Target:").grid(row=0, column=0, sticky="w")
        ttk.Entry(auto_controls, textvariable=self.ac_auto_target, width=8).grid(row=0, column=1, padx=(5, 15))
        
        ttk.Label(auto_controls, text="Done:").grid(row=0, column=2, sticky="w")
        ttk.Label(auto_controls, textvariable=self.ac_auto_done, font=('Monaco', 10, 'bold')).grid(row=0, column=3, padx=(5, 15))
        
        self.auto_start_btn = ttk.Button(auto_controls, text="Start Auto", command=self._start_auto)
        self.auto_start_btn.grid(row=0, column=4, padx=(10, 5))
        
        self.auto_stop_btn = ttk.Button(auto_controls, text="Stop", command=self._stop_auto, state=tk.DISABLED)
        self.auto_stop_btn.grid(row=0, column=5)
        
        # Waggle controls
        self.waggle_on_var = tk.BooleanVar(value=AC_DEFAULT_WAGGLE_ON)
        self.waggle_secs_var = tk.IntVar(value=AC_DEFAULT_WAGGLE_SECS)
        self.waggle_amp_var = tk.IntVar(value=AC_DEFAULT_WAGGLE_AMP)
        
        waggle_frame = ttk.Frame(auto_frame)
        waggle_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Checkbutton(waggle_frame, text="Anti-idle waggle every").pack(side=tk.LEFT)
        ttk.Entry(waggle_frame, textvariable=self.waggle_secs_var, width=4).pack(side=tk.LEFT, padx=(5, 5))
        ttk.Label(waggle_frame, text="sec, amplitude").pack(side=tk.LEFT)
        ttk.Entry(waggle_frame, textvariable=self.waggle_amp_var, width=4).pack(side=tk.LEFT, padx=(5, 5))
        ttk.Label(waggle_frame, text="px").pack(side=tk.LEFT)
        
        # Embedded calculator
        self.clicker_calculator = EmbeddedCalculator(tab_clicker, self, "Autoclicker")
        self.clicker_calculator.pack(fill=tk.X, padx=8, pady=8)

    # ---------- Browser Selection ----------

    def _select_browser(self):
        self._log("Starting browser window selection...")
        try:
            selected = self.browser_detector.show_selection_dialog(self)
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

    # ---------- FIXED: Enhanced Spinner Capture ----------

    def _capture_spinner_delayed(self):
        """FIXED: Proper delayed capture with countdown (not immediate)"""
        if not PIL_AVAILABLE:
            messagebox.showerror("PIL Required", "PIL is required for spinner capture.")
            return
        
        # Clear existing capture
        self.state_slots.spinner = SpinnerCapture()
        self.spinner_status_var.set("Preparing to capture...")
        
        self._log("Spinner capture starting - Move mouse over spin button NOW", green=True)
        self._log("Capturing in 3...", green=True)
        
        # Properly schedule the countdown
        self.after(1000, lambda: self._log("Capturing in 2...", green=True))
        self.after(2000, lambda: self._log("Capturing in 1...", green=True))
        self.after(3000, self._execute_spinner_capture)
    
    def _execute_spinner_capture(self):
        """Execute spinner capture after countdown"""
        try:
            x, y = self.winfo_pointerxy()
            w = h = 40
            left, top = int(x - w//2), int(y - h//2)
            
            baseline = ImageGrab.grab(bbox=(left, top, left + w, top + h))
            
            # Create thumbnail for display
            thumb_img = baseline.copy()
            thumb_img.thumbnail((32, 32))
            thumbnail = ImageTk.PhotoImage(thumb_img)
            
            # Store enhanced capture
            self.state_slots.spinner.roi = SpinnerROI(left, top, w, h)
            self.state_slots.spinner.baseline_ready = baseline
            self.state_slots.spinner.ready_color = _avg_rgb(baseline)
            self.state_slots.spinner.ready_brightness = _brightness(baseline)
            self.state_slots.spinner.center_xy = (x, y)
            self.state_slots.spinner.capture_time = time.time()
            self.state_slots.spinner.is_valid = True
            self.state_slots.spinner.thumbnail = thumbnail
            
            # Update UI
            self.spinner_status_var.set(f"✓ Captured at ({x},{y}) - Ready for all features")
            self.spinner_thumb_label.config(image=thumbnail)
            self.status.config(text="Universal spinner captured - Ready for automation")
            
            self._log("Universal spinner button READY state captured", green=True)
            self._log(f"Location: ({x},{y}), ROI: {w}x{h}px", blue=True)
            
        except Exception as e:
            self.spinner_status_var.set("Capture failed")
            self._log(f"Capture error: {e}")
            messagebox.showerror("Capture Error", str(e))

    def _capture_fs_native(self):
        """Native macOS FS area selection"""
        self._log("Starting native FS area selection...", green=True)
        
        try:
            proceed = messagebox.askyesno("FS Area Selection", 
                "This will use the native macOS screenshot tool.\n\n"
                "Click YES, then:\n"
                "1. Click and drag to select the Free-Spins banner area\n"
                "2. The selection will be stored for detection\n\n"
                "Click NO to cancel.")
            
            if proceed:
                success = ROISelector.select_roi_native(self)
                if success:
                    self._log("FS area captured using native selection", green=True)
                else:
                    self._log("FS area selection cancelled")
        except Exception as e:
            self._log(f"Native FS selection error: {e}")

    def _toggle_fs(self):
        self.state_slots.detect_fs = self.detect_fs_var.get()
        self._log(f"FS detection: {'ON' if self.state_slots.detect_fs else 'OFF'}")

    # ---------- NEW: Enhanced Target Logic ----------

    def _check_target_reached(self) -> bool:
        """Check if any target limits are reached"""
        try:
            # Check calculator targets if they exist
            for calc in [getattr(self, 'slots_calculator', None)]:
                if calc:
                    target_str = calc.target_var.get()
                    if target_str != "—" and target_str != "Error":
                        target_spins = int(target_str)
                        if target_spins > 0 and self.state_slots.total_spins >= target_spins:
                            self._log(f"Target spins reached: {self.state_slots.total_spins}/{target_spins}", green=True)
                            return True
                    
                    # Check wager target
                    total_str = calc.total_var.get()
                    bet_str = calc.bet_var.get()
                    if total_str != "—" and bet_str:
                        try:
                            target_wager = float(total_str.replace("£", ""))
                            bet_per_spin = float(bet_str)
                            current_wager = self.state_slots.total_spins * bet_per_spin
                            if target_wager > 0 and current_wager >= target_wager:
                                self._log(f"Target wager reached: £{current_wager:.2f}/£{target_wager:.2f}", green=True)
                                return True
                        except:
                            pass
        except:
            pass
        
        return False

    # ---------- NEW: Enhanced Slots Automation ----------

    def _start_slots(self):
        """Enhanced slots automation with proper state management"""
        if self._running_slots:
            if self.state_slots.paused_by_mouse:
                self.state_slots.paused_by_mouse = False
                self._log("Slots automation resumed manually", green=True)
            return
            
        if not self.browser_detector.selected_window:
            messagebox.showwarning("Setup Required", "Select browser window first.")
            return
        if not self.state_slots.spinner.is_valid:
            messagebox.showwarning("Setup Required", "Capture spinner button first.")
            return
        
        self._running_slots = True
        self._stop_evt.clear()
        
        # Update UI
        self.slots_start_btn.config(state=tk.DISABLED, text="Running...")
        self.slots_pause_btn.config(state=tk.NORMAL)
        self.slots_stop_btn.config(state=tk.NORMAL)
        
        # Start mouse monitoring
        self.mouse_monitor.start_monitoring()
        
        threading.Thread(target=self._enhanced_slots_loop, daemon=True).start()
        self._log("Enhanced slots automation started with target checking", green=True)

    def _pause_slots(self):
        """Manually pause slots automation"""
        self.state_slots.paused_by_mouse = True
        self.slots_start_btn.config(state=tk.NORMAL, text="Resume Auto Spins")
        self._log("Slots automation manually paused", blue=True)

    def _stop_slots(self):
        """Stop slots automation"""
        self._stop_evt.set()
        self.mouse_monitor.stop_monitoring()

    def _reset_slots(self):
        """Reset slots counters and calculations"""
        self.state_slots.total_spins = 0
        self.state_slots.paused_by_mouse = False
        self.spin_counter_var.set("0")
        self.slots_start_btn.config(state=tk.NORMAL, text="Start Auto Spins")
        
        # Reset calculator if it exists
        if hasattr(self, 'slots_calculator'):
            if hasattr(self.slots_calculator, '_reset'):
                self.slots_calculator._reset()
        
        self._log("Slots automation reset - counters and calculations cleared")

    def _enhanced_slots_loop(self):
        """Enhanced slots loop with full state cycle tracking and target checking"""
        try:
            while not self._stop_evt.is_set():
                # Check if paused by mouse movement
                if self.state_slots.paused_by_mouse:
                    self.slots_start_btn.config(state=tk.NORMAL, text="Resume Auto Spins")
                    time.sleep(0.5)
                    continue
                else:
                    self.slots_start_btn.config(state=tk.DISABLED, text="Running...")
                
                # Check if targets reached
                if self._check_target_reached():
                    self._log("Target reached - stopping automation", green=True)
                    break
                
                # Execute spin with enhanced state detection
                spin_num = self.state_slots.total_spins + 1
                self._log(f"Executing spin #{spin_num}")
                
                if self._do_click():
                    if self.spin_detector.wait_for_spin_cycle():
                        self.state_slots.total_spins += 1
                        self.spin_counter_var.set(str(self.state_slots.total_spins))
                        self._log(f"Spin #{spin_num} completed successfully", green=True)
                    else:
                        self._log(f"Spin #{spin_num} cycle timeout - continuing", blue=True)
                else:
                    self._log(f"Spin #{spin_num} click failed", blue=True)
                
                # Brief pause before next spin
                if self._stop_evt.wait(random.uniform(0.3, 0.8)):
                    break
                    
        except Exception as e:
            self._log(f"Slots automation error: {e}")
        finally:
            self._running_slots = False
            self.mouse_monitor.stop_monitoring()
            self.slots_start_btn.config(state=tk.NORMAL, text="Start Auto Spins")
            self.slots_pause_btn.config(state=tk.DISABLED)
            self.slots_stop_btn.config(state=tk.DISABLED)
            self._log(f"Slots automation stopped - {self.state_slots.total_spins} spins completed")

    def _do_click(self) -> bool:
        """Enhanced click with proper error handling"""
        if not PYAUTOGUI_AVAILABLE or not self.state_slots.spinner.center_xy:
            return False
        
        x, y = self.state_slots.spinner.center_xy
        try:
            # Small jitter for natural movement
            jitter_x = random.randint(-1, 1)
            jitter_y = random.randint(-1, 1)
            pg.moveTo(x + jitter_x, y + jitter_y, duration=0.05)
            pg.click()
            return True
        except Exception as e:
            self._log(f"Click error: {e}")
            return False

    # ---------- Manual Clicker ----------

    def _manual_click(self):
        """Enhanced manual clicker with state tracking"""
        if not self.state_slots.spinner.is_valid:
            messagebox.showwarning("Setup Required", "Capture spinner button from Environment Setup first.")
            return
        
        current = self.ac_manual_done.get()
        target = self.ac_manual_target.get()
        
        if target > 0 and current >= target:
            self._log("Manual target already reached")
            return
        
        new_count = current + 1
        self._log(f"Manual click {new_count} executing...")
        
        if self._do_click():
            if self.spin_detector.wait_for_spin_cycle(timeout_s=10.0):
                self.ac_manual_done.set(new_count)
                self._log(f"Manual click {new_count} completed", green=True)
                
                if target > 0 and new_count >= target:
                    self._log("Manual target reached!", green=True)
            else:
                self._log(f"Manual click {new_count} - cycle timeout")
        else:
            self._log(f"Manual click {new_count} - click failed")

    def _reset_manual(self):
        """Reset manual clicker"""
        self.ac_manual_target.set(0)
        self.ac_manual_done.set(0)
        self._log("Manual autoclicker reset")

    # ---------- Automatic Clicker ----------

    def _start_auto(self):
        """Enhanced automatic clicker"""
        if self._running_ac:
            return
        if not self.state_slots.spinner.is_valid:
            messagebox.showwarning("Setup Required", "Capture spinner button from Environment Setup first.")
            return
        
        target = self.ac_auto_target.get()
        if target <= 0:
            messagebox.showwarning("Invalid Target", "Set target > 0.")
            return
        
        self._running_ac = True
        self._stop_evt.clear()
        
        self.auto_start_btn.config(state=tk.DISABLED)
        self.auto_stop_btn.config(state=tk.NORMAL)
        
        threading.Thread(target=self._auto_loop, daemon=True).start()
        self._log(f"Automatic clicker started - Target: {target}", green=True)

    def _stop_auto(self):
        """Stop automatic clicker"""
        self._stop_evt.set()

    def _auto_loop(self):
        """Enhanced automatic clicker loop"""
        try:
            done = 0
            target = self.ac_auto_target.get()
            last_waggle = time.time()
            
            while not self._stop_evt.is_set() and done < target:
                done += 1
                
                self._log(f"Auto click {done}/{target} executing...")
                
                if self._do_click():
                    if self.spin_detector.wait_for_spin_cycle():
                        self.ac_auto_done.set(done)
                        self._log(f"Auto click {done}/{target} completed", green=True)
                    else:
                        self._log(f"Auto click {done}/{target} - cycle timeout")
                else:
                    self._log(f"Auto click {done}/{target} - click failed")
                
                # Anti-idle waggle
                if (self.waggle_on_var.get() and 
                    time.time() - last_waggle > self.waggle_secs_var.get() and
                    self.state_slots.spinner.center_xy):
                    self._perform_waggle()
                    last_waggle = time.time()
                
                if self._stop_evt.wait(random.uniform(0.3, 0.7)):
                    break
            
            if done >= target:
                self._log(f"Automatic target reached - {done} clicks completed", green=True)
                
        except Exception as e:
            self._log(f"Auto clicker error: {e}")
        finally:
            self._running_ac = False
            self.auto_start_btn.config(state=tk.NORMAL)
            self.auto_stop_btn.config(state=tk.DISABLED)
            self._log("Automatic clicker stopped")

    def _perform_waggle(self):
        """Anti-idle waggle movement"""
        if not PYAUTOGUI_AVAILABLE:
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

    def _log(self, msg, green=False, blue=False):
        color = "green" if green else ("blue" if blue else None)
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

    def destroy(self):
        try:
            if hasattr(self, 'keyboard_listener') and self.keyboard_listener:
                self.keyboard_listener.stop()
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
        print("INFO: pynput not available - keyboard shortcuts disabled")
    
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