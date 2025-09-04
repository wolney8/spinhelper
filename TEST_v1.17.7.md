## Spin Helper v1.17.7 - Test Results and Changes Required


# General:
1. Please ensure the Balance (user entered) value is reflected in the currently visible feature and is applied to the same balance box if Apply Target (withing the Target Calculator) is used. For example, if i'm in Click>Automatic, and i use the calculator, fill in my Balance and click Apply Target, i expect the same 'Balance' field within Automatic to populate based on the value i put in by using the 'Clicker Target Calculator'.
2. Change the colour of the Spin button click phases in the log to orange, for clearer viewing.
3. Change the colour of Pausing/stopping and resetting in the log to bright blue, for clearer viewing.

# Clicker - Automatic:
1. in this test it was working fine and I could see the actuall clicks vs spins completed. But when i moved the mouse to pretend I need to do something else, the app auto-paused, my pointer got pulled away and back to the spin button, causing the app to the 'oh he's back, lets resume'. See Log output.
2. during the above test, i'm also convinced there was a miscount of clicks to spins. My spins completed now reads 33 but actual clicks reads 31.
- can we ensure that the Actual Clicks are a count of when the spin button status is 'ready' and the spin completed is a count of the full cycle of the spin button and only for clicks made on the spin button itself. No other clicks, user generated or grace clicks/rescue clicks, should be counted.
- can we ensure that the Pause mechanic waits until the completion of the current spin, then initiates a hold on the next click so we don't get faux clicks or movement to pull the mouse pointer back to the spin button

Log output:
[2025-09-04 14:43:59] Auto-paused: mouse moved 832px from spinner
[2025-09-04 14:44:00] Rescue click #1
[2025-09-04 14:44:00] Auto-resume: mouse returned to spinner area
[2025-09-04 14:44:03] Auto-paused: mouse moved 646px from spinner
[2025-09-04 14:44:03] Automatic: Click #29/1875 completed in 4689 ms
[2025-09-04 14:44:13] Auto-resume: mouse returned to spinner area
[2025-09-04 14:44:13] Automatic: Executing click #30/1875
[2025-09-04 14:44:13] Pre-click phase: initial_wait
[2025-09-04 14:44:18] Auto-paused: mouse moved 880px from spinner
[2025-09-04 14:44:19] Pre-click phase: overlay_progress (attempt 1)
[2025-09-04 14:44:19] Overlay-progress click (away from spin)
[2025-09-04 14:44:19] Auto-resume: mouse returned to spinner area
[2025-09-04 14:44:24] Grace click after long wait (overlay suspected)
[2025-09-04 14:44:27] Automatic: Click #30/1875 completed in 7926 ms
[2025-09-04 14:44:27] Anti-idle waggle performed
[2025-09-04 14:44:28] Automatic: Executing click #31/1875
[2025-09-04 14:44:28] Pre-click phase: initial_wait
[2025-09-04 14:44:28] Pre-click phase: ready
[2025-09-04 14:44:31] Automatic: Click #31/1875 completed in 3041 ms
[2025-09-04 14:44:32] Automatic: Executing click #32/1875
[2025-09-04 14:44:32] Pre-click phase: initial_wait
[2025-09-04 14:44:32] Pre-click phase: ready
[2025-09-04 14:44:35] Automatic: Click #32/1875 completed in 3127 ms
[2025-09-04 14:44:35] Automatic: Executing click #33/1875
[2025-09-04 14:44:35] Pre-click phase: initial_wait
[2025-09-04 14:44:36] Pre-click phase: ready
[2025-09-04 14:44:41] Grace click after long wait (overlay suspected)
[2025-09-04 14:44:44] Auto-paused: mouse moved 1535px from spinner
[2025-09-04 14:44:45] Automatic: Pause requested - will pause at next ready position
[2025-09-04 14:44:45] Automatic: Click #33/1875 completed in 9308 ms


# Slots (auto):
1. not tested.