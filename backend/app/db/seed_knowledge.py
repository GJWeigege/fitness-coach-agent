import hashlib
import logging
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import KnowledgeDocument
from app.llm.dashscope_client import DashScopeClient
from app.services.ingest_service import IngestService

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "data" / "knowledge"

COACH_KNOWLEDGE_FILES: tuple[str, ...] = (
    "训练计划与周期化.md",
    "营养与恢复.md",
    "损伤预防与安全.md",
    "睡眠与过度训练.md",
    "常见问题FAQ.md",
)


class EmbeddingClient(Protocol):
    async def embedding(self, texts: list[str]) -> list[list[float]]: ...


def _file_content_hash(file_path: Path) -> str:
    text = file_path.read_text(encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resolve_knowledge_files() -> list[Path]:
    if not KNOWLEDGE_DIR.is_dir():
        return []
    by_name = {path.name: path for path in KNOWLEDGE_DIR.glob("*.md")}
    return [by_name[name] for name in COACH_KNOWLEDGE_FILES if name in by_name]


def _create_ingest_service(llm_client: EmbeddingClient | None) -> IngestService | None:
    if llm_client is not None:
        return IngestService(llm_client=llm_client)  # type: ignore[arg-type]
    settings = get_settings()
    if not settings.dashscope_api_key or settings.dashscope_api_key.startswith("replace"):
        logger.warning("未配置 DASHSCOPE_API_KEY，跳过知识库演示数据导入。")
        return None
    try:
        return IngestService(llm_client=DashScopeClient())
    except ValueError as exc:
        logger.warning("无法初始化嵌入客户端，跳过知识库导入: %s", exc)
        return None


async def seed_demo_knowledge(
    db: AsyncSession,
    *,
    llm_client: EmbeddingClient | None = None,
) -> int:
    """导入 backend/data/knowledge 下教练域演示文档（按标题与内容哈希去重）。"""
    files = _resolve_knowledge_files()
    if not files:
        logger.warning("知识库演示目录不存在或缺少设计文档: %s", KNOWLEDGE_DIR)
        return 0

    service = _create_ingest_service(llm_client)
    if service is None:
        return 0

    rows = (await db.execute(select(KnowledgeDocument.title, KnowledgeDocument.content_hash))).all()
    existing_titles = {row[0] for row in rows}
    existing_hashes = {row[1] for row in rows}

    imported = 0
    for file_path in files:
        title = file_path.stem
        content_hash = _file_content_hash(file_path)
        if title in existing_titles or content_hash in existing_hashes:
            continue
        try:
            await service.ingest_file(db=db, file_path=file_path, title=title)
            existing_titles.add(title)
            existing_hashes.add(content_hash)
            imported += 1
        except ValueError as exc:
            logger.warning("导入知识库文档失败 %s: %s", file_path.name, exc)

    if imported:
        await db.flush()
    return imported
