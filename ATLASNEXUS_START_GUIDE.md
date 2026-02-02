# ============================================================
# AtlasNexus Daily Console - Quick Start Guide
# ============================================================

## Issue: Tabs not showing content and window not opening

### Root Cause:
1. App needs to be run with the correct conda environment
2. Browser window needs to open automatically  
3. App was set to debug=False which hides errors

### Solution Applied:
The app has been updated to:
- ✅ Automatically open a browser window at http://127.0.0.1:8080
- ✅ Enable debug mode to show errors
- ✅ Display startup messages

## How to Start the Application:

### Option 1: Manual Start (Recommended)
Open PowerShell in this directory and run:

```powershell
# Step 1: Activate conda environment
& C:\ProgramData\anaconda3\shell\condabin\conda-hook.ps1
conda activate dev

# Step 2: Start the application  
python web\apps\atlasnexus_daily.py
```

The browser will open automatically to http://127.0.0.1:8080

### Option 2: One-Line Command
```powershell
& C:\ProgramData\anaconda3\shell\condabin\conda-hook.ps1 ; conda activate dev ; python web\apps\atlasnexus_daily.py
```

## Expected Behavior:
When started correctly, you should see:
```
============================================================
AtlasNexus Daily Console starting...
Server: http://127.0.0.1:8080
Browser window will open automatically
Press Ctrl+C to stop the server
============================================================
Dash is running on http://127.0.0.1:8080/
```

Then a browser window will automatically open showing the application with 4 main tabs:
1. **Run Center** - Job management and logs
2. **Beta Book** - Top-down factor analysis (with 5 subtabs: FACTOR, PORTFOLIO, FUTURES, REBALANCE, SURFACE)
3. **Alpha Book** - Bottom-up analysis (with 8 subtabs: CANDIDATES, PORTFOLIO, BACKTEST, BASKET, SPREAD, PAIRS, CURVES, VOLATILITY)
4. **Summary** - Risk and exposure summary

## Troubleshooting:

### If you see "Module not found" errors:
Ensure you're in the correct directory:
```powershell
cd D:\PyProjects\FIEngine\bin-v4.0
```

### If conda activate fails:
Initialize conda for PowerShell:
```powershell
conda init powershell
```
Then restart your PowerShell terminal.

### If port 8080 is already in use:
Find and kill the process:
```powershell
netstat -ano | findstr :8080
taskkill /F /PID <PID>
```

### If browser doesn't open:
Manually navigate to: http://127.0.0.1:8080

## Changes Made to Fix the Issues:

### File: web\apps\atlasnexus_daily.py
- Added automatic browser opening (using webbrowser module with 1.5s delay)
- Changed debug=False to debug=True for better error visibility
- Added startup console messages
- Kept use_reloader=False to prevent duplicate processes

### Files Created:
- `START_ATLASNEXUS.bat` - Batch file launcher (may need conda init)
- `START_ATLASNEXUS.ps1` - PowerShell launcher (may need conda init)
- `ATLASNEXUS_START_GUIDE.md` - This guide

## Next Steps:
1. Close any currently running instances of the app
2. Follow "Option 1: Manual Start" above  
3. Wait for browser to open automatically
4. Navigate through the tabs to verify content is visible

If you still encounter issues, check the console output for specific error messages.
