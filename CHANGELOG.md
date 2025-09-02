# Changelog — Spin Helper

All notable changes to this project are documented here.

Format follows **Keep a Changelog** and **Semantic Versioning**:
- **Added** for new features
- **Changed** for changes in existing functionality
- **Fixed** for any bug fixes
- **Removed** for removed features
- **Security** for vulnerabilities

---

## [Unreleased]
### Planned
- Per-game templates (save & recall multiple spinner/ROI profiles)
- Enhanced readiness detection with machine learning
- Richer anti-idle patterns
- Advanced free-spins detection
- Comprehensive test suite

---

## [2.1.0] — 2025-09-02
**Phase 3 implementation** adding enhanced automation features and keyboard shortcuts.

### Added
- **Global keyboard shortcuts** using pynput integration
  - Space bar increments manual spin counter from anywhere
  - Works even when app doesn't have focus
- **Manual spin counter** with keyboard and button controls
  - Large, bold counter display for easy monitoring
  - Session persistence across app restarts
  - Target comparison alerts
- **Enhanced visual detection** for game state monitoring
  - Screen change detection with configurable thresholds
  - Free-spins banner monitoring with pause/resume logic
  - Multi-monitor display binding support
- **Advanced slots automation** 
  - Free-spins automatic detection and handling
  - Enhanced anti-idle waggle timing
  - Randomized delays between spins (0.2-0.5s)
  - Improved rescue click logic
- **Better error handling** and dependency management
  - Graceful degradation when optional libraries missing
  - Enhanced permission checking for macOS
  - Proper keyboard listener cleanup on shutdown

### Changed
- **Version increment**: 2.0.0 → 2.1.0 for Phase 3 features
- **Slots automation**: Enhanced with free-spins handling and natural timing
- **Session management**: Now includes manual spin counter state
- **Dependency checking**: More detailed feedback about missing components
- **Logging detail**: Additional context for debugging and monitoring

### Fixed
- **Keyboard listener cleanup**: Proper shutdown prevents resource leaks
- **Thread management**: Enhanced cleanup for all automation threads
- **Session persistence**: Manual spin counter now saved and restored
- **Error recovery**: Better handling of image processing failures

### Technical Improvements
- **Natural automation**: Randomized timing prevents pattern detection
- **Resource management**: Proper cleanup of all background processes
- **Permission handling**: Better feedback for macOS accessibility requirements
- **Multi-threaded safety**: Enhanced synchronization between automation modes

### Testing
- ✅ Keyboard shortcuts work globally (Space bar increments counter)
- ✅ Free-spins detection pauses automation appropriately
- ✅ Enhanced visual detection identifies game state changes
- ✅ Natural timing variations in automation
- ✅ Proper cleanup on application shutdown
- ✅ Session persistence includes all new features

---

## [2.0.0] — 2025-09-02
**Complete ground-up rewrite** implementing Phase 1 foundational framework and Phase 2 core functionality.

### Added
- **Complete ground-up rewrite** following project plan architecture
- **Real macOS browser detection** using AppleScript integration
  - Detects Chrome, Safari, Firefox, and Edge windows
  - Shows actual browser tab titles
  - Graceful fallback to manual selection modes
- **Enhanced spinner capture system** from proven older code
  - 40x40 pixel ROI capture with baseline image storage
  - Multi-method readiness detection (RMS, brightness, color distance)
  - Visual feedback for capture status
- **Automated slots functionality** (Phase 2/3)
  - Real clicking with pyautogui and 1px jitter
  - Smart readiness waiting with rescue clicks
  - Timeout handling and error recovery
- **Free-spins detection framework**
  - Two-stage ROI capture process
  - Toggle for enable/disable detection
- **Complete autoclicker system**
  - Manual mode: Single-click with target tracking
  - Automatic mode: Continuous clicking with progress tracking
  - Anti-idle waggle with configurable interval and amplitude
- **Embedded target calculator**
  - Wagering requirement calculations
  - Apply calculated targets to both manual and automatic modes
  - Session persistence for calculator values
- **Comprehensive logging system**
  - Color-coded log entries by type (INFO/SUCCESS/WARNING/ERROR/ACTION)
  - Real-time queue-based processing
  - Log export functionality
- **Session management**
  - Persistent window geometry and settings
  - Calculator state preservation
  - Counter values restoration
  - Auto-restore on application restart

