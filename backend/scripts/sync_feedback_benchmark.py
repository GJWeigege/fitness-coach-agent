#!/usr/bin/env python3
"""CLI: sync chat feedback into benchmark queue and SFT dataset."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import AsyncSessionLocal
from app.services.feedback_benchmark_service import FeedbackBenchmarkService


async def _run(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as db:
        service = FeedbackBenchmarkService()
        result = await service.sync_from_feedback(
            db,
            include_down=not args.up_only,
            include_up=not args.down_only,
            dry_run=args.dry_run,
        )
        merged = None
        if args.merge and not args.dry_run:
            merge_result = service.merge_feedback_queue_into_benchmark()
            merged = merge_result["merged"]
            await db.commit()
        elif not args.dry_run:
            await db.commit()

    payload = {
        "queue_added": result.queue_added,
        "queue_skipped": result.queue_skipped,
        "sft_added": result.sft_added,
        "sft_skipped": result.sft_skipped,
        "merged": merged,
        "benchmark_path": result.benchmark_path,
        "sft_path": result.sft_path,
        "queue_path": result.queue_path,
        "dry_run": args.dry_run,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Export feedback to benchmark/SFT datasets")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--merge", action="store_true", help="Merge feedback queue into coach_eval")
    parser.add_argument("--down-only", action="store_true")
    parser.add_argument("--up-only", action="store_true")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
