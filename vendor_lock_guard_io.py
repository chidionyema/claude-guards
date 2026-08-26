"""Transcript helpers shared by the Stop-hook guards (loaded from vendor-lock-guard.py, one copy)."""
import importlib.util
from pathlib import Path
_spec = importlib.util.spec_from_file_location("vendor_lock_guard", Path(__file__).with_name("vendor-lock-guard.py"))
_m = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_m)
above_the_fold = _m.above_the_fold
last_assistant_text = _m.last_assistant_text
