import json, os, tempfile, shutil


DEFAULT_CONFIG = {
    "server": "",
    "mac":    "",
    "model":  "",
    "auto_connect": True,
    "auto_answer": False,
}

def config_path_from_here() -> str:
    """Return the default examples/cli.config path relative to the repo root."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "examples", "cli.config")


def resolve_config_path(config_arg) -> str | None:
    """Map CLI --config (True) or an explicit path to a config file path."""
    if not config_arg:
        return None
    if config_arg is True:
        return config_path_from_here()
    return str(config_arg)


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
    return bool(cfg.get("server") and cfg.get("model")) and (cfg.get("mac") or cfg.get("device"))
