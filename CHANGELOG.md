# Changelog — Spin Helper

All notable changes to this project are documented here.

Format follows **Keep a Changelog** and **Semantic Versioning**:
- **Added** for new features
- **Changed** for changes in existing functionality
- **Deprecated** for soon-to-be removed features
- **Removed** for removed features
- **Fixed** for any bug fixes
- **Security** for vulnerabilities

---

## [Unreleased]
### Planned
- Per-game templates (save & recall multiple spinner/ROI profiles).
- Richer readiness quorums (multi-ROI consensus with thresholds).
- Test harness for ROI checks (offline images to simulate states).
- Headless / CLI mode for scripted runs and CI smoke tests.

### Regression Watchlist (must verify before each release)
- Window **Always-on-Top** toggle exists, works, and **persists** across launches.
- **Delayed capture with 3-2-1 countdown** - never capture immediately when button pressed.
- Clicker **Counter / Automatic** sub-tabs exist and function properly.
- **Embedded calculators** in ALL tabs (Slots, Roulette, Clicker).
- **Universal spinner capture** from Environment Setup works across all features.
- Real mouse **clicks** occur at captured coordinates with jitter.
- Geometry file `~/.spin_helper_geometry.json` loads/saves without error.
- **No cross-contamination** between different automation modes.
- **Consistent button behavior** (Ready/Pause/Stop) across all features.

---

## [1.17.4] — 2025-09-03
Minor update to improve usability and address test feedback.

### Added
- **Focus click after Ready**: A small click 15–25px above the spinner runs once after Ready to bring the browser to front without triggering a spin. Applies to Counter, Automatic, and Slots.
- **Clicker Automatic current wager**: Live “Current Wager” display in Automatic controls (before waggle). Computes clicks_done × bet/spin from the Clicker calculator and resets on Stop/Reset.

### Fixed
- **Slots run state corrected**: Slots now starts in RUNNING and resets pause flags on Ready, so mouse‑move auto‑pause works immediately and reliably.

---

## [1.17.3] — 2025-09-03
**CRITICAL HOTFIX** release fixing major functionality issues from v1.17.2.

### FIXED - Critical Functionality Issues
- **Counter mode click detection** - Manual clicks near spinner now properly increment the counter
  - Added `ClickDetector` class using pynput to monitor left mouse clicks within 50px of spinner
  - Counter correctly tracks clicks when in "Ready" state
- **Cross-contamination between modes** - Fixed automatic mode starting when using Counter's Ready button
  - Implemented `_stop_all_modes()` to ensure clean state transitions
  - Added mode tracking flags: `counter_mode_active`, `automatic_mode_active`, `slots_mode_active`
  - Each mode now properly isolates its state from others
- **Mouse positioning** - Fixed issue where mouse didn't move to spinner on Ready/Start
  - Implemented `_position_mouse_with_grace()` helper with actual pyautogui movement
  - Added visual feedback with grace period after positioning
- **Stop/Reset behavior** - Now properly resets counters while preserving calculator values
  - Separate reset functions for each mode maintain calculator state
  - Consistent logging of reset actions

### FIXED - UI Consistency
- **Unified button behavior** across all features:
  - **Ready**: Positions mouse on spinner, applies grace period, then:
    - Counter: Starts click detection for manual counting
    - Automatic: Begins automated clicking with spin detection
    - Slots: Starts automated spinning with full cycle detection
  - **Pause**: Gracefully pauses at next ready position (automation modes only)
  - **Stop/Reset**: Stops all activity and clears counters (preserves calculators)
- **Button state management** - Proper enable/disable logic prevents conflicting actions
- **Renamed "Start Auto Spins"** to "Ready" in Slots for consistency

### Technical Improvements
- **State isolation** - Each mode maintains independent state to prevent interference
- **Grace period implementation** - 1-second pause after mouse positioning for all modes
- **Enhanced logging** - Clear mode prefixes (e.g., "Counter:", "Automatic:", "Slots:")
- **Click detection boundaries** - 50px radius for Counter mode click detection
- **Error handling** - Graceful fallbacks when pynput unavailable


### Breaking Changes
- None - all existing functionality preserved with bug fixes only

### Upgrade Notes
1. **Counter mode** now requires pynput for click detection (optional dependency)
2. **Consistent workflow**: All modes use Ready → Pause → Stop/Reset pattern
3. **Calculator preservation**: Stop/Reset no longer clears calculator values

