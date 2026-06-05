#!/usr/bin/env python3
"""Evaluate base vs LoRA adapter on benchmark subset (local inference only)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "data" / "benchmark" / "coach_eval.jsonl"
DEFAULT_ADAPTER = Path(__file__).resolve().parents[1] / "adapters" / "coach-lora"


def build_config(args: argparse.Namespace) -> dict:
    return {
        "dataset": str(args.dataset),
        "subset_size": args.subset_size,
        "base_model": args.base_model,
        "adapter_path": str(args.adapter),
        "lora_enabled": os.getenv("LORA_ENABLED", "false").lower() == "true",
        "metrics": ["intent_accuracy", "plan_agent_recall"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare base vs LoRA on coach benchmark subset")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--subset-size", type=int, default=20)
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--adapter", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = build_config(args)
    print("=== Coach LoRA Eval Config ===")
    print(json.dumps(config, indent=2, ensure_ascii=False))

    if args.dry_run:
        print("\n[dry-run] Would run benchmark subset with base and LoRA weights locally.")
        if not config["lora_enabled"]:
            print("[dry-run] LORA_ENABLED=false — only base model path would run in production API mode.")
        return 0

    if not args.dataset.exists():
        print(f"Dataset not found: {args.dataset}", file=sys.stderr)
        return 1

    print("Eval harness not wired in MVP — use benchmark_runner against local vLLM endpoint.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
