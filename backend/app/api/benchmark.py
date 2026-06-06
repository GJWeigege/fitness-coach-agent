import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_permissions
from app.db.models import BenchmarkRun, User
from app.db.session import AsyncSessionLocal
from app.schemas.benchmark import (
    BenchmarkResultItem,
    BenchmarkRunCancelResponse,
    BenchmarkRunCreateRequest,
    BenchmarkRunCreateResponse,
    BenchmarkRunDetailResponse,
    BenchmarkRunListItem,
    BenchmarkRunListResponse,
    FeedbackSyncRequest,
    FeedbackSyncResponse,
)
from app.services.benchmark_service import (
    BenchmarkRunAlreadyActiveError,
    BenchmarkRunNotCancellableError,
    BenchmarkRunNotFoundError,
    BenchmarkService,
)
from app.services.feedback_benchmark_service import FeedbackBenchmarkService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/benchmark", tags=["benchmark"])


def get_benchmark_service() -> BenchmarkService:
    return BenchmarkService()


async def _load_usernames(db: AsyncSession, runs: list[BenchmarkRun]) -> dict[uuid.UUID, str]:
    user_ids = {run.created_by_user_id for run in runs}
    if not user_ids:
        return {}
    rows = list((await db.scalars(select(User).where(User.id.in_(user_ids)))).all())
    return {user.id: user.username for user in rows}


def _run_list_item(run: BenchmarkRun, usernames: dict[uuid.UUID, str]) -> BenchmarkRunListItem:
    return BenchmarkRunListItem(
        id=run.id,
        dataset_name=run.dataset_name,
        status=run.status,
        created_by_user_id=run.created_by_user_id,
        created_by_username=usernames.get(run.created_by_user_id),
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        metrics=run.metrics,
        error_message=run.error_message,
    )


async def _execute_benchmark_background(
    run_id: uuid.UUID,
    *,
    sample_limit: int | None = None,
    sample_ids: list[str] | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        service = BenchmarkService()
        try:
            await service.execute_run(
                db,
                run_id,
                sample_limit=sample_limit,
                sample_ids=sample_ids,
            )
        except Exception:
            async with AsyncSessionLocal() as check_db:
                run = await BenchmarkService().get_run(check_db, run_id)
                if run is not None and run.status == "cancelled":
                    return
            logger.exception("benchmark_background_failed run_id=%s", run_id)


@router.post("/runs", status_code=202, response_model=BenchmarkRunCreateResponse)
async def create_benchmark_run(
    body: BenchmarkRunCreateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("benchmark:run")),
    service: BenchmarkService = Depends(get_benchmark_service),
) -> BenchmarkRunCreateResponse:
    try:
        run = await service.create_run(
            db,
            dataset_name=body.dataset_name,
            created_by_user_id=user.id,
        )
        await db.commit()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BenchmarkRunAlreadyActiveError as exc:
        raise HTTPException(status_code=409, detail="已有评测正在运行，请等待结束或停止后再启动。") from exc

    background_tasks.add_task(
        _execute_benchmark_background,
        run.id,
        sample_limit=body.sample_limit,
        sample_ids=body.sample_ids,
    )
    return BenchmarkRunCreateResponse(id=run.id, dataset_name=run.dataset_name, status=run.status)


@router.post("/runs/{run_id}/cancel", response_model=BenchmarkRunCancelResponse)
async def cancel_benchmark_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("benchmark:run")),
    service: BenchmarkService = Depends(get_benchmark_service),
) -> BenchmarkRunCancelResponse:
    try:
        run = await service.cancel_run(db, run_id)
        await db.commit()
    except BenchmarkRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="评测运行不存在。") from exc
    except BenchmarkRunNotCancellableError as exc:
        raise HTTPException(status_code=409, detail="该评测已结束，无法取消。") from exc

    return BenchmarkRunCancelResponse(id=run.id, status=run.status)


@router.get("/runs", response_model=BenchmarkRunListResponse)
async def list_benchmark_runs(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("benchmark:read")),
    service: BenchmarkService = Depends(get_benchmark_service),
) -> BenchmarkRunListResponse:
    runs, total = await service.list_runs(db, limit=limit, offset=offset)
    usernames = await _load_usernames(db, runs)
    return BenchmarkRunListResponse(
        runs=[_run_list_item(r, usernames) for r in runs],
        total=total,
    )


@router.get("/runs/{run_id}", response_model=BenchmarkRunDetailResponse)
async def get_benchmark_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("benchmark:read")),
    service: BenchmarkService = Depends(get_benchmark_service),
) -> BenchmarkRunDetailResponse:
    run = await service.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评测运行不存在。")

    results = await service.get_run_results(db, run_id)
    usernames = await _load_usernames(db, [run])
    return BenchmarkRunDetailResponse(
        id=run.id,
        dataset_name=run.dataset_name,
        status=run.status,
        created_by_user_id=run.created_by_user_id,
        created_by_username=usernames.get(run.created_by_user_id),
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        metrics=run.metrics,
        error_message=run.error_message,
        results=[
            BenchmarkResultItem(
                id=r.id,
                sample_id=r.sample_id,
                question=r.question,
                expected_intent=r.expected_intent,
                predicted_intent=r.predicted_intent,
                passed=r.passed,
                metrics=r.metrics,
                agent_run_id=r.agent_run_id,
            )
            for r in results
        ],
    )


@router.post("/feedback/sync", response_model=FeedbackSyncResponse)
async def sync_feedback_to_datasets(
    body: FeedbackSyncRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions("benchmark:run")),
) -> FeedbackSyncResponse:
    service = FeedbackBenchmarkService()
    result = await service.sync_from_feedback(
        db,
        include_down=body.include_down,
        include_up=body.include_up,
        dry_run=body.dry_run,
    )
    merged_count: int | None = None
    if body.merge_queue and not body.dry_run:
        merge_result = service.merge_feedback_queue_into_benchmark()
        merged_count = merge_result["merged"]
    if not body.dry_run:
        await db.commit()
    return FeedbackSyncResponse(
        queue_added=result.queue_added,
        queue_skipped=result.queue_skipped,
        sft_added=result.sft_added,
        sft_skipped=result.sft_skipped,
        merged=merged_count,
        benchmark_path=result.benchmark_path,
        sft_path=result.sft_path,
        queue_path=result.queue_path,
    )
