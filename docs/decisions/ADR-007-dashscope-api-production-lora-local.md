# ADR-007: 生产 DashScope API，LoRA 仅本地实验

- **状态**: Accepted
- **关联**: [reference/LLM_FINETUNE_EXPERIMENT](../reference/LLM_FINETUNE_EXPERIMENT.md)

## 决策

`LORA_ENABLED=false` 默认；LoRA 脚本与 eval 为 portfolio 加分，不自训 base model。

## 面试一句话

「线上稳定走 API；LoRA 是本地实验管线，和 RAG 正交。」
