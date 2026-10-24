"""Remember a value for the rest of one Streamlit run.

A full rerun and each auto-refresh fragment get their own bucket, so a later click
or a later poll never reuses the previous result. Outside Streamlit (tests, scripts)
nothing is stored.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

_lock = threading.Lock()
_buckets: OrderedDict[int, dict] = OrderedDict()


def _run_id():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
    except Exception:
        return None
    return id(ctx) if ctx is not None else None


def memo(key, loader):
    """Return the cached value for this run, calling loader() at most once."""
    rid = _run_id()
    if rid is None:
        return loader()
    with _lock:
        bucket = _buckets.get(rid)
        if bucket is None:
            bucket = {}
            _buckets[rid] = bucket
            while len(_buckets) > 32:
                _buckets.popitem(last=False)
        else:
            _buckets.move_to_end(rid)
        if key in bucket:
            return bucket[key]
    value = loader()
    with _lock:
        bucket = _buckets.get(rid)
        if bucket is not None:
            bucket[key] = value
    return value


def forget(key=None) -> None:
    """Drop one key (or the whole bucket) so a write in this run is visible immediately."""
    rid = _run_id()
    if rid is None:
        return
    with _lock:
        bucket = _buckets.get(rid)
        if not bucket:
            return
        if key is None:
            bucket.clear()
        else:
            bucket.pop(key, None)
