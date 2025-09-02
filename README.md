# Spin Helper

Desktop assistant for low-friction casino wagering workflows. It automates repeatable **spin clicks**, basic **readiness checks**, and includes an embedded **Target Calculator** housed inside the Autoclicker tab. It does **not** place bets or decide strategy; it only clicks where you tell it to.

> **Current version:** v1.14.1 (hotfix)

## What it does

- **Slots (auto)**
  - Capture **spin button** location.
  - Define a small **readiness ROI** for detecting when the game is ready for the next click.
  - Optional detection of **Free-Spins banners** to pause and resume correctly.
  - **Anti-idle waggle** (gentle mouse jiggle) to avoid timeouts.
  - Structured logging: “Clicking #N…”, “Ready confirmed.”, etc.

- **Roulette (manual)**
  - Manual capture helpers and logging to support non-automated flows.

- **Autoclicker**
  - Notebook with **Manual / Automatic / Calculator** sub-tabs.
  - **Manual:** one-shot clicks, optional target count.
  - **Automatic:** looping clicker with target count, readiness waits, gentle rescue/poke clicks, optional anti-idle waggle.
  - **Calculator (embedded):** quick computation of targets (e.g., spins = total_to_wager / per-spin amount) and **“Apply to Target”**.

- **Navigation helpers**
  - **“Target Calculator…”** buttons in **Slots** and **Roulette** jump directly to **Autoclicker → Calculator** (no pop-ups).

- **Window behaviour**
  - **Stay on top** toggle in the header toolbar, persists across launches.
  - Window geometry + “stay on top” stored in `~/.spin_helper_geometry.json`.

## Goals and non-goals

- **Goals**
  - Keep UI simple and deterministic.
  - Embed the calculator (no separate dialogs).
  - Provide clear logs suitable for later scripting/integration.

- **Non-goals / Safety**
  - The app **does not** choose bets, scrape odds, or bypass game rules.
  - All stake selection, offer mechanics, and bankroll choices remain with the user.

## Dependencies

- **Python:** 3.9+
- **GUI:** `tkinter` (stdlib)
- **Imaging:** `Pillow`
- **Desktop automation:** `pyautogui` (for real clicks / mouse moves)
  - **macOS:** grant **Accessibility** permissions to your Terminal/IDE:
    - System Settings → Privacy & Security → Accessibility → enable for Terminal/VSCode.

Install:

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
