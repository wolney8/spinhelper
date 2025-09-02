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
- Autoclicker **Manual / Automatic / Calculator** sub-tabs exist and function.
- **“Target Calculator…”** buttons on **Slots** and **Roulette** jump to **Autoclicker → Calculator**.
- Real mouse **clicks** occur at captured coordinates (no stubs).
- Geometry file `~/.spin_helper_geometry.json` loads/saves without error.

---

## [1.14.1] — 2025-09-02
**Hotfix** release to undo regressions introduced in 1.14.0 and restore expected behaviour.

### Fixed
- Restored **Always-on-Top** behaviour (regression in 1.14.0).
  - Implemented **toolbar toggle** and ensured it’s applied early at startup.
  - Ensured **persistence** via geometry file.
- Re-enabled **real clicking** (1.14.0 had a stub).
  - `_do_click()` now uses `pyautogui` with 1px jitter and short movement duration to reduce misfires.
- Restored **calculator navigation**:
  - Added **“Target Calculator…”** buttons to **Slots** and **Roulette** that jump to **Autoclicker → Calculator** (embedded), not a popup.

### Added
- **Toolbar** row in the left pane with **“Stay on top”** checkbox.
- Calculator navigation helper `_goto_ac_calc()` and reference to `self.ac_tab_calc` for reliable switching.
- Gentle logs for navigation (e.g., “Opened Autoclicker → Calculator.”).

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
