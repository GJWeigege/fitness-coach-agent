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


# ---------------------------------------------------------------------------
# 实体：与 backend/data/knowledge 主题对齐（动作 / 伤病 / 营养）
# ---------------------------------------------------------------------------
COACH_GRAPH_ENTITIES: tuple[SeedEntitySpec, ...] = (
    # 伤病
    SeedEntitySpec("膝盖损伤", "injury", {"body_part": "knee"}),
    SeedEntitySpec("前交叉韧带损伤", "injury", {"body_part": "knee", "alias": "ACL"}),
    SeedEntitySpec("髌股疼痛", "injury", {"body_part": "knee"}),
    SeedEntitySpec("腰椎间盘突出", "injury", {"body_part": "lumbar"}),
    SeedEntitySpec("腰背痛", "injury", {"body_part": "lumbar"}),
    SeedEntitySpec("肩袖损伤", "injury", {"body_part": "shoulder"}),
    SeedEntitySpec("肩峰撞击", "injury", {"body_part": "shoulder"}),
    SeedEntitySpec("踝扭伤", "injury", {"body_part": "ankle"}),
    SeedEntitySpec("跟腱病", "injury", {"body_part": "achilles"}),
    # 下肢与复合动作
    SeedEntitySpec("深蹲", "exercise", {"pattern": "squat", "muscle": "leg"}),
    SeedEntitySpec("硬拉", "exercise", {"pattern": "hinge", "muscle": "posterior_chain"}),
    SeedEntitySpec("罗马尼亚硬拉", "exercise", {"pattern": "hinge"}),
    SeedEntitySpec("单腿罗马尼亚硬拉", "exercise", {"pattern": "hinge", "unilateral": True}),
    SeedEntitySpec("箱式深蹲", "exercise", {"pattern": "box_squat"}),
    SeedEntitySpec("暂停深蹲", "exercise", {"pattern": "pause_squat"}),
    SeedEntitySpec("高脚杯深蹲", "exercise", {"pattern": "goblet_squat"}),
    SeedEntitySpec("保加利亚分腿蹲", "exercise", {"pattern": "split_squat"}),
    SeedEntitySpec("腿举", "exercise", {"pattern": "leg_press"}),
    SeedEntitySpec("臀桥", "exercise", {"pattern": "glute_bridge"}),
    # 上肢推/拉
    SeedEntitySpec("卧推", "exercise", {"pattern": "horizontal_push"}),
    SeedEntitySpec("哑铃卧推", "exercise", {"pattern": "horizontal_push"}),
    SeedEntitySpec("地板卧推", "exercise", {"pattern": "horizontal_push"}),
    SeedEntitySpec("过头推举", "exercise", {"pattern": "vertical_push"}),
    SeedEntitySpec("地雷管推举", "exercise", {"pattern": "landmine_press"}),
    SeedEntitySpec("引体向上", "exercise", {"pattern": "vertical_pull"}),
    SeedEntitySpec("弹力带划船", "exercise", {"pattern": "horizontal_pull"}),
    SeedEntitySpec("面拉", "exercise", {"pattern": "rear_delt"}),
    # 有氧与爆发力
    SeedEntitySpec("跑步", "exercise", {"pattern": "cardio"}),
    SeedEntitySpec("固定单车", "exercise", {"pattern": "cardio"}),
    SeedEntitySpec("泳池行走", "exercise", {"pattern": "cardio", "low_impact": True}),
    SeedEntitySpec("箱跳", "exercise", {"pattern": "plyometric"}),
    SeedEntitySpec("北欧腘绳肌弯举", "exercise", {"pattern": "hamstring"}),
    # 营养与补剂
    SeedEntitySpec("蛋白质", "nutrient", {"macro": "protein"}),
    SeedEntitySpec("碳水化合物", "nutrient", {"macro": "carb"}),
    SeedEntitySpec("肌酸", "nutrient", {"supplement": "creatine"}),
    SeedEntitySpec("维生素D", "nutrient", {"supplement": "vitamin_d"}),
    SeedEntitySpec("咖啡因", "nutrient", {"supplement": "caffeine"}),
    SeedEntitySpec("欧米伽3", "nutrient", {"supplement": "omega_3"}),
    SeedEntitySpec("支链氨基酸", "nutrient", {"supplement": "bcaa"}),
    SeedEntitySpec("电解质", "nutrient", {"supplement": "electrolyte"}),
)

