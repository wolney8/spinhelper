# spin_helper.py — v1.15.0
# Iterative update from v1.14.2 with fixes and enhancements
# 
# Fixes:
# - CRITICAL: Fixed PYNPUT_AVAILABLE NameError 
# - CRITICAL: Fixed browser selection dialog z-order issue
# - ENHANCEMENT: Real macOS browser detection via AppleScript
# - ENHANCEMENT: Enhanced readiness detection and automation
# 
# Features maintained from v1.14.2:
# - Always-on-top toggle with persistence
# - Embedded calculator with navigation
# - Real pyautogui clicks with jitter
# - Anti-idle waggle functionality

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

import tkinter as tk
from tkinter import ttk, messagebox

# Import checks with proper variable definitions at module level
PIL_AVAILABLE = False
PYAUTOGUI_AVAILABLE = False
PYNPUT_AVAILABLE = False

try:
    from PIL import Image, ImageGrab, ImageChops, ImageStat
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

APP_VERSION = "1.15.0"

# UI Configuration
UI_FLUSH_MS = 60

# Spinner readiness thresholds (proven from v1.14.2)
PIX_DIFF_READY = 7.5
BRIGHT_READY_TOL = 0.14  
COLOR_D_READY_TOL = 18.0

# Autoclicker defaults
AC_DEFAULT_WAGGLE_ON = False
AC_DEFAULT_WAGGLE_SECS = 25
AC_DEFAULT_WAGGLE_AMP = 10

# --------------- Utility Functions ---------------

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

@dataclass
class WindowInfo:
    title: str
    app_name: str
    window_id: Optional[str] = None

# --------------- Browser Detection Module ---------------

class BrowserDetector:
    """Enhanced browser detection using AppleScript for real window detection"""
    
    def __init__(self):
        self.detected_windows = []
        self.selected_window = None
    
    def _run_applescript(self, script: str) -> str:
        """Execute AppleScript and return output"""
        try:
            result = subprocess.run(
                ["osascript", "-e", script], 
                capture_output=True, 
                text=True, 
                timeout=10
            )
            if result.returncode != 0:
                return ""
            return result.stdout.strip()
        except Exception:
            return ""
    
    def detect_browser_windows(self) -> List[WindowInfo]:
        """Detect real browser windows using AppleScript"""
        detected = []
        browser_apps = ["Google Chrome", "Safari", "Firefox", "Microsoft Edge"]
        
        for app_name in browser_apps:
            try:
                # Check if app is running
                check_script = f'''
                tell application "System Events"
                    return name of every application process whose name is "{app_name}"
                end tell
                '''
                
                if not self._run_applescript(check_script):
                    continue
                
                # Get window titles
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
                if not windows_output:
                    continue
                
                # Parse window titles
                window_titles = [title.strip().strip('"') for title in windows_output.split(",") if title.strip()]
                
                for i, title in enumerate(window_titles):
                    if title:
                        detected.append(WindowInfo(
                            title=title,
                            app_name=app_name,
                            window_id=f"{app_name.lower().replace(' ', '_')}_{i}"
                        ))
            
            except Exception:
                continue
        
        # Add manual fallbacks if no browsers detected
        if not detected:
            detected.extend([
                WindowInfo(title="Chrome Browser - Manual Mode", app_name="Google Chrome (Manual)", window_id="manual_chrome"),
                WindowInfo(title="Safari Browser - Manual Mode", app_name="Safari (Manual)", window_id="manual_safari"),
                WindowInfo(title="Firefox Browser - Manual Mode", app_name="Firefox (Manual)", window_id="manual_firefox"),
                WindowInfo(title="Other Browser - Manual Mode", app_name="Other Browser (Manual)", window_id="manual_other")
            ])
        
        self.detected_windows = detected
        return detected
    
    def show_selection_dialog(self, parent):
        """Show browser selection dialog with proper z-order"""
        dialog = tk.Toplevel(parent)
        dialog.title("Select Browser Window")
        dialog.geometry("700x500")
        dialog.transient(parent)
        dialog.grab_set()
        
        # CRITICAL FIX: Ensure dialog appears above stay-on-top parent
        dialog.attributes("-topmost", True)
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
            "Step 2: Select the browser window containing your casino game\n" 
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
            
            if windows:
                for window in windows:
                    display_text = f"{window.app_name}: {window.title}"
                    window_listbox.insert(tk.END, display_text)
                status_label.config(text=f"Found {len(windows)} browser windows")
            else:
                status_label.config(text="No browser windows found")
        
        ttk.Button(detect_frame, text="Detect Windows", command=detect_windows).pack(side=tk.LEFT)
        ttk.Button(detect_frame, text="Refresh", command=detect_windows).pack(side=tk.LEFT, padx=(10, 0))
        
        # Window list
        ttk.Label(dialog, text="Select browser window:").pack(anchor='w', padx=20, pady=(15, 5))
        
        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))
        
        window_listbox = tk.Listbox(list_frame)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=window_listbox.yview)
        window_listbox.configure(yscrollcommand=scrollbar.set)
        
        window_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Auto-detect on open
        dialog.after(100, detect_windows)
        
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
        
        # Run modal dialog
        dialog.wait_window()
        
        if selected_window:
            self.selected_window = selected_window
        
        return selected_window

