# examples/config_io.py
import json, os, tempfile, shutil

DEFAULT_CONFIG = {
    "server": "",
    "mac":    "",
    "model":  "",
    "auto_connect": True    # you can toggle this from CLI if you like
}

def config_path_from_here() -> str:
    # Go up one level from this file, then into examples/cli.config
    here = os.path.dirname(__file__)                 # current directory
    parent = os.path.dirname(here)                   # one level up
    return os.path.join(parent, "examples", "cli.config")

def load_config(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            return None
        # ensure all keys exist
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    except FileNotFoundError:
        return None
    except Exception:
        return None

def save_config(path: str, cfg: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = tempfile.NamedTemporaryFile("w", delete=False, dir=os.path.dirname(path), encoding="utf-8")
    try:
        json.dump(cfg, tmp, indent=2, sort_keys=True)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        shutil.move(tmp.name, path)
    finally:
        try: os.unlink(tmp.name)
        except Exception: pass

def is_config_complete(cfg: dict) -> bool:
    return bool(cfg.get("server") and cfg.get("mac") and cfg.get("model"))
