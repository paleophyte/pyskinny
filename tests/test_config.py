import json
from argparse import Namespace

import pytest

from config import config_path_from_here, load_config, resolve_config_path
from state import build_state_from_args, PhoneState


def test_resolve_config_path_true_uses_default_file():
    path = resolve_config_path(True)
    assert path == config_path_from_here()
    assert path.endswith("cli.config")


def test_resolve_config_path_explicit():
    assert resolve_config_path("/tmp/my.config") == "/tmp/my.config"
    assert resolve_config_path(None) is None
    assert resolve_config_path(False) is None


def test_build_state_from_args_cli(tmp_path):
    args = Namespace(
        config=None,
        server="10.0.0.180",
        mac="222233334444",
        device=None,
        model="7970",
    )
    state = build_state_from_args(args)
    assert state.server == "10.0.0.180"
    assert state.device_name == "SEP222233334444"
    assert state.model_name == "Cisco 7970"


def test_build_state_from_args_config_file(tmp_path):
    cfg_file = tmp_path / "cli.config"
    cfg_file.write_text(
        json.dumps(
            {
                "server": "10.0.0.99",
                "mac": "AABBCCDDEEFF",
                "model": "7970",
                "auto_connect": False,
            }
        ),
        encoding="utf-8",
    )
    args = Namespace(
        config=str(cfg_file),
        server=None,
        mac=None,
        device=None,
        model=None,
    )
    state = build_state_from_args(args)
    assert state.server == "10.0.0.99"
    assert state.device_name == "SEPAABBCCDDEEFF"


def test_build_state_from_args_config_flag(tmp_path, monkeypatch):
    cfg_file = tmp_path / "examples" / "cli.config"
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text(
        json.dumps({"server": "10.0.0.50", "mac": "111122223333", "model": "7970"}),
        encoding="utf-8",
    )

    def fake_config_path():
        return str(cfg_file)

    monkeypatch.setattr("config.config_path_from_here", fake_config_path)

    args = Namespace(
        config=True,
        server=None,
        mac=None,
        device=None,
        model=None,
    )
    state = build_state_from_args(args)
    assert state.server == "10.0.0.50"
    assert state.device_name == "SEP111122223333"


def test_build_state_from_args_missing_fields():
    args = Namespace(config=None, server="10.0.0.1", mac="222233334444", device=None, model=None)
    with pytest.raises(SystemExit, match="--model"):
        build_state_from_args(args)
