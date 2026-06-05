import logging
import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import GraphEdge, GraphEntity
from app.llm.dashscope_client import DashScopeClient

logger = logging.getLogger(__name__)


class EmbeddingClient(Protocol):
    async def embedding(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class SeedEntitySpec:
    name: str
    entity_type: str
    properties: dict | None = None


@dataclass(frozen=True)
class SeedEdgeSpec:
    source_name: str
    target_name: str
    relation_type: str
    weight: float = 1.0


COACH_GRAPH_ENTITIES: tuple[SeedEntitySpec, ...] = (
    SeedEntitySpec("膝盖损伤", "injury", {"body_part": "knee"}),
    SeedEntitySpec("腰椎间盘突出", "injury", {"body_part": "lumbar"}),
    SeedEntitySpec("肩袖损伤", "injury", {"body_part": "shoulder"}),
    SeedEntitySpec("深蹲", "exercise", {"pattern": "squat"}),
    SeedEntitySpec("硬拉", "exercise", {"pattern": "hinge"}),
    SeedEntitySpec("保加利亚分腿蹲", "exercise", {"pattern": "split_squat"}),
    SeedEntitySpec("箱式深蹲", "exercise", {"pattern": "box_squat"}),
    SeedEntitySpec("臀桥", "exercise", {"pattern": "glute_bridge"}),
    SeedEntitySpec("蛋白质", "nutrient", {"macro": "protein"}),
    SeedEntitySpec("肌酸", "nutrient", {"supplement": "creatine"}),
    SeedEntitySpec("维生素D", "nutrient", {"supplement": "vitamin_d"}),
    SeedEntitySpec("碳水化合物", "nutrient", {"macro": "carb"}),
)

COACH_GRAPH_EDGES: tuple[SeedEdgeSpec, ...] = (
    SeedEdgeSpec("深蹲", "膝盖损伤", "contraindicated_for", 0.9),
    SeedEdgeSpec("硬拉", "腰椎间盘突出", "contraindicated_for", 0.85),
    SeedEdgeSpec("箱式深蹲", "深蹲", "alternative_for", 0.8),
    SeedEdgeSpec("保加利亚分腿蹲", "深蹲", "alternative_for", 0.75),
    SeedEdgeSpec("臀桥", "深蹲", "alternative_for", 0.7),
    SeedEdgeSpec("蛋白质", "深蹲", "supports_recovery", 0.8),
    SeedEdgeSpec("肌酸", "硬拉", "supports_performance", 0.75),
    SeedEdgeSpec("维生素D", "深蹲", "supports_bone_health", 0.7),
    SeedEdgeSpec("碳水化合物", "深蹲", "supports_energy", 0.65),
)


def _entity_embed_text(spec: SeedEntitySpec) -> str:
    return f"{spec.entity_type}:{spec.name}"


def _create_embedding_client(llm_client: EmbeddingClient | None) -> EmbeddingClient | None:
    if llm_client is not None:
        return llm_client
    settings = get_settings()
    if not settings.dashscope_api_key or settings.dashscope_api_key.startswith("replace"):
        logger.warning("未配置 DASHSCOPE_API_KEY，跳过图谱演示数据导入。")
        return None
    try:
        return DashScopeClient()
    except ValueError as exc:
        logger.warning("无法初始化嵌入客户端，跳过图谱导入: %s", exc)
        return None


async def seed_demo_graph(
    db: AsyncSession,
    *,
    llm_client: EmbeddingClient | None = None,
) -> int:
    """写入教练域图谱实体与边；已存在同名实体会跳过。"""
    client = _create_embedding_client(llm_client)
    if client is None:
        return 0

    existing_rows = (
        await db.execute(select(GraphEntity.name, GraphEntity.entity_type))
    ).all()
    existing_keys = {(row[0], row[1]) for row in existing_rows}

    to_create = [spec for spec in COACH_GRAPH_ENTITIES if (spec.name, spec.entity_type) not in existing_keys]
    if not to_create:
        await _ensure_edges(db)
        return 0

    vectors = await client.embedding([_entity_embed_text(spec) for spec in to_create])
    name_to_id: dict[str, uuid.UUID] = {
        row.name: row.id
        for row in (await db.scalars(select(GraphEntity))).all()
    }

    for spec, vector in zip(to_create, vectors, strict=True):
        entity = GraphEntity(
            name=spec.name,
            entity_type=spec.entity_type,
            properties=spec.properties,
            embedding=vector,
        )
        db.add(entity)
        await db.flush()
        name_to_id[spec.name] = entity.id

    created_edges = await _ensure_edges(db, name_to_id=name_to_id)
    await db.flush()
    return len(to_create) + created_edges


async def _ensure_edges(
    db: AsyncSession,
    *,
    name_to_id: dict | None = None,
) -> int:
    if name_to_id is None:
        name_to_id = {
            row.name: row.id for row in (await db.scalars(select(GraphEntity))).all()
        }

    existing_edges = set(
        (row[0], row[1], row[2])
        for row in (
            await db.execute(
                select(GraphEdge.source_id, GraphEdge.target_id, GraphEdge.relation_type)
            )
        ).all()
    )

    created = 0
    for spec in COACH_GRAPH_EDGES:
        source_id = name_to_id.get(spec.source_name)
        target_id = name_to_id.get(spec.target_name)
        if source_id is None or target_id is None:
            continue
        key = (source_id, target_id, spec.relation_type)
        if key in existing_edges:
            continue
        db.add(
            GraphEdge(
                source_id=source_id,
                target_id=target_id,
                relation_type=spec.relation_type,
                weight=spec.weight,
            )
        )
        existing_edges.add(key)
        created += 1
    return created
