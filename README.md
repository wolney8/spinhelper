# Spin Helper (Python)

A minimal, cross-platform autoclicker for casino *wagering* tasks:
- Always-on-top mini UI (Tkinter)
- **Marquee OCR** for balance capture (default) or manual balance entry
- **Spinner button capture** (F9) – binds XY click location and a small watch-area snapshot
- **Pixel-change detection** to count a spin only when the in-game button visually changes **and** returns
- **Global hotkeys**: F8 Start/Pause, F9 Capture Spinner, F10 Stop
- **Movement panic**: big mouse movement auto-pauses and warns
- **CSV logging**: `./spin_logs/YYYY-MM-DD_session.csv` (timestamp, spin #, XY, balance)

> Designed for matched-betting style **wager tracking**, not to “game” the slots. Keep click rates human and respect site rules.

---

## 0) Prerequisites

### Install Python 3.10+  
macOS: from python.org or `brew install python`  
Windows: from python.org

### Install Tesseract (for OCR of your balance)
- **macOS**: `brew install tesseract`
- **Windows**: download “Tesseract-OCR” from UB Mannheim builds and install.  
  If `pytesseract` can’t find it, set the path (e.g.):

```python
# add near the imports in spin_helper.py if needed:
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
