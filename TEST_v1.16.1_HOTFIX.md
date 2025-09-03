## Spin Helper v1.16.1 HOTFIX

# Slots (auto) - Issues/fixes and suggestions:
1. Spin capture is still unreliable, see Log output below. I firstly had to do the initial click myself as 'Executing spin #1' did not actually happen, before it detected the spin movement, so the app was stuck in a waiting state. There was no grace click during this period (it should gracefully click to see if the spinner moves or moves back, every so often and ONLY count the successful spin if a click has caused it to go from READ -> NOT_READY and back to READY)

[2025-09-03 10:07:19] Executing spin #1
[2025-09-03 10:07:20] Waiting for spin to start (READY→NOT_READY)...
[2025-09-03 10:07:20] Auto-resume: mouse returned to spinner area
[2025-09-03 10:07:36] Spin transition detected (NOT_READY)
[2025-09-03 10:07:36] Waiting for spin completion (NOT_READY→READY)...
[2025-09-03 10:07:39] Spin cycle complete (READY detected)
[2025-09-03 10:07:39] Spin #1 completed successfully
[2025-09-03 10:07:39] Executing spin #2
[2025-09-03 10:07:40] Waiting for initial READY state...
[2025-09-03 10:07:43] Waiting for spin to start (READY→NOT_READY)...
[2025-09-03 10:07:55] Spin transition detected (NOT_READY)
[2025-09-03 10:07:55] Waiting for spin completion (NOT_READY→READY)...
[2025-09-03 10:07:58] Spin cycle complete (READY detected)
[2025-09-03 10:07:58] Spin #2 completed successfully
[2025-09-03 10:07:58] Executing spin #3
[2025-09-03 10:07:59] Waiting for initial READY state...
[2025-09-03 10:08:01] Waiting for spin to start (READY→NOT_READY)...
[2025-09-03 10:08:06] Auto-paused: mouse moved 331px from spinner

2. Current wager and spins completed is in a dark blue (in all parts of the app) which cannot be seen on a grey background, make this text inside the app white.

# Autoclicker - Issues/fixes and suggestions:
1. the auto clicker needs to be renamed "Clicker" and keep two sub sections, Manual (rename to Counter) and Automatic.
2. Within Automatic and Manual (after rename: "Counter"), the same issues that fail to detect full spins are present as in Slots and the outputs in the log are not consistent across all functionality as they need to be.
3. Manual (after rename: "Counter"), needs to explicitly be manual, NO AUTOMATIC CLICKING SHOULD OCCUR HERE, USER INPUT IS REQUIRED. The point of the Counter within Clicker is simply to count how many clicks the user has done, on the button, until paused or until the max is reached. It does not need spin detection for readiness, it only needs to know where to place the mouse 'Single Click' should not auto click, it should be renamed 'Ready' and the mouse should be placed on the spinner, then the user should be instructed to click (in the log). 
4. The Automatic part needs to be designed for the exact same logic, only it uses the spin detection to determine when to click automatically agian (like in Slots) and must Pause on mouse movement and be able to be Resumed gracefully too.
5. If movement is detected, like in Slots, it should Pause gracefully. A pause button needs to be added next to Rest (in Manual, or "Counter") and next to Stop (in Automatic)

# General:
1. Please ensure the app only uses detection in clicks and spin button when in focus if the App is not in focus it should be Paused and must be Resumed. 
2. If the user clicks 'Select Browser Window' or 'Select FS Area (Native)' please automatically toggle off 'Stay on top', then initiate the clicked command. This will improve user flow.