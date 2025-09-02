# Spin Helper v2.0.0

Desktop assistant for low-friction casino wagering workflows. Automates repeatable **spin clicks**, provides **readiness detection**, and includes an embedded **Target Calculator**. Built natively for **macOS** following Google UX/UI design principles.

> **Current version:** v2.0.0 - Complete rewrite with proven automation and real browser detection

## ✨ What's New in v2.0.0

### 🔧 **FIXED: Dialog Z-Order Issue**
- **Browser selection now works properly** even with "stay on top" enabled
- **Real browser detection** shows your actual Chrome/Safari/Firefox tabs
- **AppleScript integration** for native macOS window detection

### 🎰 **Complete Slots Automation** 
- **Smart spinner capture**: 40x40px ROI with proven readiness detection
- **Multi-method detection**: RMS difference, brightness, and color distance algorithms
- **Real clicking**: PyAutoGUI integration with 1px jitter for natural movement
- **Rescue logic**: Gentle pokes and rescue clicks for stuck spins
- **Anti-idle waggle**: Configurable mouse movement to prevent timeouts

### 📊 **Full-Featured Calculator**
- **Embedded design**: No pop-ups, integrated into Autoclicker tab
- **Complete calculations**: Bonus × Multiple ÷ Bet per spin = Required spins
- **Auto-apply targets**: Sets both manual and automatic click targets
- **Session persistence**: All values saved and restored automatically

## 🚀 Core Features

### **Real Browser Detection**
- **Environment Setup**: Guided browser window selection with AppleScript
- **Live detection**: Shows actual casino game tab titles
- **Multiple browsers**: Chrome, Safari, Firefox, Edge support
- **Manual fallbacks**: Options when auto-detection fails

### **Proven Automation**
- **Capture spin button**: Smart ROI capture with visual feedback  
- **Readiness detection**: Multi-method algorithms detect when game is ready
- **Natural clicking**: Random jitter and timing variations
- **Comprehensive logging**: Every action tracked with color-coded entries

### **Dual Autoclicker Modes**
- **Manual mode**: Single-click testing with target tracking
- **Automatic mode**: Continuous clicking with progress display
- **Target management**: Set goals and track completion
- **Stop/start controls**: Full user control over automation

### **Advanced Features**
- **Free-spins detection**: Optional banner detection with custom ROI
- **Anti-idle waggle**: Gentle mouse movement to prevent timeouts  
- **Session management**: Window geometry, settings, and progress saved
- **Stay-on-top**: Window remains visible above other applications

## 📋 Quick Start Guide

### **1. Installation**
```bash
# Ensure you have Python 3.9+
python --version

# Install dependencies  
pip install pyautogui pillow

# Download and run
python spin_helper.py
```

### **2. Basic Setup**
1. **Open your casino game** in Chrome, Safari, or Firefox
2. **Launch Spin Helper** - should show v2.0.0 in title
3. **Environment Setup tab** → "Select Browser Window"
4. **Choose your casino tab** from the detected list

### **3. Capture Spin Button** 
1. **Slots (auto) tab** → position mouse over spin button
2. **Click "Capture Spin Button"** → should show "✓ Captured at (x,y)"
3. **Optional**: Capture Free-Spins ROI for advanced detection

### **4. Set Target (Calculator)**
1. **Autoclicker tab** → **Calculator sub-tab**
2. **Enter**: Bonus £50, Wagering 35x, Bet £0.20
3. **Click "Calculate"** → shows 8,750 spins required
4. **Click "Apply to Targets"** → sets autoclicker goals

### **5. Start Automation**
- **Manual mode**: Single clicks for testing
- **Automatic mode**: Continuous until target reached
- **Slots auto**: Smart automation with readiness detection

## 🔧 Technical Details

### **Readiness Detection Thresholds**
- **RMS Difference**: ≤ 7.5 (pixel difference from baseline)
- **Brightness Tolerance**: ≤ 14% darker than baseline
- **Color Distance**: ≤ 18.0 RGB distance from baseline

