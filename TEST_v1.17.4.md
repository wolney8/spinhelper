## Spin Helper v1.17.4 - Test Results and Changes Required


# General:
1. Tighten up LOG to show how many miliseconds each spin took (for all features)
2. Click/spin detection is working well we should note this as a success for v1.17.4

# Clicker:
1. No issues currently in Count or Automatic.

# Slots (auto):
12. On rescue clicks - rescue clicks have been observed during longer spins (over 3.5 seconds) and the reason the spin button may not be ready, is likely because there is either an extra slot spinning longer (for anticipation/user engagement to the game) or because winnings have been delivered, either minor (mild animations on screen) or major (lots of animations on screen), and could even be mega/jackpot which would mean the spin button will take longer to be fully ready - so we might need to give a big of grace period and monitor the on-screen animations that might be delaying the spin button being ready. After a long period of waiting, we should probably give it a grace click (if the button is detected as not ready) in case of unseen overlays. I do not think most casino games and their winning animations can be 'rushed', unless the spin button shows ready.
2. Under Automation Controls and under the section 'Spins Completed <X>' - can we add 'Total Wagering <X>' (which is also in the calculator) for better visibility and can we add the total 'Target Spins: <X>' there too which is determined from the calc below.
3. Can we include the Anti-idle functionality and settings into the Slots feature too? Obviously the anti-idle process should only run when the app is running slots or autoclicker.

