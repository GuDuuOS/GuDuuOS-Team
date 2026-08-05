/** Nexus 大屏 XSS 回归检查。
 *
 * 大屏是零依赖原生 JavaScript，项目没有浏览器 DOM 测试框架。这个脚本直接检查最敏感的
 * 服务端数据渲染函数，确保后续改样式时不会把 textContent/replaceChildren 又改回 innerHTML。
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const dashboardRoot = fileURLToPath(new URL("..", import.meta.url));
const appSource = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const pageSource = readFileSync(new URL("../index.html", import.meta.url), "utf8");

function functionSource(name) {
  const marker = `function ${name}(`;
  const start = appSource.indexOf(marker);
  if (start < 0) throw new Error(`找不到函数 ${name}`);
  const bodyStart = appSource.indexOf("{", start);
  let depth = 0;
  for (let index = bodyStart; index < appSource.length; index += 1) {
    if (appSource[index] === "{") depth += 1;
    if (appSource[index] === "}") depth -= 1;
    if (depth === 0) return appSource.slice(start, index + 1);
  }
  throw new Error(`函数 ${name} 的花括号不完整`);
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

for (const name of ["renderRanking", "renderModelDist", "renderRecent", "addActivity"]) {
  const source = functionSource(name);
  assert(!source.includes(".innerHTML"), `${name} 禁止使用 innerHTML 渲染动态数据`);
  assert(
    source.includes("textContent") || source.includes("createActivityIcon"),
    `${name} 必须通过 DOM 文本 API 输出动态字段`,
  );
}

const tokenSource = functionSource("dashToken");
assert(tokenSource.includes("sessionStorage.setItem"), "大屏令牌必须写入 sessionStorage");
assert(
  !tokenSource.includes("localStorage.setItem"),
  "大屏令牌禁止写入可跨会话持久化的 localStorage",
);
assert(tokenSource.includes("history.replaceState"), "读取令牌后必须从地址栏移除 token hash");

// 运营数据真实性回归：生产默认节点数组必须为空；虚构舰队只能在本机显式启用。
assert(
  appSource.includes('new Set(["localhost", "127.0.0.1", "::1"])')
    && appSource.includes("DEMO_REQUESTED && DEMO_HOSTS.has"),
  "演示数据必须同时受 ?demo=1 与本机 hostname 限制",
);
assert(
  appSource.includes("const OEMS = DEMO_MODE ? DEMO_OEMS.map") && appSource.includes(": [];"),
  "生产默认 OEMS 必须为空，禁止把 DEMO_OEMS 作为接口失败回退",
);
const fetchSource = functionSource("fetchSummary");
for (const state of ['kind: "auth"', 'kind: "error"', 'kind: "empty"', 'kind: "ready"']) {
  assert(fetchSource.includes(state), `fetchSummary 必须区分数据状态 ${state}`);
}
const initSource = functionSource("init");
assert(
  initSource.includes('showDashboardState(fleetResult.kind'),
  "初始化失败/空数据时必须展示明确状态页",
);
assert(
  pageSource.includes('class="dashboard-pending"')
    && pageSource.includes('id="dashboard-data-state"')
    && pageSource.includes('id="dashboard-demo-badge"'),
  "HTML 必须默认隐藏演示占位，并提供真实数据状态页与 Demo 标识",
);

// 让成功输出可被本地验证和 CI 日志明确识别。
console.log(`Nexus dashboard security checks passed (${dashboardRoot})`);
