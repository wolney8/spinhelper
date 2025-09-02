# spin_helper.py — v2.0.0 - Complete rewrite following project plan
# Phase 1: Foundational Framework & User Interface (MVP)
# 
# This is a complete ground-up rewrite that implements:
# - Clean two-panel GUI layout (left controls, right log)
# - Environment interaction with guided browser window selection
# - Persistent window geometry and "stay on top" functionality
# - Real-time logging system
# - Foundation for Phase 2 calculator and Phase 3 automation

import os
import sys
import time
import json
import queue
import threading
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any

import tkinter as tk
from tkinter import ttk, messagebox

# Optional imports for future phases
try:
    from PIL import Image, ImageGrab, ImageChops, ImageStat
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("PIL not available - image processing disabled")

try:
    import pyautogui as pg
    pg.FAILSAFE = False
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    print("pyautogui not available - automation disabled")

# --------------- Constants ---------------

APP_VERSION = "2.0.0"
APP_TITLE = f"Spin Helper v{APP_VERSION}"

# UI Configuration
UI_FLUSH_INTERVAL_MS = 60
MIN_WINDOW_WIDTH = 980
MIN_WINDOW_HEIGHT = 540
DEFAULT_GEOMETRY = "1200x700"

# File paths
GEOMETRY_FILE = os.path.join(os.path.expanduser("~"), ".spin_helper_geometry.json")
SESSION_FILE = os.path.join(os.path.expanduser("~"), ".spin_helper_session.json")

# --------------- Data Models ---------------

@dataclass
class AppConfig:
    """Application configuration settings"""
    stay_on_top: bool = True
    log_timestamps: bool = True
    auto_save_session: bool = True

@dataclass 
class WindowInfo:
    """Information about a detected window"""
    title: str
    app_name: str
    window_id: Optional[str] = None
    bounds: Optional[Tuple[int, int, int, int]] = None  # (x, y, width, height)

@dataclass
class BrowserTarget:
    """Selected browser window for automation"""
    window_info: Optional[WindowInfo] = None
    selection_time: Optional[float] = None
    is_valid: bool = False

# --------------- Utility Functions ---------------

def get_timestamp() -> str:
    """Get formatted timestamp for logging"""
    return time.strftime("[%Y-%m-%d %H:%M:%S]")

def safe_json_load(filepath: str, default: Dict[str, Any]) -> Dict[str, Any]:
    """Safely load JSON file with fallback to default"""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, Exception):
        return default.copy()

def safe_json_save(filepath: str, data: Dict[str, Any]) -> bool:
    """Safely save JSON file"""
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False

# --------------- Environment Interaction Module ---------------

class EnvironmentDetector:
    """Handles detection and interaction with the Mac OS desktop environment"""
    
    def __init__(self):
        self.detected_windows: List[WindowInfo] = []
        self.selected_browser: Optional[BrowserTarget] = None
    
    def detect_browser_windows(self) -> List[WindowInfo]:
        """Detect currently open browser windows"""
        # Simplified implementation for Phase 1
        # In future phases, this will use more sophisticated detection
        browser_apps = ["Chrome", "Safari", "Firefox", "Edge"]
        detected = []
        
        # Placeholder implementation - will be enhanced in Phase 3
        for app in browser_apps:
            detected.append(WindowInfo(
                title=f"{app} - Casino Tab",
                app_name=app,
                window_id=f"mock_{app.lower()}"
            ))
        
        self.detected_windows = detected
        return detected
    
    def guided_selection_dialog(self, parent_window) -> Optional[BrowserTarget]:
        """Show guided dialog for user to select browser window"""
        
        dialog = tk.Toplevel(parent_window)
        dialog.title("Select Browser Window")
        dialog.geometry("600x400")
        dialog.resizable(False, False)
        dialog.transient(parent_window)
        dialog.grab_set()
        
        # Center on parent
        parent_window.update_idletasks()
        x = parent_window.winfo_x() + (parent_window.winfo_width() // 2) - 300
        y = parent_window.winfo_y() + (parent_window.winfo_height() // 2) - 200
        dialog.geometry(f"600x400+{x}+{y}")
        
        selected_target = None
        
        # Instructions
        instructions = ttk.Label(dialog, text=(
            "Step 1: Click 'Detect Windows' to scan for open browsers\n"
            "Step 2: Select the browser window containing your casino game\n"
            "Step 3: Click 'Confirm Selection' to complete setup"
        ), justify=tk.LEFT)
        instructions.pack(pady=20, padx=20)
        
        # Detection button
        def detect_windows():
            windows = self.detect_browser_windows()
            window_listbox.delete(0, tk.END)
            for i, window in enumerate(windows):
                display_text = f"{window.app_name}: {window.title}"
                window_listbox.insert(tk.END, display_text)
            status_label.config(text=f"Found {len(windows)} browser windows")
        
        ttk.Button(dialog, text="Detect Windows", command=detect_windows).pack(pady=10)
        
        # Window list
        ttk.Label(dialog, text="Select browser window:").pack(anchor='w', padx=20)
        
        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        window_listbox = tk.Listbox(list_frame)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=window_listbox.yview)
        window_listbox.configure(yscrollcommand=scrollbar.set)
        
        window_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Status and buttons
        status_label = ttk.Label(dialog, text="Click 'Detect Windows' to begin")
        status_label.pack(pady=10)
        
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=20)
        
        def confirm_selection():
            nonlocal selected_target
            selection = window_listbox.curselection()
            if not selection:
                messagebox.showwarning("No Selection", "Please select a browser window first.")
                return
            
            window_info = self.detected_windows[selection[0]]
            selected_target = BrowserTarget(
                window_info=window_info,
                selection_time=time.time(),
                is_valid=True
            )
            
            status_label.config(text=f"Selected: {window_info.app_name}")
            dialog.after(500, dialog.destroy)  # Small delay for user feedback
        
        ttk.Button(button_frame, text="Confirm Selection", command=confirm_selection).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=10)
        
        # Run modal dialog
        dialog.wait_window()
        
        if selected_target:
            self.selected_browser = selected_target
            
        return selected_target