---

## [1.17.2] — 2025-09-03
**HOTFIX** release removing problematic focus handling that interfered with manual operations.

### REMOVED - Focus Handling
- **Focus monitoring completely removed** - Was causing automation to pause when users moved mouse to click after "Ready" button
- **FocusMonitor class removed** - Eliminated all focus detection and related pause logic
- **Auto-pause on focus loss removed** - No longer interferes with normal clicking workflow

### FIXED - Mouse Movement Behavior  
- **Mouse movement pause** now only affects active automation, not manual positioning
- **Counter mode workflow** - "Ready" button positioning no longer triggers unwanted pauses
- **Manual clicking** - Users can freely move mouse for manual operations without interference

### Technical Changes
- Removed `FocusMonitor` class and all focus detection logic
- Simplified pause state management to mouse movement only during automation
- Updated system info to clarify mouse movement behavior
- Maintained all robust spin detection from v1.17.1

### Upgrade Notes
1. **Manual operations** - Mouse positioning for manual clicks no longer causes pauses
2. **Automation pause** - Only mouse movement during active automation triggers pause
3. **Focus behavior** - App no longer monitors or reacts to window focus changes

---

## [1.17.1] — 2025-09-03
**HOTFIX** release addressing critical spin detection and UX issues from test feedback.

### FIXED - Critical Regression Prevention
- **Robust spin detection** - Integrated working patterns from August code to eliminate stuck "waiting for spin" states:
  - `_ensure_ready_before_click()` with proper grace clicks that don't count toward totals
  - `_rescue_once_then_wait_ready()` for single rescue attempts
  - `_wait_change_sticky()` for proper state transition detection
  - Blip detection ignores invalid short spins (<2000ms)
- **UI visibility** - Changed dark blue text to **white** for readability on grey backgrounds:
  - Spin counters, current wager displays, click counters now use white text
- **Focus-based automation** - App pauses when losing focus, requires manual resume

### FIXED - Naming and Behavior Alignment
- **Autoclicker → Clicker** - Renamed tab and updated functionality
- **Manual → Counter** - Sub-tab renamed with proper manual-only behavior:
  - "Single Click" → "Ready" button (positions mouse only, user must click)
  - No automatic clicking in Counter mode
  - User input required for all actions
- **Consistent logging** - Unified log output format across all features

### Added - Enhanced UX Features
- **Auto stay-on-top toggle** - Automatically disables during browser/FS selection, restores after
- **Comprehensive pause system** - Pause buttons added to:
  - Slots automation controls
  - Clicker Counter mode  
  - Clicker Automatic mode
- **Focus monitoring** - `FocusMonitor` class detects app focus loss and pauses automation
- **Enhanced error handling** - Better detection of stuck states with recovery mechanisms

### Technical Improvements
- Integrated proven spin detection algorithms from working August 2025 codebase
- Enhanced state machine with proper ready→not_ready→ready cycle validation
- Improved mouse movement pause detection with graceful resume
- Better error logging with color coding (white=info, green=success, red=error)

### Breaking Changes
- Counter mode behavior changed: no automatic clicking, user must manually click after "Ready"
- Focus loss now pauses automation (requires manual resume)

### Upgrade Notes
1. **Counter Mode**: Use "Ready" to position mouse, then manually click. No automation in this mode.
2. **Focus Handling**: Automation pauses if app loses focus - resume manually when ready.
3. **Stay-on-Top**: Automatically toggles during dialogs for better UX.

---

## [1.16.0] — 2025-09-03
**Major enhancement** release addressing core spin detection, target logic, and user experience issues.

### FIXED - Critical Regression Prevention
- **Delayed spinner capture** - Restored proper 3-2-1 countdown before capture (never immediate).
- **Embedded calculators** - Restored calculators in ALL tabs (Slots, Roulette, Autoclicker).
- **Autoclicker functionality** - Fixed Manual/Automatic sub-tabs with proper state management.
- **Universal spinner detection** - Centralized capture works across all features.

### Added - Core Enhancements
- **Proper spin state machine** - Full ready→not_ready→ready cycle detection to ignore "hey click me" animations.
- **Mouse movement pause detection** - Auto-pause when mouse moves >80px from spinner, seamless resume.
- **Target stopping logic** - Stops at target spins OR target wager amount (whichever comes first).
- **Current wager display** - Live calculation shows spins × bet/spin in calculator.
- **Pause button** - Manual pause/resume in automation controls.
- **Enhanced Environment Setup** - Universal spinner capture with thumbnail preview.
- **Spin counter display** - Real-time spin progress in Slots tab.

