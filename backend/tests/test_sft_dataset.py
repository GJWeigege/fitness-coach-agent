
def test_coach_sft_dataset_has_minimum_samples():
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "data" / "finetune" / "coach_sft.jsonl"
    count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    assert count >= 200