### Fixed
- **CRITICAL: Browser selection dialog z-order issue**
  - Dialog now properly appears above "stay on top" main window
  - Added `dialog.attributes("-topmost", True)` and `dialog.focus_force()`
  - Prevents dialog from being hidden behind main window
- **Browser detection using real system integration** instead of mock data
  - AppleScript queries actual browser windows
  - Handles permission requirements and timeouts
  - Provides meaningful fallbacks when detection fails
- **Proper threading cleanup** on application shutdown
  - All automation threads properly stopped
  - Graceful error handling during shutdown
- **Enhanced error handling** throughout application
  - Missing dependency graceful fallbacks
  - Image processing error recovery
  - File operation safety with try-catch blocks

### Changed
- **Version number**: Incremented to 2.0.0 for major rewrite
- **UI Architecture**: Complete redesign following project plan
  - Clean two-panel layout (controls left, log right)
  - Scrollable left panel for large control sets
  - Dedicated log area with syntax highlighting
- **Navigation system**: Tab-based organization
  - Environment Setup (Phase 1)
  - Slots (auto) with full functionality (Phase 2)
  - Autoclicker with Manual/Automatic/Calculator sub-tabs
- **Configuration management**: JSON-based persistence
  - Window geometry saved to `~/.spin_helper_geometry.json`
  - Session state saved to `~/.spin_helper_session.json`
- **Readiness detection**: Enhanced from proven algorithms
  - Multiple detection methods with configurable thresholds
  - RMS difference: 7.5, Brightness tolerance: 14%, Color distance: 18.0

### Technical Details
- **Dependencies**: Enhanced error handling for missing PIL/pyautogui
- **macOS Integration**: Native AppleScript browser detection with timeout protection
- **Image Processing**: Proven readiness detection algorithms from working codebase
- **Threading**: Proper daemon threads with stop events and cleanup
- **Error Recovery**: Comprehensive exception handling with user feedback
- **Natural automation**: Random jitter and timing variations in clicking

### Testing Results
- ✅ Application launches without errors on macOS
- ✅ Browser window selection works with real Chrome detection
- ✅ Stay-on-top toggle functions and persists across sessions
- ✅ Dialog z-order issue completely resolved
- ✅ Spinner capture stores baseline images correctly
- ✅ Calculator performs wagering calculations accurately
- ✅ Manual autoclicker executes real clicks with readiness waiting
- ✅ Automatic autoclicker runs with progress tracking
- ✅ Real-time logging displays with color coding
- ✅ Session persistence works for all settings and values

### Migration Notes
This is a complete rewrite. Previous configuration files are incompatible.
- Remove old geometry files if experiencing issues
- All previous automation logic has been rewritten with improvements
- Enhanced error handling prevents crashes on missing dependencies

### Development Notes
- **Project Plan Compliance**: Fully implements Phase 1 and Phase 2 objectives
- **Code Quality**: Comprehensive type hints, docstrings, and error handling
- **Modularity**: Clean separation of concerns for iterative development
- **Mac Optimization**: Native macOS features and styling

---

## [1.14.2] — 2025-09-02 (Legacy - Pre-Rewrite)
**Final version of legacy codebase** with critical fixes before ground-up rewrite.

### Fixed
- Added missing `_ac_reset_target` method
- Corrected `_color_dist` blue-channel calculation bug
- Bound Free-Spins checkbox to application state

### Issues Leading to Rewrite
- Browser detection used mock data instead of real detection
- Dialog z-order problems with stay-on-top functionality
- Inconsistent UI architecture
- Limited error handling and recovery

---

## Development Process Notes

### Known Issues Resolved
1. **Browser Detection**: Mock detection replaced with real AppleScript integration
2. **Dialog Z-Order**: Stay-on-top compatibility fixed
3. **Missing Methods**: Complete method implementation
4. **Thread Management**: Proper cleanup and error handling
5. **UI Consistency**: Following project plan architecture

### Testing Environment
- **Platform**: macOS (Darwin)
- **Python**: 3.13.7
- **IDE**: VSCode with MatchedBetting virtual environment
- **Browser**: Chrome with multiple casino tabs
- **Dependencies**: PIL, pyautogui, tkinter

### Quality Assurance
- All UI components have proper error handling
- Threading uses daemon threads with stop events
- File operations use safe JSON helpers
- Image processing has PIL availability checks
- AppleScript calls have timeout protection