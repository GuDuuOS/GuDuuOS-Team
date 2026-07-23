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
    api("/nexus/oem/register", { body: {
      email: email, password: pw, inviter: f.inviter.value,
      company: f.company.value, contact_name: f.contact_name.value, phone: f.phone.value,
    }, noKick: true })
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
  var CH_ZH = { alipay: "支付宝", wechat: "微信支付", mock: "模拟支付(开发)" };
  function fmtYuan(cents) {
    var y = (Number(cents) || 0) / 100;
    return "¥" + (y % 1 ? y.toFixed(2) : String(y));
  }

  // 渲染「购买与充值」区（定价 + 渠道可用性 + 我的实例下拉）
  function renderShop(products, instances) {
    var pricing = products.pricing, ch = products.channels;
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
      $("#shop-key-desc").textContent = "附赠 " + fmtTokens(pricing.key_token_grant) + " token · 付款后授权码即时出码";
      $("#shop-key-btns").innerHTML = '<span class="shop-price">' + fmtYuan(pricing.key_price_cents) + "</span>" + chButtons("buykey");
    }
    $("#shop-topup").hidden = !topupOn;
    if (topupOn) {
      $("#topup-inst").innerHTML = instances.map(function (i) {
        return '<option value="' + i.id + '">' + esc(i.domain) + "（余额 " + fmtTokens(i.balance_tokens) + "）</option>";
      }).join("");
      $("#topup-pack").innerHTML = pricing.topup_packs.map(function (p, idx) {
        return '<option value="' + idx + '">' + fmtTokens(p.tokens) + " token · " + fmtYuan(p.cents) + "</option>";
      }).join("");
      $("#shop-topup-btns").innerHTML = chButtons("buytopup");
    }
    $("#shop-none").hidden = keyOn || topupOn;
  }

  // 渲染「我的订单」
  var ORDER_ST = { pending: ["warning", "待支付"], paid: ["active", "已支付"], closed: ["idle", "已关闭"] };
  function renderOrders(orders) {
    $("#panel-orders").hidden = orders.length === 0;
    $("#oem-orders tbody").innerHTML = orders.map(function (o) {
      var st = ORDER_ST[o.status] || ["idle", o.status];
      var what = o.kind === "key" ? "授权码 ×1" : "充值 " + fmtTokens(o.tokens) + "（实例 #" + o.instance_id + "）";
      var keyCell = o.key ? '<b style="user-select:all">' + esc(o.key) + "</b>"
        : (o.kind === "key" && o.status === "paid" ? '<span class="zh">已使用</span>' : "—");
      return "<tr><td>" + esc(o.order_no) + '</td><td class="zh">' + what + "</td><td>" + fmtYuan(o.amount_cents) + "</td>" +
        '<td class="zh">' + (CH_ZH[o.channel] || o.channel) + '</td><td class="zh"><span class="badge ' + st[0] + '">' + st[1] + "</span></td>" +
        "<td>" + keyCell + "</td><td>" + fmtTime(o.created_ts) + "</td></tr>";
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
    Promise.all([api("/nexus/oem/me"), api("/nexus/oem/products")]).then(function (rs) {
      var r = rs[0];
      renderShop(rs[1], r.instances);
      renderOrders(r.orders || []);
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
      // 申请单列表（approved 且未装机时展示明文——即交付通道；装机后明文被服务端清空）
      var reqs = r.requests || [];
      var REQ_ZH = { pending: "待处理", approved: "已批准", rejected: "已拒绝" };
      var REQ_CLS = { pending: "warning", approved: "active", rejected: "revoked" };
      $("#oem-requests").hidden = reqs.length === 0;
      $("#oem-requests tbody").innerHTML = reqs.map(function (q) {
        var keyCell = q.key
          ? '<b style="user-select:all">' + esc(q.key) + "</b>"
          : (q.status === "approved" ? '<span class="zh">已使用（实例开通）</span>' : "—");
        return "<tr><td>#" + q.id + '</td><td class="zh"><span class="badge ' + (REQ_CLS[q.status] || "idle") + '">' + (REQ_ZH[q.status] || q.status) + "</span>" +
          (q.status === "rejected" && q.decide_note ? '<div class="hint">' + esc(q.decide_note) + "</div>" : "") + "</td>" +
          '<td class="zh">' + esc(q.note || "—") + "</td><td>" + keyCell + "</td><td>" + fmtTime(q.created_ts) + "</td></tr>";
      }).join("");
    }).catch(function (err) { toast(err.message, true); });
  }

  $("#form-request").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    api("/nexus/oem/request_key", { body: { note: f.note.value } })
      .then(function () { toast("申请已提交，等待平台处理"); f.reset(); loadOem(); })
      .catch(function (err) { toast(err.message, true); });
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
  function loadAdmin() {
    Promise.all([
      api("/nexus/admin/instances"),
      api("/nexus/admin/keys"),
      api("/nexus/admin/oems"),
      api("/nexus/admin/requests"),
      api("/nexus/admin/pricing"),
      api("/nexus/admin/orders"),
    ]).then(function (rs) {
      var insts = rs[0].instances, keys = rs[1].keys, oems = rs[2].oems;
      var reqs = rs[3].requests || [];
      var pricing = rs[4].pricing, orders = rs[5].orders || [];

      // 定价表单回填（仅在超管未编辑时覆盖,避免打字被刷新冲掉）
      var pf = $("#form-pricing");
      if (document.activeElement === null || !pf.contains(document.activeElement)) {
        pf.key_yuan.value = (pricing.key_price_cents / 100) || 0;
        pf.key_grant.value = pricing.key_token_grant;
        if (document.activeElement !== $("#pricing-packs")) {
          $("#pricing-packs").value = pricing.topup_packs.map(function (p) {
            return (p.cents / 100) + ":" + p.tokens;
          }).join("\n");
        }
      }

      // 订单表（超管全量;无单隐藏）
      $("#panel-admin-orders").hidden = orders.length === 0;
      var oemEmailById = {};
      oems.forEach(function (o) { oemEmailById[o.id] = o.email; });
      $("#admin-orders tbody").innerHTML = orders.map(function (o) {
        var st = ORDER_ST[o.status] || ["idle", o.status];
        var what = o.kind === "key" ? "授权码" : "充值 " + fmtTokens(o.tokens);
        return "<tr><td>" + esc(o.order_no) + "</td><td>" + esc(oemEmailById[o.oem_id] || "#" + o.oem_id) + "</td>" +
          '<td class="zh">' + what + "</td><td>" + fmtYuan(o.amount_cents) + '</td><td class="zh">' + (CH_ZH[o.channel] || o.channel) + "</td>" +
          '<td class="zh"><span class="badge ' + st[0] + '">' + st[1] + "</span></td><td>" + fmtTime(o.created_ts) + "</td></tr>";
      }).join("");

      // 待处理申请（无申请时整个面板隐藏，不占版面）
      $("#panel-requests").hidden = reqs.length === 0;
      $("#admin-requests tbody").innerHTML = reqs.map(function (q) {
        return "<tr><td>#" + q.id + "</td><td>" + esc(q.oem_email) + '</td><td class="zh">' + esc(q.note || "—") + "</td>" +
          "<td>" + fmtTime(q.created_ts) + "</td>" +
          '<td class="zh"><input type="number" min="0" value="100000000" style="width:130px" data-grantfor="' + q.id + '" title="附赠 token" /></td>' +
          '<td class="zh"><button class="ghost small" data-approve="' + q.id + '">批准签发</button> ' +
          '<button class="ghost small" data-reject="' + q.id + '">拒绝</button></td></tr>';
      }).join("");

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

      // OEM 客户表（自助注册模式：超管唯一管控 = 停用/启用；账号状态用"正常/停用"措辞）
      $("#admin-oems tbody").innerHTML = oems.map(function (o) {
        var on = o.status === "active";
        // 邀请人列：平台直属显示 GuDuu(橙),下线显示上线邮箱——分销层级一眼可辨
        var inviter = o.inviter === "GuDuu"
          ? '<span style="color:var(--orange)">GuDuu</span>'
          : esc(o.inviter || "—");
        return "<tr><td>#" + o.id + "</td><td>" + esc(o.email) + "</td><td class=\"zh\">" + esc(o.name || "—") + "</td>" +
          "<td>" + inviter + "</td>" +
          '<td class="zh"><span class="badge ' + (on ? "active" : "disabled") + '">' + (on ? "正常" : "停用") + "</span></td>" +
          "<td>" + o.keys_claimed + "</td><td>" + fmtTime(o.created_ts) + "</td>" +
          '<td class="zh"><button class="ghost small" data-detail="' + o.id + '">详情</button> ' +
          '<button class="ghost small" data-oemstatus="' + o.id + '" data-tostatus="' + (on ? "disabled" : "active") + '" data-email="' + esc(o.email) + '">' + (on ? "停用" : "启用") + "</button></td></tr>";
      }).join("") || '<tr><td colspan="8" class="zh empty">暂无注册客户</td></tr>';
    }).catch(function (err) { toast(err.message, true); });
  }

  $("#btn-refresh").addEventListener("click", loadAdmin);

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

  // 定价保存：packs 文本每行 "元:token"，空行忽略；格式错就地报错不提交
  $("#form-pricing").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    var packs = [];
    var lines = $("#pricing-packs").value.split("\n");
    for (var i = 0; i < lines.length; i++) {
      var ln = lines[i].trim();
      if (!ln) continue;
      var m = ln.split(":");
      var yuan = Number(m[0]), tokens = Number(m[1]);
      if (m.length !== 2 || !(yuan > 0) || !(tokens > 0)) {
        return toast("充值包第 " + (i + 1) + " 行格式应为 元:token数（如 99:50000000）", true);
      }
      packs.push({ cents: Math.round(yuan * 100), tokens: tokens });
    }
    api("/nexus/admin/pricing", {
      body: {
        key_price_cents: Math.round(Number(f.key_yuan.value || 0) * 100),
        key_token_grant: Number(f.key_grant.value || 0),
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
    if (t.dataset && t.dataset.buykey) {
      placeOrder({ kind: "key", channel: t.dataset.buykey });
    }
    if (t.dataset && t.dataset.buytopup) {
      placeOrder({
        kind: "topup",
        channel: t.dataset.buytopup,
        instance_id: Number($("#topup-inst").value),
        pack_index: Number($("#topup-pack").value),
      });
    }
    if (t.dataset && t.dataset.approve) {
      var rid = t.dataset.approve;
      var grantInput = document.querySelector('input[data-grantfor="' + rid + '"]');
      var grant = grantInput ? Number(grantInput.value) || 0 : 0;
      api("/nexus/admin/request_decide", { body: { request_id: Number(rid), approve: true, token_grant: grant } })
        .then(function () { toast("已批准，授权码已交付到对方门户"); loadAdmin(); })
        .catch(function (err) { toast(err.message, true); });
    }
    if (t.dataset && t.dataset.reject) {
      var reason = prompt("拒绝理由（会展示给申请人，可留空）");
      if (reason === null) return; // 点了取消 = 中止，不是"空理由拒绝"
      api("/nexus/admin/request_decide", { body: { request_id: Number(t.dataset.reject), approve: false, decide_note: reason } })
        .then(function () { toast("已拒绝"); loadAdmin(); })
        .catch(function (err) { toast(err.message, true); });
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
      if (!confirm("确认删除该附件？删除后不可恢复。")) return;
      api("/nexus/admin/oem_file_delete", { body: { file_id: Number(t.dataset.delfile) } })
        .then(function () { toast("已删除"); openDetail(detailOemId); })
        .catch(function (err) { toast(err.message, true); });
    }
    if (t.dataset && t.dataset.oemstatus) {
      var to = t.dataset.tostatus;
      // 停用是打断客户使用的动作，要确认；启用无副作用直接放行
      if (to === "disabled" && !confirm("确认停用 " + t.dataset.email + "？停用后其登录与已有会话立即失效（数据保留，可随时启用恢复）。")) return;
      api("/nexus/admin/oem_status", { body: { oem_id: Number(t.dataset.oemstatus), status: to } })
        .then(function () { toast(to === "disabled" ? "已停用" : "已启用"); loadAdmin(); })
        .catch(function (err) { toast(err.message, true); });
    }
  });

  // ---------- 大屏链接带上 dash token（超管令牌也能看大屏） ----------
  var auth0 = getAuth();
  if (auth0 && auth0.mode === "admin") $("#nav-dash").href = "/#token=" + encodeURIComponent(auth0.token);

  route();
})();
