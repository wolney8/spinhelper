## Spin Helper v1.17.1 

# Slots (auto) - Issues/fixes and suggestions:
1. Unable to test due to Mouse focus issue


# General:
1. The pausing due to focus is causign the app to pause when the mouse is moved to its ready possition. We need to remove this feature altogether. 

Here's what happened:
``
<user clicked Ready button>
[2025-09-03 10:39:13] Mouse positioned at spinner - YOU must click manually
[2025-09-03 10:39:16] App lost focus - automation paused
<user tried to click>
<user saw the app did not register any clicks>
<user moves over and into the App>
[2025-09-03 10:39:30] App regained focus - ready for manual resume
``