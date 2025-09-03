# spin_helper.py — v1.16.0
# Major fixes: proper spin state machine, target stopping, mouse pause detection, 
# centralized spinner detection, current wager display, universal spin logic

import os, sys, time, math, threading, queue, json, random
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
from enum import Enum

import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageChops, ImageStat, ImageGrab, ImageTk

# Desktop automation
try:
    import pyautogui as pg
    pg.FAILSAFE = False
except Exception:
    pg = None

# Permission checking (Mac-specific)
try:
    import subprocess
    import platform
    IS_MAC = platform.system() == "Darwin"
except Exception:
    IS_MAC = False

# --------------- Constants ---------------

APP_VERSION = "1.16.0"

# Spinner state detection
PIX_DIFF_READY = 7.5
BRIGHT_READY_TOL = 0.14
COLOR_D_READY_TOL = 18.0

# Mouse movement pause detection
MOUSE_PAUSE_THRESHOLD = 80  # pixels from capture point
MOUSE_CHECK_INTERVAL = 0.5  # seconds

UI_FLUSH_MS = 60

# --------------- Enums ---------------

class SpinState(Enum):
    UNKNOWN = "unknown"
    READY = "ready" 
    NOT_READY = "not_ready"
    TRANSITIONING = "transitioning"

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
    return math.sqrt((c1[0]-c2[0])**2 + (c1[1]-c2[1])**2 + (c1[2]-c2[2])**2)

def _rms(img_a: Image.Image, img_b: Image.Image) -> float:
    diff = ImageChops.difference(img_a, img_b)
    stat = ImageStat.Stat(diff)
    mean = stat.mean[0] if stat.mean else 0.0
    return mean

def _brightness(img: Image.Image) -> float:
    stat = ImageStat.Stat(img.convert("L"))
    mean = stat.mean[0] if stat.mean else 0.0
    return mean / 255.0

def _check_mac_permissions():
    """Check Mac permissions for screenshots and accessibility"""
    if not IS_MAC:
        return True, []
    
    missing = []
    
    # Check screenshot permission
    try:
        result = subprocess.run(['osascript', '-e', 'tell application "System Events" to get name of every application process'], 
                              capture_output=True, text=True, timeout=2)
        if result.returncode != 0:
            missing.append("Accessibility")
    except Exception:
        missing.append("Accessibility")
    
    # Try a small screenshot to check screen recording
    try:
        ImageGrab.grab(bbox=(0, 0, 10, 10))
    except Exception:
        missing.append("Screen Recording")
    
    return len(missing) == 0, missing

# --------------- Data Models ---------------

@dataclass
class SpinnerROI:
    x: int
    y: int
    w: int
    h: int

@dataclass
class SpinnerCapture:
    """Centralized spinner detection data"""
    xy: Optional[Tuple[int,int]] = None
    roi: Optional[SpinnerROI] = None
    baseline_img: Optional[Image.Image] = None
    ready_color: Optional[Tuple[float,float,float]] = None
    brightness: Optional[float] = None
    thumbnail: Optional[ImageTk.PhotoImage] = None

@dataclass
class SessionState:
    spinner: SpinnerCapture = field(default_factory=SpinnerCapture)
    fs_roi: Optional[SpinnerROI] = None
    detect_fs: bool = True
    current_spin_state: SpinState = SpinState.UNKNOWN
    last_state_change: float = field(default_factory=time.time)
    total_spins: int = 0
    paused_by_mouse: bool = False
    last_mouse_pos: Optional[Tuple[int,int]] = None

# --------------- Spin Detection Engine ---------------

