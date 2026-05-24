import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import notify as notify_mod


async def test_notify_skips_when_no_token(monkeypatch):
    monkeypatch.setattr(notify_mod, "BOT_TOKEN", "")
    monkeypatch.setattr(notify_mod, "OWNER_CHAT_ID", 12345)
    await notify_mod.notify_owner("test")  # must not raise


async def test_notify_skips_when_no_chat_id(monkeypatch):
    monkeypatch.setattr(notify_mod, "BOT_TOKEN", "fake-token")
    monkeypatch.setattr(notify_mod, "OWNER_CHAT_ID", None)
    await notify_mod.notify_owner("test")  # must not raise


async def test_notify_sends_message(monkeypatch):
    monkeypatch.setattr(notify_mod, "BOT_TOKEN", "fake-token")
    monkeypatch.setattr(notify_mod, "OWNER_CHAT_ID", 99999)

    sent = []

    # aiohttp session.post() is a sync call returning an async context manager
    mock_resp = AsyncMock()
    mock_resp.ok = True
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    def _post(url, json=None, **kwargs):
        sent.append(json)
        return mock_resp

    mock_session.post.side_effect = _post

    with patch("aiohttp.ClientSession", return_value=mock_session):
        await notify_mod.notify_owner("hello world")

    assert len(sent) == 1
    assert sent[0]["text"] == "hello world"
    assert sent[0]["chat_id"] == 99999


async def test_notify_suppresses_network_error(monkeypatch):
    monkeypatch.setattr(notify_mod, "BOT_TOKEN", "fake-token")
    monkeypatch.setattr(notify_mod, "OWNER_CHAT_ID", 99999)

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.post.side_effect = OSError("network error")

    with patch("aiohttp.ClientSession", return_value=mock_session):
        await notify_mod.notify_owner("test")  # must not raise
