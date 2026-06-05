"""initial

Revision ID: 0001
Revises:
Create Date: 2026-06-05

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("password_salt", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), server_default=sa.text("'user'"), nullable=False),
        sa.Column("custom_permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=False)

    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("turn_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_sessions_user_id"), "chat_sessions", ["user_id"], unique=False)

    op.create_table(
        "knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_documents_content_hash"), "knowledge_documents", ["content_hash"], unique=False)

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assistant_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("intent", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("step_count", sa.Integer(), nullable=False),
        sa.Column("total_latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("memory_compacted", sa.Boolean(), nullable=False),
        sa.Column("dropped_message_count", sa.Integer(), nullable=False),
        sa.Column("memory_summary_updated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_runs_session_id"), "agent_runs", ["session_id"], unique=False)
    op.create_index(op.f("ix_agent_runs_trace_id"), "agent_runs", ["trace_id"], unique=False)

    op.create_table(
        "retrieval_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_retrieval_logs_message_id"), "retrieval_logs", ["message_id"], unique=False)
    op.create_index(op.f("ix_retrieval_logs_session_id"), "retrieval_logs", ["session_id"], unique=False)

    op.create_table(
        "graph_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_graph_entities_entity_type"), "graph_entities", ["entity_type"], unique=False)
    op.create_index(op.f("ix_graph_entities_name"), "graph_entities", ["name"], unique=False)

    op.create_table(
        "benchmark_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "user_profiles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("sex", sa.String(length=16), nullable=True),
        sa.Column("height_cm", sa.Float(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("goals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("experience_level", sa.String(length=32), server_default=sa.text("'beginner'"), nullable=False),
        sa.Column("injuries", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("equipment", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("diet_preference", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "training_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("activity_type", sa.String(length=64), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("intensity", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_training_logs_user_id"), "training_logs", ["user_id"], unique=False)

    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("retrieved_chunks", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("feedback", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_messages_agent_run_id"), "chat_messages", ["agent_run_id"], unique=False)
    op.create_index(op.f("ix_chat_messages_session_id"), "chat_messages", ["session_id"], unique=False)

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_chunks_document_id"), "knowledge_chunks", ["document_id"], unique=False)

    op.create_table(
        "agent_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_steps_run_id"), "agent_steps", ["run_id"], unique=False)

    op.create_table(
        "llm_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_calls_run_id"), "llm_calls", ["run_id"], unique=False)

    op.create_table(
        "graph_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(length=64), nullable=False),
        sa.Column("weight", sa.Float(), server_default=sa.text("1.0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["graph_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["graph_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "target_id", "relation_type", name="uq_graph_edges_source_target_relation"),
    )
    op.create_index(op.f("ix_graph_edges_source_id"), "graph_edges", ["source_id"], unique=False)
    op.create_index(op.f("ix_graph_edges_target_id"), "graph_edges", ["target_id"], unique=False)

    op.create_table(
        "benchmark_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sample_id", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_intent", sa.String(length=32), nullable=False),
        sa.Column("predicted_intent", sa.String(length=32), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["benchmark_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_benchmark_results_agent_run_id"), "benchmark_results", ["agent_run_id"], unique=False)
    op.create_index(op.f("ix_benchmark_results_run_id"), "benchmark_results", ["run_id"], unique=False)

    op.create_table(
        "graph_entity_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confidence", sa.Float(), server_default=sa.text("1.0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["knowledge_chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["graph_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_graph_entity_links_chunk_id"), "graph_entity_links", ["chunk_id"], unique=False)
    op.create_index(op.f("ix_graph_entity_links_entity_id"), "graph_entity_links", ["entity_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_graph_entity_links_entity_id"), table_name="graph_entity_links")
    op.drop_index(op.f("ix_graph_entity_links_chunk_id"), table_name="graph_entity_links")
    op.drop_table("graph_entity_links")
    op.drop_index(op.f("ix_benchmark_results_run_id"), table_name="benchmark_results")
    op.drop_index(op.f("ix_benchmark_results_agent_run_id"), table_name="benchmark_results")
    op.drop_table("benchmark_results")
    op.drop_index(op.f("ix_graph_edges_target_id"), table_name="graph_edges")
    op.drop_index(op.f("ix_graph_edges_source_id"), table_name="graph_edges")
    op.drop_table("graph_edges")
    op.drop_index(op.f("ix_llm_calls_run_id"), table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_index(op.f("ix_agent_steps_run_id"), table_name="agent_steps")
    op.drop_table("agent_steps")
    op.drop_index(op.f("ix_knowledge_chunks_document_id"), table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index(op.f("ix_chat_messages_session_id"), table_name="chat_messages")
    op.drop_index(op.f("ix_chat_messages_agent_run_id"), table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index(op.f("ix_training_logs_user_id"), table_name="training_logs")
    op.drop_table("training_logs")
    op.drop_table("user_profiles")
    op.drop_table("benchmark_runs")
    op.drop_index(op.f("ix_graph_entities_name"), table_name="graph_entities")
    op.drop_index(op.f("ix_graph_entities_entity_type"), table_name="graph_entities")
    op.drop_table("graph_entities")
    op.drop_index(op.f("ix_retrieval_logs_session_id"), table_name="retrieval_logs")
    op.drop_index(op.f("ix_retrieval_logs_message_id"), table_name="retrieval_logs")
    op.drop_table("retrieval_logs")
    op.drop_index(op.f("ix_agent_runs_trace_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_session_id"), table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index(op.f("ix_knowledge_documents_content_hash"), table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_index(op.f("ix_chat_sessions_user_id"), table_name="chat_sessions")
    op.drop_table("chat_sessions")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_table("users")
