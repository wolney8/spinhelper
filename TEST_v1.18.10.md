## Spin Helper v1.18.10 - Test Results and Changes Required


# Clicker - Automatic :
1. 



# Clicker - Counter :
1. Ensure clicks are only counted if done inside the captured spinner area (spinner capture should be a pre-requisit for Automatic and Counter)
2. Use SPIN DETECTION for determining if the user's click actually changed the state of the spin button and if so, +1 spin completed but reduce log information to only show the user if spin detection can see their pointer in the area and if it sees changes.
3. Allow user to add/minus spins manually (use an up and down arrow next to the spins completed) if any are added/removed. Note this in the log.
4. Do not show 'last spin was X ms long'. Just something like 'waiting for next click...'


# General - Saving files :
1. Allow 'saving over' the current loaded file (automatically overwrite)
2. Instead of showing the File / finder then a pop up for a short name; First, ask user for a name of the session, use that name for the filename and save it in the root dir /saved_sessions immediately. The name can be asked in-app (where the name would show) as a field-box.