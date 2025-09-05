import json
import yaml
from pathlib import Path


def load_config(config_path: str) -> dict:
    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    ext = path.suffix.lower()

    try:
        with path.open("r", encoding="utf-8") as f:
            if ext == ".json":
                return json.load(f)
            elif ext in [".yaml", ".yml"]:
                return yaml.safe_load(f)
            else:
                raise ValueError(f"Unsupported config file format: {ext}")
    except Exception as e:
        raise RuntimeError(f"Failed to load config: {e}")
