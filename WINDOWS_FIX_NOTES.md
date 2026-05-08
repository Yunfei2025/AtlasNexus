# Windows Compatibility Fix: Periodic Refresh & Tab Freeze

## Symptoms (Windows only)

1. App starts, curve generation runs, prints `INFO: All curve generation tasks completed!`, then refreshers in `curves/refreshers/` never fire.
2. Webpage loads with frames but no data in the Data subtab; clicking other tabs/subtabs does not change the visible content.

Both symptoms appear together and share the same root cause.

---

## Root Cause

### Refreshers not running

`web/core/scripts.py` originally used Dash's `DiskcacheManager` to run `autoruns1`, `autoruns2`, and `initialise` as **background callbacks**:

```python
cache = diskcache.Cache("./cache")
background_callback_manager = DiskcacheManager(cache)

@app.callback(..., background=True, manager=background_callback_manager)
def autoruns1(interval, status_text):
    ...  # calls BondCurveRefresher, IRSRefresher, StatRefresher, etc.
```

`DiskcacheManager` spawns a worker subprocess via `multiprocess.Process`. On macOS, `multiprocess` can use `fork`, inheriting the parent's memory. On Windows, only `spawn` is available — a fresh Python interpreter is started, re-importing all modules. This re-import path hangs or fails silently on Windows, so background callbacks never execute.

### Tabs not switching

`web/apps/atlasnexus_daily.py` calls `autoruns1` **synchronously inside a regular Flask callback**:

```python
@app.callback(Output("an-autoruns1-status", "data"), ..., Input("data-refresh", "n_intervals"))
def _run_core_autoruns(n_intervals):
    from web.core.scripts import autoruns1 as _ar1
    r1 = _ar1(n_intervals, "AtlasNexus Daily active")
```

The old `autoruns1` body ran all four refreshers synchronously, blocking the Flask request thread. On Windows, if any refresher stalls (e.g. network/socket/file-lock issue), that thread is held indefinitely. With Werkzeug's small thread pool and the browser's ~6-connection limit, subsequent callbacks (including the tab-switcher) queue behind the stuck thread and never resolve.

---

## Fix Applied (Option A — Thread-based refresh)

### `web/core/scripts.py`

- Removed `diskcache`, `DiskcacheManager`, `cache`, and `background_callback_manager`.
- Removed `background=True, manager=...` from all three Dash callbacks.
- Added thread-safe status registry (`_status_state`, `_status_lock`, `_set_status`, `_get_status`).
- Hoisted `autoruns1` / `autoruns2` bodies into `_autoruns1_tick()` / `_autoruns2_tick()` — plain functions driven by a daemon thread.
- Added `start_periodic_refresh(interval_seconds)`: idempotent, launches a single daemon thread (`atlas-periodic-refresh`) that calls `_autoruns1_tick()` every `t_int` ms. Behaves identically on macOS and Windows; no subprocess spawning.
- Dash callbacks `autoruns1` / `autoruns2` / `initialise` are now lightweight UI readers that return the latest cached status string instantly.

### `main.py`

- `run_atlasnexus_daily_app()` now calls `start_periodic_refresh()` right after starting the `_bg_init` thread. The refresh thread defers its first tick by up to 30 s so curve generation can finish first.

---

## Behavioral Notes

- The `futures-spds.pkl` mtime-vs-today gating and the 9–17 trading-hour window check are preserved in `_autoruns1_tick()` — refreshers only run when the file is dated today and inside the window.
- `_run_core_autoruns` in `atlasnexus_daily.py` still calls `autoruns1` / `autoruns2` directly on each `data-refresh` tick — it now returns in microseconds (cached status read), so Flask threads are never blocked.
- Manual "generate" button still works: `initialise` kicks off `run_initialise()` in a thread and returns immediately.

---

## If Tab Freeze Persists After Fix

If tabs still don't switch after deploying the fix:

1. Check the **server-side console** at startup for any Python traceback during callback registration (particularly from `register_fi_callbacks`, `register_multiasset_callbacks`, etc.).
2. In the browser **DevTools → Network**, click a tab and confirm a callback HTTP request is actually sent and what response it receives.
3. A callback registration failure (unregistered tab-switcher) would show as a 404 or missing callback error in DevTools.

---

## Files Changed

| File | Change |
|------|--------|
| `web/core/scripts.py` | Removed DiskcacheManager; added `_autoruns1_tick`, `_autoruns2_tick`, `start_periodic_refresh`, status registry; simplified Dash callbacks |
| `main.py` | Added `start_periodic_refresh()` call in `run_atlasnexus_daily_app()` |
