import json, os, tempfile, shutil
from pathlib import Path


DEFAULT_CONFIG = {
    "server": "",
    "mac":    "",
    "model":  "",
    "auto_connect": True,
    "auto_answer": False,
}


def _config_parent_writable(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        probe = path.parent / ".write_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def config_path_from_here() -> str:
    """Default CLI config path (repo file in dev, user config when installed)."""
    env = os.environ.get("PYSKINNY_CONFIG")
    if env:
        return env
    dev_cfg = Path(__file__).resolve().parent / "examples" / "cli.config"
    if dev_cfg.is_file() and _config_parent_writable(dev_cfg):
        return str(dev_cfg)
    return str(Path.home() / ".pyskinny" / "cli.config")


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