class SpinDetector:
    def __init__(self, state: SessionState, log_func):
        self.state = state
        self.log = log_func
        
    def capture_spinner(self, x: int, y: int, w: int = 40, h: int = 40):
        """Capture spinner button at coordinates"""
        try:
            left = int(x - w//2)
            top = int(y - h//2)
            img = ImageGrab.grab(bbox=(left, top, left + w, top + h))
            
            # Create thumbnail for UI
            thumb_img = img.copy()
            thumb_img.thumbnail((32, 32))
            thumbnail = ImageTk.PhotoImage(thumb_img)
            
            self.state.spinner = SpinnerCapture(
                xy=(x, y),
                roi=SpinnerROI(left, top, w, h),
                baseline_img=img,
                ready_color=_avg_rgb(img),
                brightness=_brightness(img),
                thumbnail=thumbnail
            )
            
            self.state.current_spin_state = SpinState.READY
            self.log("Spinner captured and set to READY state", green=True)
            return True
            
        except Exception as e:
            self.log(f"Capture failed: {e}")
            return False
    
    def get_current_state(self) -> SpinState:
        """Get current spinner state based on visual comparison"""
        if not self.state.spinner.roi or not self.state.spinner.baseline_img:
            return SpinState.UNKNOWN
            
        r = self.state.spinner.roi
        try:
            curr = ImageGrab.grab(bbox=(r.x, r.y, r.x + r.w, r.y + r.h))
        except Exception:
            return SpinState.UNKNOWN
            
        rms = _rms(curr, self.state.spinner.baseline_img)
        br = _brightness(curr)
        
        # Check if current image matches baseline (ready state)
        ok_rms = rms <= PIX_DIFF_READY
        ok_bright = (self.state.spinner.brightness is not None) and \
                   ((self.state.spinner.brightness - br) <= BRIGHT_READY_TOL)
        ok_color = True
        
        if self.state.spinner.ready_color is not None:
            ok_color = _color_dist(_avg_rgb(curr), self.state.spinner.ready_color) <= COLOR_D_READY_TOL
            
        if ok_rms or (ok_bright and ok_color):
            return SpinState.READY
        else:
            return SpinState.NOT_READY
    
    def wait_for_spin_cycle(self, timeout_s: float = 30.0) -> bool:
        """Wait for complete ready->not_ready->ready cycle"""
        start_time = time.time()
        
        # Must start in ready state
        initial_state = self.get_current_state()
        if initial_state != SpinState.READY:
            self.log(f"Spin cycle started in {initial_state.value} state, waiting for READY...")
            while time.time() - start_time < 5.0:
                if self.get_current_state() == SpinState.READY:
                    break
                time.sleep(0.1)
            else:
                self.log("Timeout waiting for initial READY state")
                return False
        
        # Wait for transition to NOT_READY (spin started)
        self.log("Waiting for spin to start (READY->NOT_READY)...")
        while time.time() - start_time < timeout_s:
            current_state = self.get_current_state()
            if current_state == SpinState.NOT_READY:
                self.log("Spin started (NOT_READY detected)")
                break
            time.sleep(0.1)
        else:
            self.log("Timeout waiting for NOT_READY state")
            return False
        
        # Wait for return to READY (spin complete)
        self.log("Waiting for spin to complete (NOT_READY->READY)...")
        while time.time() - start_time < timeout_s:
            current_state = self.get_current_state()
            if current_state == SpinState.READY:
                self.log("Spin complete (READY detected)")
                return True
            time.sleep(0.1)
                
        self.log("Timeout waiting for spin completion")
        return False
    
    def do_click(self, with_jitter: bool = True):
        """Perform click at spinner coordinates"""
        if not self.state.spinner.xy:
            return False
            
        x, y = self.state.spinner.xy
        try:
            if pg:
                if with_jitter:
                    jx = random.randint(-1, 1)
                    jy = random.randint(-1, 1)
                    pg.moveTo(x + jx, y + jy, duration=0.05)
                else:
                    pg.moveTo(x, y, duration=0.05)
                pg.click()
                return True
            else:
                time.sleep(0.05)  # Fallback delay
                return True
        except Exception as e:
            self.log(f"Click failed: {e}")
            return False

# --------------- Mouse Movement Monitor ---------------

class MouseMonitor:
    def __init__(self, state: SessionState, log_func):
        self.state = state
        self.log = log_func
        self.monitoring = False
        self.monitor_thread = None
        
    def start_monitoring(self):
        """Start monitoring mouse movement for auto-pause"""
        if self.monitoring:
            return
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        
    def stop_monitoring(self):
        """Stop monitoring mouse movement"""
        self.monitoring = False
        
    def _monitor_loop(self):
        """Monitor mouse position and trigger pause if moved too far"""
        while self.monitoring:
            try:
                if not self.state.spinner.xy:
                    time.sleep(MOUSE_CHECK_INTERVAL)
                    continue
                    
                # Get current mouse position
                try:
                    current_pos = pg.position() if pg else (0, 0)
                except Exception:
                    time.sleep(MOUSE_CHECK_INTERVAL)
                    continue
                
                # Calculate distance from spinner
                sx, sy = self.state.spinner.xy
                distance = math.sqrt((current_pos[0] - sx)**2 + (current_pos[1] - sy)**2)
                
                # Check if mouse moved too far
                if distance > MOUSE_PAUSE_THRESHOLD and not self.state.paused_by_mouse:
                    self.state.paused_by_mouse = True
                    self.log(f"Auto-paused: mouse moved {distance:.0f}px from spinner")
                elif distance <= MOUSE_PAUSE_THRESHOLD and self.state.paused_by_mouse:
                    self.state.paused_by_mouse = False
                    self.log("Auto-resume: mouse returned to spinner area")
                    
            except Exception as e:
                self.log(f"Mouse monitor error: {e}")
                
            time.sleep(MOUSE_CHECK_INTERVAL)

# --------------- Main App ---------------

class SpinHelperApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Spin Helper v{APP_VERSION}")
        self.minsize(1000, 600)
        
        # Check permissions on startup
        self._check_permissions()
        
        # Initialize state
        self.state = SessionState()
        self.spin_detector = SpinDetector(self.state, self._log)
        self.mouse_monitor = MouseMonitor(self.state, self._log)
        
        self._log_q = queue.Queue()
        self._running_slots = False
        self._running_ac = False
        self._stop_evt = threading.Event()
        
        # Restore geometry and build UI
        self._restore_geometry()
        self._build_ui()
        self.after(UI_FLUSH_MS, self._drain_log)
        
    def _check_permissions(self):
        """Check and request necessary permissions"""
        if not IS_MAC:
            return
            
        has_perms, missing = _check_mac_permissions()
        if not has_perms:
            msg = f"Spin Helper needs these permissions:\n\n{', '.join(missing)}\n\n"
            msg += "Please grant these in System Settings > Privacy & Security, then restart the app."
            messagebox.showinfo("Permissions Required", msg)

    # ---------- UI Layout ----------
    
    def _build_ui(self):
        # Main paned window
        self.paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)
        
        # Left panel with scrolling
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
        self._build_toolbar()
        
        # Environment Setup section
        self._build_environment_setup()
        
        # Main tabs
        self.sections = ttk.Notebook(self.left_inner)
        self.sections.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        self._build_slots_tab()
        self._build_roulette_tab() 
        self._build_autoclicker_tab()
        
        # Right log panel
        self._build_log_panel()
        
        # Status bar
        self.status = ttk.Label(self, text="Ready")
        self.status.pack(fill=tk.X)
        
        # Configure log styling
        self.log.tag_configure("green", foreground="#00a000")
        self.log.tag_configure("red", foreground="#cc0000")
        self.log.tag_configure("blue", foreground="#0066cc")
        
        # Mouse wheel support
        self.left_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        
    def _build_toolbar(self):
        """Build top toolbar with stay-on-top toggle"""
        toolbar = ttk.Frame(self.left_inner)
        toolbar.pack(fill=tk.X, padx=8, pady=(8, 0))
        
        # Stay on top toggle
        current_top = False
        try:
            current_top = bool(self.attributes("-topmost"))
        except Exception:
            pass
        self.topmost_var = tk.BooleanVar(value=current_top)
        ttk.Checkbutton(toolbar, text="Stay on top", variable=self.topmost_var, 
                       command=self._apply_topmost).pack(side=tk.LEFT)
    
    def _build_environment_setup(self):
        """Build centralized environment setup section"""
        env_frame = ttk.LabelFrame(self.left_inner, text="Environment Setup")
        env_frame.pack(fill=tk.X, padx=8, pady=8)
        
        # Spinner detection row
        spinner_frame = ttk.Frame(env_frame)
        spinner_frame.pack(fill=tk.X, padx=6, pady=6)
        
        ttk.Label(spinner_frame, text="Spinner Button:").pack(side=tk.LEFT)
        
        # Capture button
        ttk.Button(spinner_frame, text="Capture from Cursor", 
                  command=self._capture_spinner_universal).pack(side=tk.LEFT, padx=(10, 5))
        
        # Status and thumbnail
        self.spinner_status = ttk.Label(spinner_frame, text="Not captured", foreground="red")
        self.spinner_status.pack(side=tk.LEFT, padx=(10, 5))
        
        self.spinner_thumb_label = ttk.Label(spinner_frame)
        self.spinner_thumb_label.pack(side=tk.LEFT, padx=(5, 0))
    
    def _build_slots_tab(self):
        """Build Slots tab"""
        self.tab_slots = ttk.Frame(self.sections)
        self.sections.add(self.tab_slots, text="Slots (auto)")
        
        # Target Calculator section
        calc_frame = ttk.LabelFrame(self.tab_slots, text="Target Calculator")
        calc_frame.pack(fill=tk.X, padx=8, pady=8)
        
        # Calculator inputs
        inputs_frame = ttk.Frame(calc_frame)
        inputs_frame.pack(fill=tk.X, padx=6, pady=6)
        
        self.calc_amount = tk.StringVar()
        self.calc_mult = tk.StringVar()
        self.calc_unit = tk.StringVar()
        
        ttk.Label(inputs_frame, text="Amount (£):").grid(row=0, column=0, sticky="w", padx=2)
        ttk.Entry(inputs_frame, textvariable=self.calc_amount, width=10).grid(row=0, column=1, padx=2)
        
        ttk.Label(inputs_frame, text="Wagering ×:").grid(row=0, column=2, sticky="w", padx=2)
        ttk.Entry(inputs_frame, textvariable=self.calc_mult, width=8).grid(row=0, column=3, padx=2)
        
        ttk.Label(inputs_frame, text="Bet/Spin (£):").grid(row=0, column=4, sticky="w", padx=2)
        ttk.Entry(inputs_frame, textvariable=self.calc_unit, width=10).grid(row=0, column=5, padx=2)
        
        # Calculator outputs
        outputs_frame = ttk.Frame(calc_frame)
        outputs_frame.pack(fill=tk.X, padx=6, pady=6)
        
        self.calc_total = tk.StringVar(value="—")
        self.calc_target = tk.StringVar(value="—")
        self.calc_current_wager = tk.StringVar(value="£0.00")
        
        ttk.Label(outputs_frame, text="Total Wager:").grid(row=0, column=0, sticky="w", padx=2)
        ttk.Label(outputs_frame, textvariable=self.calc_total).grid(row=0, column=1, sticky="w", padx=2)
        
        ttk.Label(outputs_frame, text="Target Spins:").grid(row=0, column=2, sticky="w", padx=2)
        ttk.Label(outputs_frame, textvariable=self.calc_target).grid(row=0, column=3, sticky="w", padx=2)
        
        ttk.Label(outputs_frame, text="Current Wager:").grid(row=0, column=4, sticky="w", padx=2)
        ttk.Label(outputs_frame, textvariable=self.calc_current_wager, foreground="blue").grid(row=0, column=5, sticky="w", padx=2)
        
        # Calculator buttons
        calc_buttons = ttk.Frame(calc_frame)
        calc_buttons.pack(fill=tk.X, padx=6, pady=6)
        
        ttk.Button(calc_buttons, text="Calculate", command=self._calc_update).pack(side=tk.LEFT, padx=2)
        ttk.Button(calc_buttons, text="Reset", command=self._calc_reset).pack(side=tk.LEFT, padx=2)
        
        # Automation controls
        controls_frame = ttk.LabelFrame(self.tab_slots, text="Automation Controls")
        controls_frame.pack(fill=tk.X, padx=8, pady=8)
        
        controls_buttons = ttk.Frame(controls_frame)
        controls_buttons.pack(fill=tk.X, padx=6, pady=6)
        
        self.slots_start_btn = ttk.Button(controls_buttons, text="Start Auto Spins", command=self._start_slots)
        self.slots_start_btn.pack(side=tk.LEFT, padx=2)
        
        ttk.Button(controls_buttons, text="Pause", command=self._pause_slots).pack(side=tk.LEFT, padx=2)
        ttk.Button(controls_buttons, text="Stop", command=self._stop_slots).pack(side=tk.LEFT, padx=2)
        ttk.Button(controls_buttons, text="Reset", command=self._reset_slots).pack(side=tk.LEFT, padx=2)
        
        # Spin counter display
        counter_frame = ttk.Frame(controls_frame)
        counter_frame.pack(fill=tk.X, padx=6, pady=6)
        
        ttk.Label(counter_frame, text="Spins Completed:").pack(side=tk.LEFT)
        self.spin_counter_var = tk.StringVar(value="0")
        ttk.Label(counter_frame, textvariable=self.spin_counter_var, font=("TkDefaultFont", 12, "bold")).pack(side=tk.LEFT, padx=(5, 0))
    
    def _build_roulette_tab(self):
        """Build Roulette tab"""
        self.tab_roulette = ttk.Frame(self.sections)
        self.sections.add(self.tab_roulette, text="Roulette (manual)")
        
        ttk.Label(self.tab_roulette, text="Roulette features use the universal spinner detection from Environment Setup.").pack(anchor="w", padx=8, pady=8)
        
        # Manual controls
        manual_frame = ttk.LabelFrame(self.tab_roulette, text="Manual Controls")
        manual_frame.pack(fill=tk.X, padx=8, pady=8)
        
        ttk.Button(manual_frame, text="Single Click", command=self._roulette_single_click).pack(side=tk.LEFT, padx=6, pady=6)
    
    def _build_autoclicker_tab(self):
        """Build Autoclicker tab with sub-tabs"""
        self.tab_ac = ttk.Frame(self.sections)
        self.sections.add(self.tab_ac, text="Autoclicker")
        
        self.ac_tabs = ttk.Notebook(self.tab_ac)
        self.ac_tabs.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        
        # Manual sub-tab
        self._build_ac_manual_tab()
        
        # Automatic sub-tab  
        self._build_ac_automatic_tab()
    
    def _build_ac_manual_tab(self):
        """Build manual autoclicker tab"""
        tab_manual = ttk.Frame(self.ac_tabs)
        self.ac_tabs.add(tab_manual, text="Manual")
        
        self.ac_manual_target = tk.IntVar(value=0)
        self.ac_manual_done = tk.IntVar(value=0)
        
        # Target setting
        target_frame = ttk.Frame(tab_manual)
        target_frame.pack(fill=tk.X, padx=6, pady=6)
        
        ttk.Label(target_frame, text="Target clicks:").pack(side=tk.LEFT)
        ttk.Entry(target_frame, textvariable=self.ac_manual_target, width=10).pack(side=tk.LEFT, padx=(5, 10))
        ttk.Button(target_frame, text="Reset", command=self._ac_manual_reset).pack(side=tk.LEFT)
        
        # Click button
        ttk.Button(tab_manual, text="Single Click", command=self._ac_manual_click).pack(padx=6, pady=6)
        
        # Progress display
        progress_frame = ttk.Frame(tab_manual)
        progress_frame.pack(fill=tk.X, padx=6, pady=6)
        
        ttk.Label(progress_frame, text="Progress:").pack(side=tk.LEFT)
        self.ac_manual_progress = ttk.Label(progress_frame, text="0 / 0")
        self.ac_manual_progress.pack(side=tk.LEFT, padx=(5, 0))
    
    def _build_ac_automatic_tab(self):
        """Build automatic autoclicker tab"""
        tab_auto = ttk.Frame(self.ac_tabs)
        self.ac_tabs.add(tab_auto, text="Automatic")
        
        self.ac_auto_target = tk.IntVar(value=0)
        self.ac_auto_done = tk.IntVar(value=0)
        
        # Target and controls
        controls_frame = ttk.Frame(tab_auto)
        controls_frame.pack(fill=tk.X, padx=6, pady=6)
        
        ttk.Label(controls_frame, text="Target clicks:").grid(row=0, column=0, sticky="w", padx=2)
        ttk.Entry(controls_frame, textvariable=self.ac_auto_target, width=10).grid(row=0, column=1, padx=2)
        ttk.Button(controls_frame, text="Reset", command=self._ac_auto_reset).grid(row=0, column=2, padx=2)
        
        # Start/Stop buttons
        ttk.Button(controls_frame, text="Start Auto", command=self._ac_auto_start).grid(row=1, column=0, sticky="w", padx=2, pady=5)
        ttk.Button(controls_frame, text="Stop", command=self._ac_auto_stop).grid(row=1, column=1, padx=2, pady=5)
        
        # Anti-idle settings
        waggle_frame = ttk.LabelFrame(tab_auto, text="Anti-idle Waggle")
        waggle_frame.pack(fill=tk.X, padx=6, pady=6)
        
        self.waggle_on_var = tk.BooleanVar(value=False)
        self.waggle_secs_var = tk.IntVar(value=25)
        self.waggle_amp_var = tk.IntVar(value=10)
        
        ttk.Checkbutton(waggle_frame, text="Enable", variable=self.waggle_on_var).pack(anchor="w", padx=6, pady=2)
        
        waggle_settings = ttk.Frame(waggle_frame)
        waggle_settings.pack(fill=tk.X, padx=6, pady=2)
        
        ttk.Label(waggle_settings, text="Interval (s):").pack(side=tk.LEFT)
        ttk.Entry(waggle_settings, textvariable=self.waggle_secs_var, width=6).pack(side=tk.LEFT, padx=(5, 10))
        ttk.Label(waggle_settings, text="Amplitude (px):").pack(side=tk.LEFT)
        ttk.Entry(waggle_settings, textvariable=self.waggle_amp_var, width=6).pack(side=tk.LEFT, padx=(5, 0))
        
        # Progress display
        progress_frame = ttk.Frame(tab_auto)
        progress_frame.pack(fill=tk.X, padx=6, pady=6)
        
        ttk.Label(progress_frame, text="Progress:").pack(side=tk.LEFT)
        self.ac_auto_progress = ttk.Label(progress_frame, text="0 / 0")
        self.ac_auto_progress.pack(side=tk.LEFT, padx=(5, 0))
    
    def _build_log_panel(self):
        """Build right-side log panel"""
        right = ttk.Frame(self.paned)
        self.paned.add(right, weight=1)
        
        log_frame = ttk.LabelFrame(right, text="Activity Log")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        # Log text widget with scrollbar
        log_container = ttk.Frame(log_frame)
        log_container.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        
        self.log = tk.Text(log_container, wrap="word", height=15)
        log_scrollbar = ttk.Scrollbar(log_container, orient=tk.VERTICAL, command=self.log.yview)
        self.log.configure(yscrollcommand=log_scrollbar.set)
        
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _on_mousewheel(self, event):
        """Handle mousewheel scrolling"""
        self.left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ---------- Geometry Management ----------
    
    def _restore_geometry(self):
        """Restore window geometry and topmost state"""
        cfg = os.path.join(os.path.expanduser("~"), ".spin_helper_geometry.json")
        try:
            with open(cfg, "r") as f:
                data = json.load(f)
            self.geometry(data.get("geom", "1000x600"))
            try:
                self.attributes("-topmost", bool(data.get("topmost", True)))
            except Exception:
                pass
        except Exception:
            pass
    
    def _save_geometry(self):
        """Save window geometry and topmost state"""
        cfg = os.path.join(os.path.expanduser("~"), ".spin_helper_geometry.json")
        try:
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
        """Clean shutdown"""
        self._save_geometry()
        self.mouse_monitor.stop_monitoring()
        super().destroy()
    
    def _apply_topmost(self):
        """Apply topmost setting"""
        try:
            self.attributes("-topmost", bool(self.topmost_var.get()))
            self._save_geometry()
        except Exception:
            pass

    # ---------- Logging ----------
    
    def _log(self, msg, green=False, red=False, blue=False):
        """Add message to log queue"""
        color = "green" if green else ("red" if red else ("blue" if blue else None))
        self._log_q.put((msg, color))
    
    def _drain_log(self):
        """Drain log queue and update UI"""
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

    # ---------- Universal Spinner Capture ----------
    
    def _capture_spinner_universal(self):
        """Capture spinner for all features"""
        try:
            x, y = self.winfo_pointerxy()
            if self.spin_detector.capture_spinner(x, y):
                # Update UI
                self.spinner_status.config(text="Captured", foreground="green")
                if self.state.spinner.thumbnail:
                    self.spinner_thumb_label.config(image=self.state.spinner.thumbnail)
                self._update_ui_state()
        except Exception as e:
            messagebox.showerror("Capture Error", str(e))
    
    def _update_ui_state(self):
        """Update UI based on current state"""
        has_spinner = self.state.spinner.xy is not None
        
        # Update button states
        if hasattr(self, 'slots_start_btn'):
            state = "normal" if has_spinner else "disabled"
            self.slots_start_btn.config(state=state)

    # ---------- Calculator ----------
    
    def _calc_update(self):
        """Update calculator displays"""
        try:
            amount = float(self.calc_amount.get().strip() or "0")
            mult = float(self.calc_mult.get().strip() or "0") 
            unit = float(self.calc_unit.get().strip() or "0")
            
            total = amount * mult
            target = int(round(total / unit)) if unit > 0 else 0
            
            self.calc_total.set(f"£{total:.2f}")
            self.calc_target.set(str(target))
            
            # Update current wager based on spins completed
            current_wager = self.state.total_spins * unit
            self.calc_current_wager.set(f"£{current_wager:.2f}")
            
            self._log(f"Calculator: £{amount:.2f} × {mult} = £{total:.2f} ({target} spins @ £{unit:.2f})")
            
        except ValueError:
            self.calc_total.set("—")
            self.calc_target.set("—")
    
    def _calc_reset(self):
        """Reset calculator"""
        self.calc_amount.set("")
        self.calc_mult.set("")
        self.calc_unit.set("")
        self.calc_total.set("—")
        self.calc_target.set("—")
        self.calc_current_wager.set("£0.00")
        self._log("Calculator reset")

    # ---------- Slots Automation ----------
    
    def _start_slots(self):
        """Start slots automation"""
        if self._running_slots:
            return
        if not self.state.spinner.xy:
            messagebox.showwarning("Missing Setup", "Please capture spinner button first")
            return
            
        self._running_slots = True
        self._stop_evt.clear()
        self.mouse_monitor.start_monitoring()
        
        # Update button text based on pause state
        if self.state.paused_by_mouse:
            self.slots_start_btn.config(text="Resume Auto Spins")
        else:
            self.slots_start_btn.config(text="Running...")
            
        threading.Thread(target=self._slots_loop, daemon=True).start()
        self._log("Slots automation started")
    
    def _pause_slots(self):
        """Pause slots automation"""
        self.state.paused_by_mouse = True
        self._log("Slots automation paused")
    
    def _stop_slots(self):
        """Stop slots automation"""
        self._stop_evt.set()
        self.mouse_monitor.stop_monitoring()
        
    def _reset_slots(self):
        """Reset slots counters"""
        self.state.total_spins = 0
        self.spin_counter_var.set("0")
        self.state.paused_by_mouse = False
        self.slots_start_btn.config(text="Start Auto Spins")
        self._calc_update()  # Update current wager display
        self._log("Slots counters reset")
    
    def _slots_loop(self):
        """Main slots automation loop"""
        try:
            while not self._stop_evt.is_set():
                # Check if paused
                if self.state.paused_by_mouse:
                    time.sleep(0.5)
                    continue
                
                # Check target limits
                if self._check_slots_targets():
                    break
                
                # Perform click and wait for cycle
                self._log(f"Executing spin #{self.state.total_spins + 1}")
                
                if self.spin_detector.do_click():
                    if self.spin_detector.wait_for_spin_cycle():
                        self.state.total_spins += 1
                        self.spin_counter_var.set(str(self.state.total_spins))
                        self._calc_update()  # Update current wager
                        self._log(f"Spin #{self.state.total_spins} completed", green=True)
                    else:
                        self._log("Spin cycle timeout", red=True)
                        break
                else:
                    self._log("Click failed", red=True)
                    break
                    
        except Exception as e:
            self._log(f"Slots automation error: {e}", red=True)
        finally:
            self._running_slots = False
            self.mouse_monitor.stop_monitoring()
            self.slots_start_btn.config(text="Start Auto Spins")
            self._log("Slots automation stopped")
    
    def _check_slots_targets(self) -> bool:
        """Check if slots targets are reached"""
        try:
            # Check spin target
            target_str = self.calc_target.get()
            if target_str != "—":
                target_spins = int(target_str)
                if target_spins > 0 and self.state.total_spins >= target_spins:
                    self._log(f"Target spins reached: {self.state.total_spins}/{target_spins}", green=True)
                    return True
            
            # Check wager target
            total_str = self.calc_total.get()
            if total_str != "—":
                target_wager = float(total_str.replace("£", ""))
                unit = float(self.calc_unit.get() or "0")
                if target_wager > 0 and unit > 0:
                    current_wager = self.state.total_spins * unit
                    if current_wager >= target_wager:
                        self._log(f"Target wager reached: £{current_wager:.2f}/£{target_wager:.2f}", green=True)
                        return True
        except (ValueError, AttributeError):
            pass
        
        return False

    # ---------- Roulette ----------
    
    def _roulette_single_click(self):
        """Single click for roulette"""
        if not self.state.spinner.xy:
            messagebox.showwarning("Missing Setup", "Please capture spinner button first")
            return
            
        self._log("Roulette single click")
        if self.spin_detector.do_click():
            self._log("Click executed", green=True)
        else:
            self._log("Click failed", red=True)

    # ---------- Autoclicker ----------
    
    def _ac_manual_click(self):
        """Manual autoclicker single click"""
        if not self.state.spinner.xy:
            messagebox.showwarning("Missing Setup", "Please capture spinner button first")
            return
            
        target = self.ac_manual_target.get()
        done = self.ac_manual_done.get()
        
        if target > 0 and done >= target:
            self._log("Manual target already reached")
            return
            
        self._log(f"Manual click #{done + 1}")
        if self.spin_detector.do_click():
            if self.spin_detector.wait_for_spin_cycle(timeout_s=10.0):
                self.ac_manual_done.set(done + 1)
                self._update_ac_manual_progress()
                self._log(f"Manual click #{done + 1} completed", green=True)
            else:
                self._log("Manual click cycle timeout", red=True)
        else:
            self._log("Manual click failed", red=True)
    
    def _ac_manual_reset(self):
        """Reset manual autoclicker"""
        self.ac_manual_target.set(0)
        self.ac_manual_done.set(0)
        self._update_ac_manual_progress()
        self._log("Manual autoclicker reset")
    
    def _update_ac_manual_progress(self):
        """Update manual progress display"""
        done = self.ac_manual_done.get()
        target = self.ac_manual_target.get()
        self.ac_manual_progress.config(text=f"{done} / {target}")
    
    def _ac_auto_start(self):
        """Start automatic autoclicker"""
        if self._running_ac:
            return
        if not self.state.spinner.xy:
            messagebox.showwarning("Missing Setup", "Please capture spinner button first")
            return
            
        self._running_ac = True
        self._stop_evt.clear()
        self.mouse_monitor.start_monitoring()
        threading.Thread(target=self._ac_auto_loop, daemon=True).start()
        self._log("Automatic autoclicker started")
    
    def _ac_auto_stop(self):
        """Stop automatic autoclicker"""
        self._stop_evt.set()
        self.mouse_monitor.stop_monitoring()
    
    def _ac_auto_reset(self):
        """Reset automatic autoclicker"""
        self.ac_auto_target.set(0)
        self.ac_auto_done.set(0)
        self._update_ac_auto_progress()
        self._log("Automatic autoclicker reset")
    
    def _update_ac_auto_progress(self):
        """Update automatic progress display"""
        done = self.ac_auto_done.get()
        target = self.ac_auto_target.get()
        self.ac_auto_progress.config(text=f"{done} / {target}")
    
    def _ac_auto_loop(self):
        """Automatic autoclicker loop"""
        try:
            last_waggle = time.time()
            
            while not self._stop_evt.is_set():
                # Check pause state
                if self.state.paused_by_mouse:
                    time.sleep(0.5)
                    continue
                
                target = self.ac_auto_target.get()
                done = self.ac_auto_done.get()
                
                # Check if target reached
                if target > 0 and done >= target:
                    self._log(f"Automatic target reached: {done}/{target}", green=True)
                    break
                
                # Execute click
                self._log(f"Auto click #{done + 1}")
                if self.spin_detector.do_click():
                    if self.spin_detector.wait_for_spin_cycle():
                        self.ac_auto_done.set(done + 1)
                        self._update_ac_auto_progress()
                        self._log(f"Auto click #{done + 1} completed", green=True)
                    else:
                        self._log("Auto click cycle timeout", red=True)
                        break
                else:
                    self._log("Auto click failed", red=True)
                    break
                
                # Anti-idle waggle
                if (self.waggle_on_var.get() and 
                    time.time() - last_waggle > self.waggle_secs_var.get()):
                    self._perform_waggle()
                    last_waggle = time.time()
                    
        except Exception as e:
            self._log(f"Automatic autoclicker error: {e}", red=True)
        finally:
            self._running_ac = False
            self.mouse_monitor.stop_monitoring()
            self._log("Automatic autoclicker stopped")
    
    def _perform_waggle(self):
        """Perform anti-idle mouse waggle"""
        if not self.state.spinner.xy or not pg:
            return
            
        try:
            x, y = self.state.spinner.xy
            amp = clamp(self.waggle_amp_var.get(), 1, 40)
            
            pg.moveTo(x + amp, y, duration=0.05)
            pg.moveTo(x - amp, y, duration=0.05)  
            pg.moveTo(x, y, duration=0.05)
            
            self._log("Anti-idle waggle performed")
        except Exception as e:
            self._log(f"Waggle failed: {e}")

# ---------- Main ----------

def main():
    app = SpinHelperApp()
    app.mainloop()

if __name__ == "__main__":
    main()