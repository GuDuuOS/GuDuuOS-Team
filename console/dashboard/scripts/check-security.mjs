/** Nexus 大屏 XSS 回归检查。
 *
 * 大屏是零依赖原生 JavaScript，项目没有浏览器 DOM 测试框架。这个脚本直接检查最敏感的
 * 服务端数据渲染函数，确保后续改样式时不会把 textContent/replaceChildren 又改回 innerHTML。
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const dashboardRoot = fileURLToPath(new URL("..", import.meta.url));
const appSource = readFileSync(new URL("../app.js", import.meta.url), "utf8");

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

// 让成功输出可被本地验证和 CI 日志明确识别。
console.log(`Nexus dashboard security checks passed (${dashboardRoot})`);
