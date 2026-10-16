# Wind Crash Root Cause and Stabilization Notes

## Context

Observed symptom:
- Daily web app exited quietly during normal tab interactions (e.g., Beta Backtest UI actions).
- `logs/crash.log` showed `Windows fatal exception: access violation`.
- Python traceback often ended at Flask/Dash server loop (`serve_forever`), indicating process-level native crash rather than a catchable Python exception.

## Root Cause (Key)

Primary root cause was **native extension instability under concurrent web callback/runtime activity**.

In practice this manifested as:
1. Wind SDK calls timing out/failing repeatedly (`wss`, `wsq`, `wsd`, `wset`) while the app continued to issue requests.
2. Background startup/refresh paths and UI traffic overlapping in one process.
3. Native crash (`access violation`) occurring in/around the web server process, which Python exception handlers cannot recover from.

Important: this is not a normal Python logic exception. It is a process-fatal native failure path.

## Evidence Summary

- `logs/crash.log`: repeated `Windows fatal exception: access violation`.
- `logs/app.log`: repeated Wind timeout/failure messages and stale instrument update failures before/around crash windows.
- Crash persisted despite try/except guards, confirming process-level native failure behavior.

## Fixes Applied

### 1) Server concurrency stabilization
- Switched daily web server to single-thread mode:
  - `main.py`: `atlasnexus_daily.app.run(..., threaded=False)`
- Why it matters:
  - Removes callback concurrency/race pressure on non-thread-safe native paths.

### 2) Wind call containment and backoff
- Added/strengthened Wind failure backoff logic in `data/providers/retrieve.py`.
- Corrected failure-counter reset logic so repeated failures actually trigger cooldown.
- Added global Wind kill switch behavior (`FI_DISABLE_WIND`) to force offline mode safely.

### 3) Startup/refresh hardening
- Gated startup initialization and periodic refresh behaviors behind explicit runtime controls.
- Moved to explicit opt-in for automatic startup tasks in web mode to reduce uncontrolled background native activity.

### 4) Launcher-controlled runtime toggles
- `START_win.bat` updated to set runtime flags explicitly so behavior is predictable at launch.

## Operational Guidance (Going Forward)

1. Treat Wind/native integrations as unsafe for direct multi-threaded callback execution.
2. Keep web serving single-threaded unless native call paths are isolated in separate worker processes.
3. Use explicit env toggles for Wind/background jobs:
   - `FI_DISABLE_WIND`
   - `FI_AUTO_INITIALISE`
   - `FI_AUTO_REFRESH`
   - `FI_AUTO_EOD`
4. If a crash reappears:
   - Capture fresh `logs/crash.log` and tail of `logs/app.log` immediately.
   - Confirm whether any new direct/native call path bypasses the provider wrappers.
5. Prefer artifact-first UI reads; avoid synchronous native fetches directly in request callbacks.

## Recommended Future Architecture

For higher throughput without regressing stability:
- Keep web process callback handling lightweight.
- Move Wind/native fetches to dedicated worker process(es) with IPC queue.
- Persist fetched data to artifacts/cache.
- Let UI callbacks read artifacts only.

This preserves responsiveness while isolating process-fatal native failures away from the web server.

## Final Takeaway

The decisive stabilization was not a single `try/except`; it was **reducing concurrency on native paths and controlling background Wind activity explicitly**.
