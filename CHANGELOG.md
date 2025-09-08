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

## [1.17.5] — 2025-09-03
Follow-up release addressing v1.17.4 test feedback and UX.

### Added
- Calculator scenarios: support both
  - Bonus + Total Target → Wager × (and Spins if Bet/spin provided)
  - Bonus + Wager × → Total Target (and Spins if Bet/spin provided)
- Millisecond timing logs: Slots and Automatic now log "completed in <ms>" for each spin; Counter logs ms since last click.
- Slots UI visibility: shows Target Spins and Total Wagering near Automation Controls.
- Anti-idle in Slots: shared waggle toggle + settings available and used during Slots automation.

### Changed
- Long-spin grace: both Slots and Automatic wait for READY with a grace window before attempting a rescue, with a single optional grace click if overlays suspected.
- Automatic pre-click readiness: extended timeout and multiple pre-click grace attempts; checks READY after each attempt to detect effect and reduce false timeouts.

### Fixed
- Consistent ms logging across features and shared anti-idle settings across Slots and Clicker.

---

## [1.17.4] — 2025-09-03
Minor update to improve usability and address test feedback.

### Added
- **Focus click after Ready**: A small click 15–25px above the spinner runs once after Ready to bring the browser to front without triggering a spin. Applies to Counter, Automatic, and Slots.
- **Clicker Automatic current wager**: Live “Current Wager” display in Automatic controls (before waggle). Computes clicks_done × bet/spin from the Clicker calculator and resets on Stop/Reset.
- **Calculator scenarios**: Embedded calculators now support two workflows:
  - Scenario 1: Enter Bonus Amount and Total Wager Target to compute Wager × (and Target Spins if Bet/spin is provided).
  - Scenario 2: Enter Bonus Amount and Wager × to compute Total Wager Target (and Target Spins if Bet/spin is provided).

### Fixed
- **Slots run state corrected**: Slots now starts in RUNNING and resets pause flags on Ready, so mouse‑move auto‑pause works immediately and reliably.

### Verified
- Click/spin detection stability improvements validated during testing.

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
## [1.17.6] — 2025-09-03
UI consistency and click telemetry improvements.

### Added
- Actual Clicks counter in Slots and Clicker (Counter and Automatic). Counts all clicks after Ready, including spin, grace, and rescue clicks (or manual clicks in Counter).

### Changed
- Consistent naming: "Spins Completed" replaces "Done" in Clicker (Counter and Automatic) labels.

### Notes
- Version incremented in both script and changelog.
- Actual Clicks guarded: only increments when spinner is captured, a Ready state is active for a feature, and the mouse pointer is within the spinner area (ROI or within proximity). Also respects mouse-move auto-pause.

---
## [1.17.7] — 2025-09-03
Improved overlay handling and pre-click resilience for Slots/Automatic.

### Added
- Pre-click overlay progression: performs up to 3 away-from-spin clicks (with waits and READY rechecks) when the button doesn’t become READY quickly.
- FS animation gating: when a user-selected FS/slots ROI appears active, the app waits for animations/free-spins to complete instead of timing out.
- In-app FS ROI selector: drag-to-select overlay replaces the native macOS screencapture helper; FS ROI is persisted in `~/.spin_helper_geometry.json`.

### Changed
- Slots and Automatic use multi-grace readiness with longer waits before giving up.
- Overlay progression clicks are targeted away from the spin button to avoid accidental spins.
- Minimal pre-click state logging: phases logged as `initial_wait`, `overlay_progress`, `fs_hold`, `ready`, `timeout` for easier diagnosis.

### Notes
- Uses the existing Free-Spins Detection ROI as a generic “slots activity” detector. If not set, logic still functions with best-effort heuristics.
 - Telemetry: logs FS hold duration and overlay attempt count via phase messages.

### Issue & Resolution
- Issue: The new in-app FS ROI selector showed a black overlay on multi-monitor setups and appeared on the wrong display, making selection impractical.
- Resolution: Reverted the UI to use the native macOS screencapture marquee (reliable across monitors). Since it doesn’t provide coordinates, FS/animation gating now falls back to a heuristic ROI derived from the spinner position when an explicit FS ROI isn’t available. This preserves robustness without user friction.

---
## [1.17.8] — 2025-09-03
Guardrails for wager target and balance inputs; minor UI tweaks.

