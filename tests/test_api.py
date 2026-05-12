"""Webhook + signature verification + manual review API tests."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from prsquad import config, main


@pytest.fixture(autouse=True)
def reset_settings(monkeypatch):
    """Force a fresh Settings instance per test (env vars can drift)."""
    monkeypatch.setattr(config, "_settings", None)


@pytest.fixture
def client():
    return TestClient(main.app)


def test_health_returns_provider(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["llm_provider"] == "stub"


def test_manual_review_works_in_demo_mode(client):
    payload = {"owner": "octocat", "repo": "demo", "pr_number": 42, "diff": "+ hi"}
    r = client.post("/v1/review", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["pr_number"] == 42
    assert len(body["reports"]) == 4
    assert body["posted_to_github"] is False  # default


def test_webhook_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setenv("PRSQUAD_WEBHOOK_SECRET", "shhh")
    monkeypatch.setattr(config, "_settings", None)
    payload = b'{"action":"opened"}'
    r = client.post(
        "/v1/webhook/github",
        content=payload,
        headers={"X-Hub-Signature-256": "sha256=deadbeef", "X-GitHub-Event": "pull_request"},
    )
    assert r.status_code == 401


def test_webhook_accepts_good_signature(client, monkeypatch):
    monkeypatch.setenv("PRSQUAD_WEBHOOK_SECRET", "shhh")
    monkeypatch.setattr(config, "_settings", None)
    payload = json.dumps({
        "action": "opened",
        "pull_request": {"number": 7, "title": "feat: it"},
        "repository": {"full_name": "octocat/demo"},
    }).encode()
    sig = "sha256=" + hmac.new(b"shhh", payload, hashlib.sha256).hexdigest()
    r = client.post(
        "/v1/webhook/github",
        content=payload,
        headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "pull_request"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["reports"] == 4