# --------------- Main Application ---------------

class SpinHelperApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Spin Helper v{APP_VERSION}")
        self.minsize(980, 540)

        # Initialize state
        self.browser_detector = BrowserDetector()
        self.state_slots = SessionStateSlots()
        self._log_q = queue.Queue()
        self._running_slots = False
        self._running_ac = False
        self._stop_evt = threading.Event()
        
        # Manual spin counter
        self.manual_spin_count = 0
        
        # Keyboard listener
        self.keyboard_listener = None
        self._setup_keyboard_shortcuts()

        # Restore geometry and build UI
        self._restore_geometry()
        self._build_ui()
        self.after(UI_FLUSH_MS, self._drain_log)
        
        self._log("Spin Helper v1.15.0 initialized successfully", green=True)

    # ---------- Keyboard Shortcuts ----------
    
    def _setup_keyboard_shortcuts(self):
        """Setup global keyboard shortcuts"""
        if not PYNPUT_AVAILABLE:
            return
        
        def on_key_press(key):
            try:
                if key == keyboard.Key.space:
                    self._increment_manual_spin_counter()
            except Exception:
                pass
        
        try:
            self.keyboard_listener = keyboard.Listener(on_press=on_key_press)
            self.keyboard_listener.daemon = True
            self.keyboard_listener.start()
        except Exception:
            pass
    
    def _increment_manual_spin_counter(self):
        """Increment manual spin counter"""
        try:
            self.manual_spin_count += 1
            if hasattr(self, 'manual_spin_count_var'):
                self.manual_spin_count_var.set(self.manual_spin_count)
            self._log(f"Manual spin count: {self.manual_spin_count}")
        except Exception:
            pass

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

        # Toolbar with stay-on-top
        toolbar = ttk.Frame(self.left_inner)
        toolbar.pack(fill=tk.X, padx=8, pady=(8, 0))
        
        try:
            current_top = bool(self.attributes("-topmost"))
        except Exception:
            current_top = False
        self.topmost_var = tk.BooleanVar(value=current_top)
        ttk.Checkbutton(toolbar, text="Stay on top", variable=self.topmost_var, command=self._apply_topmost).pack(side=tk.LEFT)

        # Sections notebook
        self.sections = ttk.Notebook(self.left_inner)
        self.sections.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Environment Setup tab (new)
        self.tab_env = ttk.Frame(self.sections)
        self.sections.add(self.tab_env, text="Environment Setup") 
        self._build_env_tab(self.tab_env)

        # Slots tab
        self.tab_slots = ttk.Frame(self.sections)
        self.sections.add(self.tab_slots, text="Slots (auto)")
        self._build_slots_tab(self.tab_slots)

        # Roulette tab
        self.tab_roulette = ttk.Frame(self.sections)
        self.sections.add(self.tab_roulette, text="Roulette (manual)")
        self._build_roulette_tab(self.tab_roulette)

        # Autoclicker tab
        self.tab_ac = ttk.Frame(self.sections)
        self.sections.add(self.tab_ac, text="Autoclicker")
        self._build_ac_tab(self.tab_ac)

        # Right log panel
        right = ttk.Frame(self.paned)
        self.paned.add(right, weight=1)

        self.log = tk.Text(right, wrap="word", height=12)
        self.log.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Status bar
        self.status = ttk.Label(self, text="Ready")
        self.status.pack(fill=tk.X)

        # Log styling
        self.tag_green = "green"
        self.log.tag_configure(self.tag_green, foreground="#00a000")

        # Set pane position
        try:
            self.paned.sashpos(0, int(self.winfo_width() * 0.48))
        except Exception:
            pass

        # Mouse wheel support
        self.left_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        self.left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ---------- Build Tabs ----------

    def _build_env_tab(self, parent):
        """Build environment setup tab with real browser detection"""
        
        # Browser detection section
        browser_frame = ttk.LabelFrame(parent, text="Browser Window Selection", padding=10)
        browser_frame.pack(fill=tk.X, padx=8, pady=8)
        
        ttk.Label(browser_frame, text=(
            "Step 1: Open your casino game in Chrome/Safari/Firefox\n"
            "Step 2: Click 'Select Browser Window' below\n"
            "Step 3: Choose your casino tab from the list"
        )).pack(anchor='w', pady=(0, 10))
        
        button_frame = ttk.Frame(browser_frame)
        button_frame.pack(fill=tk.X)
        
        ttk.Button(button_frame, text="Select Browser Window", command=self._select_browser_window).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Refresh Window List", command=self._refresh_windows).pack(side=tk.LEFT)
        
        # Status display
        self.browser_status_var = tk.StringVar(value="No browser window selected")
        ttk.Label(browser_frame, textvariable=self.browser_status_var).pack(anchor='w', pady=(10, 0))
        
        # System info section
        sys_frame = ttk.LabelFrame(parent, text="System Information", padding=10)
        sys_frame.pack(fill=tk.X, padx=8, pady=8)
        
        info_text = f"Python: {sys.version.split()[0]}\nPlatform: {sys.platform}\n"
        info_text += f"PIL Available: {PIL_AVAILABLE}\nPyAutoGUI Available: {PYAUTOGUI_AVAILABLE}\n"
        info_text += f"Pynput Available: {PYNPUT_AVAILABLE}"
        
        ttk.Label(sys_frame, text=info_text, justify=tk.LEFT).pack(anchor='w')
        
        # Manual spin counter section (new feature)
        counter_frame = ttk.LabelFrame(parent, text="Manual Spin Counter", padding=10)
        counter_frame.pack(fill=tk.X, padx=8, pady=8)
        
        counter_controls = ttk.Frame(counter_frame)
        counter_controls.pack(fill=tk.X)
        
        ttk.Label(counter_controls, text="Manual spins:").pack(side=tk.LEFT)
        
        self.manual_spin_count_var = tk.IntVar(value=self.manual_spin_count)
        ttk.Label(counter_controls, textvariable=self.manual_spin_count_var, font=('Monaco', 12, 'bold')).pack(side=tk.LEFT, padx=(10, 20))
        
        ttk.Button(counter_controls, text="+1 Spin", command=self._increment_manual_spin_counter).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(counter_controls, text="Reset", command=self._reset_manual_spin_counter).pack(side=tk.LEFT)
        
        if PYNPUT_AVAILABLE:
            ttk.Label(counter_frame, text="Keyboard shortcut: Space bar").pack(anchor='w', pady=(5, 0))

    def _build_slots_tab(self, parent):
        col = 0
        r = 0

        ttk.Label(parent, text="Capture Spin Button:").grid(row=r, column=col, sticky="w", padx=6, pady=4)
        ttk.Button(parent, text="Capture from cursor", command=self._capture_spinner_from_cursor).grid(row=r, column=col+1, sticky="w", padx=6, pady=4)

        r += 1
        # Bind detect FS to app state properly
        if not hasattr(self, "detect_fs_var"):
            self.detect_fs_var = tk.BooleanVar(value=self.state_slots.detect_fs)
        ttk.Checkbutton(parent, text="Detect Free-Spins banner", variable=self.detect_fs_var, command=self._toggle_fs_detect).grid(row=r, column=col, sticky="w", padx=6, pady=4)
        ttk.Button(parent, text="Capture FS ROI", command=self._capture_fs_roi).grid(row=r, column=col+1, sticky="w", padx=6, pady=4)

        r += 1
        ttk.Button(parent, text="Bind to this display", command=self._bind_display).grid(row=r, column=col, sticky="w", padx=6, pady=4)

        r += 1
        ttk.Separator(parent, orient=tk.HORIZONTAL).grid(row=r, column=0, columnspan=6, sticky="ew", pady=6)

        r += 1
        ttk.Button(parent, text="Start Auto Spins", command=self._start_slots).grid(row=r, column=col, sticky="w", padx=6, pady=4)
        ttk.Button(parent, text="Stop", command=self._stop_slots).grid(row=r, column=col+1, sticky="w", padx=6, pady=4)
        ttk.Button(parent, text="Target Calculator…", command=self._goto_ac_calc).grid(row=r, column=col+2, sticky="w", padx=6, pady=4)

    def _build_roulette_tab(self, parent):
        ttk.Label(parent, text="Roulette (manual) — unchanged; uses capture helpers and logging.").pack(anchor="w", padx=6, pady=6)
        ttk.Button(parent, text="Target Calculator…", command=self._goto_ac_calc).pack(anchor="w", padx=6, pady=4)

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
        ttk.Entry(tab_m, textvariable=self.ac_manual_target, width=10).grid(row=row, column=1, sticky="w", padx=6, pady=4)

        row += 1
        ttk.Button(tab_m, text="Click once", command=self._ac_manual_click_once).grid(row=row, column=0, sticky="w", padx=6, pady=4)
        ttk.Button(tab_m, text="Reset Target", command=self._ac_reset_target).grid(row=row, column=1, sticky="w", padx=6, pady=4)

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
        ttk.Entry(tab_a, textvariable=self.ac_auto_target, width=10).grid(row=r, column=1, sticky="w", padx=6, pady=4)
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

        # Configure grid weights
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

    # ---------- Browser Selection Methods ----------

    def _select_browser_window(self):
        """Launch browser window selection with real detection"""
        self._log("Starting browser window selection...", green=True)
        try:
            selected = self.browser_detector.show_selection_dialog(self)
            if selected:
                self.browser_status_var.set(f"✓ Selected: {selected.app_name} - {selected.title}")
                self._log(f"Browser selected: {selected.app_name}", green=True)
            else:
                self._log("Browser selection cancelled")
        except Exception as e:
            self._log(f"Browser selection error: {e}")
            messagebox.showerror("Selection Error", str(e))

    def _refresh_windows(self):
        """Refresh browser window list"""
        self._log("Refreshing browser window list...")
        try:
            windows = self.browser_detector.detect_browser_windows()
            self._log(f"Found {len(windows)} browser windows")
        except Exception as e:
            self._log(f"Error refreshing windows: {e}")

    # ---------- Navigation Methods ----------

    def _goto_ac_calc(self):
        """Navigate to embedded calculator"""
        try:
            self.sections.select(self.tab_ac)
            if hasattr(self, "ac_tabs") and hasattr(self, "ac_tab_calc"):
                self.ac_tabs.select(self.ac_tab_calc)
            self._log("Opened Autoclicker → Calculator.")
        except Exception as e:
            self._log(f"Could not open Calculator tab: {e}")

    # ---------- Spinner Capture Methods ----------

    def _capture_spinner_from_cursor(self):
        """Capture spinner button from cursor position (enhanced from v1.14.2)"""
        if not PIL_AVAILABLE:
            messagebox.showerror("PIL Required", "PIL (Pillow) is required for image capture.")
            return
            
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
        """Capture Free-Spins ROI using two-stage process"""
        self._log("Free-Spins ROI: move mouse to TOP-LEFT. Capturing in 3…", green=True)
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
        """Toggle Free-Spins detection"""
        try:
            self.state_slots.detect_fs = bool(self.detect_fs_var.get())
        except Exception:
            self.state_slots.detect_fs = not self.state_slots.detect_fs
            if hasattr(self, "detect_fs_var"):
                self.detect_fs_var.set(self.state_slots.detect_fs)
        self._log(f"Detect Free-Spins banner: {'ON' if self.state_slots.detect_fs else 'OFF'}")

    def _bind_display(self):
        """Bind to current display"""
        try:
            if PYAUTOGUI_AVAILABLE:
                w, h = pg.size()
                self._log(f"Bound to display: {w}x{h}", green=True)
            else:
                self._log("Display binding requires PyAutoGUI")
        except Exception as e:
            self._log(f"Display binding error: {e}")

    # ---------- Readiness Detection ----------

    def _is_ready(self) -> bool:
        """Enhanced readiness detection from proven v1.14.2 code"""
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
        return bool(ok_rms or (ok_bright and ok_color))

    # ---------- Slots Auto ----------

    def _start_slots(self):
        """Start automated slots spinning"""
        if self._running_slots:
            return
        if not self.browser_detector.selected_window:
            messagebox.showwarning("Missing", "Select a browser window first.")
            return
        if not self.state_slots.spinner_xy:
            messagebox.showwarning("Missing", "Capture the spin button first.")
            return
        self._running_slots = True
        self._stop_evt.clear()
        threading.Thread(target=self._slots_loop, daemon=True).start()
        self._log("Started Slots auto.", green=True)

    def _stop_slots(self):
        """Stop slots automation"""
        self._stop_evt.set()

    def _slots_loop(self):
        """Enhanced slots automation loop"""
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

                self._log(f"Spin #{idx} complete.", green=True)
        finally:
            self._running_slots = False
            self._log("Slots automation stopped.")

    def _wait_ready_with_rescue(self, timeout_s=20.0):
        """Wait for readiness with rescue click logic"""
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
        """Perform click with jitter (enhanced from v1.14.2)"""
        s = self.state_slots
        if not s.spinner_xy:
            return
        x, y = s.spinner_xy
        try:
            if PYAUTOGUI_AVAILABLE:
                JITTER_PX = 1
                pg.moveTo(x + random.randint(-JITTER_PX, JITTER_PX),
                          y + random.randint(-JITTER_PX, JITTER_PX),
                          duration=0.05)
                pg.click()
            else:
                time.sleep(0.05)
        except Exception as e:
            self._log(f"Click failed: {e}")

    # ---------- Autoclicker Methods ----------

    def _ac_reset_target(self):
        """Reset autoclicker targets and counters"""
        try:
            self.ac_manual_target.set(0)
            self.ac_manual_done.set(0)
            self.ac_auto_target.set(0)
            self.ac_auto_done.set(0)
            self._log("Targets reset.", green=True)
        except Exception as e:
            self._log(f"Reset error: {e}")

    def _ac_manual_click_once(self):
        """Manual single click"""
        s = self.state_slots
        if not s.spinner_xy:
            messagebox.showwarning("Missing", "Capture the spin button first.")
            return
        tgt = self.ac_manual_target.get()
        done = self.ac_manual_done.get()
        if tgt and done >= tgt:
            self._log("Target already reached.")
            return

        n = done + 1
        self._log(f"Clicking #{n}…")
        self._do_click()
        self._wait_ready_with_rescue(timeout_s=8.0)
        self.ac_manual_done.set(n)
        if tgt and n >= tgt:
            self._log("Manual Target reached.", green=True)

    def _ac_auto_start(self):
        """Start automatic autoclicker"""
        if self._running_ac:
            return
        if not self.state_slots.spinner_xy:
            messagebox.showwarning("Missing", "Capture the spin button first.")
            return
        self._running_ac = True
        self._stop_evt.clear()
        threading.Thread(target=self._ac_auto_loop, daemon=True).start()
        self._log("Autoclicker: start", green=True)

    def _ac_auto_stop(self):
        """Stop automatic autoclicker"""
        self._stop_evt.set()

    def _ac_auto_loop(self):
        """Automatic clicking loop"""
        try:
            self.ac_auto_done.set(0)
            last_waggle = time.time()
            while not self._stop_evt.is_set():
                tgt = self.ac_auto_target.get()
                done = self.ac_auto_done.get()
                if tgt and done >= tgt:
                    self._log("Auto Target reached.", green=True)
                    break

                self._log(f"Clicking #{done+1}…")
                self._do_click()

                if self._wait_ready_with_rescue(timeout_s=30.0):
                    self._log(f"Click #{done+1} done; READY.")
                else:
                    self._log("No READY; continuing loop.")

                self.ac_auto_done.set(done + 1)

                # Anti-idle waggle
                if (self.waggle_on_var.get() and 
                    (time.time() - last_waggle > max(5, self.waggle_secs_var.get())) and 
                    self.state_slots.spinner_xy):
                    try:
                        bx, by = self.state_slots.spinner_xy
                        amp = clamp(self.waggle_amp_var.get(), 1, 40)
                        if PYAUTOGUI_AVAILABLE:
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

    # ---------- Calculator Methods ----------

    def _calc_reset(self):
        """Reset calculator fields"""
        self.calc_amount.set("")
        self.calc_mult.set("")
        self.calc_unit.set("")
        self.calc_total.set("—")
        self.calc_target.set("—")
        self._log("Calculator reset.")

    def _calc_apply_target(self):
        """Apply calculated target to autoclicker"""
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

    # ---------- Manual Spin Counter ----------
    
    def _increment_manual_spin_counter(self):
        """Increment manual spin counter"""
        try:
            self.manual_spin_count += 1
            if hasattr(self, 'manual_spin_count_var'):
                self.manual_spin_count_var.set(self.manual_spin_count)
            self._log(f"Manual spin count: {self.manual_spin_count}")
        except Exception as e:
            self._log(f"Error incrementing spin count: {e}")
    
    def _reset_manual_spin_counter(self):
        """Reset manual spin counter"""
        try:
            self.manual_spin_count = 0
            if hasattr(self, 'manual_spin_count_var'):
                self.manual_spin_count_var.set(0)
            self._log("Manual spin count reset.")
        except Exception as e:
            self._log(f"Error resetting spin count: {e}")

    # ---------- Geometry Management ----------

    def _restore_geometry(self):
        """Restore window geometry from file"""
        cfg = os.path.join(os.path.expanduser("~"), ".spin_helper_geometry.json")
        try:
            with open(cfg, "r") as f:
                data = json.load(f)
            self.geometry(data.get("geom", "980x580"))
            try:
                self.attributes("-topmost", bool(data.get("topmost", True)))
            except Exception:
                pass
        except Exception:
            pass

    def _save_geometry(self):
        """Save window geometry to file"""
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
        """Handle application shutdown"""
        try:
            if self.keyboard_listener:
                self.keyboard_listener.stop()
        except Exception:
            pass
        self._save_geometry()
        super().destroy()

    def _apply_topmost(self):
        """Apply stay-on-top setting"""
        try:
            self.attributes("-topmost", bool(self.topmost_var.get()))
            self._save_geometry()
        except Exception:
            pass

    # ---------- Logging ----------

    def _log(self, msg, green=False):
        """Add message to log queue"""
        self._log_q.put((msg, green))

    def _drain_log(self):
        """Process log queue and display messages"""
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