### Added
- Calculator: renamed "Amount (£)" to "Bonus (£)" and added a user-entered "Balance (£)" field plus a "Bonus used before cash" toggle (advisory).
- Clicker Automatic: Balance input under "Current Wager" for quick reference.
- Apply Target now also applies the Balance value from the calculator to the current feature (e.g., Clicker → Automatic Balance box).
- Session save/load: Manual Save/Load buttons store current counters, calculator values, FS detection state, spinner geometry (for reference), and last log lines. Saves to `~/spin_helper_sessions/`. Loads remind to re-capture the spinner baseline and re-select browser.
- Auto-saves: When Slots/Automatic targets/wager goals are reached, the app writes a timestamped autosave in the sessions folder.
 - Session name indicator: Shows current session name (or “No session loaded”) beside Load Session. Defaults to filename when loading.

### Changed
- Automatic: stops when wager target is reached (based on Clicker calculator Total Wager and Bet/spin), in addition to click target.
- Log colors: pre-click phases now orange; pause/stop/reset messages use bright blue for clarity.
- Actual Clicks (Automatic): counts only the primary spin clicks when the button is READY; does not include rescue or away-from-spin overlay clicks.
- Pause behavior: pre-click overlay attempts abort immediately when paused (mouse away or manual pause) to avoid pointer movement until resume.
 - Stop/Reset buttons use a red-with-white-text style for visibility.
 - Target Calculator frames use a blue background (#4a86e8) consistently.
 - Suppress auto-pause during intentional overlay clicks away from spinner to avoid false “Auto-paused” events.
 - Spin readiness: added auxiliary ROI (below spinner) check to better detect “spin in progress” on games with static spin buttons.

### Fixed
- Session save/load: define `SESSIONS_DIR` early and create directory on demand to prevent "name 'SESSIONS_DIR' is not defined" and missing-directory errors during Save/Load.

### Notes
- Balance is user-entered; the app does not read game balances. If you see the in-game cash balance drop to your configured amount, stop playing and withdraw.

---
## [1.17.9] — 2025-09-05
Quality-of-life controls and static-button detection improvements.

### Added
- Overlay handling control: toggle to "Suppress auto-pause during overlay handling" with configurable suppression duration.
- Session name indicator in toolbar.
- Infinite wait toggle: optionally wait indefinitely for READY after a click (Slots/Automatic).
- Auto-save on target toggle (default OFF) in Environment.
- Consistent "Current Wager" readout added to Slots and Counter; updates every second.

### Changed
- Auxiliary ROI captured beneath spinner and used in readiness checks to better detect "spin in progress" on static spin buttons.
- Stop/Reset buttons styled red/white for clarity; calculators use blue background.
- Post-click validation requires true NOT_READY → READY cycle to count a spin (prevents false completions after pause/resume or animations).
- Rescue/grace clicks are performed away from the spinner and never counted.
- Away-from-spin clicks prefer the slots ROI area to avoid large pointer swings.

### Fixed
- Reduced false auto-pauses during intentional overlay clicks by suppressing mouse-based pause for the configured duration.
- Pause semantics: pre-click waits for READY when paused, then yields control without moving the cursor; loops hold until unpaused.
- Indentation hotfix in Slots target auto-save try/except (prevents runtime error when starting the app).
- Automatic first-click stability: overlay clicks no longer target other monitors; clicks occur near the spinner, and topmost is temporarily dropped to ensure the browser receives them.
- Strict post-click validation in Slots/Automatic requires NOT_READY → READY before incrementing spins; prevents false completions.
- Progress preservation: Automatic resumes counting from the previous Done value unless Stop/Reset is used.
- Consistent Current Wager layout and naming across Slots, Counter, and Automatic.

---
## [1.18.0] — 2025-09-06
Stability hotfix and UI consistency from v1.17.9 HOTFIX testing.

### Added
- Status banner heuristic: bottom-center banner ROI considered alongside FS and slots ROIs to bias waits during animations/wins.

### Changed
- Automatic/Slots: Actual Clicks increment only when a NOT_READY state immediately follows the primary click (real spin start).
- Overlay/rescue clicks: localized near spinner; app temporarily drops topmost during the click so the game receives it.
- Environment: "Infinite wait after click" renamed to "Infinite Wait (Manual Mode)".
- Environment: System Information panel hidden (terminal logs remain via dependency checks).
- Slots UI: Target Spins and Total Wagering shown under Automation Controls only reflect applied targets (Calculate no longer updates these until Apply Target is used).
- Current Wager layout/naming consistent across Slots, Counter, and Automatic.
- Actual Clicks semantics: increments only once a real spin begins (NOT_READY observed), so Actual Clicks generally leads Spins Completed by at most one and never lags due to resume.

### Fixed
- Automatic: preserved progress (Done) across Ready after pauses; removed reset scenarios.
- Automatic/Slots: prevented overlay clicks from jumping to other monitors; reduced false completes and miscounts.
- Automatic: preserve Actual Clicks and Done across Ready after pause (no resets unless Stop/Reset is used).

---
## [1.18.1] — 2025-09-07
Hotfix: restore robust counting while flagging short spins

### Changed
- Reverted strict spin-duration gating. Spins are counted once NOT_READY→READY is observed; durations under a heuristic threshold (default 3000 ms) are logged as “short” but not discarded.
- Relaxed READY check in pre-click path: if animations are not active and spinner ROI closely matches baseline (small tolerance), proceed to click.

### Rationale
- Some games legitimately complete spins a bit faster than 3.5s; skipping them caused missed wagering. This hotfix restores dependable counting while retaining visibility on suspiciously fast cycles.

---
## [1.18.2] — 2025-09-07
Stability: click→spin bookkeeping and short-spin retry

### Changed
- Automatic: increments Spins Completed only after a confirmed spin (NOT_READY→READY) and moves the Done increment to post‑confirmation. “No visual change” no longer advances the sequence number.
- Actual Clicks semantics preserved: increments only when NOT_READY follows the primary click.
- Short spins: if a confirmed spin completes in < 2500 ms, it is treated as suspect and retried (not counted). Threshold is `MIN_VALID_SPIN_MS`.

### Notes
- Pre‑click remains the primary gate. Overlay/rescue clicks stay near the spinner and never count towards Actual Clicks.

---
## [1.18.3] — 2025-09-08
Precision: overlay clicks and readiness wait

### Changed
- Grace click target changed to bottom‑center banner area (never on the spin button) to avoid unintended spins during waits.
- Added bottom‑center click helper and used it in the post‑click READY wait path.
- Kept pre‑click gating primary; readiness includes relaxed tolerance when animations inactive to prevent stalls.

### Notes
- Actual Clicks increments only when a real spin begins (NOT_READY observed). Spins Completed increments only after NOT_READY→READY. Short spins < 2500 ms are retried.

---

## [1.18.4] — 2025-09-08
Hotfix: keep grace clicks on the same screen and off the spin button

### Changed
- Replaced post‑click grace action to use a local, near‑spinner offset again (same monitor), never the spin button, to avoid unintended spins and focus changes.

### Notes
- Pre‑click gating and NOT_READY→READY counting logic unchanged; short‑spin retry (< 2500 ms) remains active.

---

## [1.18.5] — 2025-09-08
Hotfix: remove grace clicks to prevent focus loss and unintended spins

### Changed
- Disabled all grace/overlay clicks during pre‑click readiness and post‑click WAIT. The detector now passively waits for READY based solely on visual state (and animation heuristics), preventing any cursor movement that might trigger spins or jump to another monitor.

### Notes
- Primary gate and counting unaffected: Actual Clicks increments on immediate NOT_READY after click; Spins Completed increments on NOT_READY→READY; short spins < 2500 ms retried.

---
## [1.18.6] — 2025-09-08
Hotfix: restore gentle pre‑click overlay progression (same monitor)

### Changed
- Re‑enabled a safe, near‑spinner overlay progression click in the pre‑click path to clear “press anywhere” overlays without touching the spin button. This mirrors the stable 1.18.2 behavior and prevents stalling during pre‑click readiness.

### Notes
- Post‑click waiting remains passive (no grace clicks). Counting continues to require NOT_READY immediately after the primary click, and NOT_READY→READY to increment Spins Completed. Short spins < 2500 ms are retried.

---

## [1.18.7] — 2025-09-08
Hotfix: eliminate click/spin mismatches and restore progress

### Changed
- Automatic/Slots: Actual Clicks now increments together with a confirmed spin (after NOT_READY→READY) to avoid mismatches when completions time out. Primary gate and short‑spin retry remain unchanged.
- Pre‑click: retains safe near‑spinner overlay progression to prevent stalls (same monitor, never spin button).

### Notes
- Counting remains strict: click logs appear, but numbers advance only once a real spin cycle is confirmed. Short spins (< 2500 ms) are retried.

---

### Milestone (v1.18.7)
- Working baseline: Clicker → Automatic ran 75 consecutive clicks without issue (no focus loss), confirming core spin detection flow is stable again.
- Scope: Only working feature validated is Clicker → Automatic; other modes not part of this milestone.
- No click/spin mismatches: Clicks and Spins advance together only after NOT_READY→READY; “no visual change” does not advance.
- Short‑spin policy: spins < 2500 ms are treated as suspect and retried (not counted).
- Overlays: Not fully re‑tested in this milestone; pre‑click overlay progression matches v1.18.2 approach (small, near‑spinner poke on same monitor, never the spin button). Post‑click remains passive.
- Focus: Spinner detection and clicking do not steal focus; no cross‑monitor jumps observed.
- Reference code used to restore behavior: reviewed and ported patterns from `_backup/spin_helper (d9cba47).py` (v1.17.9 baseline) and the previously stable v1.18.2 pre‑click overlay progression.
