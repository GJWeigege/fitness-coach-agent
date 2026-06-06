import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.agent.tools.base import ToolContext
from app.agent.tools.alternatives import SuggestAlternativesTool
from app.agent.tools.contraindication import CheckContraindicationTool
from app.agent.tools.graph_lookup import GraphLookupTool
from app.agent.tools.knowledge import KnowledgeSearchTool
from app.agent.tools.macros import CalculateMacrosTool
from app.agent.tools.profile import GetUserProfileTool
from app.agent.tools.training_log import LogTrainingTool
from app.core.config import Settings
from app.db.models import GraphEdge, GraphEntity, KnowledgeChunk, KnowledgeDocument, User, UserProfile
from app.services.rag_service import RagService

EMBEDDING_DIM = 1024


def _vec(*head: float) -> list[float]:
    return list(head) + [0.0] * (EMBEDDING_DIM - len(head))


class MockLLM:
    async def embedding(self, texts: list[str]) -> list[list[float]]:
        return [_vec(1.0, 0.0) for _ in texts]


@pytest.fixture
def tool_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        embedding_dim=EMBEDDING_DIM,
        rag_top_k=4,
        graph_rag_enabled=True,
    )
    monkeypatch.setattr("app.services.rag_service.get_settings", lambda: settings)
    monkeypatch.setattr("app.agent.tools.graph_lookup.get_settings", lambda: settings)
    return settings


def _ctx(db_session, *, use_rag: bool = True) -> ToolContext:
    user_id = uuid.uuid4()
    return ToolContext(
        db=db_session,
        user_id=user_id,
        session_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        use_rag=use_rag,
    )


async def _seed_user_profile(db_session, user_id: uuid.UUID):
    db_session.add(
        User(
            id=user_id,
            username=f"tooluser_{user_id.hex[:8]}",
            password_hash="h",
            password_salt="s",
        )
    )
    db_session.add(
        UserProfile(
            user_id=user_id,
            age=28,
            sex="male",
            height_cm=175,
            weight_kg=72,
            goals=["增肌"],
            experience_level="intermediate",
            injuries=["膝盖损伤"],
        )
    )
    await db_session.flush()


async def _seed_knowledge(db_session):
    doc = KnowledgeDocument(
        title="Coach KB",
        source_path="data/knowledge/squat.md",
        content_hash="hash-tool",
    )
    db_session.add(doc)
    await db_session.flush()
    db_session.add(
        KnowledgeChunk(
            document_id=doc.id,
            chunk_index=0,
            content="深蹲训练注意膝盖对齐。",
            embedding=_vec(1.0, 0.0),
        )
    )
    await db_session.flush()


async def _seed_graph(db_session):
    squat = GraphEntity(name="深蹲", entity_type="exercise", embedding=_vec(1.0, 0.0))
    knee = GraphEntity(name="膝盖损伤", entity_type="injury", embedding=_vec(0.0, 1.0))
    box = GraphEntity(name="箱式深蹲", entity_type="exercise", embedding=_vec(0.8, 0.2))
    db_session.add_all([squat, knee, box])
    await db_session.flush()
    db_session.add_all(
        [
            GraphEdge(
                source_id=squat.id,
                target_id=knee.id,
                relation_type="contraindicated_for",
            ),
            GraphEdge(
                source_id=box.id,
                target_id=squat.id,
                relation_type="alternative_for",
            ),
        ]
    )
    await db_session.flush()
    return squat, knee, box


@pytest.mark.asyncio
async def test_knowledge_search_tool(db_session, tool_settings):
    await _seed_knowledge(db_session)
    ctx = _ctx(db_session)
    tool = KnowledgeSearchTool(RagService(MockLLM()))
    result = await tool.run(ctx, {"query": "深蹲"})
    assert "citations" in result
    assert len(result["citations"]) >= 1


@pytest.mark.asyncio
async def test_knowledge_search_respects_use_rag_false(db_session, tool_settings):
    ctx = _ctx(db_session, use_rag=False)
    tool = KnowledgeSearchTool(RagService(MockLLM()))
    result = await tool.run(ctx, {"query": "深蹲"})
    assert result["citations"] == []


@pytest.mark.asyncio
async def test_check_contraindication_tool(db_session, tool_settings):
    await _seed_graph(db_session)
    ctx = _ctx(db_session)
    tool = CheckContraindicationTool()
    result = await tool.run(ctx, {"exercise": "深蹲", "conditions": ["膝盖损伤"]})
    assert result["contraindicated"] is True
    assert result["reasons"]


@pytest.mark.asyncio
async def test_get_user_profile_tool(db_session):
    ctx = _ctx(db_session)
    await _seed_user_profile(db_session, ctx.user_id)
    tool = GetUserProfileTool()
    result = await tool.run(ctx, {})
    assert result["profile"]["weight_kg"] == 72
    assert "膝盖损伤" in (result["profile"]["injuries"] or [])


@pytest.mark.asyncio
async def test_log_training_tool(db_session):
    ctx = _ctx(db_session)
    await _seed_user_profile(db_session, ctx.user_id)
    tool = LogTrainingTool()
    result = await tool.run(
        ctx,
        {
            "session_date": "2026-06-01",
            "activity_type": "力量训练",
            "duration_min": 45,
            "intensity": "moderate",
            "notes": "练腿日",
        },
    )
    assert result["log"]["activity_type"] == "力量训练"
    assert "已记录" in result["output_preview"]


@pytest.mark.asyncio
async def test_calculate_macros_tool(db_session):
    ctx = _ctx(db_session)
    await _seed_user_profile(db_session, ctx.user_id)
    tool = CalculateMacrosTool()
    result = await tool.run(ctx, {})
    assert result["protein_g"] > 0
    assert result["tdee_kcal"] > result["bmr_kcal"]
    assert "增肌" in result["note"] or result["tdee_kcal"] > 0


@pytest.mark.asyncio
async def test_suggest_alternatives_tool(db_session, tool_settings):
    await _seed_graph(db_session)
    ctx = _ctx(db_session)
    tool = SuggestAlternativesTool()
    result = await tool.run(ctx, {"exercise": "深蹲", "injury_or_limit": "膝盖损伤"})
    assert result["alternatives"]
    names = [a["name"] for a in result["alternatives"]]
    assert "箱式深蹲" in names


@pytest.mark.asyncio
async def test_graph_lookup_tool(db_session, tool_settings):
    squat, _, _ = await _seed_graph(db_session)
    ctx = _ctx(db_session)
    tool = GraphLookupTool()
    result = await tool.run(ctx, {"entity_name": "深蹲"})
    assert "深蹲" in result["entities"]
    assert result["context"] is not None
    assert "contraindicated_for" in result["context"] or squat.name in result["context"]