# --------------- Dependency Check & Main ---------------

def check_dependencies():
    """Check required dependencies are available"""
    missing = []
    warnings = []
    
    if not PIL_AVAILABLE:
        missing.append("Pillow (PIL)")
    
    if not PYAUTOGUI_AVAILABLE:
        missing.append("pyautogui")
    
    if not PYNPUT_AVAILABLE:
        warnings.append("pynput (keyboard shortcuts disabled)")
    
    # Check macOS permissions
    if sys.platform == 'darwin' and PYAUTOGUI_AVAILABLE:
        try:
            pg.size()
        except Exception:
            warnings.append("PyAutoGUI may need Accessibility permissions")
    
    if missing:
        print(f"ERROR: Missing required dependencies: {', '.join(missing)}")
        print("Install with: pip install -r requirements.txt")
        return False
    
    if warnings:
        print("WARNINGS:")
        for warning in warnings:
            print(f"  - {warning}")
    
    return True

def main():
    """Application entry point"""
    print(f"Starting Spin Helper v{APP_VERSION}")
    print(f"Platform: {sys.platform}")
    print(f"Python: {sys.version.split()[0]}")
    
    # Check dependencies
    if not check_dependencies():
        print("Cannot start - missing required dependencies")
        return 1
    
    try:
        app = SpinHelperApp()
        app.mainloop()
    except Exception as e:
        print(f"Fatal error: {e}")
        messagebox.showerror("Fatal Error", f"Application failed to start: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())