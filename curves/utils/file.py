
import os
import numpy as np
import pandas as pd
import pickle
import warnings

# Pure-Python unpickler — needed so load_build can be overridden via dispatch.
# The C-extension _pickle.Unpickler does not route opcodes through Python MRO.
_PureUnpickler = pickle._Unpickler


class _DatetimeCompatUnpickler(_PureUnpickler):
    """Fallback unpickler for cross-version datetime64 pickle failures.

    Handles pandas 2.3+ NDArrayBacked (DatetimeArray etc.) stored with an old
    tuple-based __setstate__ format (dtype, array) that raises NotImplementedError.
    """

    def load_build(self):
        stack = self.stack
        state = stack[-1]
        inst = stack[-2] if len(stack) >= 2 else None
        if inst is not None and isinstance(state, tuple) and len(state) == 2:
            try:
                from pandas._libs.arrays import NDArrayBacked
                if isinstance(inst, NDArrayBacked):
                    np_dtype, data = state
                    if hasattr(np_dtype, 'kind') and np_dtype.kind in ('M', 'm'):
                        target = 'datetime64[ns]' if np_dtype.kind == 'M' else 'timedelta64[ns]'
                        arr = np.asarray(data).astype(target)
                        stack.pop()
                        stack.pop()
                        NDArrayBacked.__init__(inst, arr, arr.dtype)
                        stack.append(inst)
                        return
            except Exception:
                pass
        super().load_build()

    dispatch = dict(_PureUnpickler.dispatch)
    dispatch[ord('b')] = load_build


_INCOMPATIBLE_MSGS = ("manager items", "block items", "BlockManager", "NotImplementedError")
_CORRUPT_MSGS = ("truncated", "invalid load key", "unexpected end of file")


