from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.rate_limit import RateLimitRule
from tests.test_auth import auth_headers, bootstrap_admin

EMBED_DIM = get_settings().embedding_dim


class MockDashScopeClient:
    async def embedding(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * EMBED_DIM for _ in texts]


async def create_kb_editor(client: AsyncClient) -> dict:
    admin = await bootstrap_admin(client)
    response = await client.post(
        "/auth/users",
        headers=auth_headers(admin["access_token"]),
        json={
            "username": "kb_editor_user",
            "password": "Demo@123456",
            "role": "kb_editor",
        },
    )
    assert response.status_code == 200, response.text
    login = await client.post(
        "/auth/login",
        json={"username": "kb_editor_user", "password": "Demo@123456"},
    )
    assert login.status_code == 200, login.text
    return login.json()


@pytest.fixture
def mock_dashscope_client():
    with patch("app.api.knowledge.DashScopeClient", MockDashScopeClient):
        yield


@pytest.mark.asyncio
async def test_list_documents_requires_knowledge_read(client: AsyncClient):
    await bootstrap_admin(client)
    registered = await client.post(
        "/auth/register",
        json={"username": "no_kb_user", "password": "Demo@123456"},
    )
    token = registered.json()["access_token"]
    response = await client.get("/knowledge/documents", headers=auth_headers(token))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_documents_empty(client: AsyncClient, mock_dashscope_client):
    kb = await create_kb_editor(client)
    response = await client.get("/knowledge/documents", headers=auth_headers(kb["access_token"]))
    assert response.status_code == 200
    assert response.json()["documents"] == []


@pytest.mark.asyncio
async def test_upload_and_list_document(client: AsyncClient, mock_dashscope_client, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    kb = await create_kb_editor(client)
    headers = auth_headers(kb["access_token"])

    content = "\n".join([f"训练建议段落{i} " + ("z" * 80) for i in range(1, 4)])
    files = {"file": ("coach-tips.md", content.encode("utf-8"), "text/markdown")}
    upload = await client.post("/knowledge/upload", headers=headers, files=files)
    assert upload.status_code == 200, upload.text
    body = upload.json()
    assert body["title"] == "coach-tips.md"
    assert body["chunks"] >= 1

    listed = await client.get("/knowledge/documents", headers=headers)
    assert listed.status_code == 200
    docs = listed.json()["documents"]
    assert len(docs) == 1
    assert docs[0]["id"] == body["document_id"]
    assert docs[0]["chunk_count"] == body["chunks"]
    assert docs[0]["status"] == "indexed"


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_type(client: AsyncClient, mock_dashscope_client, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    kb = await create_kb_editor(client)
    files = {"file": ("bad.exe", b"binary", "application/octet-stream")}
    response = await client.post(
        "/knowledge/upload",
        headers=auth_headers(kb["access_token"]),
        files=files,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_requires_knowledge_write(client: AsyncClient, mock_dashscope_client, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    await bootstrap_admin(client)
    registered = await client.post(
        "/auth/register",
        json={"username": "plain_user", "password": "Demo@123456"},
    )
    token = registered.json()["access_token"]
    files = {"file": ("tips.md", b"hello", "text/markdown")}
    response = await client.post("/knowledge/upload", headers=auth_headers(token), files=files)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reindex_document(client: AsyncClient, mock_dashscope_client, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    kb = await create_kb_editor(client)
    headers = auth_headers(kb["access_token"])

    content = "段落一\n段落二\n段落三"
    upload = await client.post(
        "/knowledge/upload",
        headers=headers,
        files={"file": ("reindex.md", content.encode("utf-8"), "text/markdown")},
    )
    assert upload.status_code == 200
    doc_id = upload.json()["document_id"]

    reindex = await client.post(f"/knowledge/documents/{doc_id}/reindex", headers=headers)
    assert reindex.status_code == 200
    assert reindex.json()["document_id"] == doc_id
    assert reindex.json()["chunks"] >= 1


@pytest.mark.asyncio
async def test_reindex_requires_knowledge_reindex(client: AsyncClient, mock_dashscope_client, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    admin = await bootstrap_admin(client)
    admin_headers = auth_headers(admin["access_token"])

    upload = await client.post(
        "/knowledge/upload",
        headers=admin_headers,
        files={"file": ("admin-doc.md", b"content", "text/markdown")},
    )
    assert upload.status_code == 200
    doc_id = upload.json()["document_id"]

    writer = await client.post(
        "/auth/users",
        headers=admin_headers,
        json={
            "username": "kb_writer",
            "password": "Demo@123456",
            "role": "user",
            "custom_permissions": ["knowledge:read", "knowledge:write"],
        },
    )
    assert writer.status_code == 200
    login = await client.post(
        "/auth/login",
        json={"username": "kb_writer", "password": "Demo@123456"},
    )
    writer_token = login.json()["access_token"]
    me = await client.get("/auth/me", headers=auth_headers(writer_token))
    assert "knowledge:reindex" not in me.json()["permissions"]

    response = await client.post(f"/knowledge/documents/{doc_id}/reindex", headers=auth_headers(writer_token))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_upload_rate_limit(client: AsyncClient, mock_dashscope_client, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    kb = await create_kb_editor(client)
    headers = auth_headers(kb["access_token"])
    files = {"file": ("rate.md", b"rate limit test", "text/markdown")}
    tight_limit = RateLimitRule(max_requests=2, window_seconds=60)

    with (
        patch("app.api.knowledge.UPLOAD_RATE", tight_limit),
        patch("app.api.knowledge.enforce_rate_limit", lambda *_a, **_k: None),
    ):
        first = await client.post("/knowledge/upload", headers=headers, files=files)
        second = await client.post("/knowledge/upload", headers=headers, files=files)
        third = await client.post("/knowledge/upload", headers=headers, files=files)
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429


@pytest.mark.asyncio
async def test_reindex_rate_limit(client: AsyncClient, mock_dashscope_client, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    kb = await create_kb_editor(client)
    headers = auth_headers(kb["access_token"])

    with patch("app.api.knowledge.UPLOAD_RATE", RateLimitRule(max_requests=100, window_seconds=60)):
        upload = await client.post(
            "/knowledge/upload",
            headers=headers,
            files={"file": ("reindex-rate.md", b"content for reindex", "text/markdown")},
        )
    assert upload.status_code == 200
    doc_id = upload.json()["document_id"]
    tight_limit = RateLimitRule(max_requests=2, window_seconds=60)

    with (
        patch("app.api.knowledge.REINDEX_RATE", tight_limit),
        patch("app.api.knowledge.enforce_rate_limit", lambda *_a, **_k: None),
    ):
        first = await client.post(f"/knowledge/documents/{doc_id}/reindex", headers=headers)
        second = await client.post(f"/knowledge/documents/{doc_id}/reindex", headers=headers)
        third = await client.post(f"/knowledge/documents/{doc_id}/reindex", headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
