import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_permissions
from app.db.models import User
from app.db.session import AsyncSessionLocal
from app.schemas.benchmark import (
    BenchmarkResultItem,
    BenchmarkRunCreateRequest,
    BenchmarkRunCreateResponse,
    BenchmarkRunDetailResponse,
    BenchmarkRunListItem,
    BenchmarkRunListResponse,
)
from app.services.benchmark_service import BenchmarkService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/benchmark", tags=["benchmark"])


def get_benchmark_service() -> BenchmarkService:
    return BenchmarkService()


async def _execute_benchmark_background(run_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        service = BenchmarkService()
        try:
            await service.execute_run(db, run_id)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("benchmark_background_failed run_id=%s", run_id)


@router.post("/runs", status_code=202, response_model=BenchmarkRunCreateResponse)
async def create_benchmark_run(
    body: BenchmarkRunCreateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions("benchmark:run")),
    service: BenchmarkService = Depends(get_benchmark_service),
) -> BenchmarkRunCreateResponse:
    try:
        run = await service.create_run(db, dataset_name=body.dataset_name)
        await db.commit()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    background_tasks.add_task(_execute_benchmark_background, run.id)
    return BenchmarkRunCreateResponse(id=run.id, dataset_name=run.dataset_name, status=run.status)


@router.get("/runs", response_model=BenchmarkRunListResponse)
async def list_benchmark_runs(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions("benchmark:read")),
    service: BenchmarkService = Depends(get_benchmark_service),
) -> BenchmarkRunListResponse:
    runs, total = await service.list_runs(db, limit=limit, offset=offset)
    return BenchmarkRunListResponse(
        runs=[
            BenchmarkRunListItem(
                id=r.id,
                dataset_name=r.dataset_name,
                status=r.status,
                started_at=r.started_at,
                finished_at=r.finished_at,
                metrics=r.metrics,
                error_message=r.error_message,
            )
            for r in runs
        ],
        total=total,
    )


@router.get("/runs/{run_id}", response_model=BenchmarkRunDetailResponse)
async def get_benchmark_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions("benchmark:read")),
    service: BenchmarkService = Depends(get_benchmark_service),
) -> BenchmarkRunDetailResponse:
    run = await service.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评测运行不存在。")

    results = await service.get_run_results(db, run_id)
    return BenchmarkRunDetailResponse(
        id=run.id,
        dataset_name=run.dataset_name,
        status=run.status,
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
