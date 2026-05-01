"""Tests for org-aware context + header propagation in the CLI."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from deepalpha.auth import Credentials
from deepalpha.clients.basement import BasementClient
from deepalpha.context import (
    _active_org_id_context,
    get_active_org_id,
    set_active_org_id,
)


@pytest.fixture(autouse=True)
def _reset_org_context():
    """Ensure each test starts with no active org set."""
    token = _active_org_id_context.set(None)
    try:
        yield
    finally:
        _active_org_id_context.reset(token)


def test_set_and_get_active_org_id():
    assert get_active_org_id() is None
    set_active_org_id("00000000-0000-0000-0000-000000000001")
    assert get_active_org_id() == "00000000-0000-0000-0000-000000000001"
    set_active_org_id(None)
    assert get_active_org_id() is None


def test_headers_include_x_org_id_from_context():
    client = BasementClient()
    set_active_org_id("11111111-1111-1111-1111-111111111111")
    headers = client._headers("token-123")
    assert headers["Authorization"] == "Bearer token-123"
    assert headers["X-Org-Id"] == "11111111-1111-1111-1111-111111111111"


def test_headers_omit_x_org_id_when_unset():
    client = BasementClient()
    headers = client._headers("token-abc")
    assert "X-Org-Id" not in headers


def test_headers_explicit_org_id_wins_over_context():
    client = BasementClient()
    set_active_org_id("ctx-org")
    headers = client._headers("token", org_id="explicit-org")
    assert headers["X-Org-Id"] == "explicit-org"


def test_headers_explicit_empty_string_suppresses_x_org_id():
    """list_organizations passes org_id='' to avoid scoping the list call."""
    client = BasementClient()
    set_active_org_id("ctx-org")
    headers = client._headers("token", org_id="")
    assert "X-Org-Id" not in headers


def test_credentials_roundtrip_preserves_pinned_org(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    from deepalpha import auth as auth_mod

    # Force the deepalpha dir under tmp_path.
    monkeypatch.setattr(auth_mod, "get_deepalpha_dir", lambda: tmp_path)

    creds = Credentials(
        cli_token="cli-tok",
        user_id="user-1",
        email="a@b.c",
        pinned_org_id="22222222-2222-2222-2222-222222222222",
    )
    auth_mod.save_credentials(creds)
    loaded = auth_mod.load_credentials()
    assert loaded is not None
    assert loaded.pinned_org_id == "22222222-2222-2222-2222-222222222222"


def test_set_pinned_org_updates_existing_credentials(tmp_path: Path, monkeypatch):
    from deepalpha import auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_deepalpha_dir", lambda: tmp_path)

    auth_mod.save_credentials(Credentials(cli_token="t", user_id=None, email=None))
    assert auth_mod.set_pinned_org("new-org") is True

    raw = json.loads((tmp_path / "credentials.json").read_text())
    assert raw["pinned_org_id"] == "new-org"


def test_set_pinned_org_noop_when_unauthenticated(tmp_path: Path, monkeypatch):
    from deepalpha import auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_deepalpha_dir", lambda: tmp_path)
    assert auth_mod.set_pinned_org("x") is False


def test_credentials_from_dict_defaults_pinned_org_to_none():
    creds = Credentials.from_dict(
        {"cli_token": "t", "user_id": None, "email": None}
    )
    assert creds.pinned_org_id is None


def test_org_context_isolated_per_asyncio_task():
    """ContextVars must not leak between concurrent tasks."""

    async def set_and_read(org: str) -> str | None:
        set_active_org_id(org)
        await asyncio.sleep(0)
        return get_active_org_id()

    async def run() -> list[str | None]:
        return await asyncio.gather(
            set_and_read("a"),
            set_and_read("b"),
        )

    results = asyncio.run(run())
    assert set(results) == {"a", "b"}