### **Automation Safety**
- **1px jitter**: Random movement for natural clicking
- **Rescue clicks**: Additional clicks if game appears stuck
- **Timeout handling**: 40-second maximum wait per spin
- **Stop controls**: Immediate halt capability

### **Session Persistence**
- **Window state**: Size, position, stay-on-top preference
- **Calculator values**: Bonus, wagering, bet amounts preserved
- **Progress tracking**: Manual/automatic counters saved
- **Settings**: All preferences restored on restart

## ⚠️ System Requirements

### **macOS Permissions**
- **Accessibility permission required** for PyAutoGUI
- **System Preferences** → **Privacy & Security** → **Accessibility**  
- **Enable for Terminal** (or VSCode if running from IDE)

### **Dependencies**
```bash
# Required for automation
pip install pyautogui>=0.9.54

# Required for image processing  
pip install pillow>=10.3.0

# All dependencies
pip install -r requirements.txt
```

### **Browser Support**
- ✅ **Google Chrome** (recommended)
- ✅ **Safari** 
- ✅ **Firefox**
- ✅ **Microsoft Edge**

## 🐛 Troubleshooting

### **Browser Detection Issues**
- **Grant Accessibility permissions** to Terminal/VSCode
- **Restart browser** if detection fails
- **Try "Refresh" button** in browser selection dialog
- **Use manual mode** if auto-detection doesn't work

### **Dialog Hidden Behind Window**
- ✅ **FIXED in v2.0.0**: Dialog now appears above main window
- **Updated z-order handling** ensures proper dialog visibility

### **Spinner Capture Problems**
- **Install PIL/Pillow**: `pip install pillow`
- **Position mouse precisely** over spin button center
- **Avoid overlays**: Ensure nothing blocks the spin button
- **Re-capture if needed**: Button detection may need adjustment

### **Automation Not Working**
- **Check PyAutoGUI**: `pip install pyautogui`
- **Verify permissions**: Accessibility must be enabled
- **Test manual mode first**: Confirm basic clicking works
- **Watch the logs**: Real-time feedback shows all actions

## 📝 File Locations

### **Configuration Files**
- **Window geometry**: `~/.spin_helper_geometry.json`
- **Session data**: `~/.spin_helper_session.json`
- **Exported logs**: `~/spin_helper_log_TIMESTAMP.txt`

### **Safe Cleanup**
```bash
# Reset all settings
rm ~/.spin_helper_geometry.json ~/.spin_helper_session.json

# Remove old logs
rm ~/spin_helper_log_*.txt
```

## 🎯 Usage Philosophy

### **User Control First**
- **You remain in control**: Stop/start buttons always accessible
- **No autonomous betting**: App only clicks where you direct it
- **Full transparency**: Every action logged in real-time
- **Easy override**: Manual intervention possible at any time

### **Efficiency Focus**
- **Automate repetition**: Handle tedious clicking tasks
- **Smart detection**: Wait for game readiness before proceeding
- **Natural timing**: Randomized delays prevent detection
- **Session memory**: Preserve progress across app restarts

## 📊 Testing Status

### ✅ **Verified Working**
- Application launches without errors on macOS
- Browser detection shows real Chrome/Safari/Firefox tabs
- Dialog z-order issue completely resolved
- Spinner capture creates baseline images successfully
- Calculator performs accurate wagering mathematics
- Manual autoclicker executes real clicks with readiness detection
- Automatic autoclicker runs with progress tracking
- Session persistence saves/restores all settings

### 🔄 **Continuous Testing**
- **Platform**: macOS (Darwin) with Python 3.13.7
- **Environment**: VSCode with virtual environment
- **Browser**: Chrome with multiple casino tabs
- **Dependencies**: PIL and PyAutoGUI verified working

---

**Version**: v2.0.0 | **Platform**: macOS | **Status**: Production Ready | **Updated**: September 2, 2025