import { type FormEvent } from "react";
import { Button } from "../ui/Button";

const INTENT_CHIPS = [
  { label: "训练计划", text: "帮我制定一周力量训练计划" },
  { label: "营养建议", text: "增肌期每天应该摄入多少蛋白质？" },
  { label: "恢复指导", text: "高强度训练后如何安排恢复？" },
  { label: "安全咨询", text: "训练时感到胸闷气短应该怎么办？" },
] as const;

type ChatInputProps = {
  input: string;
  useRag: boolean;
  busy: boolean;
  canSend: boolean;
  showRagToggle?: boolean;
  showIntentChips?: boolean;
  placeholder?: string;
  submitLabel?: string;
  onInputChange: (value: string) => void;
  onRagChange: (value: boolean) => void;
  onSubmit: () => void;
};

export function ChatInput({
  input,
  useRag,
  busy,
  canSend,
  showRagToggle = true,
  showIntentChips = true,
  placeholder = "请输入训练或营养问题...",
  submitLabel,
  onInputChange,
  onRagChange,
  onSubmit,
}: ChatInputProps) {
  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <form className="chat-input" onSubmit={handleSubmit}>
      <div className="chat-input__toolbar">
        {showRagToggle ? (
          <label className="toggle">
            <input type="checkbox" checked={useRag} onChange={(e) => onRagChange(e.target.checked)} />
            <span className="toggle__track" />
            <span>启用 RAG 知识检索</span>
          </label>
        ) : null}
        {showIntentChips && canSend ? (
          <div className="intent-chips">
            {INTENT_CHIPS.map((chip) => (
              <button
                key={chip.label}
                type="button"
                className="intent-chip"
                disabled={busy}
                onClick={() => {
                  onInputChange(chip.text);
                }}
              >
                {chip.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      <div className="chat-input__row">
        <textarea
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          placeholder={placeholder}
          rows={3}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (!busy && canSend && input.trim()) onSubmit();
            }
          }}
        />
        <Button type="submit" variant="primary" disabled={busy || !canSend || !input.trim()}>
          {submitLabel ?? (busy ? "发送中..." : canSend ? "发送" : "无权限")}
        </Button>
      </div>
    </form>
  );
}
