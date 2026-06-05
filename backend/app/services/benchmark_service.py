import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BenchmarkResult, BenchmarkRun
from app.llm.dashscope_client import DashScopeClient
from app.services.benchmark_runner import (
    BenchmarkRunner,
    aggregate_benchmark_metrics,
    evaluation_to_benchmark_result,
    load_benchmark_dataset,
    resolve_dataset_path,
)
from app.services.chat_service import ChatService
from app.services.rag_service import RagService

logger = logging.getLogger(__name__)


class BenchmarkService:
    def __init__(
        self,
        llm_client: DashScopeClient | None = None,
        chat_service: ChatService | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._chat_service = chat_service
        self._runner: BenchmarkRunner | None = None

    def _ensure_runner(self) -> BenchmarkRunner:
        if self._runner is None:
            llm_client = self._llm_client or DashScopeClient()
            chat_service = self._chat_service or ChatService(
                llm_client=llm_client,
                rag_service=RagService(llm_client=llm_client),
            )
            self._runner = BenchmarkRunner(chat_service)
        return self._runner

    async def create_run(self, db: AsyncSession, *, dataset_name: str) -> BenchmarkRun:
        resolve_dataset_path(dataset_name)
        run = BenchmarkRun(dataset_name=dataset_name, status="pending")
        db.add(run)
        await db.flush()
        return run

    async def list_runs(
        self,
        db: AsyncSession,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[BenchmarkRun], int]:
        stmt = select(BenchmarkRun).order_by(BenchmarkRun.started_at.desc().nullslast())
        count_stmt = select(func.count()).select_from(BenchmarkRun)
        total = await db.scalar(count_stmt) or 0
        rows = list((await db.scalars(stmt.offset(offset).limit(limit))).all())
        return rows, total

    async def get_run(
        self,
        db: AsyncSession,
        run_id: uuid.UUID,
    ) -> BenchmarkRun | None:
        return await db.get(BenchmarkRun, run_id)

    async def get_run_results(
        self,
        db: AsyncSession,
        run_id: uuid.UUID,
    ) -> list[BenchmarkResult]:
        return list(
            (
                await db.scalars(
                    select(BenchmarkResult)
                    .where(BenchmarkResult.run_id == run_id)
                    .order_by(BenchmarkResult.sample_id.asc())
                )
            ).all()
        )

    async def execute_run(self, db: AsyncSession, run_id: uuid.UUID) -> None:
        run = await db.get(BenchmarkRun, run_id)
        if run is None:
            logger.error("benchmark_run_not_found run_id=%s", run_id)
            return

        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        run.error_message = None
        await db.flush()

        try:
            dataset_path = resolve_dataset_path(run.dataset_name)
            samples = load_benchmark_dataset(dataset_path)
            user = await self._ensure_runner().resolve_benchmark_user(db)
            evaluations = await self._ensure_runner().run_dataset(db, samples, user_id=user.id)

            for evaluation in evaluations:
                db.add(evaluation_to_benchmark_result(run.id, evaluation))

            run.metrics = aggregate_benchmark_metrics(evaluations)
            run.status = "completed"
            run.finished_at = datetime.now(timezone.utc)
            await db.flush()
        except Exception as exc:
            logger.exception("benchmark_run_failed run_id=%s", run_id)
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = datetime.now(timezone.utc)
            await db.flush()
            raise