### Added - Technical Improvements
- `SpinDetector` class for robust state cycle tracking.
- `MouseMonitor` class for seamless pause/resume functionality.
- `SpinState` enum for proper state management.
- Enhanced error handling and logging with color coding.
- Improved UI responsiveness and status updates.

### Changed - User Experience
- **Environment Setup tab** now handles universal spinner capture for all features.
- Slots automation shows "Resume Auto Spins" when paused by mouse movement.
- Calculator displays current wager in real-time (blue text).
- Reset button clears both counters AND calculations.
- Enhanced logging with color coding (green=success, blue=info).

### Technical Details
- Spin detection ignores animations by requiring actual state transitions.
- Mouse monitoring runs in background thread with configurable thresholds.
- Target checking evaluates both spin count and wager amount limits.
- Universal spinner capture eliminates feature duplication.
- Enhanced state persistence across pause/resume cycles.

### Upgrade Notes
1. **Environment Setup** - Use this tab for universal spinner capture instead of individual feature captures.
2. **Calculator integration** - Current wager updates automatically as spins progress.
3. **Mouse movement** - Natural mouse movement triggers auto-pause for safety.
4. **Target logic** - Automation stops when EITHER target spins OR target wager is reached.

### Breaking Changes
- None - all existing functionality preserved and enhanced.

---

## [1.14.1] — 2025-09-02
**Hotfix** release to undo regressions introduced in 1.14.0 and restore expected behaviour.

### Fixed
- Restored **Always-on-Top** behaviour (regression in 1.14.0).
  - Implemented **toolbar toggle** and ensured it's applied early at startup.
  - Ensured **persistence** via geometry file.
- Re-enabled **real clicking** (1.14.0 had a stub).
  - `_do_click()` now uses `pyautogui` with 1px jitter and short movement duration to reduce misfires.
- Restored **calculator navigation**:
  - Added **"Target Calculator…"** buttons to **Slots** and **Roulette** that jump to **Autoclicker → Calculator** (embedded), not a popup.

### Added
- **Toolbar** row in the left pane with **"Stay on top"** checkbox.
- Calculator navigation helper `_goto_ac_calc()` and reference to `self.ac_tab_calc` for reliable switching.
- Gentle logs for navigation (e.g., "Opened Autoclicker → Calculator.").

### Changed
- Persisted **topmost** state alongside window geometry in `~/.spin_helper_geometry.json`.
  - **Schema note:** File now includes:  
    ```json
    {"geom": "WIDTHxHEIGHT+X+Y", "topmost": true}
    ```
- Minor UI polish: ensured scroll region updates and initial sash positioning are resilient.

### Upgrade Notes
1. Ensure dependencies are installed:
   ```bash
   pip install -r requirements.txt
   # or at least:
   pip install pyautogui Pillow
   ```

## Architecture Notes

### Core Components (v1.17.3)
- **SpinDetector**: Handles ready→not_ready→ready state cycle detection with rescue logic
- **MouseMonitor**: Background mouse position monitoring for auto-pause (automation only)
- **ClickDetector**: Manual click detection for Counter mode using pynput
- **EmbeddedCalculator**: Universal calculator component with current wager display
- **BrowserDetector**: Cross-browser window detection with proper z-order handling
- **SessionStateSlots**: Central state management with enhanced tracking
- **AutomationState**: Unified state tracking for all automation modes

### State Machine Logic
```
READY → (click) → NOT_READY → (spin complete) → READY
  ↑                                               ↓
  └── Only count as valid spin if full cycle ─────┘
```

### Mode Isolation (v1.17.3)
- Each mode (`counter_mode_active`, `automatic_mode_active`, `slots_mode_active`) maintains independent state
- `_stop_all_modes()` ensures clean transitions between modes
- No cross-contamination of automation states

### Critical Dependencies
- **PIL (Pillow)**: Required for all image processing and spinner detection
- **PyAutoGUI**: Required for mouse automation and clicks
- **pynput**: Optional for Counter mode click detection
- **tkinter**: Standard library GUI framework

### File Structure
```
~/.spin_helper_geometry.json - Window geometry and topmost state
/tmp/spin_helper_roi_selection.png - Temporary FS ROI selection (macOS)
```
