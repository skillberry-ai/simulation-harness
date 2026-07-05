# tests/unit/utils/test_get_bundle.py
import gzip
import io
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "utils"))
import get_bundle


def test_load_config_returns_parsed_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "harness.yaml"
    config_file.write_text("server:\n  host: localhost\n  port: 9000\n")
    assert get_bundle.load_config(config_file) == {
        "server": {"host": "localhost", "port": 9000}
    }


def test_get_server_url_replaces_bind_address() -> None:
    assert (
        get_bundle.get_server_url({"server": {"host": "0.0.0.0", "port": 8086}})
        == "http://localhost:8086"
    )


def test_human_size_scales_units() -> None:
    assert get_bundle.human_size(512) == "512 B"
    assert get_bundle.human_size(2048) == "2.0 KB"
    assert get_bundle.human_size(3 * 1024 * 1024) == "3.0 MB"


SAMPLE_FILES: dict[str, str] = {
    "SKILL.md": "# Demo\n",
    "schema.json": '{"type": "object"}',
    "db.json": '{"items": []}',
    "api.json": '{"openapi": "3.0.0"}',
}

SAMPLE_BUNDLE: dict[str, Any] = {
    "name": "demo-api",
    "files": SAMPLE_FILES,
    "sizes": {"SKILL.md": 7, "schema.json": 18, "db.json": 13, "api.json": 19},
}


def _config_args(tmp_path: Path, extra: Any = None) -> list[str]:
    config_file = tmp_path / "harness.yaml"
    config_file.write_text("server:\n  host: localhost\n  port: 8086\n")
    return ["--config", str(config_file)] + (extra or [])


def _mock_response(body: bytes, content_encoding: str = "") -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = body
    resp.headers.get.return_value = content_encoding
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_main_prints_bundle_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = json.dumps(SAMPLE_BUNDLE).encode()

    with patch("sys.argv", ["get_bundle.py"] + _config_args(tmp_path)):
        with patch("get_bundle.urlopen", lambda req: _mock_response(body)):
            get_bundle.main()

    out = capsys.readouterr().out
    assert json.loads(out) == SAMPLE_BUNDLE


def test_main_gzip_negotiates_reports_and_decompresses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = gzip.compress(json.dumps(SAMPLE_BUNDLE).encode())
    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any) -> Any:
        captured["accept_encoding"] = req.get_header("Accept-encoding")
        return _mock_response(body, content_encoding="gzip")

    with patch("sys.argv", ["get_bundle.py"] + _config_args(tmp_path, ["--gzip"])):
        with patch("get_bundle.urlopen", fake_urlopen):
            get_bundle.main()

    captured_out = capsys.readouterr()
    assert captured["accept_encoding"] == "gzip"
    assert "gzip:" in captured_out.err  # ratio reported on stderr
    assert json.loads(captured_out.out) == SAMPLE_BUNDLE  # stdout stays clean JSON


def test_main_output_dir_writes_verbatim_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = json.dumps(SAMPLE_BUNDLE).encode()
    out_dir = tmp_path / "restored"

    with patch(
        "sys.argv",
        ["get_bundle.py"] + _config_args(tmp_path, ["--output-dir", str(out_dir)]),
    ):
        with patch("get_bundle.urlopen", lambda req: _mock_response(body)):
            get_bundle.main()

    skill_dir = out_dir / "demo-api"
    for filename, contents in SAMPLE_FILES.items():
        assert (skill_dir / filename).read_text() == contents
    assert "wrote 4 files" in capsys.readouterr().err


def test_main_http_error_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from urllib.error import HTTPError

    err = HTTPError(
        url="http://x",
        code=404,
        msg="Not Found",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b"No simulation found"),
    )

    with patch("sys.argv", ["get_bundle.py"] + _config_args(tmp_path)):
        with patch("get_bundle.urlopen", side_effect=err):
            with pytest.raises(SystemExit) as exc:
                get_bundle.main()

    assert exc.value.code == 1
    assert "404" in capsys.readouterr().err


def test_main_connection_error_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from urllib.error import URLError

    with patch("sys.argv", ["get_bundle.py"] + _config_args(tmp_path)):
        with patch("get_bundle.urlopen", side_effect=URLError("connection refused")):
            with pytest.raises(SystemExit) as exc:
                get_bundle.main()

    assert exc.value.code == 1
    assert "connection refused" in capsys.readouterr().err
