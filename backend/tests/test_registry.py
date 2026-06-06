import uuid

import pytest

from app.agent.tools.base import ToolContext
from app.agent.tools.registry import CoachToolRegistry
from app.core.config import Settings
from app.db.models import KnowledgeChunk, KnowledgeDocument, User, UserProfile
from app.services.rag_service import RagService

EMBEDDING_DIM = 1024


def _vec(*head: float) -> list[float]:
    return list(head) + [0.0] * (EMBEDDING_DIM - len(head))


class MockLLM:
    async def embedding(self, texts: list[str]) -> list[list[float]]:
        return [_vec(1.0) for _ in texts]


@pytest.fixture
def registry_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        embedding_dim=EMBEDDING_DIM,
        graph_rag_enabled=True,
    )
    monkeypatch.setattr("app.services.rag_service.get_settings", lambda: settings)
    monkeypatch.setattr("app.agent.tools.registry.get_settings", lambda: settings)
    monkeypatch.setattr("app.agent.tools.graph_lookup.get_settings", lambda: settings)
    return settings


def _ctx(db_session) -> ToolContext:
    return ToolContext(
        db=db_session,
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        use_rag=True,
    )


def test_tool_context_fields():
    uid = uuid.uuid4()
    ctx = ToolContext(
        db=None,
        user_id=uid,
        session_id=uid,
        message_id=uid,
        run_id=uid,
        use_rag=False,
    )
    assert ctx.use_rag is False


def test_registry_lists_seven_tools(registry_settings):
    registry = CoachToolRegistry.build_default(RagService(MockLLM()))
    schemas = registry.list_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert names == {
        "knowledge_search",
        "check_contraindication",
        "get_user_profile",
        "log_training",
        "calculate_macros",
        "suggest_alternatives",
        "graph_lookup",
    }


def test_registry_without_graph_when_disabled(monkeypatch):
    settings = Settings(dashscope_api_key="test-key", graph_rag_enabled=False)
    monkeypatch.setattr("app.agent.tools.registry.get_settings", lambda: settings)
    registry = CoachToolRegistry.build_default(RagService(MockLLM()))
    names = {s["function"]["name"] for s in registry.list_schemas()}
    assert "graph_lookup" not in names
    assert len(names) == 6


@pytest.mark.asyncio
async def test_registry_execute_knowledge(db_session, registry_settings):
    doc = KnowledgeDocument(
        title="KB",
        source_path="data/knowledge/x.md",
        content_hash="h1",
    )
    db_session.add(doc)
    await db_session.flush()
    db_session.add(
        KnowledgeChunk(
            document_id=doc.id,
            chunk_index=0,
            content="蛋白质摄入建议。",
            embedding=_vec(1.0),
        )
    )
    await db_session.flush()

    registry = CoachToolRegistry.build_default(RagService(MockLLM()))
    ctx = _ctx(db_session)
    result = await registry.execute("knowledge_search", ctx, {"query": "蛋白质"})
    assert result["citations"]


@pytest.mark.asyncio
async def test_registry_execute_unknown_tool(db_session, registry_settings):
    registry = CoachToolRegistry.build_default(RagService(MockLLM()))
    ctx = _ctx(db_session)
    with pytest.raises(ValueError, match="未知工具"):
        await registry.execute("order_lookup", ctx, {})


@pytest.mark.asyncio
async def test_registry_execute_profile(db_session, registry_settings):
    ctx = _ctx(db_session)
    db_session.add(
        User(
            id=ctx.user_id,
            username=f"reg_{ctx.user_id.hex[:8]}",
            password_hash="h",
            password_salt="s",
        )
    )
    db_session.add(UserProfile(user_id=ctx.user_id, weight_kg=80))
    await db_session.flush()

    registry = CoachToolRegistry.build_default(RagService(MockLLM()))
    result = await registry.execute("get_user_profile", ctx, {})
    assert result["profile"]["weight_kg"] == 80
