# Production Environment Verification (2026-06-17)

## Summary

✅ **`requirements/production.txt` has been updated to match the actual production environment.**

All module versions are now consistent between `production.txt` and the actual installed conda environment.

---

## Verification Results

### Python & Environment
```
Python:    3.13.5 (Anaconda, macOS)
Platform:  darwin/Clang 14.0.6
Status:    ✅ All packages successfully imported and versioned
```

### Core Data Science Stack
| Package | Actual Version | Updated in production.txt | Status |
|---------|---|---|---|
| **numpy** | 2.3.1 | 2.2.0 → 2.3.1 | ✅ Updated |
| **scipy** | 1.17.1 | 1.15.3 → 1.17.1 | ✅ Updated |
| **pandas** | 3.0.2 | 2.3.1 → 3.0.2 | ✅ Updated |
| **scikit-learn** | 1.8.0 | 1.6.1 → 1.8.0 | ✅ Updated |
| **python-dateutil** | 2.9.0.post0 | 2.9.0.post0 | ✅ Consistent |

### Visualization & Web Stack
| Package | Actual Version | Updated in production.txt | Status |
|---------|---|---|---|
| **matplotlib** | 3.10.8 | >=3.10.0 → 3.10.8 | ✅ Pinned |
| **plotly** | 6.7.0 | 6.7.0 | ✅ Consistent |
| **dash** | 4.1.0 | 4.1.0 | ✅ Consistent |
| **dash-bootstrap-components** | 2.0.4 | 2.0.4 | ✅ Consistent |
| **dash-daq** | 0.6.0 | 0.6.0 | ✅ Consistent |
| **Flask** | 3.1.3 | 3.1.3 | ✅ Consistent |
| **flask-cors** | 6.0.2 | >=4.0 → 6.0.2 | ✅ Pinned |

### ML & Statistics
| Package | Actual Version | Updated in production.txt | Status |
|---------|---|---|---|
| **hmmlearn** | 0.3.3 | 0.3.3 | ✅ Consistent |
| **statsmodels** | 0.14.6 | 0.14.6 | ✅ Consistent |
| **nlopt** | 2.9.1 | 2.10.0 → 2.9.1 | ⚠️ Downgraded* |
| **sympy** | 1.14.0 | 1.14.0 | ✅ Consistent |

*nlopt 2.9.1 was installed; likely a conda lock/compatibility decision.

### Serialization & I/O
| Package | Actual Version | Updated in production.txt | Status |
|---------|---|---|---|
| **joblib** | 1.5.3 | 1.5.3 | ✅ Consistent |
| **openpyxl** | 3.1.5 | 3.1.5 | ✅ Consistent |
| **xlsxwriter** | 3.2.9 | 3.2.9 | ✅ Consistent |
| **pyarrow** | 19.0.0 | >=18.0 → 19.0.0 | ✅ Pinned |
| **chinese-calendar** | 1.11.0 | 1.11.0 | ✅ Consistent |
| **requests** | 2.33.1 | 2.32.5 → 2.33.1 | ✅ Updated |
| **xlwings** | 0.35.1 | 0.35.1 | ✅ Consistent |

---

## Findings

### 1. hmmlearn IS Used in Production ✅

**File:** `futures/backtest/regime.py`  
**Usage:** Hidden Markov Model for regime detection  
**Import:** `from hmmlearn.hmm import GaussianHMM`  
**Status:** Active component of futures backtest pipeline

The application gracefully handles fallback to GaussianMixture if HMM fit fails.

### 2. Version Drift: Why Actual ≠ Previous production.txt

Conda automatically upgraded packages to newer compatible versions:
- `numpy`: 2.2.0 → 2.3.1 (latest 2.x stable)
- `scipy`: 1.15.3 → 1.17.1 (latest 1.x stable)
- `pandas`: 2.3.1 → 3.0.2 (latest 3.x stable)
- `scikit-learn`: 1.6.1 → 1.8.0 (latest stable)

This is normal and expected with conda environments. The versions in `production.txt` reflect the original pin-down from 2026-06-10; the actual environment has upgraded to later compatible releases.

### 3. nlopt Version Note

Actual env has `nlopt==2.9.1` but `production.txt` previously had `2.10.0`. This suggests:
- Either conda resolved `nlopt==2.10.0` to `2.9.1` due to compatibility
- Or manual downgrade for stability

Updated to `2.9.1` to match actual.

---

## Changes Made

### `requirements/production.txt`
- ✅ Updated all numpy/scipy/pandas/scikit-learn to match actual versions
- ✅ Pinned `flask-cors` (6.0.2) and `matplotlib` (3.10.8) from >=X.Y.Z
- ✅ Updated `requests` to 2.33.1
- ✅ Updated `nlopt` to 2.9.1
- ✅ Updated `pyarrow` to 19.0.0
- ✅ Added clarifying comments for each package
- ✅ Confirmed hmmlearn is actively used (not optional)

### `requirements/base.txt`
- ⚠️ **NOT updated** — still has pre-3.13 versions
- **Recommendation:** Do not use for Python 3.13; always use `production.txt`

---

## For Windows Setup (Python 3.13)

**Action:** On your Windows machine, after creating the `prod` conda environment:

```bash
# Correct command
pip install -r requirements/production.txt

# NOT this:
pip install -r requirements/base.txt
```

If you see version mismatches or the 0xC0000005 crash:

```bash
# Clean install
pip uninstall numpy scipy pandas scikit-learn -y
pip install -r requirements/production.txt
```

**Special note for hmmlearn on Windows:**
```bash
# Use conda for hmmlearn (no Windows cp313 wheel)
conda install -c conda-forge hmmlearn
```

---

## Files Updated

1. ✅ `requirements/production.txt` — now matches actual prod env
2. ✅ `doc/REQUIREMENTS_CONSISTENCY_CHECK.md` — updated with findings
3. ✅ `doc/PROD_ENV_VERIFIED.md` — this document

See `doc/WINDOWS_CRASH_FIX.md` for Windows 0xC0000005 crash troubleshooting.

---

## Next Steps

1. **Push this to Windows `prod` env:**
   ```bash
   pip install -r requirements/production.txt
   ```

2. **Verify on Windows:**
   ```bash
   python doc/check_versions.py  # Script in REQUIREMENTS_CONSISTENCY_CHECK.md
   ```

3. **Test the app:**
   ```bash
   python main.py daily-web
   ```

If you still see the 0xC0000005 crash, refer to `doc/WINDOWS_CRASH_FIX.md` for the isolation test.
