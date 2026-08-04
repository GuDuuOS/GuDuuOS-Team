/* GuDuu Nexus 控制台逻辑（vanilla，无构建）
 * ------------------------------------------------
 * 身份两种（OEM token / 管理员非敏感显示信息只存当前标签页）：
 *   admin —— 具名管理员短期会话放 HttpOnly Cookie；SSH 单次码只作恢复入口
 *   oem   —— 会话令牌（邮箱登录签发），走 /nexus/oem/*（只见自己）
 * 所有权限由服务端强制；任何 401 一律清会话回登录页。
 */
(function () {
  "use strict";

  var AUTH_KEY = "nexus_portal_auth"; // admin 只存显示身份，OEM 才含会话 token
  var THEME_KEY = "nexus_portal_theme"; // 'dark'(默认,与大屏一致) | 'light'(白色风格)
  var ADMIN_ENTRY_PATH = "/portal/admin/";
  var volatileAuth = null; // 浏览器禁用 Storage 时的当前页面兜底，绝不回落长期存储
  var adminRestoreTried = false;
  var deploymentIntentApplied = false;

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
  function isAdminEntry() {
    // 同时兼容有无末尾斜杠；服务端会把两种地址都稳定映射到 Portal 首页。
    return window.location.pathname === "/portal/admin" ||
      window.location.pathname === ADMIN_ENTRY_PATH;
  }
  function configureLoginEntry() {
    var adminEntry = isAdminEntry();
    document.body.classList.toggle("admin-entry", adminEntry);
    document.title = adminEntry
      ? "GuDuu Nexus · 平台超管登录" : "GuDuu Nexus · 企业控制台";
    $("#login-title").textContent = adminEntry ? "平台超级管理员" : "登录企业控制台";
    $("#login-subtitle").textContent = adminEntry
      ? "使用具名管理员账号登录；SSH 单次码仅用于首次建号和故障恢复"
      : "管理你的 GuDuu OS 实例、授权与企业服务";
    $(".tabs").hidden = adminEntry;
    $("#form-admin").hidden = !adminEntry;
    if (adminEntry) {
      $all(".pane[data-pane]").forEach(function (pane) { pane.hidden = true; });
      $("#form-admin").hidden = false;
    } else {
      // 邀请链接会在路由初始化前选中注册页；这里读取当前 tab，而不是强制跳回密码
      // 登录，否则 OEM 分享二维码虽然地址正确，落地后却看不到注册表单。
      var selected = document.querySelector(".tab.on");
      var paneName = selected ? selected.dataset.tab : "oem-login";
      $all(".pane[data-pane]").forEach(function (pane) {
        pane.hidden = pane.dataset.pane !== paneName;
      });
      $("#form-admin").hidden = true;
    }
    $(".brand em").textContent = adminEntry ? "平台管理" : "控制台";
  }
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
  function activeDays(createdTs) {
    // 节点兑换开通当天记为第 1 天；未有真实开通时间时不猜测。
    var created = Number(createdTs) || 0;
    if (!created) return "—";
    return String(Math.max(1, Math.floor((Date.now() - created) / 86400000) + 1)) + " 天";
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
  var STATUS_ZH = {
    active: "在线", warning: "迟滞", offline: "离线", revoked: "已吊销",
    suspended: "已暂停", disabled: "停用", idle: "未兑换", needs_info: "待补资料",
    cancelled: "已撤回",
  };
  function badge(st) { return '<span class="badge ' + esc(st) + '">' + esc(STATUS_ZH[st] || st) + "</span>"; }

  var toastTimer = null;
  function toast(msg, bad) {
    var t = $("#toast");
    t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.hidden = true; }, 3200);
  }
  function copyText(value) {
    var text = String(value || "");
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    var area = document.createElement("textarea");
    area.value = text; area.style.position = "fixed"; area.style.opacity = "0";
    document.body.appendChild(area); area.select(); document.execCommand("copy"); area.remove();
    return Promise.resolve();
  }

  // WebAuthn 的 ArrayBuffer 不能直接放进 JSON；统一使用规范要求的无填充 base64url。
  function b64urlToBuffer(value) {
    var base64 = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
    while (base64.length % 4) base64 += "=";
    var raw = atob(base64);
    var bytes = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
    return bytes.buffer;
  }
  function bufferToB64url(value) {
    var bytes = new Uint8Array(value || new ArrayBuffer(0));
    var raw = "";
    for (var i = 0; i < bytes.length; i += 1) raw += String.fromCharCode(bytes[i]);
    return btoa(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function decodeCreationOptions(options) {
    options.challenge = b64urlToBuffer(options.challenge);
    options.user.id = b64urlToBuffer(options.user.id);
    (options.excludeCredentials || []).forEach(function (item) {
      item.id = b64urlToBuffer(item.id);
    });
    return options;
  }
  function decodeRequestOptions(options) {
    options.challenge = b64urlToBuffer(options.challenge);
    (options.allowCredentials || []).forEach(function (item) {
      item.id = b64urlToBuffer(item.id);
    });
    return options;
  }
  function registrationCredentialJson(credential) {
    return {
      id: credential.id,
      rawId: bufferToB64url(credential.rawId),
      type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment || null,
      response: {
        clientDataJSON: bufferToB64url(credential.response.clientDataJSON),
        attestationObject: bufferToB64url(credential.response.attestationObject),
        transports: credential.response.getTransports
          ? credential.response.getTransports() : [],
      },
    };
  }
  function authenticationCredentialJson(credential) {
    return {
      id: credential.id,
      rawId: bufferToB64url(credential.rawId),
      type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment || null,
      response: {
        clientDataJSON: bufferToB64url(credential.response.clientDataJSON),
        authenticatorData: bufferToB64url(credential.response.authenticatorData),
        signature: bufferToB64url(credential.response.signature),
        userHandle: credential.response.userHandle
          ? bufferToB64url(credential.response.userHandle) : null,
      },
    };
  }

  // ---------- 自家对话框（替代浏览器原生 confirm/prompt，风格统一） ----------
  var dlgResolve = null;
  function uiDialog(opts) {
    // opts: {text, input(布尔), placeholder, danger, okText}；返回 Promise：
    // 确定 → input 模式给输入串、否则 true；取消/点遮罩 → null
    return new Promise(function (resolve) {
      dlgResolve = resolve;
      $("#dlg-text").textContent = opts.text || "";
      var inp = $("#dlg-input");
      inp.hidden = !opts.input;
      inp.value = ""; inp.placeholder = opts.placeholder || "";
      var ok = $("#dlg-ok");
      ok.textContent = opts.okText || "确定";
      ok.classList.toggle("danger", !!opts.danger);
      $("#dlg-mask").hidden = false;
      if (opts.input) setTimeout(function () { inp.focus(); }, 60);
    });
  }
  function dlgClose(val) {
    $("#dlg-mask").hidden = true;
    var r = dlgResolve; dlgResolve = null;
    if (r) r(val);
  }
  function uiConfirm(text, danger, okText) {
    return uiDialog({ text: text, danger: danger, okText: okText }).then(function (v) { return v !== null; });
  }
  function uiPrompt(text, placeholder) {
    return uiDialog({ text: text, input: true, placeholder: placeholder });
  }

  // ---------- 会话 ----------
  function getAuth() {
    if (volatileAuth) return volatileAuth;
    var raw = "";
    try { raw = sessionStorage.getItem(AUTH_KEY) || ""; } catch (e) { /* 隐私模式忽略 */ }
    if (!raw) {
      // 只迁移一次旧版 localStorage 登录态，随后立即删除长期副本，避免同源大屏页面
      // 将来再发生 XSS 时跨标签、跨重启读取管理员令牌。
      try { raw = localStorage.getItem(AUTH_KEY) || ""; } catch (e) { /* 隐私模式忽略 */ }
      if (raw) {
        try { sessionStorage.setItem(AUTH_KEY, raw); } catch (e) { /* 当前页仍用内存态 */ }
      }
      // 删除长期副本必须独立执行：即使 sessionStorage 被浏览器禁用，也不能因前一步
      // 抛错而把管理员令牌继续留在 localStorage。
      try { localStorage.removeItem(AUTH_KEY); } catch (e) { /* 隐私模式忽略 */ }
    }
    try {
      volatileAuth = JSON.parse(raw || "null");
      return volatileAuth;
    } catch (e) {
      return null;
    }
  }
  function setAuth(auth) {
    volatileAuth = auth;
    try { sessionStorage.setItem(AUTH_KEY, JSON.stringify(auth)); } catch (e) { /* 隐私模式忽略 */ }
    try { localStorage.removeItem(AUTH_KEY); } catch (e) { /* 隐私模式忽略 */ }
  }
  function clearAuth() {
    volatileAuth = null;
    try { sessionStorage.removeItem(AUTH_KEY); } catch (e) { /* 隐私模式忽略 */ }
    try { localStorage.removeItem(AUTH_KEY); } catch (e) { /* 清理旧版遗留 */ }
  }

  // ---------- API ----------
  function api(path, opts) {
    opts = opts || {};
    var auth = getAuth();
    var method = opts.method || (opts.body ? "POST" : "GET");
    var headers = { "Content-Type": "application/json" };
    if (opts.token) headers["Authorization"] = "Bearer " + opts.token;
    else if (auth && auth.token) headers["Authorization"] = "Bearer " + auth.token;
    if (auth && auth.mode === "admin" && method === "POST") {
      // 管理 Cookie 会被浏览器自动携带；自定义头让跨站表单无法伪造写操作。
      headers["X-Nexus-CSRF"] = "1";
    }
    // 用 origin 拼绝对地址：当页面地址栏带 basic-auth 凭据(user:pass@host)时，
    // 相对路径 fetch 会被浏览器整体拒绝；origin 永不含凭据，稳。
    return fetch(new URL(path, window.location.origin).href, {
      method: method,
      headers: headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      credentials: "same-origin",
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

  // ---------- 超管数据大屏入口 ----------
  // 大屏聚合全部 OEM 经营数据，必须由超管先登录，再向服务端兑换只读令牌。入口初始化
  // 放在 route 生命周期里，而不是仅在脚本首次加载时执行：用户通常是“先打开登录页，
  // 再登录”，若只初始化一次，登录完成后永远拿不到大屏链接。
  var dashboardTokenLoading = false;
  function prepareDashboardLinks() {
    var auth = getAuth();
    var links = $all(".dashboard-link");
    var allowed = !!auth && auth.mode === "admin";
    links.forEach(function (link) { link.hidden = !allowed; });
    if (!allowed) {
      dashboardTokenLoading = false;
      links.forEach(function (link) {
        link.href = "/";
        link.dataset.ready = "false";
      });
      return;
    }
    if (links.some(function (link) { return link.dataset.ready === "true"; }) || dashboardTokenLoading) return;
    dashboardTokenLoading = true;
    api("/nexus/admin/dashboard-token").then(function (result) {
      if (!result || !result.token) throw new Error("服务端未返回只读大屏令牌");
      links.forEach(function (link) {
        var base = result.url || "/";
        link.href = base.replace(/\/$/, "") + "/#token=" + encodeURIComponent(result.token);
        link.dataset.ready = "true";
      });
      dashboardTokenLoading = false;
    }).catch(function (error) {
      dashboardTokenLoading = false;
      toast(error.message, true);
    });
  }
  $all(".dashboard-link").forEach(function (link) {
    link.dataset.ready = "false";
    link.addEventListener("click", function (event) {
      if (link.dataset.ready !== "true") {
        event.preventDefault();
        toast("只读大屏令牌尚未就绪，请稍后重试", true);
      }
    });
  });

  // ---------- OEM 左侧功能导航 ----------
  // OEM 门户和超管控制台都属于页面级工作台，因此同样使用 hash 保留当前功能页。
  // OEM 路径加 ``oem-`` 前缀，避免与超管已有的 overview/billing 等地址冲突。
  var OEM_PAGE_TITLES = {
    overview: "我的首页",
    network: "邀请与层级",
    announcements: "版本公告",
    commerce: "购买与充值",
    licenses: "授权申请",
    keys: "我的 KEY",
  };
  // 服务端返回开关之前采用安全默认值 false，避免页面初始渲染时短暂露出层级数据。
  var oemNetworkVisible = false;
  function oemPageFromHash() {
    var value = window.location.hash.replace(/^#oem-/, "").trim();
    return Object.prototype.hasOwnProperty.call(OEM_PAGE_TITLES, value) ? value : "overview";
  }
  function selectOemPage(page, resetScroll) {
    if (!Object.prototype.hasOwnProperty.call(OEM_PAGE_TITLES, page)) page = "overview";
    $all("[data-oem-view]").forEach(function (view) {
      view.hidden = view.dataset.oemView !== page;
    });
    $all("button[data-oem-page]").forEach(function (button) {
      var active = button.dataset.oemPage === page;
      button.classList.toggle("on", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    $("#oem-page-title").textContent = OEM_PAGE_TITLES[page];
    if (resetScroll) window.scrollTo(0, 0);
  }
  function openOemPage(page, resetScroll) {
    var targetHash = "oem-" + page;
    if (window.location.hash.replace(/^#/, "") === targetHash) {
      selectOemPage(page, resetScroll);
    } else {
      window.location.hash = targetHash;
    }
  }
  function applyOemFeatureFlags(flags) {
    oemNetworkVisible = !!(flags && flags.oem_network_visible);
    // 分享入口与二维码始终保留；开关只控制统计和名单两块敏感运营数据。
    $("#oem-network-stats").hidden = !oemNetworkVisible;
    $("#panel-network-directory").hidden = !oemNetworkVisible;
    $("#nav-oem-network").hidden = !oemNetworkVisible;
    if (!oemNetworkVisible) {
      // 清空浏览器 DOM 里的旧层级与名单数据，但不能清除分享链接和二维码。
      clearOemNetworkData();
    }
  }
  $all("button[data-oem-page]").forEach(function (button) {
    button.addEventListener("click", function () {
      openOemPage(button.dataset.oemPage, true);
    });
  });

  // ---------- 超管左侧功能导航 ----------
  // 控制台不用前端框架，但页面级功能仍要支持刷新、前进/后退和深链。因此用一个很小的
  // hash 状态机维护当前功能页；这里只切展示区域，所有权限和数据仍由服务端接口控制。
  var ADMIN_PAGE_TITLES = {
    overview: "舰队总览",
    releases: "版本与镜像",
    instances: "节点实例",
    licenses: "授权与申请",
    customers: "OEM 客户",
    billing: "支付与订单",
    security: "平台安全",
    guide: "使用教程",
  };

  // 超管教程只维护这一份结构化数据：页面渲染和“复制 Markdown”都从这里生成，
  // 避免运维规则更新后出现网页与对外文档内容不一致。
  var ADMIN_GUIDE = {
    title: "GuDuu Nexus 超级管理员安全操作指南",
    summary: "用于平台主管的日常登录、管理员开通、MFA、Passkey、应急恢复与离职撤权。",
    updated: "2026-08-03",
    sections: [
      {
        title: "1. 先理解两层安全边界",
        paragraphs: [
          "超管入口由 Cloudflare Access 和 GuDuu Nexus 两层独立鉴权共同保护。通过其中一层，不代表自动获得另一层权限。",
        ],
        items: [
          "Cloudflare Access：校验被允许的精确邮箱，并要求该用户完成 MFA。",
          "GuDuu Nexus：校验每位管理员自己的具名账号、密码或 Passkey，并记录操作审计。",
          "正式超管入口使用 https://admin-nexus.guduu.co；普通 OEM 域名不能直接调用超管接口。",
        ],
      },
      {
        title: "2. 创建首个具名管理员",
        ordered: true,
        items: [
          "仅在首次建号或故障恢复时，通过 Google Cloud SSH 运行 python -m nexus.recovery_codes 生成单次恢复码。",
          "打开“平台安全”，填写独立登录账号、显示名和高强度初始密码，创建具名管理员。",
          "退出恢复身份，使用刚创建的具名账号重新登录。",
          "重新进入“平台安全”，为该账号登记 Passkey；建议至少准备两个不同恢复设备。",
        ],
        note: "单次恢复码、密码、动态验证码和 Passkey 二维码都不得通过聊天、截图或邮件传播。",
      },
      {
        title: "3. 日常登录流程",
        ordered: true,
        items: [
          "访问独立超管域名，先通过 Cloudflare 邮箱验证。",
          "使用手机验证器、Passkey 或安全密钥完成 Cloudflare MFA。",
          "进入 Nexus 登录页后，使用自己的具名管理员账号和密码；已经登记 Passkey 时可改用 Passkey 登录。",
          "完成工作后主动退出，公共或临时设备不得保存密码和会话。",
        ],
      },
      {
        title: "4. 添加第二位及后续管理员",
        ordered: true,
        items: [
          "在 Cloudflare 的 GuDuu Nexus Admin 应用中，为新管理员创建仅包含其精确邮箱的 Allow 策略。",
          "在 App Launcher 中为同一邮箱添加精确邮箱策略，使其能够首次登记 MFA。",
          "在 Nexus“平台安全”中为对方创建独立具名账号和初始密码，禁止多人共用 owner 账号。",
          "由新管理员本人完成邮箱验证、MFA 登记、首次登录和自己的 Passkey 登记。",
        ],
        note: "不要使用 Everyone、邮箱域名后缀或其他宽泛规则；每人一条策略更便于单独撤权。",
      },
      {
        title: "5. Cloudflare MFA 与 App Launcher",
        items: [
          "超管应用应使用自定义 MFA，并设置合理的重新验证周期。",
          "首次登记 MFA 时，App Launcher 可在短暂开通窗口内只允许精确邮箱通过；登记完成后应恢复自定义 MFA。",
          "没有 Touch ID 的 Mac 可使用手机验证器；有 iPhone、密码管理器或实体安全密钥时，也可登记 Passkey 或安全密钥。",
          "MFA 设备丢失时应先撤销旧设备，再登记新设备，并检查近期 Access 登录记录。",
        ],
      },
      {
        title: "6. Nexus Passkey 建议",
        items: [
          "Passkey 只能由已经登录的具名管理员为自己登记，恢复身份不能登记。",
          "Mac 没有 Touch ID 时，可在浏览器提示中选择“使用其他设备”，用 iPhone 扫码并通过 Face ID 保存。",
          "建议至少登记两个不同恢复路径，例如 iPhone Passkey 加密码管理器或实体安全密钥。",
          "设备遗失后立即从“我的 Passkey”移除对应凭据；服务器只保存公钥，不保存设备私钥。",
        ],
      },
      {
        title: "7. 忘记账号或密码时",
        ordered: true,
        items: [
          "先确认 Cloudflare Access 仍能通过；它只保护入口，不会替你恢复 Nexus 密码。",
          "通过 Google Cloud SSH 在 Nexus 目录运行 python -m nexus.recovery_codes，终端会显示一枚 15 分钟单次码。",
          "用单次码进入“平台安全”，创建具名管理员或为现有管理员重置密码。",
          "恢复会话只用于恢复；完成后立即退出，再用具名账号登录并检查平台操作审计。",
        ],
        note: "单次码使用或过期后自动作废；如果疑似被看到，不要使用，等待过期后重新生成。",
      },
      {
        title: "8. 管理员离职或撤权",
        ordered: true,
        items: [
          "先从 Cloudflare GuDuu Nexus Admin 和 App Launcher 策略中移除该管理员邮箱。",
          "再到 Nexus“平台安全”停用其具名管理员账号，系统会立即撤销该账号的全部 Nexus 会话。",
          "确认其 Passkey 不再可用，并核对近期登录、密码重置、KEY、支付和版本发布审计。",
          "不要删除最后一个有效管理员；应始终保留至少两位可独立恢复的平台主管。",
        ],
      },
      {
        title: "9. 上线检查清单",
        items: [
          "Cloudflare 只允许明确列出的管理员邮箱。",
          "每位管理员均已登记 MFA，且没有共用验证器。",
          "每位管理员均使用独立 Nexus 账号，不共享密码。",
          "至少两位管理员拥有可用的 Passkey 或独立恢复路径。",
          "日常登录不使用 SSH 单次恢复码。",
          "管理员变更、版本发布、支付配置和 KEY 操作均可在审计中追溯。",
        ],
      },
    ],
  };

  function adminGuideMarkdown() {
    var lines = [
      "# " + ADMIN_GUIDE.title,
      "",
      ADMIN_GUIDE.summary,
      "",
      "> 更新日期：" + ADMIN_GUIDE.updated,
    ];
    ADMIN_GUIDE.sections.forEach(function (section) {
      lines.push("", "## " + section.title, "");
      (section.paragraphs || []).forEach(function (paragraph) {
        lines.push(paragraph, "");
      });
      (section.items || []).forEach(function (item, index) {
        lines.push((section.ordered ? String(index + 1) + ". " : "- ") + item);
      });
      if (section.note) lines.push("", "> 注意：" + section.note);
    });
    return lines.join("\n").trim() + "\n";
  }

  function renderAdminGuide() {
    var target = $("#admin-guide-content");
    if (target.dataset.rendered === "true") return;
    $("#admin-guide-title").textContent = ADMIN_GUIDE.title;
    $("#admin-guide-summary").textContent = ADMIN_GUIDE.summary;
    $("#admin-guide-updated").textContent = "更新于 " + ADMIN_GUIDE.updated;
    target.innerHTML = ADMIN_GUIDE.sections.map(function (section) {
      var paragraphs = (section.paragraphs || []).map(function (paragraph) {
        return "<p>" + esc(paragraph) + "</p>";
      }).join("");
      var tag = section.ordered ? "ol" : "ul";
      var items = (section.items || []).map(function (item) {
        return "<li>" + esc(item) + "</li>";
      }).join("");
      var note = section.note
        ? '<aside class="admin-guide-note"><b>注意</b><span>' + esc(section.note) + "</span></aside>"
        : "";
      return '<section class="admin-guide-section"><h3>' + esc(section.title) +
        "</h3>" + paragraphs + "<" + tag + ">" + items + "</" + tag + ">" + note + "</section>";
    }).join("");
    target.dataset.rendered = "true";
  }
  function adminPageFromHash() {
    var value = window.location.hash.replace(/^#/, "").trim();
    return Object.prototype.hasOwnProperty.call(ADMIN_PAGE_TITLES, value) ? value : "overview";
  }
  function selectAdminPage(page, resetScroll) {
    if (!Object.prototype.hasOwnProperty.call(ADMIN_PAGE_TITLES, page)) page = "overview";
    $all("[data-admin-view]").forEach(function (view) {
      view.hidden = view.dataset.adminView !== page;
    });
    $all("button[data-admin-page]").forEach(function (button) {
      var active = button.dataset.adminPage === page;
      button.classList.toggle("on", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    $("#admin-page-title").textContent = ADMIN_PAGE_TITLES[page];
    var guideOpen = page === "guide";
    $("#btn-admin-refresh").hidden = guideOpen;
    $("#btn-copy-admin-guide").hidden = !guideOpen;
    if (guideOpen) renderAdminGuide();
    if (resetScroll) window.scrollTo(0, 0);
  }
  $all("button[data-admin-page]").forEach(function (button) {
    button.addEventListener("click", function () {
      var target = button.dataset.adminPage;
      if (adminPageFromHash() === target) selectAdminPage(target, true);
      else window.location.hash = target;
    });
  });
  window.addEventListener("hashchange", function () {
    var auth = getAuth();
    if (auth && auth.mode === "admin") selectAdminPage(adminPageFromHash(), true);
    if (auth && auth.mode === "oem") selectOemPage(oemPageFromHash(), true);
  });

  // ---------- 视图切换 ----------
  function show(viewId) {
    ["#view-login", "#view-oem", "#view-admin"].forEach(function (id) { $(id).hidden = (id !== viewId); });
    var auth = getAuth();
    $("#who").hidden = !auth;
    $("#btn-logout").hidden = !auth;
    if (auth) {
      $("#who").className = "who" + (auth.mode === "admin" ? " admin" : "");
      $("#who").textContent = auth.mode === "admin"
        ? (auth.display_name || "平台超管") : (auth.email || "OEM");
    }
  }
  function route() {
    var auth = getAuth();
    if (!auth) {
      configureLoginEntry();
      show("#view-login");
      prepareDashboardLinks();
      // Cookie 是 HttpOnly，JavaScript 看不到令牌；新标签页通过 /me 恢复非敏感身份。
      if (isAdminEntry() && !adminRestoreTried) {
        adminRestoreTried = true;
        api("/nexus/admin/me", { noKick: true }).then(function (r) {
          setAuth({
            mode: "admin", token: "", admin_id: r.admin.id,
            display_name: r.admin.display_name, auth_kind: r.admin.auth_kind,
          });
          route();
        }).catch(function () { /* 没有有效 Cookie 时正常停留登录页 */ });
      }
      return;
    }
    if (auth.mode === "admin") {
      // 超管工作台只在独立地址展示；URL 分离不是权限边界，但可避免与 OEM 入口混淆。
      if (!isAdminEntry()) {
        window.location.replace(ADMIN_ENTRY_PATH + window.location.hash);
        return;
      }
      show("#view-admin");
      selectAdminPage(adminPageFromHash(), false);
      loadAdmin();
      loadAdminSecurity();
    }
    else {
      if (isAdminEntry()) {
        window.location.replace("/portal/" + window.location.hash);
        return;
      }
      show("#view-oem");
      var requestedDomain = new URLSearchParams(window.location.search).get("deployment_domain") || "";
      // 节点激活页带域名跳来时，登录/注册成功后直接落到授权申请并预填域名。只应用
      // 一次，避免用户随后手工清空或修改表单时又被 URL 强行覆盖。
      if (requestedDomain && !deploymentIntentApplied) {
        deploymentIntentApplied = true;
        window.location.hash = "oem-licenses";
        var licenseForm = $("#form-request");
        if (licenseForm && !licenseForm.deployment_domain.value) {
          licenseForm.deployment_domain.value = requestedDomain.toLowerCase().replace(/\.$/, "");
        }
      }
      selectOemPage(oemPageFromHash(), false);
      loadOem();
    }
    prepareDashboardLinks();
  }

  // ---------- 登录页 ----------
  $all(".tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      $all(".tab").forEach(function (b) { b.classList.toggle("on", b === btn); });
      $all(".pane").forEach(function (p) { p.hidden = (p.dataset.pane !== btn.dataset.tab); });
      $("#login-err").hidden = true;
      activateTurnstileForVisiblePane();
    });
  });

  // 下级 OEM 邀请链接：自动切注册页并锁定随机分享码，避免用户把直属上级填错。
  (function applyPartnerInvite() {
    var invite = new URLSearchParams(window.location.search).get("invite") || "";
    if (!invite) return;
    var form = $("#form-oem-reg");
    var tab = document.querySelector('[data-tab="oem-reg"]');
    if (!form || !tab) return;
    tab.click();
    form.inviter.value = invite;
    form.inviter.readOnly = true;
    form.inviter.title = "该直属上级来自邀请链接";
  })();
  // 节点激活页明确选择“注册成为 OEM”时直接展示注册表单；普通访问仍默认登录。
  (function applyActivationRegistrationIntent() {
    if (new URLSearchParams(window.location.search).get("register") !== "1") return;
    var tab = document.querySelector('[data-tab="oem-reg"]');
    if (tab) tab.click();
  })();
  function loginErr(msg) { var el = $("#login-err"); el.textContent = msg; el.hidden = false; }

  // 邮件能力由服务端布尔开关决定；浏览器不接触 SMTP 地址、账号或密码。配置未完成时
  // 按钮明确禁用，避免用户填完整张企业表单后才在最后一步发现邮件服务不可用。
  var oemEmailEnabled = false;
  var oemTurnstileEnabled = false;
  var oemTurnstileSiteKey = "";
  var turnstileScriptPromise = null;
  var turnstileWidgets = {};
  var turnstileActions = {
    register: "oem_register_code",
    login: "oem_login_code",
    reset: "oem_reset_code",
  };

  function loadTurnstileScript() {
    if (window.turnstile) return Promise.resolve(window.turnstile);
    if (turnstileScriptPromise) return turnstileScriptPromise;
    turnstileScriptPromise = new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      script.async = true;
      script.defer = true;
      script.onload = function () {
        if (window.turnstile) resolve(window.turnstile);
        else reject(new Error("Turnstile 未能初始化"));
      };
      script.onerror = function () { reject(new Error("Turnstile 脚本加载失败")); };
      document.head.appendChild(script);
    });
    return turnstileScriptPromise;
  }

  function disableTurnstileSending(message) {
    $all(".code-send").forEach(function (button) {
      button.disabled = true;
      button.title = message;
    });
    loginErr(message);
  }

  function setTurnstileMessage(purpose, message, state) {
    // 发码表单很长，顶部的全局错误在用户滚动到验证码区域后不可见；因此把本次
    // Turnstile/SMTP 结果同时显示在当前组件旁边。只写 textContent，避免错误文案
    // 或上游返回内容被当作 HTML 注入。
    var wrap = document.querySelector('[data-turnstile-purpose="' + purpose + '"]');
    var target = wrap && wrap.querySelector(".turnstile-message");
    if (!target) return;
    target.textContent = message;
    target.classList.toggle("bad", state === "bad");
    target.classList.toggle("ok", state === "ok");
  }

  function renderTurnstile(purpose) {
    if (!oemTurnstileEnabled || !purpose || turnstileWidgets[purpose] !== undefined) {
      return;
    }
    var wrap = document.querySelector('[data-turnstile-purpose="' + purpose + '"]');
    var slot = wrap && wrap.querySelector(".turnstile-slot");
    if (!slot) return;
    wrap.hidden = false;
    loadTurnstileScript().then(function (turnstile) {
      if (turnstileWidgets[purpose] !== undefined) return;
      turnstileWidgets[purpose] = turnstile.render(slot, {
        sitekey: oemTurnstileSiteKey,
        action: turnstileActions[purpose],
        theme: "light",
        size: "flexible",
        callback: function () {
          setTurnstileMessage(purpose, "安全验证已完成，可以发送验证码。", "ok");
        },
        "expired-callback": function () {
          setTurnstileMessage(purpose, "安全验证已过期，请重新完成验证。", "bad");
          turnstile.reset(turnstileWidgets[purpose]);
        },
        "error-callback": function () {
          var message = "人机验证加载失败，请检查网络后刷新页面";
          setTurnstileMessage(purpose, message, "bad");
          loginErr(message);
        },
      });
    }).catch(function () {
      disableTurnstileSending("人机验证暂时无法加载，请检查网络后刷新页面");
    });
  }

  function activateTurnstileForVisiblePane() {
    if (!oemTurnstileEnabled) return;
    var pane = document.querySelector(".pane:not([hidden])");
    var wrap = pane && pane.querySelector("[data-turnstile-purpose]");
    if (wrap) renderTurnstile(wrap.dataset.turnstilePurpose);
  }

  function turnstileTokenFor(purpose) {
    if (!oemTurnstileEnabled) return "";
    var widgetId = turnstileWidgets[purpose];
    if (widgetId === undefined || !window.turnstile) return "";
    return window.turnstile.getResponse(widgetId) || "";
  }

  function resetTurnstile(purpose) {
    var widgetId = turnstileWidgets[purpose];
    if (widgetId !== undefined && window.turnstile) window.turnstile.reset(widgetId);
  }

  function loadOemAuthConfig() {
    if (isAdminEntry()) return;
    api("/nexus/oem/auth/config", { noKick: true }).then(function (config) {
      oemEmailEnabled = config.email_verification === true;
      oemTurnstileEnabled = Boolean(config.turnstile && config.turnstile.enabled);
      oemTurnstileSiteKey = oemTurnstileEnabled ? String(config.turnstile.site_key || "") : "";
      $all("[data-turnstile-purpose]").forEach(function (wrap) {
        wrap.hidden = !oemTurnstileEnabled;
      });
      $all(".code-send").forEach(function (button) {
        button.disabled = !oemEmailEnabled;
        button.title = oemEmailEnabled ? "" : "邮箱验证服务正在配置中";
      });
      activateTurnstileForVisiblePane();
    }).catch(function () {
      oemEmailEnabled = false;
      $all(".code-send").forEach(function (button) {
        button.disabled = true;
        button.title = "暂时无法读取邮箱验证配置";
      });
    });
  }

  function beginCodeCooldown(button, seconds) {
    var left = Math.max(1, Number(seconds) || 60);
    var original = "发送验证码";
    button.disabled = true;
    button.textContent = left + " 秒";
    var timer = setInterval(function () {
      left -= 1;
      if (left <= 0) {
        clearInterval(timer);
        button.textContent = original;
        button.disabled = !oemEmailEnabled;
        return;
      }
      button.textContent = left + " 秒";
    }, 1000);
  }

  $all(".code-send").forEach(function (button) {
    button.addEventListener("click", function () {
      var form = button.closest("form");
      var email = form && form.email ? form.email.value.trim() : "";
      var purpose = button.dataset.codePurpose;
      if (!email) return loginErr("请先填写邮箱");
      if (!oemEmailEnabled) return loginErr("邮箱验证服务正在配置中，请稍后再试");
      var turnstileToken = turnstileTokenFor(purpose);
      if (oemTurnstileEnabled && !turnstileToken) {
        renderTurnstile(purpose);
        setTurnstileMessage(purpose, "请先完成人机验证，再发送验证码。", "bad");
        return loginErr("请先完成人机验证");
      }
      button.disabled = true;
      api("/nexus/oem/email/request-code", {
        body: {
          email: email,
          purpose: purpose,
          turnstile_token: turnstileToken,
        },
        noKick: true,
      }).then(function (result) {
        resetTurnstile(purpose);
        setTurnstileMessage(purpose, "验证码已发送；60 秒后可重新验证并发送。", "ok");
        loginErr("");
        $("#login-err").hidden = true;
        toast("如果邮箱可用，验证码已经发送");
        beginCodeCooldown(button, result.cooldown_seconds);
      }).catch(function (err) {
        resetTurnstile(purpose);
        button.disabled = false;
        setTurnstileMessage(purpose, err.message, "bad");
        loginErr(err.message);
      });
    });
  });

  $("#form-oem-login").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    api("/nexus/oem/login", { body: { email: f.email.value, password: f.password.value }, noKick: true })
      .then(function (r) { setAuth({ mode: "oem", token: r.token, email: r.oem.email }); route(); })
      .catch(function (err) { loginErr(err.message); });
  });

  $("#form-oem-code-login").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    api("/nexus/oem/login/code", {
      body: { email: f.email.value, code: f.code.value }, noKick: true,
    }).then(function (r) {
      setAuth({ mode: "oem", token: r.token, email: r.oem.email });
      f.code.value = "";
      route();
    }).catch(function (err) { loginErr(err.message); });
  });

  $("#form-oem-reg").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    var email = f.email.value, pw = f.password.value;
    api("/nexus/oem/register", { body: {
      email: email, code: f.code.value, password: pw, inviter: f.inviter.value,
      company: f.company.value, contact_name: f.contact_name.value, phone: f.phone.value,
    }, noKick: true })
      .then(function () { return api("/nexus/oem/login", { body: { email: email, password: pw }, noKick: true }); })
      .then(function (r) { setAuth({ mode: "oem", token: r.token, email: r.oem.email }); toast("注册成功，欢迎！"); route(); })
      .catch(function (err) { loginErr(err.message); });
  });

  $("#form-oem-reset").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    if (f.password.value !== f.password_confirm.value) {
      loginErr("两次输入的新密码不一致");
      return;
    }
    api("/nexus/oem/password/reset", {
      body: { email: f.email.value, code: f.code.value, password: f.password.value },
      noKick: true,
    }).then(function () {
      f.reset();
      document.querySelector('[data-tab="oem-login"]').click();
      toast("密码已重置，请使用新密码登录");
    }).catch(function (err) { loginErr(err.message); });
  });

  $("#form-admin").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    api("/nexus/admin/auth/login", {
      body: { username: f.username.value, password: f.password.value }, noKick: true,
    }).then(function (r) {
      adminRestoreTried = true;
      setAuth({
        mode: "admin", token: "", admin_id: r.admin.id,
        display_name: r.admin.display_name, auth_kind: "named_cookie",
      });
      // 登录成功后立刻清空 DOM 中的密码，避免共享屏幕或调试工具留下敏感信息。
      f.password.value = "";
      route();
    }).catch(function (err) { loginErr(err.message); });
  });

  $("#btn-passkey-login").addEventListener("click", function () {
    var form = $("#form-admin");
    var username = form.username.value.trim();
    if (!username) { loginErr("请先填写管理员账号"); return; }
    if (!window.PublicKeyCredential || !navigator.credentials) {
      loginErr("当前浏览器不支持 Passkey，请使用密码登录");
      return;
    }
    var ceremonyId = "";
    var button = this;
    button.disabled = true;
    api("/nexus/admin/auth/passkey/options", {
      body: { username: username }, noKick: true,
    }).then(function (result) {
      ceremonyId = result.ceremony_id;
      return navigator.credentials.get({
        publicKey: decodeRequestOptions(result.public_key),
      });
    }).then(function (credential) {
      if (!credential) throw new Error("未选择 Passkey");
      return api("/nexus/admin/auth/passkey/verify", {
        body: {
          ceremony_id: ceremonyId,
          credential: authenticationCredentialJson(credential),
        },
        noKick: true,
      });
    }).then(function (result) {
      adminRestoreTried = true;
      setAuth({
        mode: "admin", token: "", admin_id: result.admin.id,
        display_name: result.admin.display_name, auth_kind: "passkey_cookie",
      });
      form.password.value = "";
      route();
    }).catch(function (err) {
      // 用户主动取消时浏览器通常返回 NotAllowedError，也要给出可继续操作的提示。
      loginErr(err.name === "NotAllowedError"
        ? "Passkey 操作已取消或超时" : err.message);
    }).finally(function () { button.disabled = false; });
  });

  $("#btn-emergency-login").addEventListener("click", function () {
    var f = $("#form-admin");
    var code = f.recovery_code.value.trim();
    if (!code) { loginErr("请填写 SSH 生成的单次恢复码"); return; }
    api("/nexus/admin/auth/recovery", {
      body: { recovery_code: code }, noKick: true,
    }).then(function (r) {
      adminRestoreTried = true;
      setAuth({
        mode: "admin", token: "", admin_id: 0,
        display_name: r.admin.display_name || "服务器应急恢复",
        auth_kind: "recovery_cookie",
      });
      // 单次码消费成功后立刻从 DOM 移除，浏览器只保留短期 HttpOnly Cookie。
      f.recovery_code.value = "";
      route();
    }).catch(function (err) { loginErr(err.message); });
  });

  $("#btn-logout").addEventListener("click", function () {
    var auth = getAuth();
    if (auth && auth.mode === "oem") api("/nexus/oem/logout", { method: "POST", body: {}, noKick: true }).catch(function () {});
    if (auth && auth.mode === "admin") {
      // 等服务端撤销 Cookie 后再回登录页，避免 /me 恢复流程与退出请求发生竞态。
      api("/nexus/admin/auth/logout", { method: "POST", body: {}, noKick: true })
        .then(function () {
          clearAuth(); adminRestoreTried = true; route();
        })
        .catch(function () {
          clearAuth(); adminRestoreTried = true; route();
        });
      return;
    }
    clearAuth(); route();
  });

  // 对话框按钮（组件级监听,一次绑定）
  $("#dlg-ok").addEventListener("click", function () {
    var inp = $("#dlg-input");
    dlgClose(inp.hidden ? true : inp.value);
  });
  $("#dlg-cancel").addEventListener("click", function () { dlgClose(null); });
  $("#dlg-mask").addEventListener("click", function (e) { if (e.target === this) dlgClose(null); });
  $("#dlg-input").addEventListener("keydown", function (e) { if (e.key === "Enter") $("#dlg-ok").click(); });

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
  var CH_ZH = {
    alipay: "支付宝", wechat: "微信支付", stripe: "Stripe", paypal: "PayPal",
    usdt: "USDT", mock: "模拟支付(开发)", corporate_transfer: "企业转账（人工）"
  };
  var licensePricing = { key_price_cents: 0, key_token_grant: 0 };
  var licenseChannels = {};
  function fmtYuan(cents) {
    var y = (Number(cents) || 0) / 100;
    return "¥" + (y % 1 ? y.toFixed(2) : String(y));
  }

  function loadShareQr(img, path) {
    var auth = getAuth();
    fetch(new URL(path, window.location.origin).href, {
      headers: { "Authorization": "Bearer " + (auth ? auth.token : "") },
    }).then(function (res) {
      if (!res.ok) throw new Error("二维码生成失败(" + res.status + ")");
      return res.blob();
    }).then(function (blob) {
      if (img.dataset.objectUrl) URL.revokeObjectURL(img.dataset.objectUrl);
      var objectUrl = URL.createObjectURL(blob);
      img.dataset.objectUrl = objectUrl;
      img.src = objectUrl;
    }).catch(function (err) {
      img.alt = err.message;
    });
  }

  function clearOemNetworkData() {
    "use strict";
    // 只清除受控统计与目录，分享码、注册链接和二维码必须继续可用。
    $("#oem-ref-level").textContent = "—";
    $("#oem-ref-users").textContent = "0";
    $("#oem-ref-direct").textContent = "0";
    $("#oem-ref-network").textContent = "0 / 0";
    $("#nav-oem-network").textContent = "0";
    $("#oem-network-total").textContent = "0 家企业 · 0 个用户";
    $("#oem-downline-count").textContent = "0 家";
    $("#oem-downline-user-count").textContent = "0 人";
    $("#oem-downline-oems tbody").innerHTML = "";
    $("#oem-downline-users tbody").innerHTML = "";
    $("#oem-network-limit-note").hidden = true;
  }

  function renderReferral(referral) {
    var r = referral || {};
    $("#oem-referral-code").textContent = r.code ? ("分享码 · " + r.code) : "分享码生成中";
    $("#oem-ref-level").textContent = r.level ? ("第 " + r.level + " 层") : "—";
    $("#oem-ref-users").textContent = String(r.direct_users || 0);
    $("#oem-ref-direct").textContent = String(r.direct_oems || 0);
    $("#oem-ref-network").textContent = String(r.total_downline_oems || 0) + " / " + String(r.network_users || 0);

    var links = r.user_links || [];
    $("#oem-user-share").innerHTML = links.map(function (item) {
      return '<div class="share-item"><img class="share-qr" data-user-qr="' + item.instance_id + '" alt="用户注册二维码" />' +
        '<div><div class="share-domain">' + esc(item.domain) + '</div>' +
        '<input class="share-url" readonly value="' + esc(item.url) + '" />' +
        '<div class="share-actions"><button class="ghost small" data-copy-link="' + esc(item.url) + '">复制注册链接</button>' +
        '<a class="ghost small" href="' + esc(item.url) + '" target="_blank" rel="noopener">打开注册页</a></div></div></div>';
    }).join("") || '<p class="empty">开通并兑换实例后，这里会自动生成普通用户注册链接和二维码。</p>';
    links.forEach(function (item) {
      var img = document.querySelector('[data-user-qr="' + item.instance_id + '"]');
      if (img) loadShareQr(img, "/nexus/oem/share_qr?kind=user&instance_id=" + item.instance_id);
    });

    var partner = String(r.partner_link || "");
    $("#oem-partner-share").innerHTML = partner
      ? '<div class="share-item"><img class="share-qr" id="partner-share-qr" alt="下级 OEM 注册二维码" />' +
        '<div><div class="share-domain">OEM 合作伙伴注册链接</div><input class="share-url" readonly value="' + esc(partner) + '" />' +
        '<div class="share-actions"><button class="ghost small" data-copy-link="' + esc(partner) + '">复制 OEM 邀请链接</button>' +
        '<a class="ghost small" href="' + esc(partner) + '" target="_blank" rel="noopener">打开注册页</a></div></div></div>'
      : '<p class="empty">分享链接生成中。</p>';
    if (partner) loadShareQr($("#partner-share-qr"), "/nexus/oem/share_qr?kind=partner");
  }

  // 渲染当前 OEM 自己的下属目录。企业与用户范围已在服务端按层级树
  // 裁剪，前端不做“隐藏别家数据”这种不可靠的权限控制，只负责展示。
  function renderNetworkDirectory(directory) {
    var d = directory || {};
    var oems = d.oems || [];
    var users = d.users || [];
    var oemTotal = Number(d.oem_total || 0);
    var userTotal = Number(d.user_total || 0);

    $("#nav-oem-network").textContent = String(oemTotal + userTotal);
    $("#oem-network-total").textContent = oemTotal + " 家企业 · " + userTotal + " 个用户";
    $("#oem-downline-count").textContent = oemTotal + " 家";
    $("#oem-downline-user-count").textContent = userTotal + " 人";
    $("#oem-network-limit-note").hidden = !(d.oems_truncated || d.users_truncated);

    $("#oem-downline-oems tbody").innerHTML = oems.map(function (item) {
      var relation = item.relation === "direct"
        ? '<span class="badge active">直属下级</span>'
        : '<span class="badge idle">间接 · ' + Number(item.depth || 0) + " 级</span>";
      var status = item.status === "active"
        ? '<span class="network-status-dot active" title="企业账号正常"></span>'
        : '<span class="network-status-dot disabled" title="企业账号已停用"></span>';
      return '<tr><td class="zh"><div class="network-company">' + status + '<b>' + esc(item.company || ("OEM #" + item.id)) + '</b></div></td>' +
        '<td class="zh"><div class="network-relation">' + relation + '<small>全局第 ' + Number(item.level || 0) + " 层</small></div></td>" +
        '<td class="zh">' + esc(item.parent_company || "GuDuu") + "</td>" +
        "<td>" + Number(item.direct_users || 0) + "</td>" +
        "<td>" + Number(item.network_users || 0) + "</td>" +
        '<td><b>' + Number(item.direct_oems || 0) + '</b><small class="network-cell-note"> / 全部 ' + Number(item.total_downline_oems || 0) + "</small></td>" +
        "<td>" + fmtTime(item.created_ts) + "</td></tr>";
    }).join("") || '<tr><td colspan="7" class="zh empty network-empty">暂无下级 OEM。分享上方“OEM 合作伙伴注册链接”，对方完成注册后会自动出现在这里。</td></tr>';

    $("#oem-downline-users tbody").innerHTML = users.map(function (item) {
      var relation = item.relation === "direct"
        ? '<span class="badge active">直属我的企业</span>'
        : '<span class="badge idle">下级网络 · ' + Number(item.depth || 0) + " 级</span>";
      return "<tr><td>" + esc(item.user_id || "—") + '</td><td class="zh">' + esc(item.oem_company || "—") +
        "</td><td>" + esc(item.instance_domain || ("#" + item.instance_id)) +
        '</td><td class="zh">' + relation + "</td><td>" + fmtTime(item.created_ts) + "</td></tr>";
    }).join("") || '<tr><td colspan="5" class="zh empty network-empty">暂无归属用户。用户通过上方带分享码的实例链接注册后，会自动出现在这里。</td></tr>';
  }

  // 渲染「购买与充值」区（定价 + 渠道可用性 + 我的实例下拉）
  function renderShop(products, instances) {
    var pricing = products.pricing, ch = products.channels;
    licensePricing = pricing;
    licenseChannels = ch || {};
    // 渠道按钮：可用=亮橙可点；未配凭据=灰禁用(开通中)
    function chButtons(attr, extra) {
      return ["alipay", "wechat", "mock"].filter(function (c) { return c !== "mock" || ch.mock; })
        .map(function (c) {
          var ok = !!ch[c];
          return '<button class="' + (ok ? "primary" : "ghost") + ' small" ' + (ok ? "" : "disabled title=\"渠道开通中\" ") +
            'data-' + attr + '="' + c + '"' + (extra || "") + ">" + CH_ZH[c] + (ok ? "" : "·开通中") + "</button>";
        }).join("");
    }
    var keyOn = pricing.key_price_cents > 0;
    var topupOn = pricing.topup_packs.length > 0 && instances.length > 0;
    $("#shop-key").hidden = !keyOn;
    if (keyOn) {
      $("#shop-key-desc").textContent = "附赠 " + fmtTokens(pricing.key_token_grant) + " token · 支付与部署资料统一进入授权申请";
      $("#shop-key-btns").innerHTML = '<span class="shop-price">' + fmtYuan(pricing.key_price_cents) + "</span>" +
        chButtons("buykey") + '<button class="ghost small" data-buykey-transfer="1">企业转账购买</button>';
    }
    $("#shop-topup").hidden = !topupOn;
    if (topupOn) {
      // 卡片式选择（替代原生下拉）：默认选中第一项，点卡片切换
      $("#topup-inst").innerHTML = instances.map(function (i, idx) {
        return '<button type="button" class="pick' + (idx === 0 ? " on" : "") + '" data-pick="inst" data-val="' + i.id + '">' +
          esc(i.domain) + "<small>余额 " + fmtTokens(i.balance_tokens) + "</small></button>";
      }).join("");
      $("#topup-pack").innerHTML = pricing.topup_packs.map(function (p, idx) {
        return '<button type="button" class="pick' + (idx === 0 ? " on" : "") + '" data-pick="pack" data-val="' + idx + '">' +
          fmtTokens(p.tokens) + " token<small>" + fmtYuan(p.cents) + "</small></button>";
      }).join("");
      $("#shop-topup-btns").innerHTML = chButtons("buytopup");
    }
    $("#shop-none").hidden = keyOn || topupOn;
    var availableChannels = ["alipay", "wechat", "stripe", "paypal", "usdt", "mock"]
      .filter(function (name) { return !!licenseChannels[name]; });
    $("#license-channel").innerHTML = availableChannels.map(function (name) {
      return '<option value="' + name + '">' + esc(CH_ZH[name] || name) + "</option>";
    }).join("") || '<option value="">暂无可用在线渠道</option>';
    var method = $("#license-payment-method");
    if (method && !keyOn && method.value !== "manual_review") method.value = "manual_review";
    syncLicensePaymentForm();
  }

  function syncLicensePaymentForm() {
    var form = $("#form-request");
    if (!form) return;
    var method = form.payment_method.value;
    var editing = !!editingRequestId;
    var transfer = method === "corporate_transfer" && !editing;
    var online = method === "online" && !editing;
    $("#license-transfer-fields").hidden = !transfer;
    $("#license-online-channel").hidden = !online;
    $("#license-manual-tokens").hidden = method !== "manual_review";
    form.payer_company.required = transfer;
    form.voucher.required = transfer;
    form.payment_method.disabled = editing;
    form.requested_tokens.disabled = editing && method !== "manual_review";
    var priced = Number(licensePricing.key_price_cents) > 0;
    var summary = $("#license-price-summary");
    if (editing) {
      summary.textContent = "正在修改申请资料，已选付款方式和金额不变。";
    } else if (method === "manual_review") {
      summary.textContent = "合同/免费授权不创建付款单，由超管人工决定是否签发。";
    } else if (priced) {
      summary.textContent = "应付 " + fmtYuan(licensePricing.key_price_cents) + " · 附赠 " +
        fmtTokens(licensePricing.key_token_grant) + " Token";
    } else {
      summary.textContent = "平台尚未设置授权售价，请选择合同/免费授权。";
    }
    var submit = form.querySelector('button[type="submit"]');
    if (!editing) {
      submit.textContent = method === "corporate_transfer" ? "提交转账凭证" :
        (method === "online" ? "创建订单并支付" : "提交人工授权申请");
    }
    submit.disabled = !editing && (
      ((method === "online" || method === "corporate_transfer") && !priced) ||
      (method === "online" && !form.channel.value)
    );
  }

  $("#license-payment-method").addEventListener("change", syncLicensePaymentForm);

  // 渲染「我的订单」
  var ORDER_ST = {
    pending: ["warning", "待支付"], pending_review: ["warning", "待核对到账"],
    paid: ["active", "已支付"], rejected: ["revoked", "已拒绝"],
    cancelled: ["idle", "已撤回"], closed: ["idle", "已关闭"],
  };
  function renderOrders(orders) {
    $("#panel-orders").hidden = orders.length === 0;
    $("#oem-orders tbody").innerHTML = orders.map(function (o) {
      var st = ORDER_ST[o.status] || ["idle", o.status];
      var what = o.kind === "key" ? "授权码 ×1" : "充值 " + fmtTokens(o.tokens) + "（实例 #" + o.instance_id + "）";
      var keyCell = o.key ? '<b style="user-select:all">' + esc(o.key) + "</b>"
        : (o.kind === "key" && o.status === "paid"
          ? '<span class="zh">' + (o.request_id ? "请在授权申请中领取" : "已使用") + "</span>" : "—");
      return "<tr><td>" + esc(o.order_no) + '</td><td class="zh">' + what + "</td><td>" + fmtYuan(o.amount_cents) + "</td>" +
        '<td class="zh">' + (CH_ZH[o.channel] || o.channel) + '</td><td class="zh"><span class="badge ' + st[0] + '">' + st[1] + "</span></td>" +
        "<td>" + keyCell + "</td><td>" + fmtTime(o.created_ts) + "</td></tr>";
    }).join("");
  }

  var WITHDRAW_ST = {
    pending: ["warning", "待审核"], approved: ["active", "已批准待打款"],
    paid: ["active", "已打款"], rejected: ["revoked", "已驳回"],
  };
  function renderOemFinance(finance) {
    var summary = finance.summary || {}, terms = finance.terms || {};
    $("#oem-earned").textContent = fmtYuan(summary.earned_cents || 0);
    $("#oem-income-pending").textContent = fmtYuan(summary.pending_cents || 0);
    $("#oem-income-available").textContent = fmtYuan(summary.available_cents || 0);
    $("#oem-withdrawn").textContent = fmtYuan(summary.withdrawn_cents || 0);
    $("#oem-settlement-note").textContent = "直属下级完成真实支付后，价差进入待结算；T+" +
      Number(terms.settlement_days || 0) + " 转为可提现，平台主管订单不产生收益。";
    var termRows = [];
    if (Number(terms.key_retail_cents) > 0) {
      termRows.push('<div class="reseller-term"><b>下级 OEM 授权兑换码</b>客户价 ' +
        fmtYuan(terms.key_retail_cents) + " · 结算价 " + fmtYuan(terms.key_settlement_cents) +
        " · 每单收益 " + fmtYuan(terms.key_margin_cents) + "</div>");
    }
    (terms.topup_packs || []).forEach(function (item) {
      termRows.push('<div class="reseller-term"><b>' + fmtTokens(item.tokens) +
        " Token</b>客户价 " + fmtYuan(item.retail_cents) + " · 结算价 " +
        fmtYuan(item.settlement_cents) + " · 每单收益 " + fmtYuan(item.margin_cents) + "</div>");
    });
    $("#oem-reseller-terms").innerHTML = termRows.join("") ||
      '<p class="empty">平台尚未配置可销售的授权或充值套餐。</p>';
    var withdrawInput = $("#form-oem-withdraw").amount_yuan;
    withdrawInput.min = String((Number(terms.withdraw_min_cents) || 100) / 100);
    withdrawInput.placeholder = "最低 " + fmtYuan(terms.withdraw_min_cents || 100);
    $("#oem-income-ledger tbody").innerHTML = (finance.ledger || []).map(function (item) {
      var sale = String(item.kind || "").indexOf("sale_") === 0;
      var source = sale ? (item.kind === "sale_key" ? "授权兑换码" : "Token 充值") :
        (item.kind === "withdrawal" ? "申请提现" : (item.kind === "withdrawal_return" ? "提现退回" : item.kind));
      var valueClass = Number(item.delta_cents) >= 0 ? "income-positive" : "income-negative";
      return '<tr><td class="zh"><b>' + esc(source) + '</b><div class="hint">' + esc(item.note || "") +
        '</div></td><td>' + (sale ? fmtYuan(item.gross_cents) : "—") + '</td><td>' +
        (sale ? fmtYuan(item.settlement_cents) : "—") + '</td><td class="' + valueClass + '">' +
        (Number(item.delta_cents) >= 0 ? "+" : "") + fmtYuan(item.delta_cents) + '</td><td>' +
        (sale ? fmtTime(item.available_ts) : fmtTime(item.created_ts)) + "</td></tr>";
    }).join("") || '<tr><td colspan="5" class="empty">暂无收益流水</td></tr>';
    $("#oem-withdrawals tbody").innerHTML = (finance.withdrawals || []).map(function (item) {
      var st = WITHDRAW_ST[item.status] || ["idle", item.status];
      return '<tr><td>' + esc(item.withdrawal_no) + '</td><td>' + fmtYuan(item.amount_cents) +
        '</td><td class="zh">' + esc(item.payout_masked || "—") + '</td><td class="zh"><span class="badge ' +
        st[0] + '">' + esc(st[1]) + '</span></td><td>' + fmtTime(item.created_ts) + "</td></tr>";
    }).join("") || '<tr><td colspan="5" class="empty">暂无提现记录</td></tr>';
  }

  var paymentConfigs = {};
  var manualTransferAi = {};
  var manualTransferOems = [];
  function renderFinanceOverview(payload, configs) {
    // 所有金额都来自服务端全历史聚合；前端只负责格式化，不能从受限的近 200 单列表
    // 再次求和，否则业务增长后会悄悄少算收入。
    var f = payload.finance || {};
    manualTransferAi = payload.manual_transfer_ai || {};
    paymentConfigs = {};
    (configs || []).forEach(function (item) { paymentConfigs[item.provider] = item; });
    $("#admin-finance-stats").innerHTML =
      '<div class="stat"><small>累计已支付</small><b>' + fmtYuan(f.paid_revenue_cents) +
      '</b><span class="stat-note">' + (f.paid_order_count || 0) + ' 笔已确认收款记录</span></div>' +
      '<div class="stat"><small>近 30 天已支付</small><b>' + fmtYuan(f.paid_revenue_30d_cents) +
      '</b><span class="stat-note">按支付成功时间统计</span></div>' +
      '<div class="stat"><small>待支付金额</small><b class="plain">' + fmtYuan(f.pending_amount_cents) +
      '</b><span class="stat-note">' + (f.pending_order_count || 0) + ' 笔，不计入收入</span></div>' +
      '<div class="stat"><small>Token 充值收入</small><b>' + fmtYuan(f.topup_revenue_cents) +
      '</b><span class="stat-note">已交付 ' + fmtTokens(f.topup_tokens) + ' Token</span></div>' +
      '<div class="stat"><small>企业转账实收</small><b class="manual-money">' +
      fmtYuan(f.manual_transfer_revenue_cents) + '</b><span class="stat-note">' +
      (f.manual_transfer_count || 0) + ' 笔人工确认单</span></div>' +
      '<div class="stat"><small>OEM 待结算 / 可提现</small><b>' +
      fmtYuan(f.oem_pending_settlement_cents) + ' / ' + fmtYuan(f.oem_available_cents) +
      '</b><span class="stat-note">' + (f.withdraw_pending_count || 0) + ' 笔提现待处理</span></div>';

    $("#admin-finance-breakdown").innerHTML =
      '<div class="finance-row"><span>授权码买断</span><b>' + fmtYuan(f.key_revenue_cents) +
      ' · ' + (f.key_paid_count || 0) + ' 单</b></div>' +
      '<div class="finance-row"><span>Token 在线充值</span><b>' + fmtYuan(f.topup_revenue_cents) +
      ' · ' + (f.topup_paid_count || 0) + ' 单</b></div>' +
      '<div class="finance-row"><span>企业转账（手工确认）</span><b class="manual-money">' +
      fmtYuan(f.manual_transfer_revenue_cents) + ' · ' + (f.manual_transfer_count || 0) + ' 单</b></div>' +
      '<div class="finance-row"><span>当前全舰队 Token 余额</span><b id="finance-wallet-balance">—</b></div>';

    function channelRow(provider, fallbackLabel, fallbackNote) {
      var item = paymentConfigs[provider] || {};
      var status = item.verify_status || "not_configured";
      var statusUi = {
        not_configured: ["idle", "填写 API"],
        not_checked: ["warning", "待验证"],
        remote_verified: ["active", "官方认证通过"],
        local_valid: ["warning", "格式已验证"],
        verification_failed: ["offline", "验证失败"],
      }[status] || ["idle", status];
      return '<button type="button" class="finance-row payment-channel-row" data-payment-config="' + provider + '">' +
        '<span><b class="channel-name">' + esc(item.label || fallbackLabel) +
        '</b><small class="channel-note">' + esc(item.summary || fallbackNote) + '</small></span>' +
        '<b class="channel-status"><span class="badge ' + statusUi[0] + '">' + statusUi[1] +
        '</span><i class="channel-arrow">›</i></b></button>';
    }
    $("#admin-payment-domestic").innerHTML =
      channelRow("alipay", "支付宝", "人民币 · 网页支付") +
      channelRow("wechat", "微信支付", "人民币 · Native 扫码") +
      '<button type="button" class="finance-row payment-channel-row manual-transfer-entry" data-manual-transfer="open">' +
      '<span><b class="channel-name">企业转账</b><small class="channel-note">人工登记 · 凭证必传 · AI 辅助识别</small></span>' +
      '<b class="channel-status"><span class="badge manual">手工入账</span><i class="channel-arrow">›</i></b></button>' +
      '<div class="finance-row"><span>收入确认规则</span><b class="channel-status">自动回调 / 人工核实后计入</b></div>';
    $("#admin-payment-overseas").innerHTML =
      channelRow("stripe", "Stripe", "银行卡 · 多币种") +
      channelRow("paypal", "PayPal", "PayPal 账户 · 多币种") +
      channelRow("usdt", "USDT（NOWPayments）", "稳定币 · 自动对账") +
      '<div class="finance-row"><span>外币统计规则</span><b class="channel-status">按原币分开核算</b></div>';
  }

  // ---------- 支付配置中心 ----------
  var PAYMENT_STATUS_ZH = {
    not_configured: "尚未配置",
    not_checked: "已保存，尚未验证",
    remote_verified: "官方远程认证通过",
    local_valid: "本地格式验证通过",
    verification_failed: "验证失败",
  };
  function renderPaymentState(item) {
    var status = item.verify_status || "not_configured";
    var checked = item.last_checked_ts ? " · 最近检查 " + fmtTime(item.last_checked_ts) : "";
    $("#payment-state").innerHTML = "<strong>" + esc(PAYMENT_STATUS_ZH[status] || status) +
      "</strong> · " + esc(item.verify_message || "尚未填写凭据") + checked +
      '<br><span class="hint">真实交易状态：未开放。还需完成订单币种、下单、回调验签与沙箱交易验收。</span>';
  }
  function openPaymentConfig(provider) {
    var item = paymentConfigs[provider];
    if (!item) { toast("支付配置数据尚未加载，请刷新后重试", true); return; }
    var form = $("#form-payment-config");
    form.provider.value = provider;
    $("#payment-title").textContent = item.label + " API 配置";
    $("#payment-summary").textContent = item.summary || "";
    $("#payment-callback-url").value = item.callback_url || "";
    $("#payment-verification-note").textContent = item.verification_note || "";
    $("#payment-docs").href = item.docs_url || "#";
    $("#payment-recheck").hidden = !item.configured;
    renderPaymentState(item);
    $("#payment-fields").innerHTML = (item.fields || []).map(function (field) {
      var name = esc(field.name), label = esc(field.label), help = esc(field.help || "");
      var configured = field.configured ? "已安全保存；留空保持原值" : "请填写";
      var control = "";
      if (field.type === "select") {
        control = '<select name="' + name + '">' + (field.options || []).map(function (option) {
          var selected = String(option.value) === String(field.value || "") ? " selected" : "";
          return '<option value="' + esc(option.value) + '"' + selected + '>' + esc(option.label) + "</option>";
        }).join("") + "</select>";
      } else if (field.type === "textarea") {
        control = '<textarea name="' + name + '" placeholder="' + configured + '" autocomplete="off"></textarea>';
      } else {
        var type = field.type === "password" ? "password" : "text";
        control = '<input name="' + name + '" type="' + type + '" placeholder="' + configured +
          '" autocomplete="new-password" />';
      }
      return "<label>" + label + control + '<small class="payment-field-help">' + help + "</small></label>";
    }).join("");
    $("#payment-mask").hidden = false;
  }
  function closePaymentConfig() { $("#payment-mask").hidden = true; }

  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-payment-config]");
    if (button) openPaymentConfig(button.dataset.paymentConfig);
  });
  $("#payment-close").addEventListener("click", closePaymentConfig);
  $("#payment-mask").addEventListener("click", function (event) {
    if (event.target === this) closePaymentConfig();
  });
  $("#payment-copy-callback").addEventListener("click", function () {
    copyText($("#payment-callback-url").value).then(function () { toast("回调地址已复制"); });
  });
  $("#form-payment-config").addEventListener("submit", function (event) {
    event.preventDefault();
    var form = event.target, config = {};
    Array.prototype.slice.call(form.querySelectorAll("#payment-fields input, #payment-fields textarea, #payment-fields select"))
      .forEach(function (field) { config[field.name] = field.value; });
    var button = $("#payment-save");
    button.disabled = true; button.textContent = "正在验证…";
    api("/nexus/admin/payment_config", {
      body: { provider: form.provider.value, action: "save", config: config }
    }).then(function (result) {
      var item = result.payment_config;
      paymentConfigs[item.provider] = item;
      renderPaymentState(item);
      toast(item.verify_status === "verification_failed" ? "已加密保存，但验证未通过" : "凭据已加密保存并完成检查",
        item.verify_status === "verification_failed");
      closePaymentConfig(); loadAdmin();
    }).catch(function (error) { toast(error.message, true); }).then(function () {
      button.disabled = false; button.textContent = "加密保存并验证";
    });
  });
  $("#payment-recheck").addEventListener("click", function () {
    var provider = $("#form-payment-config").provider.value;
    var button = this; button.disabled = true; button.textContent = "检查中…";
    api("/nexus/admin/payment_config", { body: { provider: provider, action: "verify" } })
      .then(function (result) {
        var item = result.payment_config;
        paymentConfigs[item.provider] = item; renderPaymentState(item);
        toast(item.verify_status === "verification_failed" ? "验证未通过" : "验证完成",
          item.verify_status === "verification_failed");
        closePaymentConfig(); loadAdmin();
      }).catch(function (error) { toast(error.message, true); }).then(function () {
        button.disabled = false; button.textContent = "重新验证已保存凭据";
      });
  });

  // ---------- 企业转账人工入账 ----------
  // 图片只在当前页面内存中短暂停留：选择文件后用于预览、AI 识别和最终一次性保存；
  // 关闭弹窗即释放 Object URL 和 Base64，避免银行凭证残留在 local/sessionStorage。
  var transferImageBase64 = "";
  var transferPreviewUrl = "";
  var transferRecognition = null;

  function fillTransferOems() {
    var select = $("#transfer-oem");
    var selected = select.value;
    select.innerHTML = '<option value="">暂不关联</option>' + manualTransferOems.map(function (o) {
      return '<option value="' + o.id + '">#' + o.id + ' · ' + esc(o.name || o.email) + '</option>';
    }).join("");
    if (selected && manualTransferOems.some(function (o) { return String(o.id) === selected; })) {
      select.value = selected;
    }
  }

  function resetTransferForm() {
    var form = $("#form-manual-transfer");
    form.reset();
    transferImageBase64 = "";
    transferRecognition = null;
    if (transferPreviewUrl) URL.revokeObjectURL(transferPreviewUrl);
    transferPreviewUrl = "";
    $("#transfer-preview").hidden = true;
    $("#transfer-preview").removeAttribute("src");
    $("#transfer-preview-empty").hidden = false;
    $("#transfer-recognition-result").hidden = true;
    $("#transfer-recognition-result").textContent = "";
    $("#transfer-recognize").disabled = true;
    fillTransferOems();
    var configured = !!manualTransferAi.configured;
    $("#transfer-ai-state").textContent = configured
      ? "AI 已配置：" + (manualTransferAi.model || "视觉模型")
      : "AI 尚未配置，可直接人工填写并登记";
  }

  function openTransferModal() {
    resetTransferForm();
    $("#transfer-mask").hidden = false;
  }

  function closeTransferModal() {
    $("#transfer-mask").hidden = true;
    resetTransferForm();
  }

  function fileAsBase64(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () {
        var value = String(reader.result || "");
        resolve(value.indexOf(",") >= 0 ? value.split(",", 2)[1] : "");
      };
      reader.onerror = function () { reject(new Error("读取凭证图片失败")); };
      reader.readAsDataURL(file);
    });
  }

  $("#form-topup-transfer").addEventListener("submit", function (event) {
    event.preventDefault();
    var form = event.target;
    var pickInst = document.querySelector('.pick[data-pick="inst"].on');
    var pickPack = document.querySelector('.pick[data-pick="pack"].on');
    var file = form.voucher.files && form.voucher.files[0];
    if (!pickInst || !pickPack) return toast("请先选择充值实例和套餐", true);
    if (!file) return toast("企业转账必须上传银行回单", true);
    if (["image/jpeg", "image/png", "image/webp"].indexOf(file.type) < 0 || file.size > 8 * 1024 * 1024) {
      return toast("凭证必须是 8MB 以内的 JPG、PNG 或 WebP 图片", true);
    }
    var button = form.querySelector('button[type="submit"]');
    button.disabled = true; button.textContent = "正在提交…";
    fileAsBase64(file).then(function (encoded) {
      return api("/nexus/oem/topup_checkout", { body: {
        payment_method: "corporate_transfer",
        instance_id: Number(pickInst.dataset.val),
        pack_index: Number(pickPack.dataset.val),
        transfer_details: {
          payer_company: form.payer_company.value.trim(),
          transaction_id: form.transaction_id.value.trim(),
        },
        image_base64: encoded,
        content_type: file.type,
        filename: file.name,
      } });
    }).then(function (result) {
      toast("转账充值已提交，超管核对到账后自动充值");
      form.reset();
      if (result.order) renderOrders([result.order]);
      loadOem();
    }).catch(function (error) { toast(error.message, true); }).then(function () {
      button.disabled = false; button.textContent = "提交转账充值";
    });
  });

  $("#form-oem-withdraw").addEventListener("submit", function (event) {
    event.preventDefault();
    var form = event.target;
    var amount = Math.round(Number(form.amount_yuan.value || 0) * 100);
    var button = form.querySelector('button[type="submit"]');
    button.disabled = true; button.textContent = "正在提交…";
    api("/nexus/oem/withdrawals", { body: {
      amount_cents: amount,
      payout: {
        method: form.method.value,
        account_name: form.account_name.value.trim(),
        account_no: form.account_no.value.trim(),
        bank_name: form.bank_name.value.trim(),
      },
      note: form.note.value.trim(),
    } }).then(function () {
      toast("提现申请已提交，平台审核后线下打款");
      form.reset(); loadOem();
    }).catch(function (error) { toast(error.message, true); }).then(function () {
      button.disabled = false; button.textContent = "提交提现申请";
    });
  });

  document.addEventListener("click", function (event) {
    var openButton = event.target.closest && event.target.closest("[data-manual-transfer]");
    if (openButton) openTransferModal();
    var voucherButton = event.target.closest && event.target.closest("[data-transfer-voucher]");
    if (!voucherButton) return;
    var auth = getAuth();
    voucherButton.disabled = true;
    fetch(new URL("/nexus/admin/manual_transfer_voucher/" + voucherButton.dataset.transferVoucher, window.location.origin).href, {
      headers: { "Authorization": "Bearer " + (auth ? auth.token : "") },
      cache: "no-store",
    }).then(function (response) {
      if (!response.ok) return response.json().then(function (data) { throw new Error(data.error || "凭证读取失败"); });
      return response.blob();
    }).then(function (blob) {
      var url = URL.createObjectURL(blob);
      var link = document.createElement("a");
      link.href = url; link.target = "_blank"; link.rel = "noopener";
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
    }).catch(function (error) { toast(error.message, true); }).then(function () {
      voucherButton.disabled = false;
    });
  });

  $("#transfer-close").addEventListener("click", closeTransferModal);
  $("#transfer-mask").addEventListener("click", function (event) {
    if (event.target === this) closeTransferModal();
  });

  $("#transfer-file").addEventListener("change", function () {
    var file = this.files && this.files[0];
    transferImageBase64 = "";
    transferRecognition = null;
    $("#transfer-recognition-result").hidden = true;
    if (!file) return;
    if (["image/jpeg", "image/png", "image/webp"].indexOf(file.type) < 0) {
      this.value = ""; return toast("凭证必须是 JPG、PNG 或 WebP 图片", true);
    }
    if (file.size > 8 * 1024 * 1024) {
      this.value = ""; return toast("凭证图片不能超过 8MB", true);
    }
    if (transferPreviewUrl) URL.revokeObjectURL(transferPreviewUrl);
    transferPreviewUrl = URL.createObjectURL(file);
    $("#transfer-preview").src = transferPreviewUrl;
    $("#transfer-preview").hidden = false;
    $("#transfer-preview-empty").hidden = true;
    fileAsBase64(file).then(function (value) {
      transferImageBase64 = value;
      $("#transfer-recognize").disabled = !value || !manualTransferAi.configured;
    }).catch(function (error) { toast(error.message, true); });
  });

  $("#transfer-recognize").addEventListener("click", function () {
    var file = $("#transfer-file").files && $("#transfer-file").files[0];
    if (!file || !transferImageBase64) return toast("请先上传转账凭证", true);
    var button = this; button.disabled = true; button.textContent = "AI 识别中…";
    api("/nexus/admin/manual_transfer/recognize", {
      body: { image_base64: transferImageBase64, content_type: file.type },
    }).then(function (result) {
      var data = result.recognition || {};
      transferRecognition = data;
      var form = $("#form-manual-transfer");
      if (Number(data.amount_cents) > 0) form.amount_yuan.value = (Number(data.amount_cents) / 100).toFixed(2);
      ["payer_company", "payer_account", "payee_company", "payee_account", "bank_name", "transaction_id", "transfer_time", "note"]
        .forEach(function (name) { if (data[name]) form[name].value = data[name]; });
      var confidence = Math.round((Number(data.confidence) || 0) * 100);
      var box = $("#transfer-recognition-result");
      box.textContent = "AI 已识别并预填（置信度 " + confidence + "%）。请逐项对照原图，尤其核对金额、收付款方和账号。";
      box.hidden = false;
      toast("AI 识别完成，请人工核对");
    }).catch(function (error) { toast(error.message, true); }).then(function () {
      button.disabled = !manualTransferAi.configured || !transferImageBase64;
      button.textContent = "AI 识别凭证";
    });
  });

  $("#form-manual-transfer").addEventListener("submit", function (event) {
    event.preventDefault();
    var form = event.target;
    var file = $("#transfer-file").files && $("#transfer-file").files[0];
    if (!file || !transferImageBase64) return toast("必须上传转账凭证图片", true);
    var cents = Math.round(Number(form.amount_yuan.value || 0) * 100);
    if (!(cents > 0)) return toast("请输入正确的到账金额", true);
    if (!form.confirmed.checked) return toast("请确认银行实际到账", true);
    var details = {};
    ["payer_company", "payer_account", "payee_company", "payee_account", "bank_name", "transaction_id", "transfer_time", "note"]
      .forEach(function (name) { details[name] = form[name].value.trim(); });
    var button = $("#transfer-save");
    button.disabled = true; button.textContent = "正在加密保存…";
    api("/nexus/admin/manual_transfers", { body: {
      amount_cents: cents,
      oem_id: Number(form.oem_id.value || 0) || null,
      purpose: form.purpose.value.trim(),
      details: details,
      recognition: transferRecognition,
      filename: file.name,
      content_type: file.type,
      image_base64: transferImageBase64,
      confirmed: true,
    } }).then(function (result) {
      var no = result.transfer && result.transfer.order_no;
      closeTransferModal();
      toast("企业转账已入账" + (no ? " · " + no : ""));
      loadAdmin();
    }).catch(function (error) { toast(error.message, true); }).then(function () {
      button.disabled = false; button.textContent = "确认并登记入账";
    });
  });

  // Nexus 平台公告来自集中后台的已发布记录；节点公告只来自成功投放。两者都由服务端
  // 明确给出 target，前端不根据标题或版本号猜测，避免把平台上线误写成节点已安装。
  function renderAnnouncements(announcements) {
    var panel = $("#panel-announcements");
    panel.hidden = announcements.length === 0;
    $("#oem-no-announcements").hidden = announcements.length > 0;
    $("#oem-announcements").innerHTML = announcements.map(function (a) {
      var platform = a.target === "nexus";
      var meta = platform
        ? "Nexus 平台 · 已向全部 OEM 后台上线 · " + fmtTime(a.finished_ts)
        : esc(a.domain) + " · 节点已运行 v" + esc(a.version) + " · " + fmtTime(a.finished_ts);
      return '<article class="announcement-card"><div class="announcement-head"><h3>' +
        esc(a.title || ("GuDuu OS " + a.version + " 更新")) + '</h3><div class="announcement-meta">' +
        meta +
        '</div></div><div class="announcement-notes">' + esc(a.notes) + "</div></article>";
    }).join("");
  }

  // 创建订单 → mock 渠道给"模拟支付"按钮；真渠道(接入后)按返回类型跳转/出码
  function placeOrder(bodyData) {
    api("/nexus/oem/order", { body: bodyData }).then(function (r) {
      var box = $("#pay-pending");
      $("#pay-pending-msg").textContent = r.order.order_no + "（" + fmtYuan(r.order.amount_cents) + "）";
      box.hidden = false;
      var mock = r.pay && r.pay.type === "mock";
      var btn = $("#btn-mock-pay");
      btn.hidden = !mock;
      if (mock) btn.dataset.orderNo = r.order.order_no;
      if (r.pay && r.pay.type === "url") window.open(r.pay.url, "_blank"); // 支付宝(接入后)
      loadOem();
    }).catch(function (err) { toast(err.message, true); });
  }

  $("#btn-mock-pay").addEventListener("click", function () {
    var no = this.dataset.orderNo;
    if (!no) return;
    api("/nexus/pay/mock/confirm", { body: { order_no: no } })
      .then(function (r) {
        $("#pay-pending").hidden = true;
        toast(r.order.kind === "key" ? "支付成功，授权码已发放到「我的订单」" : "支付成功，token 已到账");
        loadOem();
      })
      .catch(function (err) { toast(err.message, true); });
  });

  function loadOem() {
    Promise.all([
      api("/nexus/oem/me"),
      api("/nexus/oem/products"),
      api("/nexus/oem/finance"),
    ]).then(function (base) {
      // 先读 /me 中的服务端开关；关闭时绝不请求层级目录接口，但 /me 仍会
      // 返回不含统计的分享链接，保证二维码和邀请能力可用。
      applyOemFeatureFlags(base[0].features || {});
      var networkRequest = oemNetworkVisible
        ? api("/nexus/oem/network")
        : Promise.resolve({});
      return networkRequest.then(function (network) {
        return [base[0], base[1], base[2], network];
      });
    }).then(function (rs) {
      var r = rs[0];
      var orders = r.orders || [];
      var announcements = r.announcements || [];
      var requests = r.requests || [];
      var keys = r.keys || [];
      oemInstances = (r.instances || []).slice();
      renderShop(rs[1], r.instances);
      renderOemFinance(rs[2]);
      renderOrders(orders);
      renderAnnouncements(announcements);
      renderReferral(r.referral || {});
      if (oemNetworkVisible) {
        renderNetworkDirectory(rs[3]);
      } else {
        clearOemNetworkData();
      }
      // 左栏数字全部来自当前 OEM 的服务端过滤结果，不混入平台或其他企业数据。
      $("#nav-oem-instances").textContent = String(r.instances.length);
      $("#nav-oem-announcements").textContent = String(announcements.length);
      $("#nav-oem-orders").textContent = String(orders.length);
      // 授权页同时承担申请与完整历史，因此角标显示全部申请数；待处理状态仍在
      // 表格中用颜色单独提示，避免“已批准后角标归零”让客户误以为没有记录。
      $("#nav-oem-requests").textContent = String(requests.length);
      $("#nav-oem-keys").textContent = String(keys.length);
      // 实例卡
      var box = $("#oem-instances");
      box.innerHTML = r.instances.map(function (i) {
        var st = hbStatus(i);
        var low = i.balance_tokens < 1e6; // 余额低于 100 万 token 标红提醒充值
        var selected = Number(oemInstanceDetailId) === Number(i.id);
        return '<button type="button" class="inst-card inst-card-button' + (selected ? " selected" : "") +
          '" data-oem-instance-detail="' + i.id + '" aria-expanded="' + (selected ? "true" : "false") +
          '" aria-controls="oem-instance-detail" aria-label="在下方查看节点 ' + esc(i.domain) +
          ' 的详细数据"><h3>' + esc(i.domain) + " " + badge(st) + "</h3>" +
          '<div class="row"><span>Token 余额</span><b class="' + (low ? "low" : "") + '">' + fmtTokens(i.balance_tokens) + "</b></div>" +
          '<div class="row"><span>版本</span><b>' + esc(i.version || "—") + "</b></div>" +
          '<div class="row"><span>最近心跳</span><b>' + fmtTime(i.last_seen_ts) + "</b></div>" +
          '<div class="row"><span>开通时间</span><b>' + fmtTime(i.created_ts) + "</b></div>" +
          '<span class="inst-card-open">' + (selected ? "收起详细运行数据" : "在下方查看详细运行数据") + "</span></button>";
      }).join("");
      $("#oem-noinst").hidden = r.instances.length > 0;
      // 用户主动刷新首页时保留当前选中的节点，并重新请求最新心跳快照。
      // 如果 KEY 归属已经变化，则立即收起，避免页面残留上一归属状态的数据。
      if (oemInstanceDetailId) {
        var stillOwned = oemInstances.some(function (item) {
          return Number(item.id) === Number(oemInstanceDetailId);
        });
        if (stillOwned) fetchOemInstanceDetail(oemInstanceDetailId);
        else closeOemInstanceDetail();
      }
      // KEY、节点绑定与节点心跳是三套不同状态。这里用 instance_id 关联当前 OEM
      // 的真实节点数据，绝不再把 active KEY 翻译为“在线”。
      var instancesById = {};
      r.instances.forEach(function (instance) {
        instancesById[Number(instance.id)] = instance;
      });
      var keyBoundCount = keys.filter(function (key) { return !!key.instance_id; }).length;
      var keyUnboundCount = keys.filter(function (key) {
        return key.status === "active" && !key.instance_id;
      }).length;
      var keyAlertCount = keys.filter(function (key) { return key.status !== "active"; }).length;
      $("#oem-key-total").textContent = String(keys.length);
      $("#oem-key-bound").textContent = String(keyBoundCount);
      $("#oem-key-unbound").textContent = String(keyUnboundCount);
      $("#oem-key-alert").textContent = String(keyAlertCount);

      function keyAuthorizationBadge(status) {
        if (status === "active") return '<span class="badge active">授权有效</span>';
        if (status === "suspended") return '<span class="badge suspended">授权暂停</span>';
        return '<span class="badge revoked">授权吊销</span>';
      }
      function keyNodeBadge(instance, hasBinding) {
        if (!instance) return hasBinding
          ? '<span class="badge warning">节点待同步</span>'
          : '<span class="badge idle">未部署</span>';
        var heartbeat = hbStatus(instance);
        var labels = { active: "节点在线", warning: "节点迟滞", offline: "节点离线" };
        return '<span class="badge ' + heartbeat + '">' + labels[heartbeat] + "</span>";
      }
      $("#oem-keys").innerHTML = keys.map(function (key) {
        var instance = key.instance_id ? instancesById[Number(key.instance_id)] : null;
        var bindingBadge = key.instance_id
          ? '<span class="badge active">已绑定</span>'
          : (key.status === "active"
            ? '<span class="badge idle">待部署兑换</span>'
            : '<span class="badge idle">未绑定</span>');
        var domain = instance ? esc(instance.domain) : (key.instance_id ? "节点数据待同步" : "尚未绑定节点");
        var currentBalance = instance ? fmtTokens(instance.balance_tokens) : "—";
        var nodeVersion = instance ? esc(instance.version || "—") : "—";
        var actions = instance
          ? '<button type="button" class="ghost small" data-key-view-instance="' + instance.id + '">查看节点</button>' +
            (key.status === "active"
              ? '<button type="button" class="primary small" data-key-topup-instance="' + instance.id + '">Token 充值</button>'
              : "")
          : "";
        return '<article class="key-card">' +
          '<div class="key-card-head"><div><small>授权 KEY #' + key.id + '</small><b>···' + esc(key.tail) + '</b></div>' +
          '<div class="key-card-badges">' + keyAuthorizationBadge(key.status) + bindingBadge + keyNodeBadge(instance, !!key.instance_id) + "</div></div>" +
          '<div class="key-card-details">' +
          '<div class="key-card-detail key-domain"><small>节点域名</small><b>' + domain + "</b></div>" +
          '<div class="key-card-detail"><small>初始附赠 Token</small><b>' + fmtTokens(key.token_grant) + "</b></div>" +
          '<div class="key-card-detail"><small>节点当前余额</small><b>' + currentBalance + "</b></div>" +
          '<div class="key-card-detail"><small>节点版本</small><b>' + nodeVersion + "</b></div>" +
          '<div class="key-card-detail"><small>签发时间</small><b>' + fmtTime(key.created_ts) + "</b></div>" +
          '<div class="key-card-detail"><small>兑换时间</small><b>' + fmtTime(key.redeemed_ts) + "</b></div></div>" +
          '<div class="key-card-foot"><p>' + (instance
            ? "该 KEY 已与此节点永久建立授权关系。"
            : (key.status === "active"
              ? "部署新节点时输入此 KEY，即可完成绑定与初始 Token 发放。"
              : "该授权当前不可用于部署，请联系平台确认授权状态。")) +
          '</p><div class="key-card-actions">' + actions + "</div></div></article>";
      }).join("") || '<div class="key-empty"><b>尚无授权 KEY</b><p>先提交授权申请；获批领取后会自动进入这里。</p>' +
        '<button type="button" class="primary small" data-key-open-page="licenses">前往授权申请</button></div>';
      oemRequests = requests;
      renderOemRequests();
    }).catch(function (err) { toast(err.message, true); });
  }

  var REQUEST_LABEL = {
    pending: "待处理", needs_info: "待补资料", approved: "已批准",
    rejected: "已拒绝", cancelled: "已撤回",
  };
  var REQUEST_CLASS = {
    pending: "warning", needs_info: "needs_info", approved: "active",
    rejected: "revoked", cancelled: "cancelled",
  };
  var PAYMENT_METHOD_ZH = {
    online: "在线支付", corporate_transfer: "企业转账", manual_review: "合同/免费授权",
  };
  var PAYMENT_STATUS_ZH = {
    pending_payment: "待在线支付", pending_review: "待审核", paid: "已到账待履约",
    fulfilled: "已到账并签发", rejected: "已拒绝", cancelled: "已撤回",
    manual_review: "人工审批",
  };
  var DELIVERY_LABEL = {
    none: "尚未生成", ready: "待客户领取", legacy_ready: "待客户领取",
    revealed: "领取窗口开启", locked: "查看窗口已结束", expired: "领取期已过",
    used: "已用于节点开通", unavailable: "等待平台补发",
  };

  function requestKeyCell(q) {
    var plain = revealedRequestKeys[q.id];
    if (plain) {
      return '<span class="request-key-value">' + esc(plain) + '</span> ' +
        '<button class="ghost small" data-copy-request-key="' + q.id + '">复制</button>';
    }
    if (q.delivery_status === "ready" || q.delivery_status === "legacy_ready" || q.delivery_status === "revealed") {
      return '<button class="primary small" data-reveal-request="' + q.id + '">查看授权码</button>';
    }
    var text = {
      used: "已使用（节点开通）", expired: "领取期已过", locked: "查看窗口已结束",
      unavailable: "等待平台补发",
    }[q.delivery_status];
    return '<span class="zh">' + esc(text || "—") + "</span>";
  }

  function renderOemRequests() {
    $("#oem-requests").hidden = oemRequests.length === 0;
    $("#oem-requests tbody").innerHTML = oemRequests.map(function (q) {
      var message = q.decide_note && (q.status === "rejected" || q.status === "needs_info")
        ? '<div class="hint">' + esc(q.decide_note) + "</div>" : "";
      var actions = q.status === "pending"
        ? (q.payment_method === "manual_review" ? '<button class="ghost small" data-edit-request="' + q.id + '">修改</button> ' : "") +
          '<button class="ghost small" data-cancel-request="' + q.id + '">撤回</button>'
        : q.status === "needs_info"
          ? '<button class="primary small" data-edit-request="' + q.id + '">补充资料</button>' : "—";
      var payment = '<b>' + esc(PAYMENT_METHOD_ZH[q.payment_method] || q.payment_method || "人工审批") +
        '</b><div class="hint">' + esc(PAYMENT_STATUS_ZH[q.payment_status] || q.payment_status || "—") +
        (q.payment_amount_cents ? " · " + fmtYuan(q.payment_amount_cents) : "") + " · " +
        fmtTokens(q.requested_tokens) + " Token</div>";
      return "<tr><td>#" + q.id + '</td><td class="zh"><span class="badge ' +
        (REQUEST_CLASS[q.status] || "idle") + '">' + (REQUEST_LABEL[q.status] || q.status) +
        "</span>" + message + '</td><td class="zh"><b>' + esc(q.deployment_domain || "待定") +
        '</b><div class="hint">' + esc(q.purpose || q.note || "—") +
        (q.expected_public_ip_masked ? "<br>IP " + esc(q.expected_public_ip_masked) +
          (q.strict_ip ? " · 严格绑定" : " · 风险核验") : "") + "</div></td><td>" +
        payment + '</td><td class="zh">' + requestKeyCell(q) + "</td><td>" +
        fmtTime(q.created_ts) + '</td><td class="zh">' + actions + "</td></tr>";
    }).join("");
  }

  function fillRequestForm(q) {
    var f = $("#form-request");
    editingRequestId = q.id;
    f.deployment_domain.value = q.deployment_domain || "";
    f.expected_public_ip.value = "";
    f.expected_public_ip.placeholder = q.expected_public_ip_masked
      ? "已保存 " + q.expected_public_ip_masked + "；留空保留" : "固定 IP，例如 203.0.113.10";
    f.strict_ip.checked = !!q.strict_ip;
    f.purpose.value = q.purpose || "";
    f.expected_date.value = q.expected_date || "";
    f.requested_tokens.value = q.requested_tokens || 0;
    f.note.value = q.note || "";
    f.payment_method.value = q.payment_method || "manual_review";
    f.querySelector("button[type=submit]").textContent = q.status === "needs_info" ? "补充并重新提交" : "保存修改";
    syncLicensePaymentForm();
    f.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function fileAsBase64(file) {
    return new Promise(function (resolve, reject) {
      if (!file) return reject(new Error("请上传企业转账凭证"));
      if (file.size > 8 * 1024 * 1024) return reject(new Error("转账凭证不能超过 8MB"));
      var reader = new FileReader();
      reader.onload = function () {
        var value = String(reader.result || "");
        resolve(value.indexOf(",") >= 0 ? value.split(",")[1] : value);
      };
      reader.onerror = function () { reject(new Error("无法读取转账凭证")); };
      reader.readAsDataURL(file);
    });
  }

  $("#form-request").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    var payload = {
      note: f.note.value,
      deployment_domain: f.deployment_domain.value,
      purpose: f.purpose.value,
      expected_date: f.expected_date.value,
      requested_tokens: Number(f.requested_tokens.value) || 0,
      expected_public_ip: f.expected_public_ip.value,
      strict_ip: !!f.strict_ip.checked,
    };
    if (editingRequestId) {
      payload.action = "update";
      payload.request_id = editingRequestId;
      api("/nexus/oem/request_action", { body: payload })
        .then(function () {
          toast("申请资料已更新");
          editingRequestId = 0; f.reset(); f.requested_tokens.value = "100000000";
          f.payment_method.disabled = false; syncLicensePaymentForm(); loadOem();
        })
        .catch(function (err) { toast(err.message, true); });
      return;
    }
    payload.payment_method = f.payment_method.value;
    payload.channel = f.channel.value;
    payload.transfer_details = {
      payer_company: f.payer_company.value,
      transaction_id: f.transaction_id.value,
    };
    var voucher = f.voucher.files && f.voucher.files[0];
    var voucherPromise = payload.payment_method === "corporate_transfer"
      ? fileAsBase64(voucher) : Promise.resolve("");
    var submit = f.querySelector('button[type="submit"]');
    submit.disabled = true;
    voucherPromise.then(function (encoded) {
      payload.image_base64 = encoded;
      payload.content_type = voucher ? voucher.type : "";
      payload.filename = voucher ? voucher.name : "";
      return api("/nexus/oem/license_checkout", { body: payload });
    }).then(function (result) {
      if (result.order) {
        var box = $("#pay-pending");
        $("#pay-pending-msg").textContent = result.order.order_no + "（" + fmtYuan(result.order.amount_cents) + "）";
        box.hidden = false;
        var mock = result.pay && result.pay.type === "mock";
        $("#btn-mock-pay").hidden = !mock;
        if (mock) $("#btn-mock-pay").dataset.orderNo = result.order.order_no;
        if (result.pay && result.pay.type === "url") window.open(result.pay.url, "_blank");
      }
      var message = payload.payment_method === "corporate_transfer"
        ? "转账凭证已提交，超管确认真实到账后自动发 KEY"
        : (payload.payment_method === "online" ? "订单已创建，请完成支付" : "授权申请已提交");
      toast(message);
      f.reset(); f.requested_tokens.value = "100000000"; syncLicensePaymentForm(); loadOem();
    }).catch(function (err) {
      toast(err.message, true);
    }).then(function () {
      submit.disabled = false;
      syncLicensePaymentForm();
    });
  });

  var AUDIT_ACTION_ZH = {
    submit: "提交申请", checkout_created: "选择付款方式", update: "修改申请", resubmit: "补充资料并重新提交",
    needs_info: "要求补充资料", approve: "批准并签发", reject: "拒绝申请",
    payment_auto_approve: "在线支付到账自动签发", transfer_confirm: "企业转账到账签发",
    cancel: "申请人撤回", reveal: "申请人查看授权码", redeem: "节点完成兑换",
  };

  function openRequestDetail(requestId) {
    api("/nexus/admin/request_detail?request_id=" + encodeURIComponent(requestId)).then(function (result) {
      var q = result.request || {};
      $("#request-detail-title").textContent = "授权申请 #" + q.id;
      $("#request-detail-summary").textContent = (q.company || "未补企业名") + " · " + (q.oem_email || "");
      $("#request-detail-state").innerHTML = '<span class="badge ' + (REQUEST_CLASS[q.status] || "idle") + '">' +
        esc(REQUEST_LABEL[q.status] || q.status) + "</span><span>KEY " + (q.key_id ? "#" + q.key_id : "尚未签发") +
        " · 交付状态 " + esc(DELIVERY_LABEL[q.delivery_status] || DELIVERY_LABEL.none) + "</span>";
      var fields = [
        ["计划域名", q.deployment_domain || "待定"], ["使用场景", q.purpose || "—"],
        ["计划公网 IP", q.expected_public_ip_masked || "未填写"],
        ["IP 校验策略", q.strict_ip ? "严格绑定（不一致拒绝激活）" : "风险核验（不一致告警）"],
        ["期望日期", q.expected_date || "—"], ["申请 Token", fmtTokens(q.requested_tokens)],
        ["付款方式", PAYMENT_METHOD_ZH[q.payment_method] || q.payment_method || "人工审批"],
        ["付款状态", PAYMENT_STATUS_ZH[q.payment_status] || q.payment_status || "—"],
        ["应付金额", q.payment_amount_cents ? fmtYuan(q.payment_amount_cents) : "—"],
        ["订单 / 转账单", q.order_no || q.transfer_no || "—"],
        ["联系人", q.contact_name || "—"], ["联系方式", q.contact_phone || "—"],
        ["申请时间", fmtTime(q.created_ts)], ["处理时间", fmtTime(q.decided_ts)],
        ["补充说明", q.note || "—"], ["处理意见", q.decide_note || "—"],
      ];
      $("#request-detail-kv").innerHTML = fields.map(function (field) {
        return "<small>" + esc(field[0]) + "</small><b>" + esc(field[1]) + "</b>";
      }).join("");
      var timeline = q.timeline || [];
      $("#request-detail-timeline").innerHTML = timeline.map(function (event) {
        var transition = event.from_state || event.to_state
          ? '<span> · ' + esc(event.from_state || "创建") + " → " + esc(event.to_state || "—") + "</span>" : "";
        return '<div class="audit-event"><div class="audit-event-head"><b>' +
          esc(AUDIT_ACTION_ZH[event.action] || event.action) + '</b><time>' + fmtTime(event.created_ts) +
          '</time></div><p>' + esc(event.actor_label || event.actor_type || "系统") + transition +
          (event.note ? " · " + esc(event.note) : "") + "</p></div>";
      }).join("") || '<p class="empty">历史记录尚未生成审计事件</p>';
      $("#request-detail-mask").hidden = false;
    }).catch(function (err) { toast(err.message, true); });
  }

  $("#request-detail-close").addEventListener("click", function () {
    $("#request-detail-mask").hidden = true;
  });
  $("#request-detail-mask").addEventListener("click", function (event) {
    if (event.target === this) this.hidden = true;
  });

  $all("[data-request-status]").forEach(function (button) {
    button.addEventListener("click", function () {
      adminRequestStatus = button.dataset.requestStatus;
      loadAdmin();
    });
  });
  $("#request-search").addEventListener("input", function () {
    clearTimeout(requestSearchTimer);
    requestSearchTimer = setTimeout(loadAdmin, 280);
  });

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
  var RELEASE_STATUS = {
    draft: ["idle", "未发布"],
    canary: ["warning", "灰度监测"],
    published: ["active", "全量发布"],
    rollback: ["warning", "回撤发布中"],
    paused: ["offline", "已暂停"],
  };
  var PLATFORM_RELEASE_STATUS = {
    draft: ["idle", "未发布"],
    published: ["active", "公告已发布"],
    paused: ["offline", "公告已撤下"],
  };
  var DEPLOY_STATUS = {
    pending: ["idle", "待领取"],
    downloading: ["warning", "下载中"],
    installing: ["warning", "安装中"],
    success: ["active", "成功"],
    failed: ["offline", "失败"],
    skipped: ["idle", "已跳过"],
  };
  var releaseInstanceCount = 0;
  // 节点详情使用最近一次管理列表快照，打开弹窗时无需再发请求。
  var adminInstances = [];
  // OEM 实例列表只用于点击前快速确认卡片仍属于当前页面；
  // 真正的归属校验仍在服务端做，不信任这个前端数组。
  var oemInstances = [];
  var oemInstanceDetailId = 0;
  var oemInstanceDetailRequest = 0;
  var releaseDraftChecked = false;
  // KEY 明文只保留在当前页面内存，刷新或关闭标签页即消失，绝不写入 Storage。
  var revealedRequestKeys = {};
  var oemRequests = [];
  var editingRequestId = 0;
  var adminRequestStatus = "pending";
  var requestSearchTimer = null;

  function releaseBadge(status, mapping) {
    var item = mapping[status] || ["idle", status];
    return '<span class="badge ' + item[0] + '">' + esc(item[1]) + "</span>";
  }

  // 版本列表同时展示流程状态和逐节点结果。说明、域名、错误摘要全部先转义，
  // 防止某个被入侵的 OEM 节点借上报错误内容攻击超管浏览器。
  function renderReleases(releases) {
    var box = $("#admin-releases");
    box.innerHTML = releases.map(function (r) {
      var c = r.counts || {};
      var target = r.target || "node";
      var platform = target === "nexus";
      var targetBadge = platform
        ? '<span class="badge manual">Nexus 平台</span>'
        : '<span class="badge idle">OEM 节点</span>';
      var artifact = r.artifact || { mode: "legacy_git" };
      var deliveryText = platform
        ? "集中托管"
        : artifact.mode === "container"
          ? "Docker 摘要 · bot " + esc((artifact.bot_image || "").slice(-12)) +
            " · web " + esc((artifact.web_image || "").slice(-12))
          : "兼容 Git 引导/救援";
      var statusBadge = releaseBadge(
        r.status,
        platform ? PLATFORM_RELEASE_STATUS : RELEASE_STATUS
      );
      var countText = platform
        ? (r.status === "published" ? "已向全部 OEM 后台展示公告；不创建节点安装任务。" : "平台公告尚未展示给 OEM 客户。")
        : "待领取 " + (c.pending || 0) + " · 安装中 " +
          ((c.downloading || 0) + (c.installing || 0)) + " · 成功 " +
          (c.success || 0) + " · 失败 " + (c.failed || 0);
      var actions = [];
      if (platform && ["draft", "paused"].indexOf(r.status) >= 0) {
        actions.push('<button class="primary small" data-release-action="publish" data-release-target="nexus" data-release-id="' + r.id + '">发布到全部 OEM 后台</button>');
      }
      if (platform && r.status === "published") {
        actions.push('<button class="ghost small" data-release-action="pause" data-release-target="nexus" data-release-id="' + r.id + '">撤下公告</button>');
      }
      if (!platform && ["draft", "paused", "canary"].indexOf(r.status) >= 0) {
        actions.push('<button class="ghost small" data-release-action="canary" data-release-id="' + r.id + '">推送灰度节点</button>');
      }
      if (!platform && ["draft", "canary", "paused"].indexOf(r.status) >= 0) {
        actions.push('<button class="primary small" data-release-action="publish" data-release-id="' + r.id + '">推送全部节点</button>');
      }
      if (!platform && (r.status === "canary" || r.status === "published")) {
        actions.push('<button class="ghost small" data-release-action="pause" data-release-id="' + r.id + '">暂停发布</button>');
      }
      if (!platform && r.status === "rollback") {
        actions.push('<button class="ghost small" data-release-action="pause" data-release-id="' + r.id + '">暂停回撤</button>');
      }
      // 只有真正全量发布过、且当前不再活动的历史版本才可作为回撤目标；草稿和仅灰度
      // 版本没有经过全量验证，不能通过“回撤”绕过发布门禁。
      if (!platform && r.published_ts && ["canary", "published", "rollback"].indexOf(r.status) < 0) {
        actions.push('<button class="ghost small" data-release-action="rollback" data-release-id="' + r.id + '" data-release-version="' + esc(r.version) + '">回撤到此版本</button>');
      }
      if (!platform && (c.failed || 0) > 0) {
        actions.push('<button class="ghost small" data-release-action="retry" data-release-id="' + r.id + '">重试失败节点</button>');
      }
      var deployments = (r.deployments || []).map(function (d) {
        var detail = d.detail ? '<div class="hint">' + esc(d.detail) + "</div>" : "";
        return "<tr><td>#" + d.instance_id + "</td><td>" + esc(d.domain) + '</td><td class="zh">' +
          releaseBadge(d.status, DEPLOY_STATUS) + "</td><td>" + esc(d.from_version || "—") + " → " +
          esc(d.to_version || "—") + "</td><td>" + fmtTime(d.updated_ts) + detail + "</td></tr>";
      }).join("");
      var detailBlock = platform
        ? '<p class="hint">Nexus 由平台集中部署，OEM 客户无需单独安装后台。</p>'
        : deployments
        ? '<details class="release-deployments"><summary>查看 ' + r.deployments.length +
          ' 个节点的安装明细</summary><table class="tbl"><thead><tr><th>#</th><th>节点</th><th>状态</th><th>版本</th><th>更新时间 / 说明</th></tr></thead><tbody>' +
          deployments + "</tbody></table></details>"
        : '<p class="hint">尚未推送到任何节点。</p>';
      return '<article class="release-card"><div class="release-card-head"><div>' +
        '<div class="release-card-title"><b>v' + esc(r.version) + "</b>" +
        targetBadge + statusBadge + "<strong>" + esc(r.title) + "</strong></div>" +
        '<div class="release-meta">' + deliveryText + " · Git " + esc(r.git_ref) +
        " · 创建 " + fmtTime(r.created_ts) + "</div></div>" +
        '<div class="release-actions">' + actions.join("") + "</div></div>" +
        '<div class="release-notes">' + esc(r.notes) + '</div><div class="release-counts">' + countText + "</div>" +
        detailBlock + "</article>";
    }).join("") || '<p class="empty">还没有版本记录。先保存一个未发布版本，再进行灰度监测。</p>';
  }

  function syncReleaseSubmitState() {
    // 当前产品版本如果已经落库，表单仍完整展示内容供查看/复制，但禁止重复提交同一
    // SemVer；管理员手动换成另一个版本号时按钮自动恢复，保留应急手工录入能力。
    var form = $("#form-release");
    var submit = form.querySelector('button[type="submit"]');
    var alreadySaved = form.dataset.alreadyExists === "true" &&
      form.version.value.trim() === form.dataset.generatedVersion;
    submit.disabled = alreadySaved;
    submit.textContent = alreadySaved ? "当前版本已保存" : "保存为未发布";
  }

  function syncReleaseTargetUi() {
    // 平台轨道没有客户节点灰度；隐藏选择器并把流程说明改成“公告发布”，避免超管
    // 看到同一个“发布”按钮时误以为会连接或重启 OEM 客户服务器。
    var form = $("#form-release");
    var platform = form.elements.target.value === "nexus";
    $("#release-canary-field").hidden = platform;
    $("#release-image-field").hidden = platform;
    $("#release-flow-hint").textContent = platform
      ? "Nexus 平台由我们集中部署；发布这里只向全部 OEM 后台展示公告，不更新客户服务器。"
      : "OEM 节点版本流程：保存 → 灰度监测 → 推送全部节点；支持暂停、失败重试和历史版本回撤。";
  }

  $("#form-release").elements.target.addEventListener("change", syncReleaseTargetUi);
  syncReleaseTargetUi();

  function loadReleaseDraft(force) {
    if (!force && releaseDraftChecked) return Promise.resolve();
    releaseDraftChecked = true;
    var form = $("#form-release");
    var status = $("#release-draft-status");
    var button = $("#btn-release-generate");
    button.disabled = true;
    status.textContent = "正在读取当前版本与 DEVLOG.md…";
    return api("/nexus/admin/release_draft").then(function (draft) {
      var empty = !form.version.value && !form.git_ref.value && !form.title.value && !form.notes.value;
      if (!force && !empty) {
        status.textContent = "已找到 v" + draft.version + "，当前表单正在编辑，未自动覆盖。";
        return;
      }
      form.version.value = draft.version;
      form.git_ref.value = draft.git_ref;
      form.title.value = draft.title;
      form.notes.value = draft.notes;
      form.version.dataset.previousTag = draft.git_ref;
      form.dataset.generatedVersion = draft.version;
      form.dataset.alreadyExists = draft.already_exists ? "true" : "false";
      form.dataset.imageReady = draft.image_manifest ? "true" : "false";
      $("#release-image-status").value = draft.image_manifest
        ? "已登记不可变摘要 · " + (draft.image_manifest.platforms || "")
        : "尚未登记，请等待 GitHub Actions 构建";
      syncReleaseSubmitState();
      if (draft.already_exists) {
        status.textContent = "已显示 v" + draft.version + " 的完整生成内容；该版本已存在于历史列表，无需重复保存。";
        if (force) toast("已显示当前版本的完整内容");
      } else {
        status.textContent = "已根据 " + draft.source + " 自动生成 v" + draft.version + "，请审阅后保存为未发布。";
        if (force) toast("最新版本信息已生成");
      }
    }).catch(function (err) {
      status.textContent = "自动生成失败：" + err.message;
      if (force) toast(err.message, true);
    }).then(function () {
      button.disabled = false;
    });
  }

  function requestListPath() {
    var query = $("#request-search") ? $("#request-search").value.trim() : "";
    return "/nexus/admin/requests?status=" + encodeURIComponent(adminRequestStatus) +
      "&q=" + encodeURIComponent(query);
  }

  var adminFeatureFlags = { oem_network_visible: false };
  function renderPlatformFeatures(flags) {
    // 超管看到的是服务端最终持久化状态；按钮文字、颜色和 aria-checked
    // 三处同步，便于视觉与辅助技术都能准确判断开关。
    adminFeatureFlags = {
      oem_network_visible: !!(flags && flags.oem_network_visible),
    };
    var button = $("#toggle-oem-network");
    var enabled = adminFeatureFlags.oem_network_visible;
    button.disabled = false;
    button.classList.toggle("on", enabled);
    button.setAttribute("aria-checked", enabled ? "true" : "false");
    button.querySelector("b").textContent = enabled ? "已开启" : "已关闭";
  }

  $("#toggle-oem-network").addEventListener("click", function () {
    var button = this;
    var nextValue = !adminFeatureFlags.oem_network_visible;
    button.disabled = true;
    button.querySelector("b").textContent = "保存中";
    api("/nexus/admin/features", {
      body: { oem_network_visible: nextValue },
    }).then(function (result) {
      renderPlatformFeatures(result.features || {});
      toast(nextValue
        ? "OEM 层级与归属用户数据已开放"
        : "OEM 层级与归属用户数据已隐藏，分享二维码继续可用");
    }).catch(function (error) {
      renderPlatformFeatures(adminFeatureFlags);
      toast(error.message, true);
    });
  });

  var currentAdminIdentity = { id: 0, auth_kind: "" };

  function auditObjectLabel(event) {
    var labels = {
      admin_operation: "后台接口", admin: "管理员", admin_passkey: "Passkey", key: "KEY",
      key_request: "授权申请", oem: "OEM", withdrawal: "提现",
    };
    return (labels[event.object_type] || event.object_type || "—") +
      (Number(event.object_id) ? " #" + event.object_id : "");
  }

  function loadAdminSecurity() {
    var actor = encodeURIComponent($("#admin-audit-actor").value.trim());
    var objectType = encodeURIComponent($("#admin-audit-type").value);
    Promise.all([
      api("/nexus/admin/me"),
      api("/nexus/admin/admins"),
      api("/nexus/admin/audit?limit=200&actor=" + actor + "&object_type=" + objectType),
      api("/nexus/admin/passkeys"),
    ]).then(function (rs) {
      var identity = rs[0].admin || {};
      var admins = rs[1].admins || [];
      var events = rs[2].events || [];
      var passkeyData = rs[3] || {};
      var myPasskeys = passkeyData.passkeys || [];
      currentAdminIdentity = identity;
      var emergency = String(identity.auth_kind || "").indexOf("emergency") >= 0 ||
        identity.auth_kind === "recovery_cookie";
      var passkeySession = identity.auth_kind === "passkey_cookie";
      $("#admin-auth-kind").className = "badge " + (emergency ? "warning" : "active");
      $("#admin-auth-kind").textContent = emergency
        ? "应急恢复" : (passkeySession ? "Passkey" : "密码会话");
      $("#admin-current-identity").innerHTML = emergency
        ? "<b>SSH 单次恢复</b><span>请创建具名管理员并重新登录；该身份最长 30 分钟，操作仍会写入审计。</span>"
        : "<b>" + esc(identity.display_name || "—") + "</b><span>管理员 #" +
          esc(identity.id) + " · " + (passkeySession ? "Passkey 登录" : "密码备用登录") +
          " · 会话最长 12 小时。</span>";
      $("#btn-add-passkey").hidden = emergency || !passkeyData.enabled;
      $("#admin-passkeys").innerHTML = !passkeyData.enabled
        ? '<p class="empty">Passkey 尚未绑定正式管理域名，完成域名配置后即可添加。</p>'
        : (emergency
          ? '<p class="empty">请先使用具名管理员账号登录，再为自己的账号添加 Passkey。</p>'
          : (myPasskeys.map(function (item) {
            return '<div class="passkey-item"><div><b>' + esc(item.name) +
              '</b><span>添加于 ' + fmtTime(item.created_ts) + ' · 最近使用 ' +
              fmtTime(item.last_used_ts) + '</span></div><button class="ghost small danger-text" data-passkey-delete="' +
              item.id + '">移除</button></div>';
          }).join("") || '<p class="empty">尚未添加 Passkey；建议至少登记两个不同设备用于恢复。</p>'));
      $("#nav-count-admins").textContent = String(admins.filter(function (a) { return a.status === "active"; }).length);
      $("#admin-admins tbody").innerHTML = admins.map(function (item) {
        var self = Number(identity.id) === Number(item.id);
        return "<tr><td>" + item.id + "</td><td><b>" + esc(item.username) +
          "</b></td><td>" + esc(item.display_name) + "</td><td>超级管理员</td><td>" +
          badge(item.status) + "</td><td>" + fmtTime(item.last_login_ts) + "</td><td>" +
          fmtTime(item.created_ts) + "</td><td class=\"actions\">" +
          '<button class="ghost small" data-admin-reset="' + item.id + '">重置密码</button>' +
          (item.status === "active"
            ? '<button class="ghost small danger-text" data-admin-status="' + item.id +
              '" data-next="disabled"' + (self ? " disabled" : "") + '>停用</button>'
            : '<button class="ghost small" data-admin-status="' + item.id +
              '" data-next="active">启用</button>') + "</td></tr>";
      }).join("") || '<tr><td colspan="8" class="empty">尚未创建具名管理员，请使用上方表单创建首个账号。</td></tr>';
      $("#admin-audit tbody").innerHTML = events.map(function (event) {
        var transition = event.from_state || event.to_state
          ? esc(event.from_state || "—") + " → " + esc(event.to_state || "—") : "—";
        return "<tr><td>" + fmtTime(event.created_ts) + "</td><td><b>" +
          esc(event.actor_label || event.actor_type || "系统") + "</b></td><td>" +
          esc(auditObjectLabel(event)) + "</td><td><code>" + esc(event.action) +
          "</code></td><td>" + transition + "</td><td><code>" +
          esc(event.source_ip || "—") + "</code></td><td>" + esc(event.note || "—") +
          "</td></tr>";
      }).join("") || '<tr><td colspan="7" class="empty">暂无符合条件的审计记录。</td></tr>';
    }).catch(function (err) {
      toast("平台安全数据读取失败：" + err.message, true);
    });
  }

  function loadAdmin() {
    Promise.all([
      api("/nexus/admin/instances"),
      api("/nexus/admin/keys"),
      api("/nexus/admin/oems"),
      api(requestListPath()),
      api("/nexus/admin/pricing"),
      api("/nexus/admin/orders"),
      api("/nexus/admin/releases"),
      api("/nexus/admin/finance_summary"),
      api("/nexus/admin/payment_configs"),
      api("/nexus/admin/features"),
      api("/nexus/admin/withdrawals"),
      api("/nexus/admin/oem_commercial_terms"),
    ]).then(function (rs) {
      var insts = rs[0].instances, keys = rs[1].keys, oems = rs[2].oems;
      var reqs = rs[3].requests || [], requestCounts = rs[3].counts || {};
      var pricing = rs[4].pricing, orders = rs[5].orders || [];
      var releases = rs[6].releases || [];
      var finance = rs[7] || {};
      var configs = rs[8].payment_configs || [];
      var featureFlags = rs[9].features || {};
      var withdrawals = rs[10].withdrawals || [];
      var commercialTerms = rs[11].terms || [];
      adminInstances = insts.slice();
      manualTransferOems = oems.slice();
      renderFinanceOverview(finance, configs);
      renderPlatformFeatures(featureFlags);

      // 灰度节点选择器随实例列表更新，但保留管理员当前已选值。
      var canarySelect = $("#release-canary");
      var selectedCanary = canarySelect.value;
      canarySelect.innerHTML = insts.map(function (i) {
        return '<option value="' + i.id + '">#' + i.id + " · " + esc(i.domain) +
          "（" + esc(i.version || "未知版本") + "）</option>";
      }).join("") || '<option value="">暂无可用实例</option>';
      if (selectedCanary && insts.some(function (i) { return String(i.id) === selectedCanary; })) {
        canarySelect.value = selectedCanary;
      }
      releaseInstanceCount = insts.length;
      renderReleases(releases);

      // 左侧数量让超管不进入页面也能看到各功能区规模；待处理申请尤其需要醒目，避免
      // 被埋在授权列表里。这里只展示已有接口返回的计数，不额外增加轮询请求。
      $("#nav-count-releases").textContent = String(releases.length);
      $("#nav-count-instances").textContent = String(insts.length);
      $("#nav-count-requests").textContent = String((requestCounts.pending || 0) + (requestCounts.needs_info || 0));
      $("#nav-count-customers").textContent = String(oems.length);
      $("#nav-count-orders").textContent = String(orders.length);

      // 定价表单回填（仅在超管未编辑时覆盖,避免打字被刷新冲掉）
      var pf = $("#form-pricing");
      if (document.activeElement === null || !pf.contains(document.activeElement)) {
        pf.key_yuan.value = (pricing.key_price_cents / 100) || 0;
        pf.key_oem_yuan.value = (pricing.key_oem_cost_cents / 100) || 0;
        pf.key_grant.value = pricing.key_token_grant;
        pf.settlement_days.value = pricing.settlement_days;
        pf.withdraw_min_yuan.value = (pricing.withdraw_min_cents / 100) || 1;
        if (document.activeElement !== $("#pricing-packs")) {
          $("#pricing-packs").value = pricing.topup_packs.map(function (p) {
            return (p.cents / 100) + ":" + (p.oem_cost_cents / 100) + ":" + p.tokens;
          }).join("\n");
        }
      }

      // 订单表（超管全量;无单隐藏）
      $("#panel-admin-orders").hidden = orders.length === 0;
      var oemEmailById = {};
      oems.forEach(function (o) { oemEmailById[o.id] = o.email; });
      $("#admin-orders tbody").innerHTML = orders.map(function (o) {
        var st = ORDER_ST[o.status] || ["idle", o.status];
        var manual = o.record_type === "manual_transfer";
        var what = o.kind === "key" ? "授权码" : (o.kind === "topup" ? "充值 " + fmtTokens(o.tokens) : esc(o.purpose || "企业转账收款"));
        var payer = manual && o.details && o.details.payer_company ? '<div class="hint">付款：' + esc(o.details.payer_company) + "</div>" : "";
        var customer = o.oem_id ? (oemEmailById[o.oem_id] || "#" + o.oem_id) : "未关联";
        var voucher = o.transfer_id
          ? '<button class="ghost small" data-transfer-voucher="' + o.transfer_id + '">查看图片</button>'
          : "—";
        if (!manual && o.channel === "corporate_transfer" && o.status === "pending") {
          voucher += ' <button class="primary small" data-confirm-topup-transfer="' + esc(o.order_no) + '">确认到账</button>' +
            ' <button class="ghost small" data-reject-topup-transfer="' + esc(o.order_no) + '">拒绝</button>';
        }
        return '<tr class="' + (manual ? "manual-transfer-row" : "") + '"><td>' + esc(o.order_no) + "</td><td>" + esc(customer) + "</td>" +
          '<td class="zh">' + what + payer + '</td><td class="' + (manual ? "manual-money" : "") + '">' + fmtYuan(o.amount_cents) + '</td><td class="zh">' + (CH_ZH[o.channel] || o.channel) + "</td>" +
          '<td class="zh"><span class="badge ' + (manual && o.status === "paid" ? "manual" : st[0]) + '">' +
          (manual && o.status === "paid" ? "人工确认到账" : st[1]) + "</span></td><td class=\"zh\">" + voucher + "</td><td>" + fmtTime(o.created_ts) + "</td></tr>";
      }).join("");

      $("#admin-withdrawals tbody").innerHTML = withdrawals.map(function (item) {
        var st = WITHDRAW_ST[item.status] || ["idle", item.status];
        var payout = item.payout || {};
        var account = esc(payout.account_name || "—") + '<div class="hint">' +
          esc(payout.method || item.payout_method || "") + " · " + esc(payout.account_no || "—") +
          (payout.bank_name ? " · " + esc(payout.bank_name) : "") + "</div>";
        var actions = item.status === "pending"
          ? '<button class="primary small" data-withdraw-approve="' + item.id + '">批准</button> <button class="ghost small" data-withdraw-reject="' + item.id + '">驳回</button>'
          : (item.status === "approved"
            ? '<button class="primary small" data-withdraw-paid="' + item.id + '">确认已打款</button> <button class="ghost small" data-withdraw-reject="' + item.id + '">驳回</button>'
            : esc(item.admin_note || "—"));
        return '<tr><td>' + esc(item.withdrawal_no) + '</td><td class="zh"><b>' + esc(item.company || ("OEM #" + item.oem_id)) +
          '</b><div class="hint">' + esc(item.oem_email || "") + '</div></td><td>' + fmtYuan(item.amount_cents) +
          '</td><td class="zh">' + account + '</td><td class="zh"><span class="badge ' + st[0] + '">' + st[1] +
          '</span></td><td>' + fmtTime(item.created_ts) + '</td><td class="zh">' + actions + '</td></tr>';
      }).join("") || '<tr><td colspan="7" class="empty">暂无提现申请</td></tr>';

      // 每个 OEM 可有自己的结算成本；零售价仍是平台统一价格，避免下级客户
      // 因 OEM 不同看到不同售价。表格输入只在点保存时提交，不做自动保存。
      $("#admin-oem-commercial-terms tbody").innerHTML = commercialTerms.map(function (item) {
        var rule = item.custom ? '<span class="badge active">专属</span>' : '<span class="badge idle">跟随默认</span>';
        var rate = item.topup_cost_bps === null || item.topup_cost_bps === undefined
          ? "" : Number(item.topup_cost_bps) / 100;
        return '<tr data-commercial-row="' + item.oem_id + '"><td class="zh"><b>' + esc(item.name || "未填写企业名") +
          '</b><div class="hint">' + esc(item.email) + '</div></td><td><input data-commercial-key type="number" min="0" step="0.01" value="' +
          (Number(item.key_cost_cents) / 100) + '" style="width:120px"></td><td><input data-commercial-rate type="number" min="0" max="100" step="0.01" value="' +
          rate + '" placeholder="如 70" style="width:100px">%</td><td class="zh">' + rule + '</td><td class="zh"><button class="primary small" data-commercial-save="' +
          item.oem_id + '">保存专属价</button> <button class="ghost small" data-commercial-default="' + item.oem_id + '">恢复默认</button></td></tr>';
      }).join("") || '<tr><td colspan="5" class="empty">暂无 OEM 客户</td></tr>';

      $all("[data-request-status]").forEach(function (button) {
        var status = button.dataset.requestStatus;
        var key = status || "all";
        var count = button.querySelector("em");
        if (count) count.textContent = String(requestCounts[key] || 0);
        button.classList.toggle("on", status === adminRequestStatus);
      });

      // 申请历史始终保留面板；空筛选也要明确展示，避免“处理完就消失”的旧体验。
      $("#admin-requests tbody").innerHTML = reqs.map(function (q) {
        var pendingActions = "";
        if (q.status === "pending" && q.payment_method === "corporate_transfer") {
          pendingActions = '<button class="primary small" data-confirm-transfer="' + q.id + '">确认到账并签发</button> ' +
            '<button class="ghost small" data-needs-info="' + q.id + '">补资料</button> ' +
            '<button class="ghost small" data-reject-transfer="' + q.id + '">拒绝</button>';
        } else if (q.status === "pending" && q.payment_method === "online") {
          pendingActions = '<span class="hint">等待支付回调</span> <button class="ghost small" data-reject="' + q.id + '">关闭申请</button>';
        } else if (q.status === "pending") {
          pendingActions = '<button class="primary small" data-approve="' + q.id + '">批准</button> ' +
            '<button class="ghost small" data-needs-info="' + q.id + '">补资料</button> ' +
            '<button class="ghost small" data-reject="' + q.id + '">拒绝</button>';
        }
        var requested = q.requested_tokens || 100000000;
        var paymentCell = q.payment_method === "manual_review"
          ? '<input type="number" min="0" max="1000000000000" value="' + requested +
            '" style="width:130px" data-grantfor="' + q.id + '" title="附赠 token" ' +
            (q.status === "pending" ? "" : "disabled") + " />"
          : '<b>' + esc(PAYMENT_METHOD_ZH[q.payment_method] || q.payment_method) + '</b><div class="hint">' +
            esc(PAYMENT_STATUS_ZH[q.payment_status] || q.payment_status) + " · " + fmtYuan(q.payment_amount_cents) +
            "<br>" + fmtTokens(requested) + " Token" + (q.transfer_no ? " · " + esc(q.transfer_no) : "") + "</div>";
        return "<tr><td>#" + q.id + '</td><td class="zh"><b>' + esc(q.company || "未补企业名") +
          '</b><div class="hint">' + esc(q.oem_email) + '</div></td><td class="zh"><b>' +
          esc(q.deployment_domain || "域名待定") + '</b><div class="hint">' + esc(q.purpose || q.note || "—") +
          (q.expected_public_ip_masked ? "<br>IP " + esc(q.expected_public_ip_masked) +
            (q.strict_ip ? " · 严格" : " · 核验") : "") +
          '</div></td><td class="zh"><span class="badge ' + (REQUEST_CLASS[q.status] || "idle") + '">' +
          (REQUEST_LABEL[q.status] || q.status) + "</span></td><td>" + fmtTime(q.created_ts) +
          '</td><td class="zh">' + paymentCell + '</td><td class="zh"><button class="ghost small" data-request-detail="' +
          q.id + '">详情</button> ' + pendingActions + "</td></tr>";
      }).join("") || '<tr><td colspan="7" class="zh empty">当前筛选下没有申请记录</td></tr>';

      // 统计条
      var online = insts.filter(function (i) { return hbStatus(i) !== "offline"; }).length;
      var balSum = insts.reduce(function (a, i) { return a + (i.balance_tokens || 0); }, 0);
      // 人员数只从节点心跳汇总，不掺入 Nexus 门户账号。旧节点的
      // ``users`` 只能用于账号总数，不猜测其中多少是管理员或 AI。
      var peopleTotals = insts.reduce(function (sum, inst) {
        var stats = inst.stats && typeof inst.stats === "object" ? inst.stats : {};
        var detailed = stats.users_business !== undefined;
        sum.accounts += Number(stats.users_total !== undefined ? stats.users_total : (stats.users || 0)) || 0;
        if (detailed) {
          sum.detailedNodes += 1;
          sum.business += Number(stats.users_business) || 0;
          sum.admins += Number(stats.users_admin) || 0;
          sum.ai += Number(stats.users_ai) || 0;
        }
        if (stats.rooms_total !== undefined) {
          sum.roomNodes += 1;
          sum.rooms += Number(stats.rooms_total) || 0;
        }
        if (stats.channels_total !== undefined) {
          sum.channelNodes += 1;
          sum.channels += Number(stats.channels_total) || 0;
        }
        if (stats.knowledge_bases_total !== undefined) {
          sum.knowledgeBaseNodes += 1;
          sum.knowledgeBases += Number(stats.knowledge_bases_total) || 0;
        }
        if (stats.kb_docs !== undefined) {
          sum.kbDocNodes += 1;
          sum.kbDocs += Number(stats.kb_docs) || 0;
        }
        if (stats.skills_available !== undefined) {
          sum.skillNodes += 1;
          sum.skillsAvailable += Number(stats.skills_available) || 0;
        }
        if (stats.skills_custom_enabled !== undefined) {
          sum.skillCustomNodes += 1;
          sum.skillsCustomEnabled += Number(stats.skills_custom_enabled) || 0;
        }
        if (stats.agents_available !== undefined) {
          sum.agentNodes += 1;
          sum.agentsAvailable += Number(stats.agents_available) || 0;
        }
        if (stats.agents_custom_enabled !== undefined) {
          sum.agentCustomNodes += 1;
          sum.agentsCustomEnabled += Number(stats.agents_custom_enabled) || 0;
        }
        if (stats.workflows_enabled !== undefined) {
          sum.workflowNodes += 1;
          sum.workflowsEnabled += Number(stats.workflows_enabled) || 0;
          sum.workflowsTotal += Number(stats.workflows_total) || 0;
        }
        if (stats.workflow_runs !== undefined) {
          sum.workflowRunNodes += 1;
          sum.workflowRuns += Number(stats.workflow_runs) || 0;
        }
        if (stats.members_total !== undefined) {
          sum.memberNodes += 1;
          sum.members += Number(stats.members_total) || 0;
        }
        sum.tokensTotal += Number(inst.tokens_total) || 0;
        sum.tokensToday += Number(inst.tokens_today) || 0;
        sum.requestsTotal += Number(inst.requests_total) || 0;
        sum.requestsToday += Number(inst.requests_today) || 0;
        return sum;
      }, {
        accounts: 0, business: 0, admins: 0, ai: 0, detailedNodes: 0,
        rooms: 0, roomNodes: 0, members: 0, memberNodes: 0,
        channels: 0, channelNodes: 0,
        knowledgeBases: 0, knowledgeBaseNodes: 0, kbDocs: 0, kbDocNodes: 0,
        skillsAvailable: 0, skillNodes: 0, skillsCustomEnabled: 0, skillCustomNodes: 0,
        agentsAvailable: 0, agentNodes: 0, agentsCustomEnabled: 0, agentCustomNodes: 0,
        workflowsTotal: 0, workflowsEnabled: 0, workflowNodes: 0,
        workflowRuns: 0, workflowRunNodes: 0,
        tokensTotal: 0, tokensToday: 0, requestsTotal: 0, requestsToday: 0,
      });
      var detailedHint = peopleTotals.detailedNodes + " / " + insts.length + " 个节点已分类";
      var formatPeople = function (value) {
        return (Number(value) || 0).toLocaleString("zh-CN");
      };
      var detailedValue = function (value) {
        return peopleTotals.detailedNodes ? formatPeople(value) : "—";
      };
      var reportedValue = function (value, nodeCount) {
        return nodeCount ? formatPeople(value) : "—";
      };
      var reportedHint = function (nodeCount) {
        return nodeCount + " / " + insts.length + " 个节点已上报";
      };
      var fleetLiveClass = insts.length && online === insts.length
        ? "" : (online ? " warn" : " off");
      // 舰队总览不再把二十多个指标铺成同等级大卡片。核心指标保留大字号，
      // 其余按「用户与空间 / 内容与 AI 资产 / AI 用量」分组；所有值仍来自上面的
      // 真实聚合结果，展示重构不会引入任何演示数据。
      var fleetKpi = function (icon, label, value, note, accent) {
        return '<div class="fleet-kpi' + (accent ? " accent" : "") + '">' +
          '<span class="fleet-kpi-label"><i class="fleet-kpi-icon">' + esc(icon) + "</i>" + esc(label) + "</span>" +
          "<b>" + esc(value) + "</b><small>" + esc(note) + "</small></div>";
      };
      var fleetMini = function (label, value, note, accent) {
        return '<div class="fleet-mini' + (accent ? " accent" : "") + '">' +
          '<span class="fleet-mini-label">' + esc(label) + "</span><b>" + esc(value) + "</b>" +
          (note ? "<small>" + esc(note) + "</small>" : "") + "</div>";
      };
      var fleetGroup = function (mark, title, subtitle, metrics, foot, extraClass) {
        return '<section class="fleet-group ' + (extraClass || "") + '"><div class="fleet-group-head"><div>' +
          "<h3>" + esc(title) + "</h3><p>" + esc(subtitle) + "</p></div>" +
          '<span class="fleet-group-mark">' + esc(mark) + '</span></div><div class="fleet-metrics">' +
          metrics.join("") + '</div><p class="fleet-group-foot">' + esc(foot) + "</p></section>";
      };
      $("#finance-wallet-balance").textContent = fmtTokens(balSum);
      $("#admin-stats").innerHTML =
        '<section class="fleet-summary"><div class="fleet-summary-head"><div>' +
        '<span class="fleet-eyebrow">FLEET STATUS</span><h2>舰队运行状态</h2></div>' +
        '<span class="fleet-live"><i class="fleet-live-dot' + fleetLiveClass + '"></i>' +
        online + " / " + insts.length + " 个节点在线</span></div><div class=\"fleet-summary-grid\">" +
        fleetKpi("◇", "实例总数", String(insts.length), "已接入 Nexus 的节点", false) +
        fleetKpi("●", "在线节点", String(online), online === insts.length ? "全部运行正常" : "请检查离线节点", true) +
        fleetKpi("◎", "OEM 客户", String(oems.length), "已建立企业档案", false) +
        fleetKpi("⌁", "授权 KEY", keys.length + " / " + keys.filter(function (k) { return k.instance_id; }).length, "已发 / 已兑换", false) +
        fleetKpi("◈", "钱包余额", fmtTokens(balSum), "全舰队 Token 余额", true) +
        "</div></section><div class=\"fleet-groups\">" +
        fleetGroup("人", "节点与用户", "账号构成及协作空间", [
          fleetMini("节点账号总数", formatPeople(peopleTotals.accounts), "含管理员与系统账号", false),
          fleetMini("业务用户", detailedValue(peopleTotals.business), "真实业务账号", true),
          fleetMini("管理员账号", detailedValue(peopleTotals.admins), "服务器管理员", false),
          fleetMini("AI / 系统账号", detailedValue(peopleTotals.ai), "主 AI 与协作 AI", false),
          fleetMini("全部 Matrix 房间", reportedValue(peopleTotals.rooms, peopleTotals.roomNodes), "完整房间口径", false),
          fleetMini("业务频道", reportedValue(peopleTotals.channels, peopleTotals.channelNodes), "已排除空间、私聊和 AI 会话", true),
        ], "账号分类：" + detailedHint + " · 频道：" + reportedHint(peopleTotals.channelNodes), "") +
        fleetGroup("AI", "内容与 AI 资产", "可复用的知识与自动化能力", [
          fleetMini("有内容的知识库", reportedValue(peopleTotals.knowledgeBases, peopleTotals.knowledgeBaseNodes), "共 " + reportedValue(peopleTotals.kbDocs, peopleTotals.kbDocNodes) + " 篇文档", false),
          fleetMini("平台可用技能", reportedValue(peopleTotals.skillsAvailable, peopleTotals.skillNodes), "内置 + 控制室目录", true),
          fleetMini("自建技能（启用）", reportedValue(peopleTotals.skillsCustomEnabled, peopleTotals.skillCustomNodes), "节点 PostgreSQL", false),
          fleetMini("平台 AI Agent", reportedValue(peopleTotals.agentsAvailable, peopleTotals.agentNodes), "内置 + 控制室目录", true),
          fleetMini("自建 AI Agent", reportedValue(peopleTotals.agentsCustomEnabled, peopleTotals.agentCustomNodes), "节点 PostgreSQL", false),
          fleetMini("启用工作流", reportedValue(peopleTotals.workflowsEnabled, peopleTotals.workflowNodes), "共 " + reportedValue(peopleTotals.workflowsTotal, peopleTotals.workflowNodes) + " 个定义", false),
          fleetMini("工作流累计运行", reportedValue(peopleTotals.workflowRuns, peopleTotals.workflowRunNodes), "真实运行记录", false),
          fleetMini("有效会员", peopleTotals.memberNodes ? formatPeople(peopleTotals.members) : "—", "当前有效订阅", false),
        ], "资产指标来自节点 Matrix 状态与 PostgreSQL；未读取到时显示 —", "") +
        fleetGroup("↗", "AI 用量", "Token 与模型请求趋势", [
          fleetMini("今日 Token", fmtTokens(peopleTotals.tokensToday), "今日累计消耗", true),
          fleetMini("累计 Token", fmtTokens(peopleTotals.tokensTotal), "历史累计消耗", false),
          fleetMini("今日 AI 请求", formatPeople(peopleTotals.requestsToday), "成功与失败请求", true),
          fleetMini("累计 AI 请求", formatPeople(peopleTotals.requestsTotal), "历史请求总数", false),
        ], "用量来自 Nexus 账本，不依赖节点进程内计数", "fleet-usage") +
        "</div>";

      // 实例表（行内充值按钮）
      $("#admin-instances tbody").innerHTML = insts.map(function (i) {
        // 企业名来自 Nexus 服务端的 KEY 归属关联，邮箱只作为快速核对提示。
        // 历史节点尚未认领 KEY 时不猜测企业，明确提醒超管后续补绑。
        var company = i.company_name
          ? "<b>" + esc(i.company_name) + "</b>" + (i.oem_email ? '<div class="hint">' + esc(i.oem_email) + "</div>" : "")
          : '<span class="hint">未绑定企业</span>';
        var nodeStats = i.stats && typeof i.stats === "object" ? i.stats : {};
        var hasBreakdown = nodeStats.users_business !== undefined;
        var people = hasBreakdown
          ? '<b>业务 ' + esc(instanceStatText(nodeStats.users_business)) + '</b><div class="hint">管理员 ' +
            esc(instanceStatText(nodeStats.users_admin || 0)) + ' · AI ' + esc(instanceStatText(nodeStats.users_ai || 0)) + '</div>'
          : '<span class="hint">账号总数 ' + esc(instanceStatText(nodeStats.users)) + '<br>待节点升级后分类</span>';
        return "<tr><td>#" + i.id + "</td><td>" + esc(i.domain) + "</td><td class=\"zh\">" + company + "</td><td class=\"zh\">" + badge(hbStatus(i)) + "</td>" +
          "<td>" + esc(i.version || "—") + "</td><td class=\"zh\">" + people + "</td><td>" + fmtTime(i.last_seen_ts) + "</td>" +
          "<td>" + fmtTokens(i.balance_tokens) + "</td>" +
          '<td class="zh"><button class="ghost small" data-instance-detail="' + i.id + '">详情</button> ' +
          '<button class="ghost small" data-topup="' + i.id + '" data-domain="' + esc(i.domain) + '">充值</button></td></tr>';
      }).join("") || '<tr><td colspan="9" class="zh empty">暂无实例</td></tr>';

      // KEY 表（吊销）
      $("#admin-keys tbody").innerHTML = keys.map(function (k) {
        var st = k.status === "suspended" ? "suspended" : (k.status !== "active" ? "revoked" : (k.instance_id ? "active" : "idle"));
        // 超管要能够直接核对 KEY 的企业归属；历史手工签发但未认领的 KEY 明确标记为未归属。
        var owner = k.company_name || k.oem_email || "未归属";
        var statusAction = k.status === "active"
          ? '<button class="ghost small" data-key-status="suspended" data-key-id="' + k.id + '">暂停</button> '
          : k.status === "suspended"
            ? '<button class="ghost small" data-key-status="active" data-key-id="' + k.id + '">恢复</button> ' : "";
        var revokeAction = k.status !== "revoked"
          ? '<button class="ghost small" data-revoke="' + k.id + '">吊销</button>' : "";
        return "<tr><td>#" + k.id + "</td><td>···" + esc(k.tail) + '</td><td class="zh">' + esc(owner) +
          "</td><td class=\"zh\">" + badge(st) + "</td>" +
          "<td>" + fmtTokens(k.token_grant) + "</td><td class=\"zh\">" + esc(k.note || "—") + "</td>" +
          "<td class=\"zh\">" + (k.instance_id ? "#" + k.instance_id : "—") + "</td>" +
          '<td class="zh">' + (statusAction + revokeAction || "—") + "</td></tr>";
      }).join("") || '<tr><td colspan="8" class="zh empty">尚未签发</td></tr>';

      // OEM 客户表（自助注册模式：超管唯一管控 = 停用/启用；账号状态用"正常/停用"措辞）
      $("#admin-oems tbody").innerHTML = oems.map(function (o) {
        var on = o.status === "active";
        // 邀请人列：平台直属显示 GuDuu(橙),下线显示上线邮箱——分销层级一眼可辨
        var inviter = o.inviter === "GuDuu"
          ? '<span style="color:var(--orange)">GuDuu</span>'
          : esc(o.inviter || "—");
        return "<tr><td>#" + o.id + "</td><td>" + esc(o.email) + "</td><td class=\"zh\">" + esc(o.name || "—") + "</td>" +
          '<td class="zh"><b>第 ' + (o.level || 1) + ' 层</b><div class="hint">直属：' + inviter + "</div></td>" +
          '<td class="zh">直属 ' + (o.direct_users || 0) + '<div class="hint">网络 ' + (o.network_users || 0) + "</div></td>" +
          '<td class="zh">直属 ' + (o.direct_oems || 0) + '<div class="hint">全部 ' + (o.total_downline_oems || 0) + "</div></td>" +
          '<td class="zh"><span class="badge ' + (on ? "active" : "disabled") + '">' + (on ? "正常" : "停用") + "</span></td>" +
          "<td>" + o.keys_claimed + "</td><td>" + fmtTime(o.created_ts) + "</td>" +
          '<td class="zh"><button class="ghost small" data-detail="' + o.id + '">详情</button> ' +
          '<button class="ghost small" data-oemstatus="' + o.id + '" data-tostatus="' + (on ? "disabled" : "active") + '" data-email="' + esc(o.email) + '">' + (on ? "停用" : "启用") + "</button></td></tr>";
      }).join("") || '<tr><td colspan="10" class="zh empty">暂无注册客户</td></tr>';
      // 首次进入后台时自动回填，之后刷新数据不覆盖管理员正在编辑的内容。
      loadReleaseDraft(false);
    }).catch(function (err) { toast(err.message, true); });
  }

  $("#btn-refresh").addEventListener("click", loadAdmin);
  $("#btn-release-refresh").addEventListener("click", loadAdmin);
  $("#btn-release-generate").addEventListener("click", function () { loadReleaseDraft(true); });
  $("#btn-admin-refresh").addEventListener("click", function () {
    loadAdmin(); loadAdminSecurity();
  });
  $("#btn-copy-admin-guide").addEventListener("click", function () {
    copyText(adminGuideMarkdown())
      .then(function () { toast("教程 Markdown 已复制"); })
      .catch(function () { toast("复制失败，请检查浏览器剪贴板权限", true); });
  });
  $("#btn-oem-refresh").addEventListener("click", function () {
    loadOem();
  });

  $("#form-admin-create").addEventListener("submit", function (e) {
    e.preventDefault();
    var form = e.target;
    api("/nexus/admin/admins", { body: {
      username: form.username.value,
      display_name: form.display_name.value,
      password: form.password.value,
    } }).then(function () {
      form.reset();
      toast("具名管理员已创建，请让对方使用自己的账号登录");
      loadAdminSecurity();
    }).catch(function (err) { toast(err.message, true); });
  });

  $("#btn-admin-audit-filter").addEventListener("click", loadAdminSecurity);
  $("#admin-audit-actor").addEventListener("keydown", function (e) {
    if (e.key === "Enter") loadAdminSecurity();
  });

  $("#btn-add-passkey").addEventListener("click", function () {
    if (!window.PublicKeyCredential || !navigator.credentials) {
      toast("当前浏览器不支持 Passkey", true);
      return;
    }
    var button = this;
    var ceremonyId = "";
    var credentialJson = null;
    button.disabled = true;
    api("/nexus/admin/passkey/register/options", { body: {} }).then(function (result) {
      ceremonyId = result.ceremony_id;
      return navigator.credentials.create({
        publicKey: decodeCreationOptions(result.public_key),
      });
    }).then(function (credential) {
      if (!credential) throw new Error("未创建 Passkey");
      credentialJson = registrationCredentialJson(credential);
      return uiPrompt("给这个 Passkey 起一个容易辨认的名称", "例如：MacBook Touch ID");
    }).then(function (name) {
      if (name === null) throw new Error("已取消保存 Passkey");
      return api("/nexus/admin/passkey/register/verify", { body: {
        ceremony_id: ceremonyId,
        credential: credentialJson,
        name: name,
      } });
    }).then(function () {
      toast("Passkey 已添加，下次可免输密码登录");
      loadAdminSecurity();
    }).catch(function (err) {
      toast(err.name === "NotAllowedError"
        ? "Passkey 操作已取消或超时" : err.message, true);
    }).finally(function () { button.disabled = false; });
  });

  $("#admin-passkeys").addEventListener("click", function (e) {
    var button = e.target.closest("button[data-passkey-delete]");
    if (!button) return;
    uiConfirm("确认移除这个 Passkey？移除后该设备不能再用于登录。", true, "确认移除")
      .then(function (ok) {
        if (!ok) return;
        return api("/nexus/admin/passkey/delete", {
          body: { passkey_id: Number(button.dataset.passkeyDelete) },
        }).then(function () {
          toast("Passkey 已移除");
          loadAdminSecurity();
        });
      }).catch(function (err) { toast(err.message, true); });
  });

  $("#admin-admins tbody").addEventListener("click", function (e) {
    var button = e.target.closest("button");
    if (!button) return;
    if (button.dataset.adminStatus) {
      var adminId = Number(button.dataset.adminStatus);
      var next = button.dataset.next;
      var label = next === "disabled" ? "停用" : "启用";
      uiConfirm("确认" + label + "这个管理员账号？停用会立即撤销其全部会话。", next === "disabled", "确认" + label)
        .then(function (ok) {
          if (!ok) return;
          return api("/nexus/admin/admin_status", { body: { admin_id: adminId, status: next } })
            .then(function () { toast("管理员已" + label); loadAdminSecurity(); });
        }).catch(function (err) { toast(err.message, true); });
    }
    if (button.dataset.adminReset) {
      var resetId = Number(button.dataset.adminReset);
      uiPrompt("输入该管理员的新密码（至少 8 位，需同时含字母和数字）", "新密码")
        .then(function (password) {
          if (password === null) return;
          return api("/nexus/admin/admin_password", { body: { admin_id: resetId, new_password: password } })
            .then(function () {
              if (Number(currentAdminIdentity.id) === resetId) {
                clearAuth(); route(); toast("密码已重置，请使用新密码重新登录");
              } else {
                toast("密码已重置，该管理员的旧会话已全部失效");
                loadAdminSecurity();
              }
            });
        }).catch(function (err) { toast(err.message, true); });
    }
  });

  // 输入版本号时自动补对应 tag；若管理员已经手动改过 tag，就不强行覆盖。
  $("#form-release").version.addEventListener("input", function () {
    var form = $("#form-release");
    var expected = this.dataset.previousTag || "";
    if (!form.git_ref.value || form.git_ref.value === expected) {
      form.git_ref.value = this.value ? "v" + this.value.trim() : "";
    }
    this.dataset.previousTag = this.value ? "v" + this.value.trim() : "";
    syncReleaseSubmitState();
  });

  $("#form-release").addEventListener("submit", function (e) {
    e.preventDefault();
    var form = e.target;
    var releaseTarget = form.elements.target.value;
    api("/nexus/admin/releases", {
      body: {
        target: releaseTarget,
        delivery_mode: releaseTarget === "node" ? "container" : "legacy_git",
        version: form.version.value,
        git_ref: form.git_ref.value,
        title: form.title.value,
        notes: form.notes.value,
      },
    }).then(function () {
      toast(releaseTarget === "nexus"
        ? "Nexus 更新已保存为未发布，审阅后可发布公告"
        : "节点版本已保存为未发布，可先推送灰度节点监测");
      form.reset();
      syncReleaseTargetUi();
      releaseDraftChecked = false;
      loadAdmin();
    }).catch(function (err) { toast(err.message, true); });
  });

  // ---------- 节点详情弹窗（运行快照 / 企业归属 / 心跳统计） ----------
  var INSTANCE_STAT_LABELS = {
    users_total: "账号总数",
    users_business: "业务用户",
    users_admin: "管理员",
    users_ai: "AI / 系统账号",
    users_guest: "访客账号",
    users_deactivated: "已停用账号",
    users_locked: "已锁定账号",
    users: "旧版账号总数",
    dau: "日活用户",
    messages_today: "今日消息（进程计数）",
    rooms_total: "全部 Matrix 房间",
    channels_total: "业务频道",
    spaces_total: "空间",
    ai_rooms_total: "AI 会话房",
    dm_rooms_total: "私聊房",
    rooms: "旧版房间数",
    members_total: "有效会员",
    members_paid: "付费会员",
    members_creator: "创作者会员",
    workflows_total: "工作流定义",
    workflows_enabled: "已启用工作流",
    workflow_runs: "工作流累计运行",
    orders_paid: "已支付订单",
    knowledge_bases_total: "有内容的知识库",
    kb_docs: "知识库文档",
    kb_chunks: "知识库分块",
    skills_available: "平台可用技能",
    skills_custom_total: "节点自建技能",
    skills_custom_enabled: "已启用自建技能",
    agents_available: "平台可用 AI Agent",
    agents_custom_total: "节点自建 AI Agent",
    agents_custom_enabled: "已启用自建 AI Agent",
    bots: "Bot 数",
    workflows: "工作流数",
  };
  var INSTANCE_STAT_ORDER = [
    "users_total", "users_business", "users_admin", "users_ai", "users_guest",
    "users_deactivated", "users_locked", "rooms_total", "channels_total",
    "spaces_total", "ai_rooms_total", "dm_rooms_total", "messages_today",
    "members_total", "members_paid", "members_creator",
    "knowledge_bases_total", "kb_docs", "kb_chunks",
    "skills_available", "skills_custom_total", "skills_custom_enabled",
    "agents_available", "agents_custom_total", "agents_custom_enabled",
    "workflows_total", "workflows_enabled", "workflow_runs", "orders_paid",
  ];

  function instanceStatText(value) {
    // 心跳 stats 允许以后增加字段；对象/数组转成 JSON 后再统一转义展示。
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "object") {
      try { return JSON.stringify(value); } catch (e) { return "—"; }
    }
    return String(value);
  }

  function closeInstanceDetail() {
    $("#instance-detail-mask").hidden = true;
  }

  function buildInstanceDetail(inst, viewer) {
    // 超管弹窗和 OEM 页面内展开区共用这一份展示模型，避免同一个心跳字段
    // 在两个页面变成不同口径；这里只整理数据，不直接操作任何界面节点。
    var isOem = viewer === "oem";
    var status = hbStatus(inst);
    var company = inst.company_name || "未绑定企业";
    var region = inst.region_label
      ? inst.region_label + (inst.region ? "（" + inst.region + "）" : "")
      : "未设置";
    var rows = isOem ? [
      ["节点编号", "#" + inst.id],
    ] : [
      ["所属企业", company],
      ["OEM 账号", inst.oem_email || "—"],
      ["OEM 编号", inst.oem_id ? "#" + inst.oem_id : "—"],
    ];
    rows = rows.concat([
      ["节点域名", inst.domain],
      ["节点管理员", inst.admin_email || "—"],
      ["当前版本", inst.version || "—"],
      ["最近心跳", fmtTime(inst.last_seen_ts)],
      ["创建时间", fmtTime(inst.created_ts)],
      ["已开通天数", activeDays(inst.created_ts)],
      ["节点地域", region],
      ["来源网段", inst.last_ip || "—"],
      ["Token 余额", fmtTokens(inst.balance_tokens) + " token"],
      ["今日 Token 消耗", fmtTokens(inst.tokens_today) + " token"],
      ["累计 Token 消耗", fmtTokens(inst.tokens_total) + " token"],
      ["今日 AI 请求", String(Number(inst.requests_today) || 0)],
      ["累计 AI 请求", String(Number(inst.requests_total) || 0)],
      ["服务状态", STATUS_ZH[status] || status],
    ]);
    var stats = inst.stats && typeof inst.stats === "object" ? inst.stats : {};
    var hasBreakdown = stats.users_business !== undefined;
    var keys = Object.keys(stats).sort(function (a, b) {
      var ai = INSTANCE_STAT_ORDER.indexOf(a);
      var bi = INSTANCE_STAT_ORDER.indexOf(b);
      if (ai >= 0 || bi >= 0) {
        if (ai < 0) return 1;
        if (bi < 0) return -1;
        return ai - bi;
      }
      return (INSTANCE_STAT_LABELS[a] || a).localeCompare(INSTANCE_STAT_LABELS[b] || b, "zh-CN");
    });
    var statsHtml = keys.map(function (key) {
      return '<div class="instance-stat"><small>' + esc(INSTANCE_STAT_LABELS[key] || key) +
        "</small><b>" + esc(instanceStatText(stats[key])) + "</b></div>";
    }).join("") || '<p class="empty">暂无心跳统计</p>';
    if (!hasBreakdown && stats.users !== undefined) {
      statsHtml += '<p class="instance-stat-note">当前是旧版节点的合计口径；升级后会自动拆分业务用户、管理员和 AI 账号。</p>';
    }
    return {
      title: isOem ? inst.domain : company,
      summary: (isOem ? "我的节点 #" : "节点 #") + inst.id + " · " + inst.domain,
      stateHtml: badge(status) + "<span>" + (status === "active"
        ? "节点心跳正常" : (status === "warning" ? "心跳已超过 15 分钟" : "节点离线或已停用")) + "</span>",
      rowsHtml: rows.map(function (row) {
        return "<small>" + esc(row[0]) + "</small><b>" + esc(row[1]) + "</b>";
      }).join(""),
      statsHtml: statsHtml,
      oemId: Number(inst.oem_id) || 0,
    };
  }

  function renderInstanceDetail(inst, viewer) {
    // 超管继续使用弹窗；OEM 则由 renderOemInstanceDetail 渲染到首页正文。
    var detail = buildInstanceDetail(inst, viewer);
    $("#instance-detail-title").textContent = detail.title;
    $("#instance-detail-summary").textContent = detail.summary;
    $("#instance-detail-state").innerHTML = detail.stateHtml;
    $("#instance-detail-kv").innerHTML = detail.rowsHtml;
    $("#instance-detail-stats").innerHTML = detail.statsHtml;
    var oemButton = $("#instance-detail-oem");
    oemButton.hidden = !detail.oemId;
    oemButton.dataset.oemId = detail.oemId ? String(detail.oemId) : "";
    $("#instance-detail-source").textContent = "详情来自 Nexus 最近一次节点心跳和 OEM 档案。";
    $("#instance-detail-mask").hidden = false;
  }

  function openInstanceDetail(instanceId) {
    var inst = adminInstances.find(function (item) { return Number(item.id) === Number(instanceId); });
    if (!inst) return toast("节点数据已更新，请刷新后重试", true);
    renderInstanceDetail(inst, "admin");
  }

  function syncOemInstanceCards() {
    $all("[data-oem-instance-detail]").forEach(function (card) {
      var selected = Number(card.dataset.oemInstanceDetail) === Number(oemInstanceDetailId);
      card.classList.toggle("selected", selected);
      card.setAttribute("aria-expanded", selected ? "true" : "false");
      var label = card.querySelector(".inst-card-open");
      if (label) label.textContent = selected ? "收起详细运行数据" : "在下方查看详细运行数据";
    });
  }

  function closeOemInstanceDetail() {
    // 递增请求序号，使已经发出的旧请求即使稍后返回也不能重新打开详情区。
    oemInstanceDetailRequest += 1;
    oemInstanceDetailId = 0;
    $("#oem-instance-detail").hidden = true;
    syncOemInstanceCards();
  }

  function renderOemInstanceDetail(inst) {
    var detail = buildInstanceDetail(inst, "oem");
    $("#oem-instance-detail-title").textContent = detail.title;
    $("#oem-instance-detail-summary").textContent = detail.summary;
    $("#oem-instance-detail-state").innerHTML = detail.stateHtml;
    $("#oem-instance-detail-kv").innerHTML = detail.rowsHtml;
    $("#oem-instance-detail-stats").innerHTML = detail.statsHtml;
    $("#oem-instance-detail").hidden = false;
  }

  function fetchOemInstanceDetail(instanceId) {
    // 前端先拒绝已不在当前卡片列表的编号，只是为了更友好的错误提示；
    // API 依然会根据会话与 KEY 归属再做一次强制校验。
    var owned = oemInstances.some(function (item) { return Number(item.id) === Number(instanceId); });
    if (!owned) return toast("该节点已不在你的实例列表，请刷新后重试", true);
    var requestId = ++oemInstanceDetailRequest;
    var summary = oemInstances.find(function (item) { return Number(item.id) === Number(instanceId); });
    $("#oem-instance-detail-title").textContent = summary ? summary.domain : "节点详情";
    $("#oem-instance-detail-summary").textContent = "正在读取节点最新心跳与账本数据…";
    $("#oem-instance-detail-state").innerHTML = '<span class="badge warning">读取中</span><span>请稍候</span>';
    $("#oem-instance-detail-kv").innerHTML = "";
    $("#oem-instance-detail-stats").innerHTML = '<p class="empty">正在加载真实运营数据…</p>';
    $("#oem-instance-detail").hidden = false;
    api("/nexus/oem/instance?instance_id=" + encodeURIComponent(instanceId))
      .then(function (result) {
        if (requestId !== oemInstanceDetailRequest || Number(instanceId) !== Number(oemInstanceDetailId)) return;
        renderOemInstanceDetail(result.instance);
      })
      .catch(function (err) {
        if (requestId !== oemInstanceDetailRequest) return;
        $("#oem-instance-detail-summary").textContent = "节点数据读取失败";
        $("#oem-instance-detail-state").innerHTML = '<span class="badge offline">读取失败</span><span>' + esc(err.message) + "</span>";
        $("#oem-instance-detail-kv").innerHTML = "";
        $("#oem-instance-detail-stats").innerHTML = "";
        toast(err.message, true);
      });
  }

  function openOemInstanceDetail(instanceId) {
    if (Number(oemInstanceDetailId) === Number(instanceId) && !$("#oem-instance-detail").hidden) {
      closeOemInstanceDetail();
      return;
    }
    oemInstanceDetailId = Number(instanceId);
    syncOemInstanceCards();
    fetchOemInstanceDetail(instanceId);
  }

  $("#instance-detail-close").addEventListener("click", closeInstanceDetail);
  $("#instance-detail-mask").addEventListener("click", function (e) {
    if (e.target === this) closeInstanceDetail();
  });
  $("#instance-detail-oem").addEventListener("click", function () {
    var oemId = Number(this.dataset.oemId || 0);
    if (!oemId) return;
    closeInstanceDetail();
    openDetail(oemId);
  });
  $("#oem-instance-detail-close").addEventListener("click", closeOemInstanceDetail);

  // ---------- 客户详情弹窗（档案/资产/合同附件/备注） ----------
  var detailOemId = 0; // 当前弹窗对应的客户 id

  function fmtSize(n) {
    n = Number(n) || 0;
    if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB";
    if (n >= 1024) return Math.round(n / 1024) + " KB";
    return n + " B";
  }

  function openDetail(oemId) {
    detailOemId = oemId;
    api("/nexus/admin/oem_detail?oem_id=" + oemId).then(function (d) {
      $("#dt-title").textContent = (d.company || d.email) + "（#" + d.id + "）";
      var rows = [
        ["企业名称", d.company || (d.profile_missing ? "未补录(历史账号)" : "—")],
        ["联系人", d.contact_name || "—"],
        ["联系方式", d.phone || "—"],
        ["登录邮箱", d.email],
        ["邀请人", d.inviter],
        ["注册时间", fmtTime(d.created_ts)],
        ["账号状态", d.status === "active" ? "正常" : "停用"],
        ["授权码", d.keys.length + " 把"],
        ["实例", d.instances.map(function (i) { return i.domain; }).join("、") || "未开通"],
        ["钱包余额", fmtTokens(d.balance_total) + " token"],
      ];
      $("#dt-kv").innerHTML = rows.map(function (r) {
        return "<small>" + r[0] + "</small><b>" + esc(String(r[1])) + "</b>";
      }).join("");
      $("#dt-files").innerHTML = d.files.map(function (f) {
        return '<div class="file-row"><span class="fname">' + esc(f.filename) + "</span>" +
          "<small>" + fmtSize(f.size) + " · " + fmtTime(f.uploaded_ts) + "</small>" +
          '<span><button class="ghost small" data-dlfile="' + f.id + '" data-fname="' + esc(f.filename) + '">下载</button> ' +
          '<button class="ghost small" data-delfile="' + f.id + '">删除</button></span></div>';
      }).join("") || '<p class="empty">尚未上传任何附件</p>';
      $("#dt-note").value = d.admin_note || "";
      $("#detail-mask").hidden = false;
    }).catch(function (err) { toast(err.message, true); });
  }

  $("#dt-close").addEventListener("click", function () { $("#detail-mask").hidden = true; });
  $("#detail-mask").addEventListener("click", function (e) {
    if (e.target === this) this.hidden = true; // 点遮罩空白处关闭
  });

  // 上传：原始字节直传（Content-Type 带文件类型，文件名走 query 转义）
  $("#dt-upload").addEventListener("change", function () {
    var file = this.files && this.files[0];
    this.value = "";
    if (!file || !detailOemId) return;
    if (file.size > 20 * 1048576) return toast("单个文件不能超过 20MB", true);
    var auth = getAuth();
    fetch(new URL("/nexus/admin/oem_upload?oem_id=" + detailOemId + "&filename=" + encodeURIComponent(file.name), window.location.origin).href, {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + (auth ? auth.token : ""),
        "Content-Type": file.type || "application/octet-stream",
      },
      body: file,
    }).then(function (res) { return res.json(); }).then(function (data) {
      if (data.errcode) throw new Error(data.error);
      toast("已上传 " + file.name);
      openDetail(detailOemId); // 刷新附件列表
    }).catch(function (err) { toast(err.message || "上传失败", true); });
  });

  // 备注保存
  $("#dt-note-save").addEventListener("click", function () {
    if (!detailOemId) return;
    api("/nexus/admin/oem_note", { body: { oem_id: detailOemId, note: $("#dt-note").value } })
      .then(function () { toast("备注已保存"); })
      .catch(function (err) { toast(err.message, true); });
  });

  // 定价保存：每行“客户价:OEM结算价:token”，金额统一换算为整数分。
  $("#form-pricing").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    var packs = [];
    var lines = $("#pricing-packs").value.split("\n");
    for (var i = 0; i < lines.length; i++) {
      var ln = lines[i].trim();
      if (!ln) continue;
      var m = ln.split(":");
      var yuan = Number(m[0]), oemYuan = Number(m[1]), tokens = Number(m[2]);
      if (m.length !== 3 || !(yuan > 0) || !(oemYuan >= 0) || oemYuan > yuan || !(tokens > 0)) {
        return toast("充值包第 " + (i + 1) + " 行格式应为 客户价:OEM结算价:token数（如 99:70:50000000）", true);
      }
      packs.push({ cents: Math.round(yuan * 100), oem_cost_cents: Math.round(oemYuan * 100), tokens: tokens });
    }
    api("/nexus/admin/pricing", {
      body: {
        key_price_cents: Math.round(Number(f.key_yuan.value || 0) * 100),
        key_oem_cost_cents: Math.round(Number(f.key_oem_yuan.value || 0) * 100),
        key_token_grant: Number(f.key_grant.value || 0),
        settlement_days: Number(f.settlement_days.value || 0),
        withdraw_min_cents: Math.round(Number(f.withdraw_min_yuan.value || 0) * 100),
        topup_packs: packs,
      },
    }).then(function () { toast("定价已保存，即刻生效"); loadAdmin(); })
      .catch(function (err) { toast(err.message, true); });
  });

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

  // 表格行内操作（事件代理：详情 / 吊销 / 充值）
  document.addEventListener("click", function (e) {
    var t = e.target;
    if (t.dataset && (t.dataset.commercialSave || t.dataset.commercialDefault)) {
      var commercialOemId = Number(t.dataset.commercialSave || t.dataset.commercialDefault);
      var useDefaultTerms = !!t.dataset.commercialDefault;
      var commercialRow = document.querySelector('[data-commercial-row="' + commercialOemId + '"]');
      var commercialBody = { oem_id: commercialOemId, use_default: useDefaultTerms };
      if (!useDefaultTerms && commercialRow) {
        var rateInput = commercialRow.querySelector("[data-commercial-rate]").value.trim();
        if (rateInput === "" || Number(rateInput) < 0 || Number(rateInput) > 100) {
          toast("请填写 0% 到 100% 的 Token 结算比例", true);
          return;
        }
        commercialBody.key_cost_cents = Math.round(Number(commercialRow.querySelector("[data-commercial-key]").value || 0) * 100);
        commercialBody.topup_cost_bps = Math.round(Number(rateInput) * 100);
      }
      api("/nexus/admin/oem_commercial_terms", { body: commercialBody })
        .then(function () { toast(useDefaultTerms ? "已恢复平台默认结算价" : "OEM 专属结算价已保存"); loadAdmin(); })
        .catch(function (error) { toast(error.message, true); });
      return;
    }
    if (t.dataset && t.dataset.requestDetail) {
      openRequestDetail(Number(t.dataset.requestDetail));
      return;
    }
    if (t.dataset && t.dataset.revealRequest) {
      var revealId = Number(t.dataset.revealRequest);
      t.disabled = true;
      api("/nexus/oem/request_action", { body: { action: "reveal", request_id: revealId } })
        .then(function (result) {
          revealedRequestKeys[revealId] = result.request.key;
          toast("授权码已显示，请立即复制并安全保存");
          loadOem();
        })
        .catch(function (err) { t.disabled = false; toast(err.message, true); });
      return;
    }
    if (t.dataset && t.dataset.copyRequestKey) {
      var copyId = Number(t.dataset.copyRequestKey);
      copyText(revealedRequestKeys[copyId] || "")
        .then(function () { toast("授权码已复制"); })
        .catch(function () { toast("复制失败，请手动选择", true); });
      return;
    }
    if (t.dataset && t.dataset.editRequest) {
      var editId = Number(t.dataset.editRequest);
      var requestRow = oemRequests.find(function (item) { return Number(item.id) === editId; });
      if (requestRow) fillRequestForm(requestRow);
      return;
    }
    if (t.dataset && t.dataset.cancelRequest) {
      var cancelId = Number(t.dataset.cancelRequest);
      uiConfirm("确认撤回申请 #" + cancelId + "？撤回后如仍需要授权，须重新提交。", true, "确认撤回").then(function (ok) {
        if (!ok) return;
        api("/nexus/oem/request_action", { body: { action: "cancel", request_id: cancelId } })
          .then(function () { toast("申请已撤回"); loadOem(); })
          .catch(function (err) { toast(err.message, true); });
      });
      return;
    }
    if (t.dataset && t.dataset.instanceDetail) {
      openInstanceDetail(Number(t.dataset.instanceDetail));
      return;
    }
    var oemInstanceTarget = t.closest ? t.closest("[data-oem-instance-detail]") : null;
    if (oemInstanceTarget) {
      openOemInstanceDetail(Number(oemInstanceTarget.dataset.oemInstanceDetail));
      return;
    }
    // KEY 卡片快捷入口：查看节点回到首页正文详情；充值则进入购买页并预选
    // 当前 KEY 绑定的真实实例，避免多节点客户充错对象。
    if (t.dataset && t.dataset.keyViewInstance) {
      var keyViewInstanceId = Number(t.dataset.keyViewInstance);
      openOemPage("overview", true);
      setTimeout(function () { openOemInstanceDetail(keyViewInstanceId); }, 30);
      return;
    }
    if (t.dataset && t.dataset.keyTopupInstance) {
      var keyTopupInstanceId = Number(t.dataset.keyTopupInstance);
      openOemPage("commerce", true);
      setTimeout(function () {
        var target = document.querySelector('.pick[data-pick="inst"][data-val="' + keyTopupInstanceId + '"]');
        if (target) target.click();
      }, 30);
      toast("已进入 Token 充值，并选中对应节点");
      return;
    }
    if (t.dataset && t.dataset.keyOpenPage) {
      openOemPage(t.dataset.keyOpenPage, true);
      return;
    }
    if (t.dataset && t.dataset.copyLink) {
      copyText(t.dataset.copyLink)
        .then(function () { toast("分享链接已复制"); })
        .catch(function () { toast("复制失败，请手动选择链接", true); });
      return;
    }
    if (t.dataset && t.dataset.releaseAction) {
      var action = t.dataset.releaseAction;
      var platformRelease = t.dataset.releaseTarget === "nexus";
      var releaseId = Number(t.dataset.releaseId);
      var body = { release_id: releaseId, action: action };
      if (action === "canary") {
        body.instance_id = Number($("#release-canary").value || 0);
        if (!body.instance_id) return toast("请先选择一个灰度节点", true);
      }
      var promptText = action === "publish" && platformRelease
        ? "确认把这条 Nexus 平台更新公告展示给全部 OEM 客户？这不会更新或重启客户节点。"
        : action === "publish"
        ? "确认向全部 " + releaseInstanceCount + " 个实例发布此版本？节点将在下一轮检查时自动安装。"
        : action === "rollback"
          ? "确认把全部 " + releaseInstanceCount + " 个实例回撤到 v" + (t.dataset.releaseVersion || "") + "？这会真实切换线上运行版本。"
        : action === "pause" && platformRelease
          ? "确认从全部 OEM 后台撤下这条 Nexus 平台公告？历史记录仍会保留。"
        : action === "pause"
          ? "确认暂停该版本？已经开始安装的节点不会被中断。"
          : action === "retry"
            ? "确认让该版本所有失败节点重新尝试一次？"
            : "确认把该版本推送到当前选中的灰度节点？";
      var dangerousReleaseAction = (action === "publish" && !platformRelease) || action === "rollback";
      var releaseOkText = action === "publish"
        ? (platformRelease ? "发布公告" : "确认全量发布")
        : (action === "rollback" ? "确认回撤" : "确认");
      uiConfirm(promptText, dangerousReleaseAction, releaseOkText).then(function (ok) {
        if (!ok) return;
        api("/nexus/admin/release_action", { body: body })
          .then(function () { toast("版本操作已生效"); loadAdmin(); })
          .catch(function (err) { toast(err.message, true); });
      });
      return;
    }
    if (t.dataset && t.dataset.revoke) {
      var revokeId = Number(t.dataset.revoke);
      uiPrompt("填写永久吊销 KEY #" + revokeId + " 的原因", "例如：授权替换 / KEY 泄露").then(function (reason) {
        if (reason === null) return;
        if (!reason.trim()) return toast("永久吊销必须填写原因", true);
        uiConfirm("确认永久吊销 KEY #" + revokeId + "？吊销后不可恢复。", true, "确认永久吊销").then(function (ok) {
          if (!ok) return;
          api("/nexus/admin/revoke", { body: { key_id: revokeId, reason: reason } })
            .then(function () { toast("已永久吊销"); loadAdmin(); })
            .catch(function (err) { toast(err.message, true); });
        });
      });
      return;
    }
    if (t.dataset && t.dataset.keyStatus) {
      var keyId = Number(t.dataset.keyId);
      var targetStatus = t.dataset.keyStatus;
      var statusText = targetStatus === "active" ? "恢复" : "暂停";
      uiPrompt(statusText + " KEY #" + keyId + " 的原因", "用于审计记录，可简要填写").then(function (reason) {
        if (reason === null) return;
        if (!reason.trim()) return toast(statusText + "操作必须填写原因", true);
        api("/nexus/admin/key_status", { body: { key_id: keyId, status: targetStatus, reason: reason } })
          .then(function () { toast("KEY 已" + statusText); loadAdmin(); })
          .catch(function (err) { toast(err.message, true); });
      });
      return;
    }
    if (t.dataset && t.dataset.topup) {
      var topupId = Number(t.dataset.topup);
      uiPrompt("给 " + t.dataset.domain + " 充值多少 token？", "如 100000000 = 1亿").then(function (v) {
        if (v === null || v === "") return;
        var n = Number(v);
        if (!(n > 0)) return toast("请输入正整数", true);
        api("/nexus/admin/topup", { body: { instance_id: topupId, tokens: n, note: "控制台手动充值" } })
          .then(function (r) { toast("充值成功，新余额 " + fmtTokens(r.balance_tokens)); loadAdmin(); })
          .catch(function (err) { toast(err.message, true); });
      });
    }
    if (t.dataset && t.dataset.buykey) {
      var licenseForm = $("#form-request");
      licenseForm.payment_method.value = "online";
      licenseForm.channel.value = t.dataset.buykey;
      syncLicensePaymentForm();
      openOemPage("licenses", false);
      // hashchange 与 hidden 切换需要一个渲染帧；延后滚动确保表单已经可见。
      setTimeout(function () {
        licenseForm.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 30);
      toast("请填写部署资料后创建在线支付订单");
      return;
    }
    if (t.dataset && t.dataset.buykeyTransfer) {
      var transferLicenseForm = $("#form-request");
      transferLicenseForm.payment_method.value = "corporate_transfer";
      syncLicensePaymentForm();
      openOemPage("licenses", false);
      setTimeout(function () {
        transferLicenseForm.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 30);
      toast("请填写下级 OEM 部署资料并上传企业转账凭证");
      return;
    }
    // 卡片选择切换（同组单选；点击可能落在卡片内部的 small 上,向上找到卡片本体）
    var pickBtn = t.closest ? t.closest(".pick[data-pick]") : null;
    if (pickBtn) {
      $all('.pick[data-pick="' + pickBtn.dataset.pick + '"]').forEach(function (el) { el.classList.remove("on"); });
      pickBtn.classList.add("on");
    }
    if (t.dataset && t.dataset.buytopup) {
      var pickInst = document.querySelector('.pick[data-pick="inst"].on');
      var pickPack = document.querySelector('.pick[data-pick="pack"].on');
      if (!pickInst || !pickPack) return toast("请先选择实例和套餐", true);
      placeOrder({
        kind: "topup",
        channel: t.dataset.buytopup,
        instance_id: Number(pickInst.dataset.val),
        pack_index: Number(pickPack.dataset.val),
      });
    }
    if (t.dataset && t.dataset.confirmTopupTransfer) {
      var topupOrderNo = t.dataset.confirmTopupTransfer;
      uiConfirm("确认银行已收到这笔 Token 充值款？确认后会立即给目标节点充值并记录 OEM 价差。", false, "确认到账并充值").then(function (ok) {
        if (!ok) return;
        api("/nexus/admin/topup_transfer_decide", { body: {
          order_no: topupOrderNo, approve: true, note: "已核对银行真实到账",
        } }).then(function () { toast("到账已确认，Token 已充值"); loadAdmin(); })
          .catch(function (error) { toast(error.message, true); });
      });
      return;
    }
    if (t.dataset && t.dataset.rejectTopupTransfer) {
      var rejectTopupOrderNo = t.dataset.rejectTopupTransfer;
      uiPrompt("拒绝这笔 Token 转账充值的原因", "例如：未查到到账 / 金额不符").then(function (reason) {
        if (reason === null || !reason.trim()) return toast("请填写拒绝原因", true);
        api("/nexus/admin/topup_transfer_decide", { body: {
          order_no: rejectTopupOrderNo, approve: false, note: reason,
        } }).then(function () { toast("充值转账已拒绝"); loadAdmin(); })
          .catch(function (error) { toast(error.message, true); });
      });
      return;
    }
    if (t.dataset && t.dataset.withdrawApprove) {
      api("/nexus/admin/withdrawal_decide", { body: {
        withdrawal_id: Number(t.dataset.withdrawApprove), action: "approve", note: "审核通过，等待线下打款",
      } }).then(function () { toast("提现已批准，请完成线下打款"); loadAdmin(); })
        .catch(function (error) { toast(error.message, true); });
      return;
    }
    if (t.dataset && t.dataset.withdrawPaid) {
      var paidWithdrawalId = Number(t.dataset.withdrawPaid);
      uiPrompt("填写线下打款流水号或付款备注", "必填，用于财务对账").then(function (reference) {
        if (reference === null || !reference.trim()) return toast("请填写打款流水号或备注", true);
        api("/nexus/admin/withdrawal_decide", { body: {
          withdrawal_id: paidWithdrawalId, action: "paid", note: reference,
        } }).then(function () { toast("提现已标记为已打款"); loadAdmin(); })
          .catch(function (error) { toast(error.message, true); });
      });
      return;
    }
    if (t.dataset && t.dataset.withdrawReject) {
      var rejectWithdrawalId = Number(t.dataset.withdrawReject);
      uiPrompt("填写驳回提现原因", "必填；驳回后金额自动退回可提现余额").then(function (reason) {
        if (reason === null || !reason.trim()) return toast("请填写驳回原因", true);
        api("/nexus/admin/withdrawal_decide", { body: {
          withdrawal_id: rejectWithdrawalId, action: "reject", note: reason,
        } }).then(function () { toast("提现已驳回，余额已退回"); loadAdmin(); })
          .catch(function (error) { toast(error.message, true); });
      });
      return;
    }
    if (t.dataset && t.dataset.confirmTransfer) {
      var transferRequestId = Number(t.dataset.confirmTransfer);
      uiConfirm("确认已在银行端核对该笔转账真实到账？确认后将计入营收并只签发一把 KEY。", false, "确认到账并签发").then(function (ok) {
        if (!ok) return;
        t.disabled = true;
        api("/nexus/admin/license_transfer_decide", {
          body: { request_id: transferRequestId, approve: true, note: "已核对银行真实到账" },
        }).then(function () {
          toast("企业转账已确认，KEY 等待 OEM 安全领取"); loadAdmin();
        }).catch(function (err) { t.disabled = false; toast(err.message, true); });
      });
      return;
    }
    if (t.dataset && t.dataset.rejectTransfer) {
      var rejectTransferId = Number(t.dataset.rejectTransfer);
      uiPrompt("拒绝这张转账凭证的原因（必填）", "例如：未查到到账 / 金额不符").then(function (reason) {
        if (reason === null || !reason.trim()) return toast("请填写拒绝原因", true);
        api("/nexus/admin/license_transfer_decide", {
          body: { request_id: rejectTransferId, approve: false, note: reason },
        }).then(function () { toast("转账凭证已拒绝"); loadAdmin(); })
          .catch(function (err) { toast(err.message, true); });
      });
      return;
    }
    if (t.dataset && t.dataset.approve) {
      var rid = t.dataset.approve;
      var grantInput = document.querySelector('input[data-grantfor="' + rid + '"]');
      var grant = grantInput ? Number(grantInput.value) || 0 : 0;
      uiConfirm("确认批准申请 #" + rid + " 并附赠 " + fmtTokens(grant) + " Token？系统只会签发一把 KEY。", false, "批准并签发").then(function (ok) {
        if (!ok) return;
        t.disabled = true;
        api("/nexus/admin/request_decide", { body: { request_id: Number(rid), action: "approve", approve: true, token_grant: grant } })
          .then(function () { toast("已批准，授权码等待对方安全领取"); loadAdmin(); })
          .catch(function (err) { t.disabled = false; toast(err.message, true); });
      });
      return;
    }
    if (t.dataset && t.dataset.needsInfo) {
      var infoId = Number(t.dataset.needsInfo);
      uiPrompt("需要申请人补充什么资料？", "例如：请确认计划部署域名").then(function (reason) {
        if (reason === null || !reason.trim()) return toast("请填写需要补充的资料", true);
        api("/nexus/admin/request_decide", { body: { request_id: infoId, action: "needs_info", decide_note: reason } })
          .then(function () { toast("已通知申请人补充资料"); loadAdmin(); })
          .catch(function (err) { toast(err.message, true); });
      });
      return;
    }
    if (t.dataset && t.dataset.reject) {
      var rejectId = Number(t.dataset.reject);
      uiPrompt("拒绝理由（会展示给申请人，必填）", "如：请先联系商务").then(function (reason) {
        if (reason === null) return; // 点了取消 = 中止，不是"空理由拒绝"
        if (!reason.trim()) return toast("拒绝申请必须填写原因", true);
        api("/nexus/admin/request_decide", { body: { request_id: rejectId, action: "reject", approve: false, decide_note: reason } })
          .then(function () { toast("已拒绝"); loadAdmin(); })
          .catch(function (err) { toast(err.message, true); });
      });
      return;
    }
    if (t.dataset && t.dataset.detail) {
      openDetail(Number(t.dataset.detail));
    }
    if (t.dataset && t.dataset.dlfile) {
      // 下载要带 Authorization 头,<a> 标签做不到 → fetch blob 转对象 URL
      var authD = getAuth();
      var fname = t.dataset.fname || "附件";
      fetch(new URL("/nexus/admin/oem_file/" + t.dataset.dlfile, window.location.origin).href, {
        headers: { "Authorization": "Bearer " + (authD ? authD.token : "") },
      }).then(function (res) {
        if (!res.ok) throw new Error("下载失败(" + res.status + ")");
        return res.blob();
      }).then(function (blob) {
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = fname;
        a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 5000);
      }).catch(function (err) { toast(err.message, true); });
    }
    if (t.dataset && t.dataset.delfile) {
      var delFileId = Number(t.dataset.delfile);
      uiConfirm("确认删除该附件？删除后不可恢复。", true, "确认删除").then(function (ok) {
        if (!ok) return;
        api("/nexus/admin/oem_file_delete", { body: { file_id: delFileId } })
          .then(function () { toast("已删除"); openDetail(detailOemId); })
          .catch(function (err) { toast(err.message, true); });
      });
    }
    if (t.dataset && t.dataset.oemstatus) {
      var to = t.dataset.tostatus;
      var statusOemId = Number(t.dataset.oemstatus);
      // 停用是打断客户使用的动作，要确认；启用无副作用直接放行
      var gate = to === "disabled"
        ? uiConfirm("确认停用 " + t.dataset.email + "？停用后其登录与已有会话立即失效（数据保留，可随时启用恢复）。", true, "确认停用")
        : Promise.resolve(true);
      gate.then(function (ok) {
        if (!ok) return;
        api("/nexus/admin/oem_status", { body: { oem_id: statusOemId, status: to } })
          .then(function () { toast(to === "disabled" ? "已停用" : "已启用"); loadAdmin(); })
          .catch(function (err) { toast(err.message, true); });
      });
    }
  });

  loadOemAuthConfig();
  route();
})();
