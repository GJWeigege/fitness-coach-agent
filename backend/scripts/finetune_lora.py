#!/usr/bin/env python3
"""QLoRA fine-tune template for coach intent/plan stability (local only).

Default deployment uses DashScope API with LORA_ENABLED=false.
Run with --dry-run to print config without training.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_DATA = Path(__file__).resolve().parents[1] / "data" / "finetune" / "coach_sft.jsonl"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "adapters" / "coach-lora"


def load_config(args: argparse.Namespace) -> dict:
    return {
        "base_model": args.base_model,
        "data_path": str(args.data),
        "output_dir": str(args.output),
        "lora_rank": args.lora_rank,
        "lora_alpha": args.lora_alpha,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "max_seq_length": args.max_seq_length,
        "lora_enabled_env": os.getenv("LORA_ENABLED", "false"),
        "lora_adapter_path_env": os.getenv("LORA_ADAPTER_PATH", ""),
    }


def count_samples(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Coach Agent LoRA fine-tune (local vLLM/Ollama path)")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="SFT jsonl path")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Adapter output directory")
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct", help="HF base model id")
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--dry-run", action="store_true", help="Print config and exit")
    args = parser.parse_args()

    config = load_config(args)
    config["sample_count"] = count_samples(args.data)

    print("=== Coach LoRA Fine-tune Config ===")
    print(json.dumps(config, indent=2, ensure_ascii=False))

    if args.dry_run:
        print("\n[dry-run] Skipping training. Install torch+peft+transformers for real run.")
        print("[dry-run] Inference: LORA_ENABLED=true LORA_ADAPTER_PATH=<output> via vLLM/Ollama only.")
        if config["sample_count"] < 200:
            print(f"[dry-run] WARNING: sample_count {config['sample_count']} < 200 (design target).")
        return 0

    try:
        import torch  # noqa: F401
        from peft import LoraConfig  # noqa: F401
        from transformers import AutoModelForCausalLM  # noqa: F401
    except ImportError:
        print(
            "Missing training deps. Install: pip install torch transformers peft datasets accelerate",
            file=sys.stderr,
        )
        return 1

    if config["sample_count"] < 200:
        print(
            f"Need >=200 SFT samples for acceptance (found {config['sample_count']}). "
            "Run: python scripts/generate_coach_sft.py",
            file=sys.stderr,
        )
        return 1

    print("Training pipeline not executed in MVP repo — use --dry-run or extend this script locally.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
