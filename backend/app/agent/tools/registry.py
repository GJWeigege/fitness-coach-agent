from typing import Any

from app.agent.tools.alternatives import SuggestAlternativesTool
from app.agent.tools.base import ToolContext
from app.agent.tools.contraindication import CheckContraindicationTool
from app.agent.tools.graph_lookup import GraphLookupTool
from app.agent.tools.knowledge import KnowledgeSearchTool
from app.agent.tools.macros import CalculateMacrosTool
from app.agent.tools.profile import GetUserProfileTool
from app.agent.tools.training_log import LogTrainingTool
from app.core.config import get_settings
from app.services.graph_service import GraphService
from app.services.profile_service import ProfileService
from app.services.rag_service import RagService


class CoachToolRegistry:
    def __init__(
        self,
        knowledge_tool: KnowledgeSearchTool,
        contraindication_tool: CheckContraindicationTool,
        profile_tool: GetUserProfileTool,
        training_log_tool: LogTrainingTool,
        macros_tool: CalculateMacrosTool,
        alternatives_tool: SuggestAlternativesTool,
        graph_lookup_tool: GraphLookupTool | None = None,
    ) -> None:
        self._tools: dict[str, Any] = {
            knowledge_tool.name: knowledge_tool,
            contraindication_tool.name: contraindication_tool,
            profile_tool.name: profile_tool,
            training_log_tool.name: training_log_tool,
            macros_tool.name: macros_tool,
            alternatives_tool.name: alternatives_tool,
        }
        if graph_lookup_tool is not None:
            self._tools[graph_lookup_tool.name] = graph_lookup_tool

    @classmethod
    def build_default(
        cls,
        rag_service: RagService,
        *,
        profile_service: ProfileService | None = None,
        graph_service: GraphService | None = None,
    ) -> "CoachToolRegistry":
        settings = get_settings()
        graph_tool = GraphLookupTool(graph_service) if settings.graph_rag_enabled else None
        return cls(
            knowledge_tool=KnowledgeSearchTool(rag_service),
            contraindication_tool=CheckContraindicationTool(),
            profile_tool=GetUserProfileTool(profile_service),
            training_log_tool=LogTrainingTool(profile_service),
            macros_tool=CalculateMacrosTool(profile_service),
            alternatives_tool=SuggestAlternativesTool(),
            graph_lookup_tool=graph_tool,
        )

    def list_schemas(self, *, agent_key: str | None = None) -> list[dict]:
        del agent_key
        return [tool.schema() for tool in self._tools.values()]

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    async def execute(self, name: str, ctx: ToolContext, arguments: dict[str, Any]) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"未知工具: {name}")
        return await tool.run(ctx, arguments)
