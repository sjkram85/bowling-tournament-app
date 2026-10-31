"""Remember a value for the rest of one Streamlit run.

A full rerun and each auto-refresh fragment get their own bucket, so a later click
or a later poll never reuses the previous result. Outside Streamlit (tests, scripts)
nothing is stored.

Streamlit keeps one ScriptRunContext for the whole browser session and calls
reset() on every rerun. Keying the bucket by id(ctx) reused the first snapshot
for the entire session — the lane heatmap then flipped between that stale read
and a fresh one. reset() replaces the per-run containers (cursors, widget ids).
A new run is a new set of those objects, even when the context object is the same.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict

_lock = threading.Lock()
_buckets: OrderedDict[str, dict] = OrderedDict()

# Replaced by ScriptRunContext.reset() at the start of every full rerun and
# every fragment poll. Hold the objects and compare with `is`. id() is not
# safe: after the old containers are freed, a new run can be handed the same
# number and would otherwise replay the previous snapshot.
_MARKER_ATTRS = (
    "cursors",
    "widget_ids_this_run",
    "tracked_commands",
    "fragment_ids_this_run",
)


def _script_context():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx()
    except Exception:
        return None


def _take_marker(ctx):
    """The per-run containers Streamlit just installed. Kept so `is` still works."""
    return tuple(getattr(ctx, attr, None) for attr in _MARKER_ATTRS)


def _marker_alive(ctx, stored) -> bool:
    """True when this context is still on the same run that stored the containers."""
    if not stored or len(stored) != len(_MARKER_ATTRS):
        return False
    for attr, old in zip(_MARKER_ATTRS, stored):
        if getattr(ctx, attr, None) is not old:
            return False
    return True


def _run_id():
    ctx = _script_context()
    if ctx is None:
        return None
    with _lock:
        token = getattr(ctx, "_prism_memo_token", None)
        refs = getattr(ctx, "_prism_memo_marker", None)
        if token is None or not _marker_alive(ctx, refs):
            token = uuid.uuid4().hex
            try:
                ctx._prism_memo_token = token
                ctx._prism_memo_marker = _take_marker(ctx)
            except Exception:
                return None
        return token


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
