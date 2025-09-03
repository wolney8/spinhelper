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
- Autoclicker **Manual / Automatic / Calculator** sub-tabs exist and function.
- **Embedded calculators** in ALL tabs (Slots, Roulette, Autoclicker).
- **Universal spinner capture** from Environment Setup works across all features.
- Real mouse **clicks** occur at captured coordinates with jitter.
- Geometry file `~/.spin_helper_geometry.json` loads/saves without error.

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

### Core Components (v1.16.0)
- **SpinDetector**: Handles ready→not_ready→ready state cycle detection
- **MouseMonitor**: Background mouse position monitoring for auto-pause
- **EmbeddedCalculator**: Universal calculator component with current wager display
- **BrowserDetector**: Cross-browser window detection with proper z-order handling
- **SessionStateSlots**: Central state management with enhanced tracking

### State Machine Logic
```
READY → (click) → NOT_READY → (spin complete) → READY
  ↑                                               ↓
  └── Only count as valid spin if full cycle ──────┘
```

### Critical Dependencies
- **PIL (Pillow)**: Required for all image processing and spinner detection
- **PyAutoGUI**: Required for mouse automation and clicks
- **pynput**: Optional for keyboard shortcuts
- **tkinter**: Standard library GUI framework

### File Structure
```
~/.spin_helper_geometry.json - Window geometry and topmost state
/tmp/spin_helper_roi_selection.png - Temporary FS ROI selection (macOS)
```