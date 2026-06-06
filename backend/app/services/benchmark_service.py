import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PUBLIC_ERROR_MESSAGE
from app.db.models import BenchmarkResult, BenchmarkRun
from app.llm.dashscope_client import DashScopeClient
from app.services.benchmark_runner import (
    BenchmarkRunner,
    aggregate_benchmark_metrics,
    evaluation_to_benchmark_result,
    load_benchmark_dataset,
    resolve_dataset_path,
    select_benchmark_samples,
)
from app.services.chat_service import ChatService
from app.services.rag_service import RagService

logger = logging.getLogger(__name__)

TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})

USER_FACING_BENCHMARK_ERRORS = frozenset(
    {
        "评测样本子集为空",
        "已有评测正在运行",
    }
)


def benchmark_error_message(exc: Exception) -> str:
    if isinstance(exc, ValueError):
        message = str(exc)
        if message in USER_FACING_BENCHMARK_ERRORS:
            return message
    return PUBLIC_ERROR_MESSAGE


class BenchmarkRunAlreadyActiveError(ValueError):
    pass


class BenchmarkRunNotFoundError(LookupError):
    pass


class BenchmarkRunNotCancellableError(ValueError):
    pass


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

    async def create_run(
        self,
        db: AsyncSession,
        *,
        dataset_name: str,
        created_by_user_id: uuid.UUID,
    ) -> BenchmarkRun:
        resolve_dataset_path(dataset_name)
        active_count = await db.scalar(
            select(func.count())
            .select_from(BenchmarkRun)
            .where(BenchmarkRun.status.in_(["pending", "running"]))
        )
        if active_count:
            raise BenchmarkRunAlreadyActiveError("已有评测正在运行")

        run = BenchmarkRun(dataset_name=dataset_name, created_by_user_id=created_by_user_id, status="pending")
        db.add(run)
        try:
            await db.flush()
        except IntegrityError as exc:
            raise BenchmarkRunAlreadyActiveError("已有评测正在运行") from exc
        return run

    async def reconcile_stale_runs(self, db: AsyncSession) -> int:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            update(BenchmarkRun)
            .where(BenchmarkRun.status.in_(["pending", "running"]))
            .values(
                status="failed",
                error_message="服务重启，评测已中断。",
                finished_at=now,
            )
        )
        return result.rowcount or 0

    async def cancel_run(
        self,
        db: AsyncSession,
        run_id: uuid.UUID,
    ) -> BenchmarkRun:
        run = await self.get_run(db, run_id)
        if run is None:
            raise BenchmarkRunNotFoundError(f"benchmark run not found: {run_id}")
        if run.status in TERMINAL_RUN_STATUSES:
            raise BenchmarkRunNotCancellableError(
                f"benchmark run already finished with status: {run.status}"
            )

        run.status = "cancelled"
        run.finished_at = datetime.now(timezone.utc)
        await db.flush()
        return run

    async def list_runs(
        self,
        db: AsyncSession,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[BenchmarkRun], int]:
        stmt = select(BenchmarkRun).order_by(
            BenchmarkRun.created_at.desc(),
            BenchmarkRun.started_at.desc().nullslast(),
        )
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

    def _build_run_metrics(
        self,
        evaluations: list,
        *,
        dataset_total: int,
        planned_sample_count: int,
        sample_limit: int | None,
        sample_ids: list[str] | None,
    ) -> dict:
        metrics = aggregate_benchmark_metrics(evaluations)
        metrics["dataset_total"] = dataset_total
        metrics["planned_sample_count"] = planned_sample_count
        if sample_limit is not None:
            metrics["subset_limit"] = sample_limit
        if sample_ids is not None:
            metrics["subset_sample_ids"] = sample_ids
        return metrics

    async def execute_run(
        self,
        db: AsyncSession,
        run_id: uuid.UUID,
        *,
        sample_limit: int | None = None,
        sample_ids: list[str] | None = None,
    ) -> None:
        run = await db.get(BenchmarkRun, run_id)
        if run is None:
            logger.error("benchmark_run_not_found run_id=%s", run_id)
            return

        now = datetime.now(timezone.utc)
        started = await db.execute(
            update(BenchmarkRun)
            .where(BenchmarkRun.id == run_id, BenchmarkRun.status == "pending")
            .values(
                status="running",
                started_at=now,
                finished_at=None,
                error_message=None,
            )
        )
        if started.rowcount == 0:
            await db.refresh(run)
            if run.status == "cancelled":
                return
            if run.status != "running":
                return
        await db.commit()

        run = await db.get(BenchmarkRun, run_id)
        if run is None or run.status == "cancelled":
            return

        evaluations: list = []

        try:
            dataset_path = resolve_dataset_path(run.dataset_name)
            all_samples = load_benchmark_dataset(dataset_path)
            samples = select_benchmark_samples(
                all_samples,
                limit=sample_limit,
                sample_ids=sample_ids,
            )
            if not samples:
                raise ValueError("评测样本子集为空")

            user = await self._ensure_runner().resolve_benchmark_user(db)
            runner = self._ensure_runner()

            async def should_cancel() -> bool:
                await db.refresh(run)
                return run.status == "cancelled"

            async def persist_sample(evaluation) -> None:
                evaluations.append(evaluation)
                db.add(evaluation_to_benchmark_result(run.id, evaluation))
                run.metrics = self._build_run_metrics(
                    evaluations,
                    dataset_total=len(all_samples),
                    planned_sample_count=len(samples),
                    sample_limit=sample_limit,
                    sample_ids=sample_ids,
                )
                await db.flush()
                await db.commit()

            evaluations = await runner.run_dataset(
                db,
                samples,
                user_id=user.id,
                should_cancel=should_cancel,
                on_sample=persist_sample,
            )

            await db.refresh(run)
            if run.status == "cancelled":
                return

            run.metrics = self._build_run_metrics(
                evaluations,
                dataset_total=len(all_samples),
                planned_sample_count=len(samples),
                sample_limit=sample_limit,
                sample_ids=sample_ids,
            )
            run.status = "completed"
            run.finished_at = datetime.now(timezone.utc)
            await db.flush()
            await db.commit()
        except Exception as exc:
            logger.exception("benchmark_run_failed run_id=%s", run_id)
            await db.refresh(run)
            if run.status != "cancelled":
                if evaluations:
                    run.metrics = self._build_run_metrics(
                        evaluations,
                        dataset_total=len(all_samples) if "all_samples" in locals() else 0,
                        planned_sample_count=len(samples) if "samples" in locals() else 0,
                        sample_limit=sample_limit,
                        sample_ids=sample_ids,
                    )
                run.status = "failed"
                run.error_message = benchmark_error_message(exc)
                run.finished_at = datetime.now(timezone.utc)
                await db.flush()
                await db.commit()
