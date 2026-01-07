# Web Module Cleanup Summary

## Import Issues Fixed

### 1. Fixed Import Paths
**Problem**: All web modules were importing from `tools.config` which doesn't exist.
**Solution**: Updated imports to use proper settings modules:

- `tools.config.BondConfig` → `settings.fixed_income.BondConfig`
- `tools.config.IRSConfig` → `settings.fixed_income.IRSConfig`
- `tools.config.InstitutionConfig` → `settings.fixed_income.InstitutionConfig`
- `tools.config.FuturesConfig` → `settings.futures.FuturesConfig`
- `tools.config.GeneralConfig` → `settings.general.GeneralConfig`
- `tools.config.DateConfig` → `settings.general.DateConfig`
- `tools.config.SpreadConfig` → `settings.general.SpreadConfig` (created)

### 2. Added Missing SpreadConfig Class
**Problem**: SpreadConfig was referenced but didn't exist.
**Solution**: Added SpreadConfig class to `settings/general.py` with `build_ospreado()` method.

## Removed Redundant Files

### 1. Duplicate Files Removed
- `web/static/styles.py` (duplicate of `web/core/styles.py`)
- `web/routes/graphs.py` (duplicate of `web/core/graphs.py`)
- `web/routes/content.py` (duplicate of `web/core/content.py`)

### 2. File Structure Simplified
**Before**:
```
web/
├── core/
│   ├── content.py
│   ├── graphs.py
│   └── styles.py
├── routes/
│   ├── content.py (duplicate)
│   ├── graphs.py (duplicate)
│   └── ...
└── static/
    └── styles.py (duplicate)
```

**After**:
```
web/
├── core/
│   ├── content.py
│   ├── graphs.py
│   └── styles.py
├── routes/
│   ├── fi.py
│   ├── futures.py
│   ├── surface.py
│   └── tables.py
└── static/
    └── (cleaned)
```

## Files Updated

### Core Module Files
- `web/core/content.py` - Fixed imports
- `web/core/load.py` - Fixed imports  
- `web/core/styles.py` - Fixed imports
- `web/core/graphs.py` - Fixed imports
- `web/core/funcs.py` - Fixed imports

### Apps Module Files
- `web/apps/fi.py` - Fixed imports
- `web/apps/futures.py` - Fixed imports

### Routes Module Files
- `web/routes/futures.py` - Fixed imports

### Settings Module Files
- `settings/general.py` - Added SpreadConfig class

## Remaining Dependencies

### Required External Packages
The web modules require these packages to be installed:
- `dash` - Main web framework
- `plotly` - Plotting library
- `dash_daq` - Additional Dash components

Install with:
```bash
pip install dash plotly dash-daq
```

## Functionality Status

### ✅ Fixed
- Import resolution errors
- Module structure duplication
- Missing configuration classes
- File organization

### ⚠️ Runtime Dependencies
- Dash framework not installed (expected - external dependency)
- Some data files may be missing (input/*.pkl files)

### 🔄 Next Steps
1. Install required packages: `pip install dash plotly dash-daq`
2. Verify data files exist in `input/` directory
3. Test web application startup: `python -m web.apps.fi`

## Import Map Summary

| Old Import | New Import | Status |
|------------|------------|---------|
| `tools.config.BondConfig` | `settings.fixed_income.BondConfig` | ✅ Fixed |
| `tools.config.IRSConfig` | `settings.fixed_income.IRSConfig` | ✅ Fixed |
| `tools.config.InstitutionConfig` | `settings.fixed_income.InstitutionConfig` | ✅ Fixed |
| `tools.config.FuturesConfig` | `settings.futures.FuturesConfig` | ✅ Fixed |
| `tools.config.GeneralConfig` | `settings.general.GeneralConfig` | ✅ Fixed |
| `tools.config.DateConfig` | `settings.general.DateConfig` | ✅ Fixed |
| `tools.config.SpreadConfig` | `settings.general.SpreadConfig` | ✅ Fixed (created) |

All import issues have been resolved and the web module structure is now clean and maintainable.