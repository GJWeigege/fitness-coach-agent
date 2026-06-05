# LoRA 微调实验说明

对应设计 [COACH_AGENT_REDESIGN.md](COACH_AGENT_REDESIGN.md) §3.14.3 与任务 T-115。

## 目标

- 稳定 **intent / plan JSON** 输出格式
- 领域话术与 **disclaimer** 一致性
- **不**替代 RAG（知识仍来自 pgvector）

## 默认部署

```env
LORA_ENABLED=false
LORA_ADAPTER_PATH=
```

生产与 demo 默认走 **DashScope API** base model + RAG。DashScope **不支持**挂载自定义 LoRA 权重。

LoRA 仅用于 **本地** 面试/demo：`vLLM` 或 `Ollama` 加载 `adapters/coach-lora/`。

## 数据

| 路径 | 说明 |
|------|------|
| `backend/data/finetune/coach_sft.jsonl` | SFT 样本（MVP 含 3 条示例；目标 ≥200） |

字段：`messages[]` 多轮，assistant 含 intent/plan/answer JSON + disclaimer。

## 脚本

### 训练

```bash
cd backend
python scripts/finetune_lora.py --dry-run
python scripts/finetune_lora.py --data data/finetune/coach_sft.jsonl --output adapters/coach-lora
```

`--dry-run` 打印超参与环境变量，不安装 GPU 依赖也可验收。

### 评估

```bash
python scripts/eval_lora.py --dry-run
python scripts/eval_lora.py --subset-size 20
```

对比指标：`intent_accuracy`、`plan_agent_recall`（与 benchmark §3.10 一致）。

## 推荐超参（模板）

| 参数 | 默认 |
|------|------|
| base_model | Qwen2.5-7B-Instruct |
| lora_rank | 16 |
| lora_alpha | 32 |
| epochs | 3 |
| learning_rate | 2e-4 |

## 何时不值得微调

- 样本 < 200 且 plan JSON 已由 prompt + benchmark 达标
- 无本地 GPU / 无 vLLM 部署能力
- 知识密集型问答 — RAG 增益大于 LoRA

## 与长上下文实验关系

Summary vs full 对比见 [LLM_ARCHITECTURE.md](LLM_ARCHITECTURE.md) §5。LoRA 不改变 Memory 策略，两者正交。

## 验收

```bash
python scripts/finetune_lora.py --dry-run
python scripts/eval_lora.py --dry-run
```

输出 config JSON 即 MVP 通过；真实训练为可选本地步骤。
