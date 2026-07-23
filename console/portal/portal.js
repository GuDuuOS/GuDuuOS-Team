/* GuDuu Nexus 控制台逻辑（vanilla，无构建）
 * ------------------------------------------------
 * 身份两种（登录后存 localStorage，刷新不丢）：
 *   admin —— NEXUS_ADMIN_TOKEN，走 /nexus/admin/*（看全部/签发/充值）
 *   oem   —— 会话令牌（邮箱登录签发），走 /nexus/oem/*（只见自己）
 * 所有权限由服务端强制；任何 401 一律清会话回登录页。
 */
(function () {
  "use strict";

  var LS_KEY = "nexus_portal_auth"; // {mode:'admin'|'oem', token:'...'}
  var THEME_KEY = "nexus_portal_theme"; // 'dark'(默认,与大屏一致) | 'light'(白色风格)

  // ---------- 主题（白色/暗色双风格,同一设计语言,只换明暗;选择持久化） ----------
  function applyTheme(theme) {
    // 默认暗色时不落 data-theme 属性,保持与老页面行为一致
    if (theme === "light") document.documentElement.dataset.theme = "light";
    else delete document.documentElement.dataset.theme;
    try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* 隐私模式忽略 */ }
    var btn = document.querySelector("#btn-theme");
    if (btn) btn.textContent = theme === "light" ? "🌙 暗色" : "☀️ 白色";
  }

  // ---------- 小工具 ----------
  function $(sel) { return document.querySelector(sel); }
  function $all(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  // token 数字人性化：1.2亿 这种中文单位比 K/M/B 对商务更友观
  function fmtTokens(n) {
    n = Number(n) || 0;
    var neg = n < 0 ? "-" : ""; n = Math.abs(n);
    if (n >= 1e8) return neg + (n / 1e8).toFixed(n % 1e8 ? 1 : 0) + "亿";
    if (n >= 1e4) return neg + (n / 1e4).toFixed(n % 1e4 ? 1 : 0) + "万";
    return neg + String(n);
  }
  function fmtTime(ms) {
    if (!ms) return "—";
    var d = new Date(Number(ms));
    function p(x) { return (x < 10 ? "0" : "") + x; }
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }
  // 心跳新旧 → 三色状态（与 fleet._display_status 同阈值：15 分钟/2 小时）
  function hbStatus(inst) {
    if (inst.status && inst.status !== "active") return "offline";
    if (!inst.last_seen_ts) return "offline";
    var age = Date.now() - inst.last_seen_ts;
    if (age > 2 * 3600e3) return "offline";
    if (age > 15 * 60e3) return "warning";
    return "active";
  }
  var STATUS_ZH = { active: "在线", warning: "迟滞", offline: "离线", revoked: "已吊销", disabled: "停用", idle: "未兑换" };
  function badge(st) { return '<span class="badge ' + esc(st) + '">' + esc(STATUS_ZH[st] || st) + "</span>"; }

  var toastTimer = null;
  function toast(msg, bad) {
    var t = $("#toast");
    t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.hidden = true; }, 3200);
  }

  // ---------- 会话 ----------
  function getAuth() {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || "null"); } catch (e) { return null; }
  }
  function setAuth(a) { localStorage.setItem(LS_KEY, JSON.stringify(a)); }
  function clearAuth() { localStorage.removeItem(LS_KEY); }

  // ---------- API ----------
  function api(path, opts) {
    opts = opts || {};
    var auth = getAuth();
    var headers = { "Content-Type": "application/json" };
    if (opts.token) headers["Authorization"] = "Bearer " + opts.token;
    else if (auth) headers["Authorization"] = "Bearer " + auth.token;
    // 用 origin 拼绝对地址：当页面地址栏带 basic-auth 凭据(user:pass@host)时，
    // 相对路径 fetch 会被浏览器整体拒绝；origin 永不含凭据，稳。
    return fetch(new URL(path, window.location.origin).href, {
      method: opts.method || (opts.body ? "POST" : "GET"),
      headers: headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (res.status === 401 && !opts.noKick) { // 会话失效 → 回登录页
          clearAuth(); route();
          throw new Error(data.error || "登录已失效，请重新登录");
        }
        if (!res.ok) throw new Error(data.error || ("请求失败(" + res.status + ")"));
        return data;
      });
    });
  }

  // ---------- 视图切换 ----------
  function show(viewId) {
    ["#view-login", "#view-oem", "#view-admin"].forEach(function (id) { $(id).hidden = (id !== viewId); });
    var auth = getAuth();
    $("#who").hidden = !auth;
    $("#btn-logout").hidden = !auth;
    if (auth) {
      $("#who").className = "who" + (auth.mode === "admin" ? " admin" : "");
      $("#who").textContent = auth.mode === "admin" ? "平台超管" : (auth.email || "OEM");
    }
  }
  function route() {
    var auth = getAuth();
    if (!auth) return show("#view-login");
    if (auth.mode === "admin") { show("#view-admin"); loadAdmin(); }
    else { show("#view-oem"); loadOem(); }
  }

  // ---------- 登录页 ----------
  $all(".tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      $all(".tab").forEach(function (b) { b.classList.toggle("on", b === btn); });
      $all(".pane").forEach(function (p) { p.hidden = (p.dataset.pane !== btn.dataset.tab); });
      $("#login-err").hidden = true;
    });
  });
  function loginErr(msg) { var el = $("#login-err"); el.textContent = msg; el.hidden = false; }

  $("#form-oem-login").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    api("/nexus/oem/login", { body: { email: f.email.value, password: f.password.value }, noKick: true })
      .then(function (r) { setAuth({ mode: "oem", token: r.token, email: r.oem.email }); route(); })
      .catch(function (err) { loginErr(err.message); });
  });

  $("#form-oem-reg").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    var email = f.email.value, pw = f.password.value;
    api("/nexus/oem/register", { body: { email: email, password: pw, name: f.name.value }, noKick: true })
      .then(function () { return api("/nexus/oem/login", { body: { email: email, password: pw }, noKick: true }); })
      .then(function (r) { setAuth({ mode: "oem", token: r.token, email: r.oem.email }); toast("注册成功，欢迎！"); route(); })
      .catch(function (err) { loginErr(err.message); });
  });

  $("#form-admin").addEventListener("submit", function (e) {
    e.preventDefault();
    var tok = e.target.token.value.trim();
    // 用一次只读请求验证令牌有效性，有效才落库进入
    api("/nexus/admin/instances", { token: tok, noKick: true })
      .then(function () { setAuth({ mode: "admin", token: tok }); route(); })
      .catch(function (err) { loginErr(err.message === "管理令牌无效" ? "令牌无效" : err.message); });
  });

  $("#btn-logout").addEventListener("click", function () {
    var auth = getAuth();
    if (auth && auth.mode === "oem") api("/nexus/oem/logout", { method: "POST", body: {}, noKick: true }).catch(function () {});
    clearAuth(); route();
  });

  // 主题切换：点击在白色/暗色之间轮换（初始值取持久化偏好,默认暗色与大屏一致）
  $("#btn-theme").addEventListener("click", function () {
    var cur = document.documentElement.dataset.theme === "light" ? "light" : "dark";
    applyTheme(cur === "light" ? "dark" : "light");
  });
  // 默认白色(负责人 2026-07-23 拍板);仅明确切过暗色的用户保持暗色
  applyTheme((function () {
    try { return localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light"; }
    catch (e) { return "light"; }
  })());

  // ---------- OEM 门户 ----------
  function loadOem() {
    api("/nexus/oem/me").then(function (r) {
      // 实例卡
      var box = $("#oem-instances");
      box.innerHTML = r.instances.map(function (i) {
        var st = hbStatus(i);
        var low = i.balance_tokens < 1e6; // 余额低于 100 万 token 标红提醒充值
        return '<div class="inst-card"><h3>' + esc(i.domain) + " " + badge(st) + "</h3>" +
          '<div class="row"><span>Token 余额</span><b class="' + (low ? "low" : "") + '">' + fmtTokens(i.balance_tokens) + "</b></div>" +
          '<div class="row"><span>版本</span><b>' + esc(i.version || "—") + "</b></div>" +
          '<div class="row"><span>最近心跳</span><b>' + fmtTime(i.last_seen_ts) + "</b></div>" +
          '<div class="row"><span>开通时间</span><b>' + fmtTime(i.created_ts) + "</b></div></div>";
      }).join("");
      $("#oem-noinst").hidden = r.instances.length > 0;
      // KEY 表
      $("#oem-keys tbody").innerHTML = r.keys.map(function (k) {
        var st = k.status !== "active" ? "revoked" : (k.instance_id ? "active" : "idle");
        return "<tr><td>#" + k.id + "</td><td>···" + esc(k.tail) + "</td><td class=\"zh\">" + badge(st) + "</td>" +
          "<td>" + fmtTokens(k.token_grant) + "</td><td class=\"zh\">" + (k.instance_id ? "#" + k.instance_id : "—") + "</td></tr>";
      }).join("") || '<tr><td colspan="5" class="zh empty">尚未认领任何授权码</td></tr>';
    }).catch(function (err) { toast(err.message, true); });
  }

  $("#form-claim").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    api("/nexus/oem/claim", { body: { key: f.key.value } })
      .then(function (r) {
        var el = $("#claim-msg");
        el.textContent = r.already ? "该授权码已在你名下" : ("认领成功（尾号 " + r.tail + "，附赠 " + fmtTokens(r.token_grant) + " token）");
        el.hidden = false; f.reset(); loadOem();
      })
      .catch(function (err) { toast(err.message, true); });
  });

  // ---------- 超管视图 ----------
  function loadAdmin() {
    Promise.all([
      api("/nexus/admin/instances"),
      api("/nexus/admin/keys"),
      api("/nexus/admin/oems"),
    ]).then(function (rs) {
      var insts = rs[0].instances, keys = rs[1].keys, oems = rs[2].oems;

      // 统计条
      var online = insts.filter(function (i) { return hbStatus(i) !== "offline"; }).length;
      var balSum = insts.reduce(function (a, i) { return a + (i.balance_tokens || 0); }, 0);
      $("#admin-stats").innerHTML =
        '<div class="stat"><small>实例总数</small><b class="plain">' + insts.length + "</b></div>" +
        '<div class="stat"><small>在线</small><b>' + online + "</b></div>" +
        '<div class="stat"><small>OEM 客户</small><b class="plain">' + oems.length + "</b></div>" +
        '<div class="stat"><small>KEY 已发/已兑换</small><b class="plain">' + keys.length + " / " + keys.filter(function (k) { return k.instance_id; }).length + "</b></div>" +
        '<div class="stat"><small>钱包余额合计</small><b>' + fmtTokens(balSum) + "</b></div>";

      // 实例表（行内充值按钮）
      $("#admin-instances tbody").innerHTML = insts.map(function (i) {
        return "<tr><td>#" + i.id + "</td><td>" + esc(i.domain) + "</td><td class=\"zh\">" + badge(hbStatus(i)) + "</td>" +
          "<td>" + esc(i.version || "—") + "</td><td>" + fmtTime(i.last_seen_ts) + "</td>" +
          "<td>" + fmtTokens(i.balance_tokens) + "</td>" +
          '<td class="zh"><button class="ghost small" data-topup="' + i.id + '" data-domain="' + esc(i.domain) + '">充值</button></td></tr>';
      }).join("") || '<tr><td colspan="7" class="zh empty">暂无实例</td></tr>';

      // KEY 表（吊销）
      $("#admin-keys tbody").innerHTML = keys.map(function (k) {
        var st = k.status !== "active" ? "revoked" : (k.instance_id ? "active" : "idle");
        return "<tr><td>#" + k.id + "</td><td>···" + esc(k.tail) + "</td><td class=\"zh\">" + badge(st) + "</td>" +
          "<td>" + fmtTokens(k.token_grant) + "</td><td class=\"zh\">" + esc(k.note || "—") + "</td>" +
          "<td class=\"zh\">" + (k.instance_id ? "#" + k.instance_id : "—") + "</td>" +
          '<td class="zh">' + (k.status === "active" ? '<button class="ghost small" data-revoke="' + k.id + '">吊销</button>' : "—") + "</td></tr>";
      }).join("") || '<tr><td colspan="7" class="zh empty">尚未签发</td></tr>';

      // OEM 客户表
      $("#admin-oems tbody").innerHTML = oems.map(function (o) {
        return "<tr><td>#" + o.id + "</td><td>" + esc(o.email) + "</td><td class=\"zh\">" + esc(o.name || "—") + "</td>" +
          "<td class=\"zh\">" + badge(o.status === "active" ? "active" : "disabled") + "</td>" +
          "<td>" + o.keys_claimed + "</td><td>" + fmtTime(o.created_ts) + "</td></tr>";
      }).join("") || '<tr><td colspan="6" class="zh empty">暂无注册客户</td></tr>';
    }).catch(function (err) { toast(err.message, true); });
  }

  $("#btn-refresh").addEventListener("click", loadAdmin);

  // 签发 KEY：明文只回显一次
  $("#form-issue").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    api("/nexus/admin/keys", {
      body: {
        count: Number(f.count.value) || 1,
        token_grant: Number(f.token_grant.value) || 0,
        note: f.note.value,
      },
    }).then(function (r) {
      $("#issued-keys").textContent = r.keys.map(function (k) { return k.key; }).join("\n");
      $("#issued-box").hidden = false;
      f.note.value = ""; loadAdmin();
    }).catch(function (err) { toast(err.message, true); });
  });

  // 表格行内操作（事件代理：吊销 / 充值）
  document.addEventListener("click", function (e) {
    var t = e.target;
    if (t.dataset && t.dataset.revoke) {
      if (!confirm("确认吊销 KEY #" + t.dataset.revoke + "？吊销后该码立即失效。")) return;
      api("/nexus/admin/revoke", { body: { key_id: Number(t.dataset.revoke) } })
        .then(function () { toast("已吊销"); loadAdmin(); })
        .catch(function (err) { toast(err.message, true); });
    }
    if (t.dataset && t.dataset.topup) {
      var v = prompt("给 " + t.dataset.domain + " 充值多少 token？（如 100000000 = 1亿）");
      if (!v) return;
      var n = Number(v);
      if (!(n > 0)) return toast("请输入正整数", true);
      api("/nexus/admin/topup", { body: { instance_id: Number(t.dataset.topup), tokens: n, note: "控制台手动充值" } })
        .then(function (r) { toast("充值成功，新余额 " + fmtTokens(r.balance_tokens)); loadAdmin(); })
        .catch(function (err) { toast(err.message, true); });
    }
  });

  // ---------- 大屏链接带上 dash token（超管令牌也能看大屏） ----------
  var auth0 = getAuth();
  if (auth0 && auth0.mode === "admin") $("#nav-dash").href = "/#token=" + encodeURIComponent(auth0.token);

  route();
})();
