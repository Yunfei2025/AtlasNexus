# Windows Exit Code -1073741819 (0xC0000005) — Troubleshooting Guide

## Problem
When running `main.py` on Windows with Python 3.13, PyCharm outputs:
```
Process finished with exit code -1073741819 (0xC0000005)
```

## What This Means
**0xC0000005** is a Windows **Access Violation (segfault)** — a hard native crash inside a C/C++ extension. This is NOT a Python import error or environment conflict; it's a binary ABI mismatch or corrupted wheel.

## Root Causes (In Priority Order)

### 1. **hmmlearn on Windows Python 3.13** ⚠️ MOST LIKELY
`requirements/production.txt` explicitly states:
> "hmmlearn note: no Windows cp313 wheel exists (limited-maintenance package)"

If installed via `pip install` on Windows with Python 3.13:
- It either compiled from source with a broken MSVC setup
- Or used an incompatible/cached binary that corrupts memory

**Status:** Check with `pip show hmmlearn`

### 2. **Numpy ABI Mismatch**
- `requirements/base.txt` pins `numpy==2.0.2`
- `requirements/production.txt` pins `numpy==2.2.0`
- If packages were built against numpy 1.x or an incompatible version, C extensions crash on first call

**Status:** Check with `python -c "import numpy; print(numpy.__version__)"`

### 3. **nlopt (C binding) Wheel Mismatch**
- `nlopt==2.10.0` is a C extension for portfolio optimization
- If the wheel is mismatched to your Python 3.13 + Windows architecture, it crashes hard

**Status:** Check with `python -c "import nlopt; print(nlopt.__version__)"`

### 4. **Mixed Requirements Files**
- Never mix `base.txt` (lightweight, older pins) with `production.txt` (full runtime)
- `requirements.txt` at root correctly redirects to `production.txt`
- Installing from `base.txt` will give you `numpy==2.0.2 + scipy==1.13.1`, which may conflict with packages expecting newer versions

---

## Fix (Step-by-Step)

### Step 1: Verify You're Using production.txt
```bash
pip freeze | head -20
# Should show: numpy==2.2.0, scipy==1.15.3, scikit-learn==1.6.1, pandas==2.3.1
# NOT numpy==2.0.2 or scipy==1.13.1
```

### Step 2: Isolate the Crash
Add this to the top of `main.py`'s `__main__` block (right after imports):

```python
if __name__ == "__main__":
    # Crash isolation — remove after debugging
    try:
        import hmmlearn
        print("✓ hmmlearn OK")
    except Exception as e:
        print(f"✗ hmmlearn FAILED: {e}")
        sys.exit(1)
    
    try:
        import nlopt
        print("✓ nlopt OK")
    except Exception as e:
        print(f"✗ nlopt FAILED: {e}")
        sys.exit(1)
    
    try:
        import scipy
        print("✓ scipy OK")
    except Exception as e:
        print(f"✗ scipy FAILED: {e}")
        sys.exit(1)
    
    # ... rest of main
```

Run this and note which line crashes first.

### Step 3: Fix hmmlearn (Most Likely)
**Option A — Use Conda (Recommended for Windows):**
```bash
pip uninstall hmmlearn -y
conda install -c conda-forge hmmlearn
```

**Option B — Build from Source (if conda not available):**
```bash
# Install MSVC Build Tools for C++, then:
pip install hmmlearn==0.3.3 --no-cache-dir --force-reinstall --no-binary :all:
```

### Step 4: Force Reinstall Numpy & Dependents
```bash
pip install numpy==2.2.0 --force-reinstall --no-cache-dir
pip install scipy==1.15.3 scikit-learn==1.6.1 pandas==2.3.1 --force-reinstall --no-cache-dir
```

### Step 5: If nlopt or scipy Still Crashes
```bash
# Verify correct architecture wheel is installed
pip install nlopt==2.10.0 --force-reinstall --no-cache-dir
pip install scipy==1.15.3 --force-reinstall --no-cache-dir
```

### Step 6: Run main.py Again
```bash
python main.py --help
```

If it crashes with no output, one of the isolation imports (Step 2) identified the culprit.

---

## Environment Setup Checklist

- [ ] Python 3.13 installed (check: `python --version`)
- [ ] `pip install -r requirements.txt` (or `pip install -r requirements/production.txt`)
- [ ] NOT `pip install -r requirements/base.txt` alone
- [ ] `pip freeze` shows `numpy==2.2.0` (not `2.0.2`)
- [ ] `pip freeze` shows `scipy==1.15.3` (not `1.13.1`)
- [ ] On Windows: conda installed and available (for hmmlearn fallback)
- [ ] MSVC Build Tools installed (only if building hmmlearn from source)

---

## Quick Verification Script

Save this as `verify_env.py` and run `python verify_env.py`:

```python
#!/usr/bin/env python3
import sys
print(f"Python: {sys.version}")

packages = [
    ("numpy", "2.2.0"),
    ("pandas", "2.3.1"),
    ("scipy", "1.15.3"),
    ("scikit-learn", "1.6.1"),
    ("matplotlib", "3.10.0"),
    ("plotly", "6.7.0"),
    ("hmmlearn", "0.3.3"),
    ("nlopt", "2.10.0"),
]

for pkg, expected_ver in packages:
    try:
        mod = __import__(pkg.replace("-", "_"))
        actual_ver = getattr(mod, "__version__", "unknown")
        status = "✓" if actual_ver.startswith(expected_ver.split(".")[0]) else "⚠"
        print(f"{status} {pkg:20} {actual_ver:15} (expected {expected_ver})")
    except ImportError:
        print(f"✗ {pkg:20} NOT INSTALLED")
    except Exception as e:
        print(f"✗ {pkg:20} ERROR: {e}")
```

---

## If Still Crashing

1. **Check PyCharm Python interpreter:**
   - Project Settings → Python Interpreter
   - Verify it points to the correct env (the one where you ran `pip install`)
   - Try running from command line: `python main.py --help`

2. **Check for Windows antivirus/defender:**
   - Can block or corrupt DLL loads from C extensions
   - Temporarily disable, run the isolation test (Step 2)

3. **Completely clean reinstall:**
   ```bash
   python -m venv .venv-clean
   .venv-clean\Scripts\activate  # Windows
   pip install -r requirements/production.txt
   python main.py --help
   ```

4. **Report crash details:**
   - If isolation test identifies the package, open an issue with:
     - `pip show <package>`
     - `python --version`
     - `pip freeze` output
     - Full PyCharm console output (enable verbose logging)

---

## References
- **hmmlearn Windows note:** `requirements/production.txt` line 8-10
- **numpy 3.13 requirement:** `requirements/production.txt` line 3
- **multiprocessing guard:** `main.py` line 333-337 (already in place ✓)
