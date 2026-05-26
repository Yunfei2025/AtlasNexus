
import os
import pandas as pd
import pickle


def _safe_read_pickle(file_path: str):
    """Load a pickle, handling pandas version incompatibility gracefully.

    Falls back to renaming the broken file and returning None so callers
    can treat it as missing and rebuild from fresh data.
    """
    try:
        return pd.read_pickle(file_path)
    except Exception as e:
        msg = str(e)
        if "manager items" in msg or "block items" in msg or "BlockManager" in msg:
            broken = file_path + ".incompatible"
            os.rename(file_path, broken)
            print(
                f"WARNING: {os.path.basename(file_path)} was saved with an incompatible "
                f"pandas version and has been renamed to {os.path.basename(broken)}. "
                f"It will be rebuilt on the next data retrieval run."
            )
            return None
        raise


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
            def _update_dataframe(target_df, new_df):
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
                combined = combined.sort_index().ffill().dropna(axis=0, how="all")
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
                        target_dict[sub_key] = _update_dataframe(sub_old, sub_new)
                    elif isinstance(sub_new, pd.Series):
                        target_dict[sub_key] = _update_series(sub_old, sub_new)
                    elif isinstance(sub_new, dict):
                        target_dict[sub_key] = _update_dict(sub_old, sub_new)
                    else:
                        target_dict[sub_key] = _update_value(sub_old, sub_new)
                return target_dict

            for k, v in dictn.items():
                if isinstance(v, pd.DataFrame):
                    dict_[k] = _update_dataframe(dict_.get(k), v)
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