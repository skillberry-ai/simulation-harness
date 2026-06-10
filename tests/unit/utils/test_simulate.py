# tests/unit/utils/test_simulate.py
import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "utils"))
import simulate


def test_load_config_returns_parsed_yaml(tmp_path):
    yaml_content = "server:\n  host: localhost\n  port: 9000\n"
    config_file = tmp_path / "harness.yaml"
    config_file.write_text(yaml_content)
    result = simulate.load_config(config_file)
    assert result == {"server": {"host": "localhost", "port": 9000}}


def test_get_server_url_standard():
    config = {"server": {"host": "localhost", "port": 8086}}
    assert simulate.get_server_url(config) == "http://localhost:8086"


def test_get_server_url_replaces_bind_address():
    config = {"server": {"host": "0.0.0.0", "port": 8086}}
    assert simulate.get_server_url(config) == "http://localhost:8086"


def test_get_server_url_defaults():
    assert simulate.get_server_url({}) == "http://localhost:8086"


SAMPLE_SPEC = {"openapi": "3.0.0", "info": {"title": "Test", "version": "1.0"}, "paths": {}}

SAMPLE_RESPONSE = {
    "name": "test",
    "status": "active",
    "mcp_endpoint": "/mcp/test",
    "created_at": "2026-06-10T00:00:00",
}


def _make_args(tmp_path, extra=None):
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(SAMPLE_SPEC))
    config_file = tmp_path / "harness.yaml"
    config_file.write_text("server:\n  host: localhost\n  port: 8086\n")
    return [str(spec_file), "--config", str(config_file)] + (extra or [])


def test_main_success_prints_json(tmp_path, capsys):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(SAMPLE_RESPONSE).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("sys.argv", ["simulate.py"] + _make_args(tmp_path)):
        with patch("simulate.urlopen", return_value=mock_response):
            simulate.main()

    out = capsys.readouterr().out
    assert json.loads(out) == SAMPLE_RESPONSE


def test_main_passes_name_flag(tmp_path):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(SAMPLE_RESPONSE).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    captured_request = {}

    def fake_urlopen(req):
        captured_request["body"] = json.loads(req.data.decode())
        return mock_response

    with patch("sys.argv", ["simulate.py"] + _make_args(tmp_path, ["--name", "my-sim"])):
        with patch("simulate.urlopen", fake_urlopen):
            simulate.main()

    assert captured_request["body"]["name"] == "my-sim"


def test_main_passes_regenerate_skill_flag(tmp_path):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(SAMPLE_RESPONSE).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    captured_request = {}

    def fake_urlopen(req):
        captured_request["body"] = json.loads(req.data.decode())
        return mock_response

    with patch("sys.argv", ["simulate.py"] + _make_args(tmp_path, ["--regenerate-skill"])):
        with patch("simulate.urlopen", fake_urlopen):
            simulate.main()

    assert captured_request["body"]["regenerate_skill"] is True


def test_main_http_error_exits_nonzero(tmp_path, capsys):
    from urllib.error import HTTPError

    err = HTTPError(url="http://x", code=409, msg="Conflict", hdrs={}, fp=io.BytesIO(b"already exists"))

    with patch("sys.argv", ["simulate.py"] + _make_args(tmp_path)):
        with patch("simulate.urlopen", side_effect=err):
            with pytest.raises(SystemExit) as exc:
                simulate.main()

    assert exc.value.code == 1
    assert "409" in capsys.readouterr().err


def test_main_connection_error_exits_nonzero(tmp_path, capsys):
    from urllib.error import URLError

    with patch("sys.argv", ["simulate.py"] + _make_args(tmp_path)):
        with patch("simulate.urlopen", side_effect=URLError("connection refused")):
            with pytest.raises(SystemExit) as exc:
                simulate.main()

    assert exc.value.code == 1
    assert "connection refused" in capsys.readouterr().err
