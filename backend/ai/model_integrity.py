import hashlib
import json
import os
from typing import Tuple
from backend.core.errors import PolyEdgeException

MODEL_HASHES_PATH = os.path.join(os.path.dirname(__file__), "models", "model_hashes.json")

class SecurityError(PolyEdgeException):
    """Raised on model integrity violations."""
    pass

def _sha256_of_file(filepath: str) -> str:
    hash_fn = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_fn.update(chunk)
    return hash_fn.hexdigest()

def _load_hashes() -> dict:
    if not os.path.exists(MODEL_HASHES_PATH):
        raise FileNotFoundError(f"Missing model hashes file: {MODEL_HASHES_PATH}")
    with open(MODEL_HASHES_PATH, "r") as f:
        return json.load(f)

def load_model_safely(pkl_path: str) -> Tuple[object, bool]:
    """
    Loads a pickled model with SHA256 hash check and RestrictedUnpickler fallback.
    Returns (model_obj, integrity_verified: bool). On hash mismatch, raises SecurityError.
    Logs violations to 'model_integrity_violations' metric (stdout for now).
    """
    hashes = _load_hashes()
    fname = os.path.basename(pkl_path)
    expected = hashes.get(fname)
    actual = _sha256_of_file(pkl_path)
    if not expected:
        print(f"[model_integrity] No stored hash for {fname} (WARN)")
    if expected and actual != expected:
        print(f"[model_integrity] HASH MISMATCH: {fname}: expected {expected}, got {actual}")
        print("[model_integrity_violations] 1 model tampering detected")
        raise SecurityError(f"Model file {fname} failed integrity check:", {"expected": expected, "actual": actual})
    elif expected:
        print(f"[model_integrity] Hash OK: {fname}")
    # RestrictedUnpickler fallback
    import pickle
    class _RestrictedUnpickler(pickle.Unpickler):
        ALLOWED_PREFIXES = (
            "sklearn.", "numpy.", "numpy", "scipy.",
            "__builtin__", "builtins", "collections", "pickle", "copyreg",
        )
        def find_class(self, module, name):
            for prefix in self.ALLOWED_PREFIXES:
                if module.startswith(prefix):
                    return super().find_class(module, name)
            raise pickle.UnpicklingError(f"Blocked: {module}.{name}")
    with open(pkl_path, "rb") as fh:
        obj = _RestrictedUnpickler(fh).load()
    return obj, bool(expected and actual == expected)
