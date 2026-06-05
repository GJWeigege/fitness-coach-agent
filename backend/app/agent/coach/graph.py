from langgraph.graph import END, START, StateGraph

from app.agent.coach.nodes.apply_guardrails import apply_guardrails_node
from app.agent.coach.nodes.coach_chitchat import coach_chitchat_node
from app.agent.coach.nodes.dispatch_sub_agents import (
    route_after_plan_execute,
    serial_dispatch_node,
)
from app.agent.coach.nodes.knowledge_prefetch import knowledge_prefetch_node
from app.agent.coach.nodes.load_profile import load_profile_node
from app.agent.coach.nodes.persist_turn import persist_turn_node
from app.agent.coach.nodes.plan_execute import plan_execute_node
from app.agent.coach.nodes.route_intent import route_intent_node
from app.agent.coach.nodes.safety_review import safety_review_node
from app.agent.coach.nodes.sub_agent import sub_agent_node
from app.agent.coach.nodes.synthesize import synthesize_node
from app.agent.coach.state import CoachState


def build_coach_graph():
    workflow = StateGraph(CoachState)

    workflow.add_node("load_profile", load_profile_node)
    workflow.add_node("route_intent", route_intent_node)
    workflow.add_node("plan_execute", plan_execute_node)
    workflow.add_node("sub_agent", sub_agent_node)
    workflow.add_node("serial_dispatch", serial_dispatch_node)
    workflow.add_node("coach_chitchat", coach_chitchat_node)
    workflow.add_node("knowledge_prefetch", knowledge_prefetch_node)
    workflow.add_node("safety_review", safety_review_node)
    workflow.add_node("synthesize", synthesize_node)
    workflow.add_node("apply_guardrails", apply_guardrails_node)
    workflow.add_node("persist_turn", persist_turn_node)

    workflow.add_edge(START, "load_profile")
    workflow.add_edge("load_profile", "route_intent")
    workflow.add_edge("route_intent", "plan_execute")
    workflow.add_conditional_edges(
        "plan_execute",
        route_after_plan_execute,
        ["coach_chitchat", "knowledge_prefetch", "sub_agent", "serial_dispatch"],
    )
    workflow.add_edge("knowledge_prefetch", "coach_chitchat")
    workflow.add_edge("coach_chitchat", "safety_review")
    workflow.add_edge("sub_agent", "safety_review")
    workflow.add_edge("serial_dispatch", "safety_review")
    workflow.add_edge("safety_review", "synthesize")
    workflow.add_edge("synthesize", "apply_guardrails")
    workflow.add_edge("apply_guardrails", "persist_turn")
    workflow.add_edge("persist_turn", END)

    return workflow.compile()