def _safe_read_pickle(file_path: str):
    """Load a pickle with fallbacks for version incompatibility and corruption.

    Attempt order:
      1. pd.read_pickle (fast path)
      2. _DatetimeCompatUnpickler (handles pandas 2.3 NDArrayBacked tuple state)
      3. Give up — rename the file so callers treat it as missing and rebuild.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return pd.read_pickle(file_path)
        except Exception as e:
            first_err = str(e)

    # Try compat unpickler for datetime64 incompatibilities.
    try:
        with open(file_path, 'rb') as f:
            data = _DatetimeCompatUnpickler(f).load()
        # Re-save in current format so future loads use the fast path.
        try:
            import shutil
            bak = file_path + ".bak"
            shutil.copy2(file_path, bak)
            with open(file_path, 'wb') as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.remove(bak)
            print(f"INFO: {os.path.basename(file_path)} re-saved in current pickle format.")
        except Exception:
            pass
        return data
    except Exception as e2:
        second_err = str(e2)

    # Unrecoverable — rename so the caller can start fresh.
    broken_suffix = ".incompatible"
    if any(m in first_err for m in _INCOMPATIBLE_MSGS):
        pass  # already the right label
    elif any(m in first_err.lower() for m in _CORRUPT_MSGS) or any(
        m in second_err.lower() for m in _CORRUPT_MSGS
    ):
        broken_suffix = ".corrupted"

    broken = file_path + broken_suffix
    try:
        os.rename(file_path, broken)
        print(
            f"WARNING: {os.path.basename(file_path)} could not be loaded "
            f"({first_err[:120]}) and has been renamed to "
            f"{os.path.basename(broken)}. It will be rebuilt on the next run."
        )
    except OSError:
        pass
    return None


def loadPKL(file_path: str) -> dict:
    """Load a pickle file without any merge/sort/ffill overhead.

    Use this instead of ``updatePKL({}, file_path)`` when you only need to
    read the stored object — the merge path in ``updatePKL`` is unnecessary
    and does O(N) work on every DataFrame key even when nothing changes.
    Returns an empty dict if the file does not exist.
    """
    if os.path.exists(file_path):
        obj = _safe_read_pickle(file_path)
        return obj if obj is not None else {}
    return {}


#: Dict keys holding actually-observed (not model-derived) data. Forward-filling
#: these would fabricate quotes on dates where no real observation exists, so
#: updatePKL must leave gaps as NaN instead of carrying the last value forward.
_NO_FFILL_KEYS = {'ytm_act'}


def updatePKL(dictn, file_path, rewrite=False):
    if rewrite:
        with open(file_path, 'wb') as file:
            pickle.dump(dictn, file, protocol=pickle.HIGHEST_PROTOCOL)
        return dictn
    else:
        if os.path.exists(file_path):
            # Load existing object using safe loading
            dict_ = _safe_read_pickle(file_path)
            if dict_ is None:
                print(f"Starting with empty dictionary for {file_path}")
                dict_ = {}

            # Helper updaters to avoid per-date loops
            def _update_dataframe(target_df, new_df, ffill=True):
                if target_df is None or not isinstance(target_df, pd.DataFrame):
                    target_df = pd.DataFrame()
                target_df = target_df.copy()
                new_df = new_df.copy()

                # If the incoming frame contains object/string data for a column,
                # preserve that column as object so bond codes and other labels
                # are not coerced into float64 during assignment.
                for col in new_df.columns.intersection(target_df.columns):
                    if new_df[col].dtype == object or target_df[col].dtype == object:
                        target_df[col] = target_df[col].astype(object)

                if not target_df.index.is_unique:
                    target_df = target_df[~target_df.index.duplicated(keep='last')]
                if not target_df.columns.is_unique:
                    target_df = target_df.loc[:, ~target_df.columns.duplicated(keep='last')]
                if not new_df.index.is_unique:
                    new_df = new_df[~new_df.index.duplicated(keep='last')]
                if not new_df.columns.is_unique:
                    new_df = new_df.loc[:, ~new_df.columns.duplicated(keep='last')]

                for col in new_df.columns:
                    if col not in target_df.columns or new_df[col].dtype == object:
                        target_df[col] = target_df.get(col, pd.Series(index=target_df.index, dtype=object)).astype(object)

                combined = new_df.combine_first(target_df)
                combined = combined.sort_index()
                if ffill:
                    combined = combined.ffill()
                combined = combined.dropna(axis=0, how="all")
                return combined

            def _update_series(target_ser, new_ser):
                if target_ser is None or not isinstance(target_ser, pd.Series):
                    target_ser = pd.Series(dtype=float)
                target_ser = target_ser.copy()
                new_ser = new_ser.copy()
                if not target_ser.index.is_unique:
                    target_ser = target_ser[~target_ser.index.duplicated(keep='last')]
                if not new_ser.index.is_unique:
                    new_ser = new_ser[~new_ser.index.duplicated(keep='last')]
                combined = new_ser.combine_first(target_ser)
                combined = combined.sort_index().dropna(axis=0, how="all")
                return combined

            def _update_value(target_val, new_val):
                # For strings or scalars, prefer new value
                return new_val

            def _update_dict(target_dict, new_dict):
                if target_dict is None or not isinstance(target_dict, dict):
                    target_dict = {}
                for sub_key, sub_new in new_dict.items():
                    sub_old = target_dict.get(sub_key)
                    if isinstance(sub_new, pd.DataFrame):
                        target_dict[sub_key] = _update_dataframe(sub_old, sub_new, ffill=sub_key not in _NO_FFILL_KEYS)
                    elif isinstance(sub_new, pd.Series):
                        target_dict[sub_key] = _update_series(sub_old, sub_new)
                    elif isinstance(sub_new, dict):
                        target_dict[sub_key] = _update_dict(sub_old, sub_new)
                    else:
                        target_dict[sub_key] = _update_value(sub_old, sub_new)
                return target_dict

            for k, v in dictn.items():
                if isinstance(v, pd.DataFrame):
                    dict_[k] = _update_dataframe(dict_.get(k), v, ffill=k not in _NO_FFILL_KEYS)
                elif isinstance(v, pd.Series):
                    dict_[k] = _update_series(dict_.get(k), v)
                elif isinstance(v, dict):
                    dict_[k] = _update_dict(dict_.get(k), v)
                else:
                    dict_[k] = _update_value(dict_.get(k), v)

            with open(file_path, 'wb') as file:
                pickle.dump(dict_, file, protocol=pickle.HIGHEST_PROTOCOL)
            return dict_
        else:
            with open(file_path, 'wb') as file:
                pickle.dump(dictn, file, protocol=pickle.HIGHEST_PROTOCOL)
            return dictn