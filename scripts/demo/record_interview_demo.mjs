/**
 * 面试演示视频自动录制脚本（Playwright 录屏）
 *
 * 前置：docker compose up -d && backend uvicorn && frontend pnpm dev
 *
 * 用法：
 *   cd scripts/demo
 *   pnpm install && pnpm run install-browser
 *   pnpm run record
 *
 * 环境变量：
 *   BASE_URL=http://localhost:5173
 *   OUTPUT_DIR=../../docs/interview/demo-videos
 */
import { chromium } from "playwright";
import { mkdir, readdir, rename, writeFile, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const BASE_URL = process.env.BASE_URL ?? "http://localhost:5173";
const OUTPUT_DIR = path.resolve(
  __dirname,
  process.env.OUTPUT_DIR ?? "../../docs/interview/demo-videos",
);
const DEMO_PASSWORD = "Demo@123456";
const DEMO_QUESTION = "我想增肌，膝盖有旧伤，请给训练和饮食建议。";
const VIEWPORT = { width: 1440, height: 900 };

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function login(page, username) {
  await page.goto(`${BASE_URL}/auth`);
  await page.getByPlaceholder("Enter username").fill(username);
  await page.getByPlaceholder("Enter password").fill(DEMO_PASSWORD);
  await page.locator("form.auth-form button[type='submit']").click();
  await page.waitForURL("**/chat**", { timeout: 30_000 });
  await page.getByText(username, { exact: false }).first().waitFor({ timeout: 15_000 });
}

async function logout(page) {
  await page.getByRole("button", { name: "退出" }).click();
  await page.waitForURL("**/auth**", { timeout: 15_000 });
}

async function gotoNav(page, label) {
  await page.getByRole("link", { name: label }).click();
}

async function fieldInput(page, labelText) {
  return page.locator("label.field").filter({ hasText: labelText }).locator("input, select, textarea").first();
}

async function showCoachProfile(page, script) {
  script.push("2. coach_demo 健身档案：目标、膝伤限制与训练记录");
  await gotoNav(page, "Profile");
  await page.getByRole("heading", { name: "健身档案" }).waitFor({ timeout: 15_000 });

  await (await fieldInput(page, "年龄")).fill("28");
  await (await fieldInput(page, "性别")).selectOption("male");
  await (await fieldInput(page, "身高")).fill("175");
  await (await fieldInput(page, "体重")).fill("70");
  await (await fieldInput(page, "训练经验")).selectOption("intermediate");
  await (await fieldInput(page, "饮食偏好")).fill("高蛋白");
  await (await fieldInput(page, "目标")).fill("增肌");
  await (await fieldInput(page, "伤病")).fill("左膝旧伤");
  await (await fieldInput(page, "可用器械")).fill("哑铃, 跑步机");
  await sleep(800);
  await page.getByRole("button", { name: "保存档案" }).click();
  await page.getByText("档案已保存").waitFor({ timeout: 10_000 });
  await sleep(1200);

  await page.evaluate(() => window.scrollTo({ top: document.body.scrollHeight * 0.55, behavior: "smooth" }));
  await sleep(1000);
  const today = new Date().toISOString().slice(0, 10);
  await (await fieldInput(page, "日期")).fill(today);
  await (await fieldInput(page, "类型")).fill("strength");
  await (await fieldInput(page, "时长")).fill("45");
  await (await fieldInput(page, "强度")).selectOption("moderate");
  await (await fieldInput(page, "备注")).fill("深蹲 5x5，避开深度屈膝");
  await sleep(600);
  await page.getByRole("button", { name: "添加记录" }).click();
  await page.getByText("训练记录已添加").waitFor({ timeout: 10_000 });
  await sleep(1500);
}

async function showAdminKnowledge(page, script) {
  script.push("6. admin_demo 知识库：RAG 文档列表与索引管理");
  await gotoNav(page, "Knowledge");
  await page.getByRole("heading", { name: "知识库管理" }).waitFor({ timeout: 15_000 });
  await sleep(1200);

  const rows = page.locator(".data-table tbody tr");
  await rows.first().waitFor({ timeout: 15_000 });
  await rows.first().scrollIntoViewIfNeeded();
  await sleep(1500);

  const reindexBtn = page.getByRole("button", { name: "重建索引" }).first();
  if (await reindexBtn.count()) {
    await reindexBtn.hover();
    await sleep(1200);
  }

  await page.locator(".upload-zone").scrollIntoViewIfNeeded();
  await sleep(1500);
}

async function showAdminBenchmark(page, script) {
  script.push("7. admin_demo Benchmark：评测指标与历史运行详情");
  await gotoNav(page, "Benchmark");
  await page.getByRole("heading", { name: "Benchmark Dashboard" }).waitFor({ timeout: 15_000 });
  await sleep(1500);

  const metrics = page.locator(".metrics-grid");
  if (await metrics.count()) {
    await metrics.scrollIntoViewIfNeeded();
    await sleep(2000);
  }

  const completedRow = page.locator(".data-table tbody tr").filter({ hasText: "completed" }).first();
  if (await completedRow.count()) {
    await completedRow.getByRole("button", { name: "查看" }).click();
    await sleep(2500);
    const sampleTable = page.locator("h4").filter({ hasText: "样本结果" });
    if (await sampleTable.count()) {
      await sampleTable.scrollIntoViewIfNeeded();
      await sleep(2000);
    }
  } else {
    await page.getByRole("button", { name: /快速评测/ }).hover();
    await sleep(1200);
    await page.getByRole("button", { name: /完整评测/ }).hover();
    await sleep(1500);
  }
}

async function showAdminAgentRuns(page, script) {
  script.push("8. admin_demo Agent Runs：全链路观测 timeline");
  await gotoNav(page, "Agent Runs");
  await page.getByRole("heading", { name: "Agent 运行记录" }).waitFor({ timeout: 15_000 });
  await sleep(1200);
  const firstRow = page.locator(".agent-runs-table__row").first();
  if (await firstRow.count()) {
    await firstRow.click();
    await sleep(2500);
  }
}

async function waitForAssistantReply(page, question, timeoutMs = 240_000) {
  const sendButton = page.getByRole("button", { name: /^发送$|^发送中\.\.\.$/ });
  await sendButton.filter({ hasText: "发送中..." }).waitFor({ timeout: 20_000 });
  await sendButton.filter({ hasText: "发送" }).waitFor({ timeout: timeoutMs });
  await page.locator(".typing-indicator").waitFor({ state: "hidden", timeout: timeoutMs });
  await page.waitForFunction(
    () => {
      const nodes = document.querySelectorAll(".message--assistant .message__content");
      const last = nodes[nodes.length - 1];
      if (!last) return false;
      const text = (last.textContent || "").trim();
      return text.length > 80 && text !== "思考中...";
    },
    undefined,
    { timeout: timeoutMs },
  );
  await sleep(3000);
}

async function collectLatestVideo(videoDir) {
  const files = await readdir(videoDir);
  const webms = files.filter((f) => f.endsWith(".webm"));
  if (webms.length === 0) return null;
  webms.sort();
  return path.join(videoDir, webms[webms.length - 1]);
}

async function main() {
  await mkdir(OUTPUT_DIR, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const finalWebm = path.join(OUTPUT_DIR, `fitness-coach-interview-demo-${stamp}.webm`);
  const tempVideoDir = path.join(OUTPUT_DIR, `.tmp-${stamp}`);

  const browser = await chromium.launch({ headless: false, slowMo: 80 });
  const context = await browser.newContext({
    viewport: VIEWPORT,
    recordVideo: { dir: tempVideoDir, size: VIEWPORT },
    locale: "zh-CN",
  });
  const page = await context.newPage();

  const script = [];

  try {
    script.push("1. 登录 coach_demo");
    await login(page, "coach_demo");
    await sleep(1000);

    await showCoachProfile(page, script);

    script.push("3. Chat：新建会话并发送典型面试问题（增肌 + 膝伤）");
    await gotoNav(page, "Chat");
    await page.getByRole("button", { name: "+ 新会话" }).click();
    await page.getByText("新会话（草稿）").waitFor({ timeout: 10_000 });
    await sleep(1200);

    await page.locator("textarea").fill(DEMO_QUESTION);
    await sleep(800);
    await page.getByRole("button", { name: "发送" }).click();
    await waitForAssistantReply(page, DEMO_QUESTION);

    script.push("4. 展开 Agent 执行过程与知识引用");
    const agentSteps = page.locator(".agent-steps");
    if (await agentSteps.count()) {
      await agentSteps.last().click();
      await sleep(1500);
    }
    const citations = page.locator(".message__citations");
    if (await citations.count()) {
      await citations.last().click();
      await sleep(1200);
    }
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
    await sleep(2000);

    script.push("5. 切换 admin_demo，展示管理端能力");
    await logout(page);
    await login(page, "admin_demo");
    await sleep(1000);

    await showAdminKnowledge(page, script);
    await showAdminBenchmark(page, script);
    await showAdminAgentRuns(page, script);

    script.push("9. 结束");
    await sleep(1500);
  } finally {
    await context.close();
    await browser.close();

    const rawVideo = await collectLatestVideo(tempVideoDir);
    if (rawVideo) {
      await rename(rawVideo, finalWebm);
    }
    await rm(tempVideoDir, { recursive: true, force: true });

    const deliverable = finalWebm;

    await writeFile(
      path.join(OUTPUT_DIR, `fitness-coach-interview-demo-${stamp}.md`),
      [
        "# Fitness Coach 面试演示录屏",
        "",
        `- 录制时间：${new Date().toLocaleString("zh-CN")}`,
        `- 视频文件：\`${path.basename(deliverable)}\``,
        `- 前端：${BASE_URL}`,
        `- 演示账号：coach_demo / admin_demo，密码 \`${DEMO_PASSWORD}\``,
        "",
        "## 演示步骤",
        ...script.map((line) => `- ${line}`),
        "",
        "## 推荐话术（5 分钟）",
        "",
        "1. **Profile**：用户档案（目标/伤病/器械）驱动个性化 tool 与建议。",
        "2. **Chat**：LangGraph Multi-Agent 并行 training/nutrition，Agent Steps 可观测。",
        "3. **RAG**：回复底部 citation 来自 Hybrid RAG，不是模型内化。",
        "4. **Knowledge**：kb 文档 ingest + pgvector 索引，支持重建。",
        "5. **Benchmark**：81 条样本 faithfulness / intent / citation 等指标。",
        "6. **Agent Runs**：agent_run / llm_calls 全链路 timeline。",
        "",
        "## 重新录制",
        "",
        "```bash",
        "cd scripts/demo",
        "pnpm install && pnpm run install-browser",
        "pnpm run record",
        "```",
        "",
        "更多口述稿见 [PITCH-15min.md](../PITCH-15min.md)。",
        "",
      ].join("\n"),
      "utf8",
    );

    console.log("\n✅ 演示视频已生成：");
    console.log(deliverable);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
