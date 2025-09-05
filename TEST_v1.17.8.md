## Spin Helper v1.17.8 - Test Results and Changes Required


# General:
1. Need 'name' of the session to show next to 'load session', either 'no session loaded' or a given name to the session (default to filename if nothing in the json found).
2. Change button colour of all Stop/Reset buttons to read with white text.
3. Change background colour of 'X Target Calculator' universally to blue "#4a86e8".


# Clicker - Automatic:
1. Mouse move/overlay detection failure: See below the log from the app, I do not believe an overlay was actually on screen and the mouse was NOT moved. It may have been a large win or delay in the spinner being ready. We need to be waiting and checking the spinner repeatedly, and if we are in Slots, we can check overlays too, but in Automatic, we just want to be; 
- doing grace clicks away from the spinner, while it's 'not ready' but do not count clicks.
- then waiting by looking at the spinner for ready, if ready, good, continue.
- if not ready, continue waiting, and clicking gracefully to 'hurry' overlays, then check again.
- ensure the mouse is not moved unless doing grace clicks or moving back to the spinner on ready/restart or unless the user interacts and full 'shakes' the mouse to signify a break or pause is needed.

Log output
[2025-09-05 11:55:17] Pre-click phase: initial_wait
[2025-09-05 11:55:23] Pre-click phase: overlay_progress (attempt 1)
[2025-09-05 11:55:23] Auto-paused: mouse moved 1231px from spinner
[2025-09-05 11:55:23] Overlay-progress click (away from spin)
[2025-09-05 11:55:23] Automatic: Click #64 - timeout waiting READY
[2025-09-05 11:55:23] Automatic clicker stopped

# Clicker - Counter:
1. Add 'current wager x' to Counter, just like we have it in Automatic.

# Slots (auto):
1. Can we modify the detection process to allow for this scenario;
- some slots have a static spin button (see first image) but below it is the 'settings' button, when the spin is active, this button disapears (see second image) and returns when the spin button is 'ready'. Would our spin detection be able to identify this if the mouse was placed at the bottom edge of the spin button circle? (biggest circle in first image).
2. Failed overlay / free spin detection: see log below, the overlay was 'suspected' but not detected at "12:02:56", after a long delay a rescue click cleared the overlay and the free spins continued automatically while the spin button was 'not_ready' (i could see it not in a ready state) unfortunately, a completion timeout occured at "12:03:30" which then made the app try spin 27 again, this then, for some reason, moved the mouse which caused the app to pause. This is incorrect behaviour we need to ensure;
- if a long delay is suspected, to initiate some function to detect if there is an overlay, if so, grace click away from the spinner.
- if not, check if slots are still moving or for 'win animations', if so, check spin button for 'not_ready' if its not ready, wait for spin button to be 'ready'. 
- During this period, perform a few grace clicks away from spinner, NEVER on the spin button, to see if an overlay can be hurried. ONLY continue when the spin button is detected to be ready again (usually when the last overlay is visible) when it is ready, grace click away (don't count it) then prepare for the next spin as we would if we clicked 'Ready' in the app.
- Avoid timeouts as much as possible (unless we've exceeded 5-10 minutes of no activity from; 1. the spin button readiness, 2. the slots/animations and 3. any overlays and our 'hurry' or 'grace click' process have returned no encoruaging changes.)
- I have attached a third image which is the spin button in its other 'not ready' state (red square). The initial 'not ready' state is simple grey/clear image without the arrows (directing the movement of the spin) for information.


[2025-09-05 12:02:56] Grace click after long wait (overlay suspected)
[2025-09-05 12:03:17] Rescue click #1
[2025-09-05 12:03:30] Slots: Spin #27 - completion timeout
[2025-09-05 12:03:30] Slots: Executing spin #27
[2025-09-05 12:03:30] Pre-click phase: initial_wait
[2025-09-05 12:03:36] Pre-click phase: overlay_progress (attempt 1)
[2025-09-05 12:03:36] Auto-paused: mouse moved 1231px from spinner
[2025-09-05 12:03:36] Overlay-progress click (away from spin)
[2025-09-05 12:03:36] Slots: Spin #27 - timeout waiting READY
[2025-09-05 12:03:36] Slots automation stopped
