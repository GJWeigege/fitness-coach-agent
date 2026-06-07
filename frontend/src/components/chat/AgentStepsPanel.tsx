import type { AgentStepEvent } from "../../types";

type AgentStepsPanelProps = {
  steps: AgentStepEvent[];
  runStatus?: string;
  traceSummary?: string;
};

export function AgentStepsPanel({ steps, runStatus, traceSummary }: AgentStepsPanelProps) {
  if (steps.length === 0 && !traceSummary) return null;

  return (
    <details className="agent-steps">
      <summary>
        Agent 执行过程（{steps.length} 个阶段）
        {runStatus === "degraded" ? <span className="agent-steps__badge">已降级</span> : null}
      </summary>
      {traceSummary ? <p className="agent-steps__trace">{traceSummary}</p> : null}
      <ol className="agent-steps__list">
        {steps.map((step, idx) => (
          <li key={`${step.phase}-${idx}`}>
            <span className="agent-steps__phase">{step.phase}</span>
            <span>{step.summary}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}
