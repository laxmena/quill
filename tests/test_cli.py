"""Tests for cli.py using Click's test runner."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

import cli


@pytest.fixture
def runner():
    return CliRunner()


# ── status ────────────────────────────────────────────────────────────────────

def test_status_shows_inbox_counts(runner, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "2024-05-10_090000_note.txt").write_text("morning")
    (inbox / "2024-05-10_150000_voice.ogg").write_bytes(b"audio")
    monkeypatch.setattr(cli, "INBOX_DIR", inbox)
    monkeypatch.setattr(cli, "BIOGRAPHIES_DIR", tmp_path / "biographies")
    with patch("processor.load_state", return_value={"last_run_date": None, "biography_count": 0}):
        result = runner.invoke(cli.cli, ["status"])
    assert result.exit_code == 0
    assert "2" in result.output  # 2 inbox items


def test_status_shows_last_biography_date(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "INBOX_DIR", tmp_path / "inbox")
    monkeypatch.setattr(cli, "BIOGRAPHIES_DIR", tmp_path / "biographies")
    with patch("processor.load_state", return_value={"last_run_date": "2024-05-14", "biography_count": 1}):
        result = runner.invoke(cli.cli, ["status"])
    assert "2024-05-14" in result.output


# ── set-webhook ───────────────────────────────────────────────────────────────

def test_set_webhook_missing_env_exits(runner, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_URL", raising=False)
    result = runner.invoke(cli.cli, ["set-webhook"])
    assert result.exit_code != 0
    assert "TELEGRAM_BOT_TOKEN" in result.output


def test_set_webhook_success(runner, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.com")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"ok": True}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = runner.invoke(cli.cli, ["set-webhook"])
    assert result.exit_code == 0
    assert "✓" in result.output


def test_set_webhook_api_failure_exits(runner, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.com")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"ok": False, "description": "Bad token"}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = runner.invoke(cli.cli, ["set-webhook"])
    assert result.exit_code != 0
    assert "Bad token" in result.output


def test_set_webhook_network_error_exits(runner, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.com")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        result = runner.invoke(cli.cli, ["set-webhook"])
    assert result.exit_code != 0
    assert "connection refused" in result.output


# ── set-commands ──────────────────────────────────────────────────────────────

def test_set_commands_missing_token_exits(runner, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    result = runner.invoke(cli.cli, ["set-commands"])
    assert result.exit_code != 0
    assert "TELEGRAM_BOT_TOKEN" in result.output


def test_set_commands_success(runner, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"ok": True}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = runner.invoke(cli.cli, ["set-commands"])
    assert result.exit_code == 0
    assert "✓" in result.output


def test_set_commands_network_error_exits(runner, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
        result = runner.invoke(cli.cli, ["set-commands"])
    assert result.exit_code != 0
    assert "timeout" in result.output


# ── process-inbox ─────────────────────────────────────────────────────────────

def test_process_inbox_cmd_shows_count(runner):
    from unittest.mock import AsyncMock
    with patch("processor.process_inbox", new=AsyncMock(return_value=(3, []))):
        result = runner.invoke(cli.cli, ["process-inbox"])
    assert "3" in result.output
