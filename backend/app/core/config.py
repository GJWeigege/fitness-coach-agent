from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_AUTH_SECRETS = frozenset(
    {
        "replace_this_for_production",
        "replace_with_random_secret",
        "dev-secret-key-change-in-production-min-32-chars",
    }
)

DEPLOYED_ENVS = frozenset({"production", "staging"})


class Settings(BaseSettings):
    app_name: str = "fitness-coach-agent"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/fitness_coach"

    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    coach_router_model: str = "qwen-plus"
    coach_answer_model: str = "qwen-plus"
    coach_planner_model: str = "qwen-plus"
    coach_embedding_model: str = "text-embedding-v3"
    coach_long_context_model: str = "qwen-long"

    embedding_dim: int = 1024
    rag_top_k: int = 4
    rag_hybrid_enabled: bool = True
    rag_keyword_top_k: int = 8
    rag_score_threshold: float = 0.35
    rag_score_floor: float = 0.01
    rag_score_min_gap: float = 0.004
    use_rag_default: bool = True

    graph_rag_enabled: bool = True

    sub_agent_max_tool_steps: int = 4
    max_sub_agents_per_turn: int = 2
    parallel_sub_agents_enabled: bool = True
    cot_enabled: bool = True
    cot_sse_enabled: bool = False
    agent_enable_thinking_steps: bool = True
    profile_required_for_plan: bool = False

    long_context_mode: str = "summary"
    lora_enabled: bool = False
    lora_adapter_path: str = ""

    llm_request_timeout_seconds: int = 60
    llm_max_retries: int = 1

    memory_max_turns: int = 8
    memory_max_prompt_tokens: int = 12000
    memory_summary_trigger_turns: int = 12
    memory_summary_max_chars: int = 500
    memory_max_user_chars: int = 8000

    ingest_chunk_size: int = 800
    ingest_chunk_overlap: int = 120
    upload_dir: str = "backend/data/uploads"
    max_upload_bytes: int = 10 * 1024 * 1024

    benchmark_concurrency: int = 2
    benchmark_faithfulness_use_llm: bool = False
    benchmark_reconcile_stale_runs: bool = True

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    trusted_proxies: str = ""
    rate_limit_max_keys: int = 10_000
    login_lockout_max_attempts: int = 5
    login_lockout_window_seconds: int = 900
    db_pool_size: int = 10
    db_max_overflow: int = 20

    auth_secret_key: str = "dev-secret-key-change-in-production-min-32-chars"
    access_token_expire_minutes: int = 720

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def trusted_proxy_set(self) -> frozenset[str]:
        return frozenset(item.strip() for item in self.trusted_proxies.split(",") if item.strip())

    def is_deployed_env(self) -> bool:
        return self.app_env in DEPLOYED_ENVS

    def validate_auth_secret_for_env(self) -> None:
        if not self.is_deployed_env():
            return
        if self.auth_secret_key in INSECURE_AUTH_SECRETS:
            raise ValueError("部署环境必须设置强随机 AUTH_SECRET_KEY，不能使用默认值。")
        if len(self.auth_secret_key) < 32:
            raise ValueError("部署环境 AUTH_SECRET_KEY 长度至少为 32 字符。")

    def validate_cors_origins_for_env(self) -> None:
        if self.cors_origin_list():
            return
        if not self.is_deployed_env():
            return
        raise ValueError("部署环境 CORS_ORIGINS 不能为空，请配置前端访问域名。")


@lru_cache
def get_settings() -> Settings:
    return Settings()