# ---------------------------------------------------------------------------
# 关系：禁忌 / 替代 / 营养支持 / 互补（深蹲-硬拉等）
# ---------------------------------------------------------------------------
COACH_GRAPH_EDGES: tuple[SeedEdgeSpec, ...] = (
    # 禁忌 contraindicated_for（动作 -> 伤病）
    SeedEdgeSpec("深蹲", "膝盖损伤", "contraindicated_for", 0.9),
    SeedEdgeSpec("深蹲", "前交叉韧带损伤", "contraindicated_for", 0.92),
    SeedEdgeSpec("深蹲", "髌股疼痛", "contraindicated_for", 0.88),
    SeedEdgeSpec("保加利亚分腿蹲", "前交叉韧带损伤", "contraindicated_for", 0.75),
    SeedEdgeSpec("箱跳", "前交叉韧带损伤", "contraindicated_for", 0.95),
    SeedEdgeSpec("硬拉", "腰椎间盘突出", "contraindicated_for", 0.9),
    SeedEdgeSpec("硬拉", "腰背痛", "contraindicated_for", 0.85),
    SeedEdgeSpec("罗马尼亚硬拉", "腰背痛", "contraindicated_for", 0.7),
    SeedEdgeSpec("过头推举", "肩袖损伤", "contraindicated_for", 0.88),
    SeedEdgeSpec("过头推举", "肩峰撞击", "contraindicated_for", 0.9),
    SeedEdgeSpec("卧推", "肩袖损伤", "contraindicated_for", 0.65),
    SeedEdgeSpec("引体向上", "肩袖损伤", "contraindicated_for", 0.6),
    SeedEdgeSpec("跑步", "踝扭伤", "contraindicated_for", 0.9),
    SeedEdgeSpec("跑步", "跟腱病", "contraindicated_for", 0.88),
    SeedEdgeSpec("跑步", "膝盖损伤", "contraindicated_for", 0.7),
    SeedEdgeSpec("箱跳", "踝扭伤", "contraindicated_for", 0.92),
    SeedEdgeSpec("箱跳", "跟腱病", "contraindicated_for", 0.9),
    # 替代 alternative_for（替代动作 -> 原动作）
    SeedEdgeSpec("箱式深蹲", "深蹲", "alternative_for", 0.85),
    SeedEdgeSpec("高脚杯深蹲", "深蹲", "alternative_for", 0.8),
    SeedEdgeSpec("暂停深蹲", "深蹲", "alternative_for", 0.78),
    SeedEdgeSpec("保加利亚分腿蹲", "深蹲", "alternative_for", 0.8),
    SeedEdgeSpec("腿举", "深蹲", "alternative_for", 0.75),
    SeedEdgeSpec("臀桥", "深蹲", "alternative_for", 0.7),
    SeedEdgeSpec("罗马尼亚硬拉", "硬拉", "alternative_for", 0.85),
    SeedEdgeSpec("单腿罗马尼亚硬拉", "硬拉", "alternative_for", 0.78),
    SeedEdgeSpec("臀桥", "硬拉", "alternative_for", 0.72),
    SeedEdgeSpec("哑铃卧推", "卧推", "alternative_for", 0.82),
    SeedEdgeSpec("地板卧推", "卧推", "alternative_for", 0.8),
    SeedEdgeSpec("地雷管推举", "过头推举", "alternative_for", 0.85),
    SeedEdgeSpec("弹力带划船", "引体向上", "alternative_for", 0.8),
    SeedEdgeSpec("固定单车", "跑步", "alternative_for", 0.85),
    SeedEdgeSpec("泳池行走", "跑步", "alternative_for", 0.8),
    SeedEdgeSpec("腿举", "箱跳", "alternative_for", 0.7),
    SeedEdgeSpec("臀桥", "箱跳", "alternative_for", 0.65),
    # 互补 complements（同周期训练常配对）
    SeedEdgeSpec("深蹲", "硬拉", "complements", 0.88),
    SeedEdgeSpec("卧推", "引体向上", "complements", 0.85),
    SeedEdgeSpec("面拉", "卧推", "complements", 0.75),
    # 营养支持 supports_*（营养素 -> 动作/场景）
    SeedEdgeSpec("蛋白质", "深蹲", "supports_recovery", 0.85),
    SeedEdgeSpec("蛋白质", "硬拉", "supports_recovery", 0.85),
    SeedEdgeSpec("蛋白质", "引体向上", "supports_recovery", 0.82),
    SeedEdgeSpec("蛋白质", "跑步", "supports_recovery", 0.8),
    SeedEdgeSpec("碳水化合物", "深蹲", "supports_energy", 0.8),
    SeedEdgeSpec("碳水化合物", "跑步", "supports_energy", 0.88),
    SeedEdgeSpec("肌酸", "硬拉", "supports_performance", 0.85),
    SeedEdgeSpec("肌酸", "深蹲", "supports_performance", 0.82),
    SeedEdgeSpec("肌酸", "卧推", "supports_performance", 0.8),
    SeedEdgeSpec("维生素D", "深蹲", "supports_bone_health", 0.75),
    SeedEdgeSpec("咖啡因", "跑步", "supports_performance", 0.7),
    SeedEdgeSpec("欧米伽3", "肩袖损伤", "supports_recovery", 0.65),
    SeedEdgeSpec("电解质", "跑步", "supports_energy", 0.78),
    SeedEdgeSpec("支链氨基酸", "深蹲", "supports_recovery", 0.55),
    # 预防性关联（动作 -> 伤病，低权重表示「有助于预防」用 supports 变体）
    SeedEdgeSpec("北欧腘绳肌弯举", "前交叉韧带损伤", "supports_recovery", 0.72),
    SeedEdgeSpec("面拉", "肩袖损伤", "supports_recovery", 0.78),
)


def _entity_embed_text(spec: SeedEntitySpec) -> str:
    """实体嵌入文本：类型 + 名称 + 关键属性，便于与知识 chunk 匹配。"""
    parts = [spec.entity_type, spec.name]
    if spec.properties:
        parts.extend(str(v) for v in spec.properties.values())
    return ":".join(parts)


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
    """写入教练域图谱实体与边；已存在同名同类型实体会跳过，缺失的边会补全。"""
    client = _create_embedding_client(llm_client)
    if client is None:
        return 0

    existing_rows = (
        await db.execute(select(GraphEntity.name, GraphEntity.entity_type))
    ).all()
    existing_keys = {(row[0], row[1]) for row in existing_rows}

    to_create = [spec for spec in COACH_GRAPH_ENTITIES if (spec.name, spec.entity_type) not in existing_keys]

    name_to_id: dict[str, uuid.UUID] = {
        row.name: row.id for row in (await db.scalars(select(GraphEntity))).all()
    }

    created_entities = 0
    if to_create:
        vectors = await client.embedding([_entity_embed_text(spec) for spec in to_create])
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
        created_entities = len(to_create)

    created_edges = await _ensure_edges(db, name_to_id=name_to_id)
    if created_entities or created_edges:
        await db.flush()
    return created_entities + created_edges


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