# --------------- Main Application ---------------

class SpinHelperApp(tk.Tk):
    """Main application class implementing the Spin Helper GUI"""
    
    def __init__(self):
        super().__init__()
        
        # Initialize core components
        self.config = AppConfig()
        self.env_detector = EnvironmentDetector()
        self._log_queue = queue.Queue()
        
        # Threading controls
        self._stop_event = threading.Event()
        self._automation_running = False
        
        # Initialize UI
        self._setup_window()
        self._build_ui()
        self._restore_geometry()
        
        # Start log processing
        self.after(UI_FLUSH_INTERVAL_MS, self._process_log_queue)
        
        # Welcome message
        self._log("Spin Helper initialized successfully", log_type="INFO")
        self._log("Phase 1: Foundational Framework ready", log_type="SUCCESS")
    
    def _setup_window(self):
        """Configure main window properties"""
        self.title(APP_TITLE)
        self.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        
        # Set up protocol for clean shutdown
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
    
    def _build_ui(self):
        """Build the main user interface following the two-panel design"""
        
        # Create main paned window (horizontal split)
        self.main_paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True)
        
        # Left panel - controls with scrolling capability
        self._build_left_panel()
        
        # Right panel - dedicated log area
        self._build_right_panel()
        
        # Status bar
        self.status_bar = ttk.Label(self, text="Ready - Select browser window to begin", relief=tk.SUNKEN)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Set initial pane positions
        self.after_idle(lambda: self.main_paned.sashpos(0, 580))
    
    def _build_left_panel(self):
        """Build left control panel with scrolling"""
        
        # Left frame container
        left_container = ttk.Frame(self.main_paned)
        self.main_paned.add(left_container, weight=1)
        
        # Toolbar with stay-on-top toggle
        self._build_toolbar(left_container)
        
        # Scrollable content area
        canvas = tk.Canvas(left_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(left_container, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        # Configure scrolling
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Pack scrolling components
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Build control sections
        self._build_control_sections(scrollable_frame)
        
        # Store references for scrolling
        self.left_canvas = canvas
        self._bind_mousewheel()
    
    def _build_toolbar(self, parent):
        """Build toolbar with stay-on-top toggle"""
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, padx=8, pady=(8, 0))
        
        # Stay on top toggle
        self.stay_on_top_var = tk.BooleanVar(value=self.config.stay_on_top)
        stay_on_top_cb = ttk.Checkbutton(
            toolbar, 
            text="Stay on top", 
            variable=self.stay_on_top_var,
            command=self._toggle_stay_on_top
        )
        stay_on_top_cb.pack(side=tk.LEFT)
        
        # Apply initial stay-on-top setting
        self._apply_stay_on_top()
    
    def _build_control_sections(self, parent):
        """Build the main control sections using notebook tabs"""
        
        # Main sections notebook
        self.sections_notebook = ttk.Notebook(parent)
        self.sections_notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        # Environment Setup Tab (Phase 1 focus)
        self._build_environment_tab()
        
        # Slots Tab (preparation for Phase 3)
        self._build_slots_tab()
        
        # Autoclicker Tab (preparation for Phase 2 & 3)
        self._build_autoclicker_tab()
    
    def _build_environment_tab(self):
        """Build environment interaction tab - core Phase 1 functionality"""
        env_frame = ttk.Frame(self.sections_notebook)
        self.sections_notebook.add(env_frame, text="Environment Setup")
        
        # Browser Detection Section
        browser_section = ttk.LabelFrame(env_frame, text="Browser Window Detection", padding=10)
        browser_section.pack(fill=tk.X, padx=8, pady=8)
        
        ttk.Label(browser_section, text=(
            "Step 1: Ensure your casino game is open in a browser\n"
            "Step 2: Click 'Select Browser Window' and choose the correct window\n"
            "Step 3: The app will remember this window for automation"
        )).pack(anchor='w', pady=(0, 10))
        
        button_frame = ttk.Frame(browser_section)
        button_frame.pack(fill=tk.X)
        
        self.select_window_btn = ttk.Button(
            button_frame, 
            text="Select Browser Window", 
            command=self._select_browser_window
        )
        self.select_window_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.refresh_windows_btn = ttk.Button(
            button_frame, 
            text="Refresh Window List", 
            command=self._refresh_windows
        )
        self.refresh_windows_btn.pack(side=tk.LEFT)
        
        # Status display
        self.browser_status_var = tk.StringVar(value="No browser window selected")
        status_label = ttk.Label(browser_section, textvariable=self.browser_status_var)
        status_label.pack(anchor='w', pady=(10, 0))
        
        # System Information Section
        sys_section = ttk.LabelFrame(env_frame, text="System Information", padding=10)
        sys_section.pack(fill=tk.X, padx=8, pady=8)
        
        # Display system info
        self._display_system_info(sys_section)
    
    def _build_slots_tab(self):
        """Build slots automation tab - foundation for Phase 3"""
        slots_frame = ttk.Frame(self.sections_notebook)
        self.sections_notebook.add(slots_frame, text="Slots (auto)")
        
        # Preparation notice
        prep_section = ttk.LabelFrame(slots_frame, text="Setup Required", padding=10)
        prep_section.pack(fill=tk.X, padx=8, pady=8)
        
        ttk.Label(prep_section, text=(
            "This section will contain automated slots functionality in Phase 3.\n"
            "Required setup:\n"
            "• Browser window selection (Environment Setup tab)\n"
            "• Spin button capture\n" 
            "• Readiness detection configuration"
        )).pack(anchor='w')
        
        # Quick navigation to calculator (Phase 2 preparation)
        nav_frame = ttk.Frame(prep_section)
        nav_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(
            nav_frame, 
            text="Open Target Calculator →", 
            command=self._navigate_to_calculator
        ).pack(side=tk.LEFT)
    
    def _build_autoclicker_tab(self):
        """Build autoclicker tab with sub-tabs - foundation for Phase 2 & 3"""
        ac_frame = ttk.Frame(self.sections_notebook)
        self.sections_notebook.add(ac_frame, text="Autoclicker")
        
        # Sub-notebook for autoclicker modes
        self.ac_notebook = ttk.Notebook(ac_frame)
        self.ac_notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        # Manual mode
        self._build_manual_autoclicker()
        
        # Automatic mode
        self._build_automatic_autoclicker()
        
        # Calculator (embedded - Phase 2 preparation)
        self._build_calculator()
    
    def _build_manual_autoclicker(self):
        """Build manual autoclicker sub-tab"""
        manual_frame = ttk.Frame(self.ac_notebook)
        self.ac_notebook.add(manual_frame, text="Manual")
        
        # Manual controls section
        controls_section = ttk.LabelFrame(manual_frame, text="Manual Click Controls", padding=10)
        controls_section.pack(fill=tk.X, padx=8, pady=8)
        
        ttk.Label(controls_section, text=(
            "Manual mode allows precise, single-click control.\n"
            "Use this for testing and precise positioning."
        )).pack(anchor='w', pady=(0, 10))
        
        # Target counter
        counter_frame = ttk.Frame(controls_section)
        counter_frame.pack(fill=tk.X)
        
        ttk.Label(counter_frame, text="Target clicks:").grid(row=0, column=0, sticky='w', padx=(0, 10))
        
        self.manual_target_var = tk.IntVar(value=0)
        target_entry = ttk.Entry(counter_frame, textvariable=self.manual_target_var, width=10)
        target_entry.grid(row=0, column=1, sticky='w', padx=(0, 10))
        
        self.manual_count_var = tk.IntVar(value=0)
        count_label = ttk.Label(counter_frame, text="Completed: 0")
        count_label.grid(row=0, column=2, sticky='w', padx=(20, 0))
        
        # Store reference for updates
        self.manual_count_label = count_label
        
        # Control buttons
        button_frame = ttk.Frame(controls_section)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(
            button_frame, 
            text="Single Click", 
            command=self._manual_single_click
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(
            button_frame, 
            text="Reset Counter", 
            command=self._reset_manual_counter
        ).pack(side=tk.LEFT)
        
        # Configure grid weights
        counter_frame.grid_columnconfigure(2, weight=1)
    
    def _build_automatic_autoclicker(self):
        """Build automatic autoclicker sub-tab"""
        auto_frame = ttk.Frame(self.ac_notebook)
        self.ac_notebook.add(auto_frame, text="Automatic")
        
        # Automatic controls section  
        controls_section = ttk.LabelFrame(auto_frame, text="Automatic Click Controls", padding=10)
        controls_section.pack(fill=tk.X, padx=8, pady=8)
        
        ttk.Label(controls_section, text=(
            "Automatic mode runs continuous clicking until target is reached.\n"
            "Includes anti-idle features and smart timing."
        )).pack(anchor='w', pady=(0, 10))
        
        # Target and progress
        target_frame = ttk.Frame(controls_section)
        target_frame.pack(fill=tk.X)
        
        ttk.Label(target_frame, text="Target clicks:").grid(row=0, column=0, sticky='w')
        
        self.auto_target_var = tk.IntVar(value=0)
        ttk.Entry(target_frame, textvariable=self.auto_target_var, width=10).grid(row=0, column=1, sticky='w', padx=(5, 20))
        
        self.auto_progress_var = tk.StringVar(value="Progress: 0/0")
        ttk.Label(target_frame, textvariable=self.auto_progress_var).grid(row=0, column=2, sticky='w')
        
        # Control buttons
        control_frame = ttk.Frame(controls_section)
        control_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.start_auto_btn = ttk.Button(
            control_frame, 
            text="Start Automatic", 
            command=self._start_automatic
        )
        self.start_auto_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.stop_auto_btn = ttk.Button(
            control_frame, 
            text="Stop", 
            command=self._stop_automatic,
            state=tk.DISABLED
        )
        self.stop_auto_btn.pack(side=tk.LEFT)
        
        # Anti-idle section (Phase 3 preparation)
        idle_section = ttk.LabelFrame(auto_frame, text="Anti-Idle Options (Phase 3)", padding=10)
        idle_section.pack(fill=tk.X, padx=8, pady=8)
        
        self.waggle_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            idle_section, 
            text="Enable anti-idle waggle", 
            variable=self.waggle_enabled_var
        ).pack(anchor='w')
        
        waggle_frame = ttk.Frame(idle_section)
        waggle_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(waggle_frame, text="Interval (seconds):").grid(row=0, column=0, sticky='w')
        self.waggle_interval_var = tk.IntVar(value=25)
        ttk.Entry(waggle_frame, textvariable=self.waggle_interval_var, width=6).grid(row=0, column=1, sticky='w', padx=(5, 20))
        
        ttk.Label(waggle_frame, text="Amplitude (pixels):").grid(row=0, column=2, sticky='w')
        self.waggle_amplitude_var = tk.IntVar(value=10)
        ttk.Entry(waggle_frame, textvariable=self.waggle_amplitude_var, width=6).grid(row=0, column=3, sticky='w', padx=(5, 0))
    
    def _build_calculator(self):
        """Build embedded calculator sub-tab - Phase 2 preparation"""
        calc_frame = ttk.Frame(self.ac_notebook)
        self.ac_notebook.add(calc_frame, text="Calculator")
        
        # Store reference for navigation
        self.calculator_tab = calc_frame
        
        # Calculator section
        calc_section = ttk.LabelFrame(calc_frame, text="Target Calculator", padding=10)
        calc_section.pack(fill=tk.X, padx=8, pady=8)
        
        ttk.Label(calc_section, text=(
            "Calculate optimal targets for wagering requirements.\n"
            "Phase 2 will implement full calculation logic."
        )).pack(anchor='w', pady=(0, 10))
        
        # Input fields (Phase 2 preparation)
        input_frame = ttk.Frame(calc_section)
        input_frame.pack(fill=tk.X)
        
        # Row 1: Amount and multiplier
        ttk.Label(input_frame, text="Bonus Amount (£):").grid(row=0, column=0, sticky='w', pady=2)
        self.calc_amount_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.calc_amount_var, width=10).grid(row=0, column=1, sticky='w', padx=(5, 20), pady=2)
        
        ttk.Label(input_frame, text="Wagering Multiple:").grid(row=0, column=2, sticky='w', pady=2)
        self.calc_multiplier_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.calc_multiplier_var, width=8).grid(row=0, column=3, sticky='w', padx=(5, 0), pady=2)
        
        # Row 2: Bet per spin and results
        ttk.Label(input_frame, text="Bet per spin (£):").grid(row=1, column=0, sticky='w', pady=2)
        self.calc_bet_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.calc_bet_var, width=10).grid(row=1, column=1, sticky='w', padx=(5, 20), pady=2)
        
        ttk.Label(input_frame, text="Required Spins:").grid(row=1, column=2, sticky='w', pady=2)
        self.calc_result_var = tk.StringVar(value="—")
        ttk.Label(input_frame, textvariable=self.calc_result_var).grid(row=1, column=3, sticky='w', padx=(5, 0), pady=2)
        
        # Action buttons
        action_frame = ttk.Frame(calc_section)
        action_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(
            action_frame, 
            text="Calculate", 
            command=self._calculate_target
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(
            action_frame, 
            text="Apply to Targets", 
            command=self._apply_calculated_target
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(
            action_frame, 
            text="Reset", 
            command=self._reset_calculator
        ).pack(side=tk.LEFT)
    
    def _build_right_panel(self):
        """Build right panel with dedicated log area"""
        
        # Right frame container
        right_container = ttk.Frame(self.main_paned)
        self.main_paned.add(right_container, weight=1)
        
        # Log section
        log_section = ttk.LabelFrame(right_container, text="Live Activity Log", padding=8)
        log_section.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        # Log text widget with scrolling
        log_frame = ttk.Frame(log_section)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = tk.Text(
            log_frame, 
            wrap=tk.WORD, 
            height=15,
            font=('Monaco', 10) if sys.platform == 'darwin' else ('Courier', 10)
        )
        
        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Configure log text tags for colored output
        self.log_text.tag_configure("INFO", foreground="#0066cc")
        self.log_text.tag_configure("SUCCESS", foreground="#009900") 
        self.log_text.tag_configure("WARNING", foreground="#ff6600")
        self.log_text.tag_configure("ERROR", foreground="#cc0000")
        self.log_text.tag_configure("ACTION", foreground="#6600cc")
        
        # Log control buttons
        log_controls = ttk.Frame(log_section)
        log_controls.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Button(log_controls, text="Clear Log", command=self._clear_log).pack(side=tk.LEFT)
        ttk.Button(log_controls, text="Save Log", command=self._save_log).pack(side=tk.LEFT, padx=(10, 0))
    
    def _display_system_info(self, parent):
        """Display system information for debugging"""
        info_text = f"Python: {sys.version.split()[0]}\n"
        info_text += f"Platform: {sys.platform}\n"
        info_text += f"PIL Available: {PIL_AVAILABLE}\n"
        info_text += f"PyAutoGUI Available: {PYAUTOGUI_AVAILABLE}\n"
        
        ttk.Label(parent, text=info_text, justify=tk.LEFT).pack(anchor='w')
    
    def _bind_mousewheel(self):
        """Bind mousewheel scrolling to left canvas"""
        def _on_mousewheel(event):
            self.left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        self.bind_all("<MouseWheel>", _on_mousewheel)  # Windows/Linux
        self.bind_all("<Button-4>", lambda e: self.left_canvas.yview_scroll(-1, "units"))  # macOS
        self.bind_all("<Button-5>", lambda e: self.left_canvas.yview_scroll(1, "units"))   # macOS
    
    # --------------- Geometry Management ---------------
    
    def _restore_geometry(self):
        """Restore window geometry and settings from file"""
        data = safe_json_load(GEOMETRY_FILE, {
            "geometry": DEFAULT_GEOMETRY,
            "stay_on_top": True
        })
        
        try:
            self.geometry(data.get("geometry", DEFAULT_GEOMETRY))
            self.config.stay_on_top = data.get("stay_on_top", True)
            self.stay_on_top_var.set(self.config.stay_on_top)
            self._apply_stay_on_top()
        except Exception as e:
            self._log(f"Could not restore geometry: {e}", log_type="WARNING")
    
    def _save_geometry(self):
        """Save current window geometry and settings"""
        try:
            data = {
                "geometry": self.geometry(),
                "stay_on_top": self.stay_on_top_var.get()
            }
            safe_json_save(GEOMETRY_FILE, data)
        except Exception as e:
            self._log(f"Could not save geometry: {e}", log_type="WARNING")
    
    def _toggle_stay_on_top(self):
        """Handle stay-on-top toggle"""
        self.config.stay_on_top = self.stay_on_top_var.get()
        self._apply_stay_on_top()
        self._save_geometry()
        self._log(f"Stay on top: {'enabled' if self.config.stay_on_top else 'disabled'}")
    
    def _apply_stay_on_top(self):
        """Apply stay-on-top setting to window"""
        try:
            self.attributes("-topmost", self.config.stay_on_top)
        except Exception as e:
            self._log(f"Could not apply stay-on-top: {e}", log_type="WARNING")
    
    # --------------- Environment Interaction ---------------
    
    def _select_browser_window(self):
        """Launch guided browser window selection"""
        self._log("Starting browser window selection...", log_type="ACTION")
        
        try:
            target = self.env_detector.guided_selection_dialog(self)
            
            if target and target.is_valid:
                self.browser_status_var.set(
                    f"Selected: {target.window_info.app_name} - {target.window_info.title}"
                )
                self.status_bar.config(text="Browser window selected - Ready for automation")
                self._log(f"Browser window selected: {target.window_info.app_name}", log_type="SUCCESS")
            else:
                self._log("Browser window selection cancelled", log_type="INFO")
                
        except Exception as e:
            self._log(f"Error in window selection: {e}", log_type="ERROR")
            messagebox.showerror("Selection Error", f"Could not select window: {e}")
    
    def _refresh_windows(self):
        """Refresh the list of detected windows"""
        self._log("Refreshing window list...", log_type="ACTION")
        try:
            windows = self.env_detector.detect_browser_windows()
            self._log(f"Detected {len(windows)} browser windows", log_type="INFO")
        except Exception as e:
            self._log(f"Error refreshing windows: {e}", log_type="ERROR")
    
    # --------------- Navigation ---------------
    
    def _navigate_to_calculator(self):
        """Navigate to the embedded calculator tab"""
        try:
            # Switch to autoclicker tab
            self.sections_notebook.select(2)  # Autoclicker is 3rd tab (index 2)
            # Switch to calculator sub-tab
            self.ac_notebook.select(2)  # Calculator is 3rd sub-tab (index 2)
            self._log("Navigated to Target Calculator", log_type="INFO")
        except Exception as e:
            self._log(f"Navigation error: {e}", log_type="ERROR")
    
    # --------------- Manual Autoclicker ---------------
    
    def _manual_single_click(self):
        """Perform a single manual click"""
        if not self.env_detector.selected_browser:
            messagebox.showwarning("No Target", "Please select a browser window first.")
            return
        
        current_count = self.manual_count_var.get()
        target = self.manual_target_var.get()
        
        if target > 0 and current_count >= target:
            self._log("Manual target already reached", log_type="WARNING")
            return
        
        # Increment counter
        new_count = current_count + 1
        self.manual_count_var.set(new_count)
        self.manual_count_label.config(text=f"Completed: {new_count}")
        
        # Log the action
        self._log(f"Manual click #{new_count} executed", log_type="ACTION")
        
        # Check if target reached
        if target > 0 and new_count >= target:
            self._log(f"Manual target of {target} clicks reached!", log_type="SUCCESS")
        
        # TODO Phase 3: Actually perform the click using pyautogui
    
    def _reset_manual_counter(self):
        """Reset manual click counter"""
        self.manual_count_var.set(0)
        self.manual_count_label.config(text="Completed: 0")
        self._log("Manual counter reset", log_type="INFO")
    
    # --------------- Automatic Autoclicker ---------------
    
    def _start_automatic(self):
        """Start automatic clicking mode"""
        if not self.env_detector.selected_browser:
            messagebox.showwarning("No Target", "Please select a browser window first.")
            return
        
        if self._automation_running:
            self._log("Automation already running", log_type="WARNING")
            return
        
        target = self.auto_target_var.get()
        if target <= 0:
            messagebox.showwarning("Invalid Target", "Please set a target greater than 0.")
            return
        
        # Start automation
        self._automation_running = True
        self._stop_event.clear()
        
        # Update UI
        self.start_auto_btn.config(state=tk.DISABLED)
        self.stop_auto_btn.config(state=tk.NORMAL)
        
        # Start automation thread
        threading.Thread(target=self._automatic_click_loop, daemon=True).start()
        self._log(f"Automatic clicking started - Target: {target}", log_type="SUCCESS")
    
    def _stop_automatic(self):
        """Stop automatic clicking mode"""
        self._stop_event.set()
        self._log("Stopping automatic clicking...", log_type="ACTION")
    
    def _automatic_click_loop(self):
        """Main automatic clicking loop"""
        try:
            click_count = 0
            target = self.auto_target_var.get()
            
            while not self._stop_event.is_set() and click_count < target:
                click_count += 1
                
                # Update progress
                progress_text = f"Progress: {click_count}/{target}"
                self.auto_progress_var.set(progress_text)
                
                # Log click
                self._log(f"Auto click #{click_count}/{target}", log_type="ACTION")
                
                # TODO Phase 3: Perform actual click with pyautogui
                # TODO Phase 3: Wait for readiness detection
                # TODO Phase 3: Implement anti-idle waggle
                
                # Placeholder delay for now
                time.sleep(0.5)
                
                # Check for stop condition
                if self._stop_event.wait(0.1):
                    break
            
            # Completion handling
            if click_count >= target:
                self._log(f"Automatic clicking completed! {click_count} clicks executed", log_type="SUCCESS")
            else:
                self._log(f"Automatic clicking stopped at {click_count}/{target}", log_type="INFO")
                
        except Exception as e:
            self._log(f"Error in automatic clicking: {e}", log_type="ERROR")
        finally:
            # Reset UI state
            self._automation_running = False
            self.start_auto_btn.config(state=tk.NORMAL)
            self.stop_auto_btn.config(state=tk.DISABLED)
            self._log("Automatic clicking stopped", log_type="INFO")
    
    # --------------- Calculator Functions ---------------
    
    def _calculate_target(self):
        """Calculate required spins based on wagering requirements"""
        try:
            amount = float(self.calc_amount_var.get() or "0")
            multiplier = float(self.calc_multiplier_var.get() or "0")
            bet_per_spin = float(self.calc_bet_var.get() or "0")
            
            if bet_per_spin <= 0:
                raise ValueError("Bet per spin must be greater than 0")
            
            total_wagering_required = amount * multiplier
            required_spins = int(round(total_wagering_required / bet_per_spin))
            
            self.calc_result_var.set(str(required_spins))
            
            self._log(
                f"Calculation: £{amount} × {multiplier} = £{total_wagering_required:.2f} "
                f"÷ £{bet_per_spin} = {required_spins} spins",
                log_type="SUCCESS"
            )
            
        except ValueError as e:
            self.calc_result_var.set("Error")
            messagebox.showwarning("Calculation Error", f"Invalid input: {e}")
            self._log(f"Calculation error: {e}", log_type="ERROR")
        except Exception as e:
            self.calc_result_var.set("Error")
            self._log(f"Unexpected calculation error: {e}", log_type="ERROR")
    
    def _apply_calculated_target(self):
        """Apply calculated result to autoclicker targets"""
        try:
            result = self.calc_result_var.get()
            if result == "—" or result == "Error":
                messagebox.showwarning("No Result", "Please calculate a target first.")
                return
            
            target = int(result)
            self.auto_target_var.set(target)
            self.manual_target_var.set(target)
            
            self._log(f"Applied calculated target ({target}) to both manual and automatic modes", log_type="SUCCESS")
            
        except ValueError:
            messagebox.showwarning("Invalid Result", "Cannot apply invalid calculation result.")
        except Exception as e:
            self._log(f"Error applying target: {e}", log_type="ERROR")
    
    def _reset_calculator(self):
        """Reset all calculator fields"""
        self.calc_amount_var.set("")
        self.calc_multiplier_var.set("")
        self.calc_bet_var.set("")
        self.calc_result_var.set("—")
        self._log("Calculator reset", log_type="INFO")
    
    # --------------- Logging System ---------------
    
    def _log(self, message: str, log_type: str = "INFO"):
        """Add message to log queue for processing"""
        self._log_queue.put((message, log_type, time.time()))
    
    def _process_log_queue(self):
        """Process pending log messages and display them"""
        try:
            processed_count = 0
            while not self._log_queue.empty() and processed_count < 50:  # Limit processing per cycle
                message, log_type, timestamp = self._log_queue.get_nowait()
                
                # Format message with timestamp if enabled
                if self.config.log_timestamps:
                    formatted_message = f"{get_timestamp()} [{log_type}] {message}\n"
                else:
                    formatted_message = f"[{log_type}] {message}\n"
                
                # Insert into log with appropriate tag
                self.log_text.insert(tk.END, formatted_message, (log_type,))
                self.log_text.see(tk.END)
                
                processed_count += 1
                
        except queue.Empty:
            pass
        except Exception as e:
            # Fallback logging to prevent infinite loops
            print(f"Log processing error: {e}")
        finally:
            # Schedule next processing cycle
            self.after(UI_FLUSH_INTERVAL_MS, self._process_log_queue)
    
    def _clear_log(self):
        """Clear the log display"""
        self.log_text.delete(1.0, tk.END)
        self._log("Log cleared", log_type="INFO")
    
    def _save_log(self):
        """Save log contents to file"""
        try:
            log_content = self.log_text.get(1.0, tk.END)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"spin_helper_log_{timestamp}.txt"
            filepath = os.path.join(os.path.expanduser("~"), filename)
            
            with open(filepath, 'w') as f:
                f.write(f"Spin Helper Log Export\n")
                f.write(f"Generated: {get_timestamp()}\n")
                f.write(f"Version: {APP_VERSION}\n")
                f.write("-" * 50 + "\n\n")
                f.write(log_content)
            
            self._log(f"Log saved to: {filename}", log_type="SUCCESS")
            
        except Exception as e:
            self._log(f"Error saving log: {e}", log_type="ERROR")
            messagebox.showerror("Save Error", f"Could not save log: {e}")
    
    # --------------- Session Management ---------------
    
    def _save_session(self):
        """Save current session state"""
        try:
            session_data = {
                "version": APP_VERSION,
                "timestamp": time.time(),
                "config": {
                    "stay_on_top": self.config.stay_on_top,
                    "log_timestamps": self.config.log_timestamps
                },
                "browser_target": {
                    "selected": self.env_detector.selected_browser is not None,
                    "app_name": self.env_detector.selected_browser.window_info.app_name if self.env_detector.selected_browser else None
                },
                "calculator_state": {
                    "amount": self.calc_amount_var.get(),
                    "multiplier": self.calc_multiplier_var.get(), 
                    "bet": self.calc_bet_var.get(),
                    "result": self.calc_result_var.get()
                },
                "counters": {
                    "manual_target": self.manual_target_var.get(),
                    "manual_count": self.manual_count_var.get(),
                    "auto_target": self.auto_target_var.get()
                }
            }
            
            safe_json_save(SESSION_FILE, session_data)
            return True
            
        except Exception as e:
            self._log(f"Error saving session: {e}", log_type="ERROR")
            return False
    
    def _restore_session(self):
        """Restore previous session state"""
        try:
            session_data = safe_json_load(SESSION_FILE, {})
            
            if not session_data:
                return
            
            # Restore calculator state
            calc_state = session_data.get("calculator_state", {})
            self.calc_amount_var.set(calc_state.get("amount", ""))
            self.calc_multiplier_var.set(calc_state.get("multiplier", ""))
            self.calc_bet_var.set(calc_state.get("bet", ""))
            self.calc_result_var.set(calc_state.get("result", "—"))
            
            # Restore counters
            counters = session_data.get("counters", {})
            self.manual_target_var.set(counters.get("manual_target", 0))
            self.manual_count_var.set(counters.get("manual_count", 0))
            self.auto_target_var.set(counters.get("auto_target", 0))
            
            # Update manual counter display
            if hasattr(self, 'manual_count_label'):
                count = self.manual_count_var.get()
                self.manual_count_label.config(text=f"Completed: {count}")
            
            self._log("Session state restored", log_type="SUCCESS")
            
        except Exception as e:
            self._log(f"Error restoring session: {e}", log_type="WARNING")
    
    # --------------- Application Lifecycle ---------------
    
    def _on_closing(self):
        """Handle application closing"""
        try:
            # Stop any running automation
            if self._automation_running:
                self._stop_event.set()
                # Give threads time to clean up
                time.sleep(0.1)
            
            # Save current state
            self._save_geometry()
            if self.config.auto_save_session:
                self._save_session()
            
            self._log("Spin Helper shutting down", log_type="INFO")
            
        except Exception as e:
            print(f"Error during shutdown: {e}")
        finally:
            self.destroy()

# --------------- Application Entry Point ---------------

def check_dependencies():
    """Check that required dependencies are available"""
    missing = []
    
    if not PIL_AVAILABLE:
        missing.append("Pillow (PIL)")
    
    if not PYAUTOGUI_AVAILABLE:
        missing.append("pyautogui")
    
    if missing:
        print(f"WARNING: Missing dependencies: {', '.join(missing)}")
        print("Some features may not work properly.")
        print("Install with: pip install -r requirements.txt")
    
    return len(missing) == 0

def main():
    """Main application entry point"""
    print(f"Starting {APP_TITLE}")
    print(f"Platform: {sys.platform}")
    
    # Check dependencies
    check_dependencies()
    
    try:
        # Create and run application
        app = SpinHelperApp()
        
        # Restore session after UI is built
        app.after(100, app._restore_session)
        
        # Start main loop
        app.mainloop()
        
    except Exception as e:
        print(f"Fatal error: {e}")
        messagebox.showerror("Fatal Error", f"Application failed to start: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())