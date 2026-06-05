from typing import Any

from app.agent.tools.base import ToolContext
from app.services.rag_service import RagService


class KnowledgeSearchTool:
    name = "knowledge_search"
    description = "在运动健康知识库中检索训练、营养、安全与恢复相关片段。"

    def __init__(self, rag_service: RagService) -> None:
        self.rag_service = rag_service

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "检索 query"},
                        "top_k": {"type": "integer", "description": "返回条数，可选"},
                    },
                    "required": ["query"],
                },
            },
        }

    async def run(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict:
        query = str(arguments.get("query", "")).strip()
        if not ctx.use_rag:
            return {"citations": [], "output_preview": "知识库检索已关闭"}
        top_k = arguments.get("top_k")
        citations = await self.rag_service.retrieve(
            db=ctx.db,
            query=query,
            top_k=top_k,
            session_id=ctx.session_id,
            message_id=ctx.message_id,
        )
        preview = "; ".join(c["content"][:80] for c in citations[:3])
        return {"citations": citations, "output_preview": preview or "无结果"}
