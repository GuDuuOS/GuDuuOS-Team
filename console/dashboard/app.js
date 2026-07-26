(() => {
  "use strict";

  const $ = (selector, scope = document) => scope.querySelector(selector);
  const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];

  const OEMS = [
    {
      id: "sg",
      name: "星河智算",
      code: "SG-01",
      initials: "SG",
      color: "#8b7cff",
      accent: "#c0b7ff",
      x: 0.22,
      y: 0.24,
      z: -0.22,
      size: 18,
      token: 5.82,
      today: 2.61,
      requests: "2.61M",
      latency: "0.82s",
      delta: 18.2,
      status: "active",
      models: 4,
      region: "华东 · CN-East-01",
      orbit: 1,
    },
    {
      id: "cz",
      name: "云舟科技",
      code: "CZ-07",
      initials: "CZ",
      color: "#35d9ff",
      accent: "#abf2ff",
      x: 0.78,
      y: 0.23,
      z: 0.18,
      size: 16,
      token: 3.96,
      today: 2.18,
      requests: "2.18M",
      latency: "1.04s",
      delta: 12.6,
      status: "warning",
      models: 3,
      region: "华南 · CN-South-02",
      orbit: 1,
    },
    {
      id: "nb",
      name: "Nebula One",
      code: "NB-03",
      initials: "NB",
      color: "#ff7aa5",
      accent: "#ffc3d7",
      x: 0.84,
      y: 0.56,
      z: -0.34,
      size: 14,
      token: 3.41,
      today: 1.94,
      requests: "1.94M",
      latency: "1.36s",
      delta: 8.4,
      status: "warning",
      models: 3,
      region: "北美 · US-West-01",
      orbit: 2,
    },
    {
      id: "gl",
      name: "引力工场",
      code: "GL-12",
      initials: "GL",
      color: "#57e6a5",
      accent: "#b2ffd9",
      x: 0.71,
      y: 0.78,
      z: 0.32,
      size: 15,
      token: 3.08,
      today: 1.72,
      requests: "1.72M",
      latency: "0.94s",
      delta: 21.7,
      status: "active",
      models: 5,
      region: "华北 · CN-North-01",
      orbit: 2,
    },
    {
      id: "ly",
      name: "光年智能",
      code: "LY-09",
      initials: "LY",
      color: "#ffb65c",
      accent: "#ffe1b6",
      x: 0.34,
      y: 0.79,
      z: 0.08,
      size: 14,
      token: 2.74,
      today: 1.45,
      requests: "1.45M",
      latency: "1.11s",
      delta: 6.9,
      status: "active",
      models: 3,
      region: "新加坡 · AP-SG-01",
      orbit: 2,
    },
    {
      id: "db",
      name: "深蓝数据",
      code: "DB-05",
      initials: "DB",
      color: "#5ca8ff",
      accent: "#b7d9ff",
      x: 0.14,
      y: 0.61,
      z: -0.3,
      size: 13,
      token: 2.33,
      today: 1.27,
      requests: "1.27M",
      latency: "1.29s",
      delta: -3.2,
      status: "offline",
      models: 2,
      region: "欧洲 · EU-West-01",
      orbit: 2,
    },
    {
      id: "hy",
      name: "寰宇引擎",
      code: "HY-11",
      initials: "HY",
      color: "#a96cff",
      accent: "#dbbaff",
      x: 0.58,
      y: 0.16,
      z: 0.4,
      size: 11,
      token: 2.05,
      today: 1.08,
      requests: "1.08M",
      latency: "0.76s",
      delta: 14.3,
      status: "active",
      models: 4,
      region: "日本 · AP-TK-01",
      orbit: 1,
    },
    {
      id: "px",
      name: "极星云",
      code: "PX-08",
      initials: "PX",
      color: "#52dfd0",
      accent: "#b8fff7",
      x: 0.48,
      y: 0.88,
      z: -0.14,
      size: 11,
      token: 1.47,
      today: 0.86,
      requests: "860K",
      latency: "0.91s",
      delta: 9.8,
      status: "active",
      models: 2,
      region: "香港 · CN-HK-01",
      orbit: 2,
    },
  ];

  const BIRTH_CANDIDATES = [
    {
      name: "Aurora Labs",
      code: "AR-16",
      initials: "AR",
      color: "#70f0c0",
      accent: "#c0ffe7",
      x: 0.9,
      y: 0.38,
      z: 0.24,
      size: 12,
      token: 0.06,
      today: 0.04,
      requests: "42K",
      latency: "1.18s",
      delta: 100,
      status: "active",
      models: 1,
      region: "北欧 · EU-North-01",
      orbit: 2,
    },
    {
      name: "熵序智能",
      code: "EX-18",
      initials: "EX",
      color: "#ff8d69",
      accent: "#ffd0c0",
      x: 0.09,
      y: 0.38,
      z: -0.18,
      size: 12,
      token: 0.04,
      today: 0.03,
      requests: "31K",
      latency: "1.24s",
      delta: 100,
      status: "active",
      models: 1,
      region: "华中 · CN-Central-01",
      orbit: 2,
    },
    {
      name: "Prism AI",
      code: "PA-21",
      initials: "PA",
      color: "#f191ff",
      accent: "#facdff",
      x: 0.63,
      y: 0.9,
      z: 0.35,
      size: 12,
      token: 0.03,
      today: 0.02,
      requests: "18K",
      latency: "1.08s",
      delta: 100,
      status: "active",
      models: 1,
      region: "澳洲 · AP-SYD-01",
      orbit: 2,
    },
  ];

  const MAP_HOTSPOT_DEFINITIONS = [
    {
      id: "nb",
      coordinates: [-87.6298, 41.8781],
      fallback: [188, 165],
      radius: 58,
      core: "#d34f66",
      mid: ["#c65b9f", "#8e62d9"],
      outer: ["#7368e5", "#586ddd", "#aaa5ee"],
    },
    {
      id: "db",
      coordinates: [13.405, 52.52],
      fallback: [520, 130],
      radius: 57,
      core: "#d74e69",
      mid: ["#c958a2", "#a85dd4"],
      outer: ["#7368e5", "#5572df", "#aaa5ee"],
    },
    {
      id: "gl",
      coordinates: [31.2357, 30.0444],
      fallback: [558, 205],
      radius: 55,
      core: "#dc526b",
      mid: ["#d35d91", "#b45fd4"],
      outer: ["#7668e0", "#a6a0eb", "#e787a0"],
    },
    {
      id: "sg",
      coordinates: [121.4737, 31.2304],
      fallback: [820, 190],
      radius: 58,
      core: "#d94d69",
      mid: ["#ce5796", "#a85ed5"],
      outer: ["#7466e3", "#5e73dd", "#aaa4ee"],
    },
    {
      id: "cz",
      coordinates: [113.2644, 23.1291],
      fallback: [797, 218],
      radius: 48,
      core: "#35c9ec",
      mid: ["#4fbbe8", "#667fe3"],
      outer: ["#7771df", "#8cddea", "#b7c8ef"],
    },
    {
      id: "ly",
      coordinates: [103.8198, 1.3521],
      fallback: [766, 268],
      radius: 49,
      core: "#f3a04e",
      mid: ["#ed8068", "#d56c9d"],
      outer: ["#8c6edf", "#c66ac2", "#d9b3e8"],
    },
    {
      id: "px",
      coordinates: [-46.6333, -23.5505],
      fallback: [318, 350],
      radius: 57,
      core: "#f39a49",
      mid: ["#ef785f", "#da6588"],
      outer: ["#8b68df", "#c45ebc", "#b4acec"],
    },
    {
      id: "hy",
      coordinates: [151.2093, -33.8688],
      fallback: [858, 372],
      radius: 57,
      core: "#46bddf",
      mid: ["#5d9de5", "#5d84e7"],
      outer: ["#6b6bdd", "#78d1e6", "#b4c6f0"],
    },
  ];

  const GLOBAL_MAP_CONFIG = {
    nodeIds: ["nb", "db", "gl", "sg", "cz", "ly", "px", "hy"],
    calloutCount: 6,
    viewBox: "0 0 1000 480",
  };
  const MAP_CALLOUT_CONFLICTS = new Set(["cz:gl"]);

  const VISUAL_MODES = {
    global: {
      kind: "map",
      eyebrow: "GLOBAL DISTRIBUTION",
      title: "OEM 全球节点网络",
    },
    universe: {
      kind: "universe",
      eyebrow: "OEM CONSTELLATION",
      title: "OEM 3D 星系网络",
    },
  };

  const state = {
    nodes: OEMS.map((node) => ({ ...node })),
    selectedId: "sg",
    drawerTrigger: null,
    hoveredId: null,
    filter: "all",
    visualMode: "global",
    running: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    birthIndex: 0,
    birth: null,
    width: 0,
    height: 0,
    dpr: Math.min(window.devicePixelRatio || 1, 2),
    stars: [],
    particles: [],
    projectedNodes: [],
    mapHotspots: [],
    mapScene: null,
    mapCalloutIds: [],
    overviewSlide: 0,
    lastRenderTime: 0,
    sphereRotation: 0.22,
    coreRotation: 0.58,
    camera: {
      yaw: -0.1,
      pitch: -0.14,
      zoom: 1,
      targetZoom: 1,
      velocityYaw: 0,
      velocityPitch: 0,
      dragging: false,
      moved: false,
      pointerId: null,
      startX: 0,
      startY: 0,
      lastX: 0,
      lastY: 0,
    },
  };

  const canvas = $("#universe-canvas");
  const ctx = canvas.getContext("2d");
  const trendCanvas = $("#trend-canvas");
  const trendCtx = trendCanvas.getContext("2d");
  const canvasFontFamily = getComputedStyle(document.body).fontFamily;
  const TAU = Math.PI * 2;
  const CAMERA_PITCH_LIMIT = 1.05;
  const OVERVIEW_AUTOPLAY_DELAY = 5200;
  const UNIVERSE_FRAME_INTERVAL = 1000 / 30;
  let overviewCarouselTimer = 0;
  let universeFrameId = 0;
  let lastUniverseFrame = 0;

  // ══════════ GuDuu Nexus 真实数据适配层 ══════════
  // 起屏时从 Nexus fleet 服务拉真实舰队数据（GET /nexus/dash/summary）。
  // 鉴权：只读大屏令牌经 URL 井号参数传入一次（https://<域名>/#token=xxx），
  // 记入 localStorage 后地址栏可清掉。拉不到数据 = 静默保持演示数据（原型模式）。
  const TOKEN_UNIT = { div: 1e9, label: "B" }; // 演示默认 B；真实模式按量级自适应

  function dashToken() {
    const fromHash = (window.location.hash.match(/token=([^&]+)/) || [])[1] || "";
    if (fromHash) {
      try { window.localStorage.setItem("nexus_dash_token", fromHash); } catch { /* 隐私模式忽略 */ }
      return fromHash;
    }
    try { return window.localStorage.getItem("nexus_dash_token") || ""; } catch { return ""; }
  }

  // djb2 哈希：域名 → 确定性视觉参数（颜色/星球坐标每次打开都一致，不乱跳）
  function hashSeed(text) {
    let h = 5381;
    for (let i = 0; i < text.length; i += 1) h = ((h << 5) + h + text.charCodeAt(i)) >>> 0;
    return h;
  }

  const REAL_PALETTE = [
    ["#8b7cff", "#c0b7ff"], ["#35d9ff", "#abf2ff"], ["#ff7aa5", "#ffc3d7"],
    ["#57e6a5", "#b2ffd9"], ["#ffb65c", "#ffe1b6"], ["#5ca8ff", "#b7d9ff"],
  ];

  /** 经纬度 → 大屏地图归一化坐标(0~1)。等距圆柱投影(Equirectangular)：
   *  x = (lon+180)/360，y = (90-lat)/180。与底图 land-110m 的常规绘制方式一致。
   *  没有真实地域的实例回落到按域名哈希的稳定伪随机位（刷新不乱跳），并标出来。 */
  function projectNode(o, rand) {
    // ⚠️ 必须先排除 null/undefined：Number(null) === 0（不是 NaN），
    // 否则"没填地域"的实例会被当成经纬度 (0,0)，画到几内亚湾的 Null Island 上去。
    const lat = o.lat === null || o.lat === undefined ? NaN : Number(o.lat);
    const lon = o.lon === null || o.lon === undefined ? NaN : Number(o.lon);
    if (Number.isFinite(lat) && Number.isFinite(lon)) {
      return {
        x: (lon + 180) / 360,
        y: (90 - lat) / 180,
        z: 0,
      };
    }
    return { x: 0.12 + rand() * 0.76, y: 0.14 + rand() * 0.66, z: rand() * 0.7 - 0.35 };
  }

  // 把 Nexus 返回的一个实例映射成大屏节点（字段形态与演示 OEMS 完全一致）
  function adaptOem(o, index) {
    const seed = hashSeed(o.domain || String(o.id));
    const rand = mulberry32(seed);
    const [color, accent] = REAL_PALETTE[seed % REAL_PALETTE.length];
    // 展示名取域名里最有辨识度的一段：首段是 im/chat 这类通用词时用第二段
    const labels = String(o.domain || `实例${o.id}`).split(".");
    const generic = new Set(["im", "chat", "app", "www", "hub", "api"]);
    const shortName = generic.has(labels[0]) && labels[1] ? labels[1] : labels[0];
    return {
      id: `nx-${o.id}`,
      name: shortName,
      code: `NX-${String(o.id).padStart(2, "0")}`,
      initials: shortName.slice(0, 2).toUpperCase(),
      color,
      accent,
      // 地图点位：有真实地域(母舰按 OEM 兑码时选的机房算出经纬度)就按经纬度投影；
      // 没填地域的实例回落到伪随机位（按域名哈希，位置稳定不乱跳），并标 geoKnown=false
      // 供上层区分——绝不把"没数据"画成"在某地"。
      ...projectNode(o, rand),
      size: 13 + Math.min(7, Math.round(Math.log10(1 + (o.tokens_total || 0) / 1e3))),
      token: Number(((o.tokens_total || 0) / TOKEN_UNIT.div).toFixed(2)),
      today: Number(((o.tokens_today || 0) / TOKEN_UNIT.div).toFixed(2)),
      requests: (o.requests_today || 0).toLocaleString("en-US"),
      // 平均延迟:网关已按分钟桶采集(fleet.record_request);无请求时为 null → 显示「—」
      latency: Number.isFinite(Number(o.avg_latency_ms))
        ? `${(Number(o.avg_latency_ms) / 1000).toFixed(2)}s`
        : "—",
      delta: Number(o.delta_pct || 0),
      status: o.status || "offline",
      models: o.models_today || 0,
      // 地域展示：优先真实地域名，没有就退回域名（旧行为）
      region: o.region_label || o.domain || "",
      regionCode: o.region || "",
      successPct: o.success_pct === null || o.success_pct === undefined ? null : Number(o.success_pct),
      avgLatencyMs: o.avg_latency_ms === null || o.avg_latency_ms === undefined ? null : Number(o.avg_latency_ms),
      peakPerMin: Number(o.peak_per_min || 0),
      geoKnown: o.lat !== null && o.lat !== undefined
        && o.lon !== null && o.lon !== undefined
        && Number.isFinite(Number(o.lat)) && Number.isFinite(Number(o.lon)),
      lat: o.lat === null || o.lat === undefined ? null : Number(o.lat),
      lon: o.lon === null || o.lon === undefined ? null : Number(o.lon),
      orbit: (index % 3) + 1,
      balance: o.balance_tokens || 0,
      users: o.users || 0,
    };
  }

  function applySummary(data) {
    const list = Array.isArray(data && data.oems) ? data.oems : [];
    if (!list.length) return false;
    // 单位自适应：让最大节点的读数落在人眼舒服的量级（K/M/B）
    const peak = Math.max(...list.map((o) => o.tokens_total || 0), 1);
    if (peak >= 1e9) { TOKEN_UNIT.div = 1e9; TOKEN_UNIT.label = "B"; }
    else if (peak >= 1e6) { TOKEN_UNIT.div = 1e6; TOKEN_UNIT.label = "M"; }
    else { TOKEN_UNIT.div = 1e3; TOKEN_UNIT.label = "K"; }
    const mapped = list.map((o, i) => adaptOem(o, i));
    OEMS.length = 0;
    OEMS.push(...mapped);
    state.nodes = mapped.map((node) => ({ ...node }));
    state.selectedId = mapped[0].id;
    // 面板接管（环比/趋势/模型分布/动态/角标/健康分/隐藏演示件）
    applyRealPanels(data);
    return true;
  }

  async function fetchSummary() {
    const token = dashToken();
    if (!token) return null;
    const res = await fetch("/nexus/dash/summary", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return null;
    return res.json();
  }

  async function loadFleetData() {
    try {
      const data = await fetchSummary();
      return data ? applySummary(data) : false;
    } catch {
      return false;
    }
  }

  // 真实模式下每 30 秒静默刷新数字（不重建场景防闪烁）；节点数变了才整页重载
  function startFleetRefresh() {
    window.setInterval(async () => {
      try {
        const data = await fetchSummary();
        const list = Array.isArray(data && data.oems) ? data.oems : [];
        if (!list.length) return;
        if (list.length !== state.nodes.length) {
          window.location.reload();
          return;
        }
        list.forEach((o, i) => {
          const fresh = adaptOem(o, i);
          const node = state.nodes.find((n) => n.id === fresh.id);
          if (!node) return;
          Object.assign(node, {
            token: fresh.token, today: fresh.today, requests: fresh.requests,
            delta: fresh.delta, status: fresh.status, models: fresh.models,
            balance: fresh.balance, users: fresh.users,
          });
          const base = OEMS.find((n) => n.id === node.id);
          if (base) Object.assign(base, node);
        });
        refreshTotals();
        renderRanking();
        applyRealPanels(data);
      } catch { /* 网络抖动静默,下轮再试 */ }
    }, 30000);
  }
  // —— 真实模式的面板接管：把演示件逐个换成母舰数据 / 无数据源的演示件隐藏 ——
  let REAL_SUMMARY = null;   // 最近一次 summary（refreshTotals/drawTrend 的真实分支用）
  let REAL_TREND = null;     // 近 24 小时逐小时消耗序列

  function fmtTokens(n) {
    const v = Math.abs(Number(n) || 0);
    if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
    if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
    if (v >= 1e3) return `${(v / 1e3).toFixed(2)}K`;
    return String(v);
  }

  function relTime(ts) {
    const d = Date.now() - (Number(ts) || 0);
    if (d < 60e3) return "刚刚";
    if (d < 3600e3) return `${Math.floor(d / 60e3)} 分钟前`;
    if (d < 86400e3) return `${Math.floor(d / 3600e3)} 小时前`;
    return `${Math.floor(d / 86400e3)} 天前`;
  }

  // 模型用量分布：环图 + 图例（数据=网关流水按模型聚合；空数据给诚实占位）
  function renderModelDist(models, todayTotal) {
    const donut = $("#model-donut");
    const legend = $("#model-legend");
    const totalEl = $("#model-total");
    if (!donut || !legend || !totalEl) return;
    const totalTxt = fmtTokens(todayTotal);
    totalEl.innerHTML = /[KMB]$/.test(totalTxt)
      ? `${totalTxt.slice(0, -1)}<em>${totalTxt.slice(-1)}</em>`
      : totalTxt;
    if (!models.length) {
      donut.style.background = "conic-gradient(rgba(139,124,255,0.16) 0 100%)";
      legend.innerHTML =
        '<div><i style="--dot-color:#8b7cff"></i><span>今日暂无 AI 调用</span><strong>—</strong></div>';
      return;
    }
    const palette = ["#8b7cff", "#35d9ff", "#57e6a5", "#ffb65c", "#ff7aa5", "#5ca8ff", "#c0b7ff", "#abf2ff"];
    const sum = models.reduce((s, m) => s + (m.tokens || 0), 0) || 1;
    let acc = 0;
    const stops = [];
    legend.innerHTML = models
      .map((m, i) => {
        const pct = ((m.tokens || 0) / sum) * 100;
        const color = palette[i % palette.length];
        stops.push(`${color} ${acc.toFixed(2)}% ${(acc + pct).toFixed(2)}%`);
        acc += pct;
        const name = String(m.model || "").split("/").pop() || m.model;
        return `<div><i style="--dot-color:${color}"></i><span>${name}</span><strong>${pct.toFixed(1)}%</strong></div>`;
      })
      .join("");
    donut.style.background = `conic-gradient(${stops.join(",")})`;
  }

  // 实时动态：母舰最近流水（消耗/充值/开通）
  function renderRecent(recent) {
    const list = $("#activity-list");
    if (!list || !recent.length) return;
    list.innerHTML = recent
      .slice(0, 4)
      .map((r) => {
        const name = String(r.domain || "").split(".")[0] || r.domain || "?";
        const amount = fmtTokens(r.tokens);
        const what =
          r.kind === "usage" ? `消耗 ${amount} tokens`
          : r.kind === "topup" ? `充值 ${amount} tokens`
          : r.kind === "grant" ? `开通并获赠 ${amount} tokens`
          : r.kind;
        const model =
          r.kind === "usage" && r.note
            ? ` · ${String(r.note).split(" ")[0].split("/").pop()}`
            : "";
        return `<article><span class="activity-icon activity-icon--success"><svg viewBox="0 0 20 20"><path d="M10 4v12M4 10h12"></path></svg></span><div><p><strong>${name}</strong> ${what}</p><small>${relTime(r.ts)}${model}</small></div></article>`;
      })
      .join("");
  }

  // 按可见文本换标签（演示文案→真实口径；只在真实模式调用）
  function swapLabelText(from, to) {
    $$(".overview-carousel span, .overview-carousel small, .overview-carousel p").forEach((el) => {
      if (el.childElementCount === 0 && el.textContent.trim() === from) el.textContent = to;
    });
  }

  function applyRealPanels(data) {
    REAL_SUMMARY = data;
    const tt = data.totals || {};
    // ① 环比：今日 vs 昨日（昨日为 0 显示 —，不伪造涨幅）
    const hasYesterday = (tt.tokens_yesterday || 0) > 0;
    const deltaNum = hasYesterday
      ? ((tt.tokens_today - tt.tokens_yesterday) / tt.tokens_yesterday) * 100
      : null;
    const deltaTxt = deltaNum === null ? "—" : `${deltaNum >= 0 ? "+" : ""}${deltaNum.toFixed(1)}%`;
    for (const sel of ["#total-delta", "#today-delta", "#map-traffic-delta"]) {
      const el = $(sel);
      if (el) el.textContent = deltaTxt;
    }
    // ② "今日预估成本"（演示）→ 今日调用（真实计量）
    const lb = $("#today-second-label"); if (lb) lb.textContent = "今日调用";
    const val = $("#today-second-value");
    if (val) val.textContent = `${(tt.requests_today || 0).toLocaleString("en-US")} 次`;
    const meta = $("#today-second-meta"); if (meta) meta.textContent = "经网关计量";
    // ③ 24 小时趋势（真实小时桶）+ 峰值
    REAL_TREND = (data.hourly || []).map((h) => h.tokens || 0);
    const peakEl = $("#trend-peak");
    if (peakEl) peakEl.textContent = `峰值 ${fmtTokens(Math.max(0, ...REAL_TREND))} / h`;
    resizeTrend();
    // ④ 模型分布 & ⑤ 实时动态
    renderModelDist(data.models || [], tt.tokens_today || 0);
    renderRecent(data.recent || []);
    // ⑥ 地图三角标：接入实例 / 今日调用 / 实例在线率
    const region = $("#map-region-label");
    if (region) region.innerHTML = `接入实例<strong id="map-region-value">${tt.instances || 0}</strong>`;
    const rps = $("#map-rps-label");
    if (rps) rps.innerHTML = `今日调用<strong id="map-rps-value">${(tt.requests_today || 0).toLocaleString("en-US")}</strong>`;
    const avail = $("#map-availability-label");
    const onlinePct = tt.instances ? (tt.online / tt.instances) * 100 : 0;
    if (avail) avail.innerHTML = `实例在线率<strong id="map-availability-value">${onlinePct.toFixed(1)}%</strong>`;
    // ⑦ 底部流量条数字 → 今日网关调用
    const tl = $("#map-traffic-label"); if (tl) tl.textContent = "GATEWAY CALLS";
    const tv = $("#map-traffic-value");
    if (tv) {
      tv.textContent = (tt.requests_today || 0).toLocaleString("en-US");
      const em = tv.parentElement && tv.parentElement.querySelector("em");
      if (em) em.textContent = "次 · 今日";
    }
    const tstat = $("#map-traffic-status"); if (tstat) tstat.textContent = `${tt.online || 0} 实例在线`;
    // ⑧ 轮播"今日收入"页 → 钱包余额合计（真实）
    const rev = $("#total-revenue");
    if (rev) {
      rev.textContent = fmtTokens(tt.balance_total || 0);
      const dollar = rev.parentElement && rev.parentElement.querySelector("span");
      if (dollar) dollar.textContent = "◎";
    }
    swapLabelText("今日收入", "钱包余额合计");
    // ⑨ 健康分：真实=在线率（不再演示 98.7）
    const scoreEl = $("#health-score");
    if (scoreEl) scoreEl.textContent = onlinePct.toFixed(1);
    const gradeEl = $("#health-grade");
    if (gradeEl) gradeEl.textContent = onlinePct >= 99 ? "A+" : onlinePct >= 90 ? "A" : onlinePct >= 75 ? "B" : "C";
    // ⑪ 还没有数据源的指标:一律落成"诚实的零/占位",绝不留演示数字(负责人 2026-07-26 定)
    neutralizeUnsourcedMetrics(tt);
    // ⑩ 无真实数据源的演示件：整体隐藏（调用效率/并发/存储/区域延迟/模拟接入按钮）
    for (const sel of ["#efficiency-panel", "#capacity-row-rps", "#capacity-row-storage", "#health-regions", "#add-oem"]) {
      const el = $(sel);
      if (el) el.style.display = "none";
    }
  }
  /** 把"还没有数据源"的指标落成诚实值,别让编出来的数字看着像真的。
   *
   *  口径(负责人 2026-07-26 定):**没有真实数据源的就显示 0 这类**。但有一个例外——
   *  **比率型指标不能显示 0%**(成功率写 0% 等于告诉运维"全部请求都失败了",比不显示更糟),
   *  这类一律用「—」并标注"未采集"。
   *  收入类目前恒为 0:真钱还没接(支付宝/微信 adapter 明天做),接通后这里换成真实订单金额。 */
  function neutralizeUnsourcedMetrics(tt) {
    const setText = (sel, text) => { const el = $(sel); if (el) el.textContent = text; };

    // —— 营收轮播页:平台还没有任何真实收入(支付未接) ——
    setText("#revenue-today", "¥ 0");
    setText("#revenue-today-delta", "—");
    setText("#revenue-month", "¥ 0");
    setText("#revenue-month-meta", "支付未接入");
    setText("#revenue-peak", "峰值 ¥ 0 / h");
    setText("#revenue-delta", "—");

    // —— 底部状态栏:接真实值 ——
    // 网关健康:用今日真实成功率判(≥99% Normal / ≥95% Degraded / 更低 Unstable);
    // 今日没有任何请求时不下结论,显示「—」。
    const sp = tt.success_pct;
    setText(
      "#footer-gateway",
      sp === null || sp === undefined ? "—" : sp >= 99 ? "Normal" : sp >= 95 ? "Degraded" : "Unstable",
    );
    // 区域:在线实例覆盖的真实地域(母舰按 OEM 装机时选的机房算)
    const regions = Array.isArray(tt.regions) ? tt.regions : [];
    setText(
      "#footer-region",
      regions.length === 0 ? "—" : regions.length === 1 ? regions[0] : `${regions.length} 个地域`,
    );
  }

  // ══════════ 真实数据适配层结束 ══════════

  function visualModeConfig(mode = state.visualMode) {
    return VISUAL_MODES[mode] || VISUAL_MODES.global;
  }

  function isMapMode(mode = state.visualMode) {
    return visualModeConfig(mode).kind === "map";
  }

  function statusText(status) {
    return status === "active" ? "运行中" : status === "warning" ? "高负载" : "维护中";
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function hexToRgba(hex, alpha = 1) {
    const normalized = hex.replace("#", "");
    const value = Number.parseInt(normalized.length === 3 ? normalized.split("").map((c) => c + c).join("") : normalized, 16);
    const red = (value >> 16) & 255;
    const green = (value >> 8) & 255;
    const blue = value & 255;
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
  }

  function mulberry32(seed) {
    return function seededRandom() {
      let value = (seed += 0x6d2b79f5);
      value = Math.imul(value ^ (value >>> 15), value | 1);
      value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
      return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
    };
  }

  function initClock() {
    const timeNode = $("#clock-time");
    const dateNode = $("#clock-date");
    const updatedNode = $("#updated-time");

    const tick = () => {
      const now = new Date();
      const time = now.toLocaleTimeString("zh-CN", {
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
      const date = now
        .toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" })
        .replaceAll("/", " / ");
      timeNode.textContent = time;
      updatedNode.textContent = time;
      dateNode.textContent = date;
    };

    tick();
    window.setInterval(tick, 1000);
  }

  function clearOverviewCarouselTimer() {
    window.clearTimeout(overviewCarouselTimer);
    overviewCarouselTimer = 0;
  }

  function scheduleOverviewCarousel() {
    clearOverviewCarouselTimer();
    const carousel = $("#overview-carousel");
    if (!carousel || !state.running || document.hidden) return;
    if (carousel.matches(":hover")) return;

    overviewCarouselTimer = window.setTimeout(() => {
      setOverviewSlide(state.overviewSlide + 1, { announce: false });
    }, OVERVIEW_AUTOPLAY_DELAY);
  }

  function setOverviewSlide(index, { announce = true, schedule = true } = {}) {
    const carousel = $("#overview-carousel");
    const track = $("#overview-carousel-track");
    const slides = $$(".overview-slide", carousel);
    const dots = $$(".overview-carousel__dot", carousel);
    if (!carousel || !track || slides.length === 0) return;

    const normalizedIndex = ((index % slides.length) + slides.length) % slides.length;
    const slideNames = slides.map((slide, slideIndex) =>
      $("h2", slide)?.textContent?.trim() || `第 ${slideIndex + 1} 页`,
    );
    const previousIndex = (normalizedIndex - 1 + slides.length) % slides.length;
    const nextIndex = (normalizedIndex + 1) % slides.length;
    state.overviewSlide = normalizedIndex;

    track.style.transform = `translate3d(-${normalizedIndex * 100}%, 0, 0)`;
    slides.forEach((slide, slideIndex) => {
      slide.setAttribute("aria-hidden", String(slideIndex !== normalizedIndex));
    });
    dots.forEach((dot, dotIndex) => {
      const active = dotIndex === normalizedIndex;
      dot.classList.toggle("is-active", active);
      dot.setAttribute("aria-selected", String(active));
      dot.tabIndex = active ? 0 : -1;
    });

    $("#overview-prev").setAttribute("aria-label", `上一页：${slideNames[previousIndex]}`);
    $("#overview-next").setAttribute("aria-label", `下一页：${slideNames[nextIndex]}`);
    if (announce) {
      $("#overview-carousel-status").textContent =
        `${slideNames[normalizedIndex]}，第 ${normalizedIndex + 1} 页，共 ${slides.length} 页`;
    }
    if (schedule) scheduleOverviewCarousel();
  }

  function initOverviewCarousel() {
    const carousel = $("#overview-carousel");
    const viewport = $(".overview-carousel__viewport", carousel);
    if (!carousel || !viewport) return;

    $("#overview-prev").addEventListener("click", () => setOverviewSlide(state.overviewSlide - 1));
    $("#overview-next").addEventListener("click", () => setOverviewSlide(state.overviewSlide + 1));
    $$(".overview-carousel__dot", carousel).forEach((dot) => {
      dot.addEventListener("click", () => setOverviewSlide(Number(dot.dataset.overviewTarget)));
    });

    let swipeStartX = null;
    let horizontalWheelLocked = false;

    viewport.addEventListener("pointerdown", (event) => {
      if (event.pointerType !== "touch") return;
      swipeStartX = event.clientX;
    });
    viewport.addEventListener("pointerup", (event) => {
      if (swipeStartX === null) return;
      const distance = event.clientX - swipeStartX;
      swipeStartX = null;
      if (Math.abs(distance) < 36) return;
      setOverviewSlide(state.overviewSlide + (distance < 0 ? 1 : -1));
    });
    viewport.addEventListener("pointercancel", () => {
      swipeStartX = null;
    });
    viewport.addEventListener(
      "wheel",
      (event) => {
        if (horizontalWheelLocked || Math.abs(event.deltaX) < 22 || Math.abs(event.deltaX) <= Math.abs(event.deltaY)) return;
        event.preventDefault();
        horizontalWheelLocked = true;
        setOverviewSlide(state.overviewSlide + (event.deltaX > 0 ? 1 : -1));
        window.setTimeout(() => {
          horizontalWheelLocked = false;
        }, 620);
      },
      { passive: false },
    );

    carousel.addEventListener("pointerenter", clearOverviewCarouselTimer);
    carousel.addEventListener("pointerleave", scheduleOverviewCarousel);
    carousel.addEventListener("focusin", clearOverviewCarouselTimer);
    carousel.addEventListener("focusout", (event) => {
      if (!carousel.contains(event.relatedTarget)) scheduleOverviewCarousel();
    });

    setOverviewSlide(0, { announce: false });
  }

  function naturalEarth1Raw(longitude, latitude) {
    const lambda = (longitude * Math.PI) / 180;
    const phi = (latitude * Math.PI) / 180;
    const phi2 = phi * phi;
    const phi4 = phi2 * phi2;
    return [
      lambda * (0.8707 - 0.131979 * phi2 + phi4 * (-0.013791 + phi4 * (0.003971 * phi2 - 0.001529 * phi4))),
      phi * (1.007226 + phi2 * (0.015085 + phi4 * (-0.044475 + 0.028874 * phi2 - 0.005916 * phi4))),
    ];
  }

  function decodeLandPolygons(topology) {
    const landObject = topology?.objects?.land;
    const sourceArcs = topology?.arcs;
    const transform = topology?.transform;
    if (!landObject || !Array.isArray(sourceArcs) || !transform?.scale || !transform?.translate) {
      throw new Error("Invalid Natural Earth topology");
    }

    const [scaleX, scaleY] = transform.scale;
    const [translateX, translateY] = transform.translate;
    const decodedArcCache = new Map();

    const decodeArc = (signedIndex) => {
      const arcIndex = signedIndex < 0 ? ~signedIndex : signedIndex;
      if (!decodedArcCache.has(arcIndex)) {
        let x = 0;
        let y = 0;
        const points = sourceArcs[arcIndex].map(([deltaX, deltaY]) => {
          x += deltaX;
          y += deltaY;
          return [x * scaleX + translateX, y * scaleY + translateY];
        });
        decodedArcCache.set(arcIndex, points);
      }
      const points = decodedArcCache.get(arcIndex);
      return signedIndex < 0 ? [...points].reverse() : points;
    };

    const stitchRing = (arcIndexes) => {
      const ring = [];
      arcIndexes.forEach((arcIndex, index) => {
        const points = decodeArc(arcIndex);
        ring.push(...(index === 0 ? points : points.slice(1)));
      });
      return ring;
    };

    const geometries = landObject.type === "GeometryCollection" ? landObject.geometries : [landObject];
    const polygons = [];

    geometries.forEach((geometry) => {
      const polygonArcs =
        geometry.type === "Polygon" ? [geometry.arcs] : geometry.type === "MultiPolygon" ? geometry.arcs : [];

      polygonArcs.forEach((rings) => {
        const polygon = rings.map(stitchRing).filter((ring) => ring.length >= 3);
        const maximumLatitude = polygon.reduce(
          (maximum, ring) => Math.max(maximum, ...ring.map((point) => point[1])),
          -Infinity,
        );

        // The reference layout presents the six inhabited continents and omits Antarctica.
        if (polygon.length && maximumLatitude > -60) polygons.push(polygon);
      });
    });

    if (!polygons.length) throw new Error("Natural Earth topology contained no usable land");
    return polygons;
  }

  function createNaturalEarthProjection(polygons) {
    let minimumX = Infinity;
    let maximumX = -Infinity;
    let minimumY = Infinity;
    let maximumY = -Infinity;

    polygons.forEach((polygon) => {
      polygon.forEach((ring) => {
        ring.forEach(([longitude, latitude]) => {
          const [x, y] = naturalEarth1Raw(longitude, latitude);
          minimumX = Math.min(minimumX, x);
          maximumX = Math.max(maximumX, x);
          minimumY = Math.min(minimumY, y);
          maximumY = Math.max(maximumY, y);
        });
      });
    });

    const extent = { x: 38, y: 18, width: 924, height: 420 };
    const rawWidth = maximumX - minimumX;
    const rawHeight = maximumY - minimumY;
    const scale = Math.min(extent.width / rawWidth, extent.height / rawHeight);
    const translateX = extent.x + (extent.width - rawWidth * scale) / 2 - minimumX * scale;
    const translateY = extent.y + (extent.height - rawHeight * scale) / 2 + maximumY * scale;

    const project = ([longitude, latitude]) => {
      const [x, y] = naturalEarth1Raw(longitude, latitude);
      return [translateX + x * scale, translateY - y * scale];
    };

    return project;
  }

  function positionMapCallouts() {
    const mapSvg = $("#hex-world-map");
    const mapStage = $("#world-map-stage");
    if (!mapSvg || !mapStage || !state.mapHotspots.length) return;

    const stageRect = mapStage.getBoundingClientRect();
    const svgRect = mapSvg.getBoundingClientRect();
    const stageScaleX = mapStage.offsetWidth ? stageRect.width / mapStage.offsetWidth : 1;
    const stageScaleY = mapStage.offsetHeight ? stageRect.height / mapStage.offsetHeight : 1;
    const svgLeft = (svgRect.left - stageRect.left) / stageScaleX;
    const svgTop = (svgRect.top - stageRect.top) / stageScaleY;
    const svgWidth = svgRect.width / stageScaleX;
    const svgHeight = svgRect.height / stageScaleY;
    const viewBox = mapSvg.viewBox.baseVal;
    const viewScale = Math.min(svgWidth / viewBox.width, svgHeight / viewBox.height);
    const renderedWidth = viewBox.width * viewScale;
    const renderedHeight = viewBox.height * viewScale;
    const offsetX = svgLeft + (svgWidth - renderedWidth) / 2;
    const offsetY = svgTop + (svgHeight - renderedHeight) / 2;

    state.mapHotspots.forEach((hotspot) => {
      const marker = $(`.geo-node[data-node-id="${hotspot.id}"]`);
      if (!marker) return;
      const x = offsetX + (hotspot.x - viewBox.x) * viewScale;
      const y = offsetY + (hotspot.y - viewBox.y) * viewScale;
      marker.style.setProperty("--geo-x", `${x.toFixed(2)}px`);
      marker.style.setProperty("--geo-y", `${y.toFixed(2)}px`);
    });
  }

  let mapStageObserver = null;

  /** 地图舞台一拿到真实尺寸就重算标记位置。
   *
   *  为什么用 ResizeObserver 而不是 rAF/setTimeout 赌时机:标记的像素位置要靠
   *  getBoundingClientRect 量 SVG,而首屏有揭示动画、布局稳定的时刻不固定——单 rAF、
   *  双 rAF 都试过,量到的仍是 0,标记卡在占位的 50%/50%(手动触发 resize 才归位)。
   *  ResizeObserver 在元素真正拿到/改变尺寸时才回调,是这件事的正确原语,顺带把
   *  窗口缩放、面板折叠等布局变化也一并覆盖了。 */
  function observeMapStageSize() {
    const stage = $("#world-map-stage");
    if (!stage || mapStageObserver || typeof ResizeObserver === "undefined") {
      // 环境不支持 ResizeObserver 时退化成一次性延时兜底,总比不定位强
      if (stage && !mapStageObserver) window.setTimeout(() => positionMapCallouts(), 400);
      return;
    }
    mapStageObserver = new ResizeObserver(() => positionMapCallouts());
    mapStageObserver.observe(stage);
  }

  function mapCellNoise(x, y, salt = 0) {
    const raw = Math.sin(x * 12.9898 + y * 78.233 + salt * 37.719) * 43758.5453;
    return raw - Math.floor(raw);
  }

  function validMapCells(cells) {
    return Array.isArray(cells)
      ? cells.filter(
          (point) =>
            Array.isArray(point) &&
            point.length === 2 &&
            Number.isFinite(point[0]) &&
            Number.isFinite(point[1]),
        )
      : [];
  }

  /** 把每个地域吸附到**最近的陆地格子**：一个地域只点亮一个格子。
   *
   *  为什么要吸附而不是直接用投影坐标：地图是六边形栅格,投影出来的点未必正好落在某个
   *  格子中心,更可能落在两格之间甚至海里(沿海城市尤其常见)。吸附到最近的陆地格子后,
   *  ①点一定在陆地上 ②标记与被点亮的格子严格对齐 ③一个实例=一个格子,不会糊成一片。
   *  已被占用的格子会跳过,保证两个相邻地域不会抢同一格。 */
  function assignRegionCells(landCells, groups, project) {
    const used = new Set();
    const byCell = new Map();     // cellIndex → group
    for (const group of groups) {
      const [px, py] = project([group.lon, group.lat]);
      let best = -1;
      let bestDistance = Infinity;
      landCells.forEach(([x, y], index) => {
        if (used.has(index)) return;
        const distance = Math.hypot(x - px, y - py);
        if (distance < bestDistance) {
          bestDistance = distance;
          best = index;
        }
      });
      if (best >= 0) {
        used.add(best);
        byCell.set(best, group);
        group.cell = landCells[best];   // 记下格子中心,标记按它定位
      }
    }
    return byCell;
  }

  function buildHexCellMarkup(landCells, hotspots, regionCells = null) {
    const radius = 5.65;
    const halfHeight = (Math.sqrt(3) * radius) / 2;

    return landCells
      .map(([x, y], cellIndex) => {
        let nearest = null;
        for (const hotspot of hotspots) {
          const distance = Math.hypot(x - hotspot.x, y - hotspot.y) / hotspot.radius;
          if (distance < 1 && (!nearest || distance < nearest.distance)) {
            nearest = { ...hotspot, distance };
          }
        }

        const colorNoise = mapCellNoise(x, y, 1);
        const scatterNoise = mapCellNoise(x, y, 2);
        let fill = "#ffffff";
        let stroke = "#dfe1ef";
        let opacity = 0.96;
        let hotClass = "";
        let hotNodeId = "";
        let heatScore = Math.round(8 + mapCellNoise(x, y, 4) * 22);

        // 真实模式:只点亮"被指派给某地域"的那一个格子。演示模式(regionCells 为空)
        // 才走下面按 radius 铺光晕的老逻辑——那是给空场景看的装饰,不能用来表示真实节点。
        if (regionCells) {
          const group = regionCells.get(cellIndex);
          if (group) {
            fill = group.color || "#6e7cf6";
            stroke = "rgba(255,255,255,0.55)";
            opacity = 1;
            hotClass = " is-hot";
            hotNodeId = group.id;
            heatScore = 99;
          }
        } else if (nearest) {
          const intensity = 1 - nearest.distance;
          heatScore = Math.round(36 + intensity * 63);
          const shouldColor = intensity > 0.56 || colorNoise < 0.14 + intensity * 0.83;
          if (shouldColor) {
            const colorBand =
              nearest.distance < 0.2 ? [nearest.core] : nearest.distance < 0.46 ? nearest.mid : nearest.outer;
            fill = colorBand[Math.floor(scatterNoise * colorBand.length) % colorBand.length];
            stroke = "rgba(255,255,255,0.42)";
            opacity = 0.64 + intensity * 0.36;
            hotClass = " is-hot";
            hotNodeId = nearest.id;
          }
        }
        // 注：这里原本还有一段"随机把 2.2% 的格子染成淡紫"的装饰逻辑，已删除——
        // 它和真实节点的热区长得一模一样，会让人误以为"全球到处都是节点"（负责人实报）。
        // 地图上出现颜色 = 那里真的有实例，不制造视觉噪音。

        const cellId = `HEX-${String(cellIndex + 1).padStart(4, "0")}`;
        const path = [
          `M${(x + radius).toFixed(2)} ${y.toFixed(2)}`,
          `L${(x + radius / 2).toFixed(2)} ${(y + halfHeight).toFixed(2)}`,
          `L${(x - radius / 2).toFixed(2)} ${(y + halfHeight).toFixed(2)}`,
          `L${(x - radius).toFixed(2)} ${y.toFixed(2)}`,
          `L${(x - radius / 2).toFixed(2)} ${(y - halfHeight).toFixed(2)}`,
          `L${(x + radius / 2).toFixed(2)} ${(y - halfHeight).toFixed(2)}Z`,
        ].join("");

        return `<path class="world-hex-cell${hotClass}" data-cell-id="${cellId}" data-center-x="${x.toFixed(2)}" data-center-y="${y.toFixed(2)}" data-heat="${heatScore}" data-cell-color="${fill}"${hotNodeId ? ` data-node-id="${hotNodeId}"` : ""} d="${path}" style="--cell-fill:${fill};--cell-stroke:${stroke};--cell-opacity:${opacity.toFixed(2)}"></path>`;
      })
      .join("");
  }

  async function renderMapDecorations() {
    const mapSvg = $("#hex-world-map");
    const cellLayer = $("#world-hex-cells");
    const sourceLayer = mapSvg ? $(".continent-source", mapSvg) : null;
    const sourcePaths = sourceLayer ? $$("path", sourceLayer) : [];
    const hitContext = document.createElement("canvas").getContext("2d");

    if (cellLayer && mapSvg) {
      let project = null;
      let landCells = [];

      try {
        const [landResponse, cellsResponse] = await Promise.all([
          fetch("./assets/land-110m.json", { cache: "force-cache" }),
          fetch("./assets/world-hex-land-cells.json", { cache: "force-cache" }),
        ]);
        if (!landResponse.ok || !cellsResponse.ok) {
          throw new Error(`Natural Earth assets failed with ${landResponse.status}/${cellsResponse.status}`);
        }
        const [topology, gridData] = await Promise.all([landResponse.json(), cellsResponse.json()]);
        const polygons = decodeLandPolygons(topology);
        project = createNaturalEarthProjection(polygons);
        landCells = validMapCells(gridData.cells);
        if (!landCells.length) throw new Error("Precomputed Natural Earth grid contained no cells");
      } catch (error) {
        if (hitContext && typeof Path2D !== "undefined") {
          const fallbackShapes = sourcePaths.map((path) => new Path2D(path.getAttribute("d")));
          let column = 0;
          for (let x = 48; x <= 952; x += 9.15) {
            const offsetY = (column % 2) * (10.45 / 2);
            for (let y = 24 + offsetY; y <= 446; y += 10.45) {
              if (fallbackShapes.some((shape) => hitContext.isPointInPath(shape, x, y))) landCells.push([x, y]);
            }
            column += 1;
          }
        }
        console.warn("Natural Earth boundary unavailable; using embedded fallback.", error);
      }

      // 热点来源：**优先用真实实例的经纬度**（母舰按 OEM 装机时选的机房算出来的）。
      // 只有一个真实实例都没定位到时，才回落到 MAP_HOTSPOT_DEFINITIONS 那组演示坐标
      // ——否则地图上画的是芝加哥/柏林这些假点，而真实节点一个都不在（负责人实报"看不到任何节点"）。
      // 真实节点**按地域合并**：同一个地域(如都在浙江)只出一个点,并记下实例数——
      // 否则同地域的多台机器会叠在同一格上、看起来像重影(负责人实报"同区域应该是一个")。
      const geoNodes = state.nodes.filter((n) => n.geoKnown);
      const groupMap = new Map();
      for (const node of geoNodes) {
        const key = node.regionCode || `${node.lat},${node.lon}`;
        const g = groupMap.get(key);
        if (g) {
          g.nodes.push(node);
        } else {
          groupMap.set(key, {
            id: node.id,               // 用组内首个节点 id 当标识,便于与排行/选中联动
            regionLabel: node.region || "",
            lat: node.lat,
            lon: node.lon,
            color: node.color,
            nodes: [node],
            cell: null,
          });
        }
      }
      const geoGroups = [...groupMap.values()];
      state.geoGroups = geoGroups;

      let regionCells = null;
      let worldHotspots;
      if (geoGroups.length && project) {
        regionCells = assignRegionCells(landCells, geoGroups, project);
        // 热点坐标用**吸附后的格子中心**,保证标记与点亮的格子严格对齐
        worldHotspots = geoGroups.map((g) => ({
          id: g.id,
          coordinates: [g.lon, g.lat],
          radius: 1,                   // 真实模式不铺光晕,点亮哪格由 regionCells 决定
          core: g.color,
          mid: [g.color],
          outer: [g.color],
          x: g.cell ? g.cell[0] : project([g.lon, g.lat])[0],
          y: g.cell ? g.cell[1] : project([g.lon, g.lat])[1],
        }));
      } else {
        // 一个真实节点都没定位到：回落演示热点，免得地图完全空白
        worldHotspots = MAP_HOTSPOT_DEFINITIONS.map((hotspot) => {
          const [x, y] = project ? project(hotspot.coordinates) : hotspot.fallback;
          return { ...hotspot, x, y };
        });
      }
      state.mapScene = {
        cellMarkup: buildHexCellMarkup(landCells, worldHotspots, regionCells),
        cellCount: landCells.length,
        hotspots: worldHotspots,
      };
    }

    const traffic = $("#map-traffic-bars");
    if (traffic) {
      // 真实模式:用**真实的 24 小时逐时消耗**画柱子(这份数据本来就有,之前没接上,
      // 柱形是 sin 波生成的装饰——数字真、波形假,容易被当成真实流量形态)。
      // 没有真实数据(演示模式)时才回落到原来的装饰波形。
      const real = REAL_TREND && REAL_TREND.length ? REAL_TREND : null;
      if (real) {
        const peak = Math.max(1, ...real);
        traffic.innerHTML = real
          .map((value) => {
            const height = clamp(Math.round((value / peak) * 53), 2, 53);
            const tone = value >= peak * 0.66 ? "hot" : value >= peak * 0.33 ? "cyan" : "base";
            return `<i class="map-traffic__bar map-traffic__bar--${tone}" style="height:${height}px"></i>`;
          })
          .join("");
      } else {
        traffic.innerHTML = Array.from({ length: 72 }, (_, index) => {
          const wave = Math.sin(index * 0.43) * 8 + Math.sin(index * 0.11 + 1.4) * 11;
          const height = clamp(23 + wave + (index > 28 && index < 48 ? 13 : 0), 8, 53);
          const tone = index > 28 && index < 48 ? "hot" : index > 56 ? "cyan" : "base";
          return `<i class="map-traffic__bar map-traffic__bar--${tone}" style="height:${height}px"></i>`;
        }).join("");
      }
    }
  }

  /** 用真实实例重建地图上的节点标记（.geo-node）。
   *
   *  为什么要这一步：index.html 里那几个 .geo-node 是**写死的演示节点**（Nebula One /
   *  深蓝数据…），它们的 data-node-id 是 nb/db 这类演示 id。真实数据接管后节点 id 变成
   *  nx-<n>，演示标记既对不上、又会被可见性逻辑判成"不在范围"而全部隐藏——结果地图上
   *  一个节点都不剩（负责人实报）。这里直接按真实节点重建，id 与热点保持一致。
   *  只渲染**定位得到**的节点：没填地域的宁可不画，也不假装它在某个地方。 */
  function renderRealGeoMarkers() {
    const stage = $("#world-map-stage");
    if (!stage) return;
    // 按地域合并后的组（renderMapDecorations 里算好的）：同地区多台机器只出一个标记
    const geoGroups = state.geoGroups || [];
    if (!geoGroups.length) return;  // 一个都没定位：保留演示件，别把地图弄成空白

    stage.querySelectorAll(".geo-node").forEach((el) => el.remove());
    const icon =
      '<svg viewBox="0 0 20 20"><rect x="4" y="4" width="12" height="12" rx="2"></rect>' +
      '<path d="M7 8h6M7 11h6M7 14h4"></path></svg>';
    const frag = document.createDocumentFragment();
    for (const group of geoGroups) {
      const node = group.nodes[0];
      const count = group.nodes.length;
      // 同地域多台：主名后缀「+N」,一眼看出这个点代表几台,而不是画成重影
      const displayName = count > 1 ? `${node.name} +${count - 1}` : node.name;
      const sumToken = group.nodes.reduce((acc, n) => acc + (Number(n.token) || 0), 0);
      const btn = document.createElement("button");
      btn.className = "geo-node";
      btn.type = "button";
      btn.dataset.nodeId = group.id;
      btn.style.setProperty("--geo-color", node.color || "#6e7cf6");
      // 具体像素位置由 positionMapCallouts() 按投影算；这里先给个占位百分比避免闪到左上角
      btn.style.setProperty("--geo-x", "50%");
      btn.style.setProperty("--geo-y", "50%");
      btn.innerHTML =
        '<span class="geo-node__card">' +
        `<span class="geo-node__icon" aria-hidden="true">${icon}</span>` +
        '<span class="geo-node__copy">' +
        `<small>${escapeHtml(group.regionLabel)}${count > 1 ? ` · ${count} 台` : ""}</small>` +
        `<strong><span class="geo-node__name">${escapeHtml(displayName)}</span>` +
        `<em>${escapeHtml(String(Number(sumToken.toFixed(2))))}${TOKEN_UNIT.label}</em></strong>` +
        "</span></span>";
      frag.appendChild(btn);
    }
    stage.appendChild(frag);
    // 关键:把"地图作用域白名单"换成真实节点 id。GLOBAL_MAP_CONFIG.nodeIds 原本是一串写死的
    // 演示 id(nb/db/gl…),真实节点不在其中会被 updateMapFilters 判成 is-out-of-scope 而隐藏
    // ——标记明明生成了却看不见,就卡在这一步(本地实测定位)。
    GLOBAL_MAP_CONFIG.nodeIds = geoGroups.map((g) => g.id);
    // 演示期的 callout 冲突表(按演示 id 写死)对真实节点没有意义,清掉免得误伤
    MAP_CALLOUT_CONFLICTS.clear();
    // 注:像素定位不在这里做——此刻 SVG 还没完成布局(量到的尺寸是 0),rAF 也不够稳。
    // 统一放到 init() 末尾、场景全部就绪后再算一次(见 init 里的 positionMapCallouts)。
  }

  /** 极简 HTML 转义：节点名/地域来自服务端，虽可信但拼进 innerHTML 前一律转义。 */
  function escapeHtml(text) {
    return String(text ?? "").replace(/[&<>"']/g, (ch) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
    ));
  }

  let worldRevealTimer = 0;
  let mapCalloutTimer = 0;
  let hoveredMapCell = null;
  let mapCalloutsSuppressedByCellHover = false;
  let mapTooltipFrame = 0;
  let pendingMapPointer = null;

  function replayWorldHexReveal() {
    const cellLayer = $("#world-hex-cells");
    const mapStage = $("#world-map-stage");
    if (!cellLayer?.children.length) return;
    clearMapCellHover();
    window.clearTimeout(worldRevealTimer);
    cellLayer.classList.remove("is-revealing");
    mapStage?.classList.remove("is-revealing");
    window.requestAnimationFrame(() => {
      cellLayer.classList.add("is-revealing");
      mapStage?.classList.add("is-revealing");
      worldRevealTimer = window.setTimeout(() => {
        cellLayer.classList.remove("is-revealing");
        mapStage?.classList.remove("is-revealing");
      }, 900);
    });
  }

  function applyMapScene({ reveal = true, rotate = true } = {}) {
    const scene = state.mapScene;
    const mapSvg = $("#hex-world-map");
    const cellLayer = $("#world-hex-cells");
    const mapStage = $("#world-map-stage");
    if (!scene || !mapSvg || !cellLayer || !mapStage) {
      console.error("Global map scene is unavailable.");
      return;
    }

    clearMapCellHover();
    window.clearTimeout(worldRevealTimer);
    window.clearTimeout(mapCalloutTimer);
    state.mapHotspots = scene.hotspots;
    state.mapCalloutIds = [];

    const isFirstMount = cellLayer.dataset.mounted !== "true";
    if (isFirstMount) {
      cellLayer.classList.remove("is-revealing");
      mapStage.classList.remove("is-revealing");
      cellLayer.innerHTML = scene.cellMarkup;
      cellLayer.dataset.mounted = "true";
      cellLayer.dataset.cellCount = String(scene.cellCount);
      mapSvg.setAttribute("viewBox", GLOBAL_MAP_CONFIG.viewBox);
      mapSvg.classList.toggle("has-generated-hexes", scene.cellCount > 0);
    }

    updateMapFilters({ rotate, schedule: rotate && isMapMode() });
    if (reveal && isFirstMount && isMapMode()) replayWorldHexReveal();
    window.requestAnimationFrame(positionMapCallouts);
  }

  function clearMapCellHover() {
    hoveredMapCell?.classList.remove("is-hovered");
    hoveredMapCell = null;
    pendingMapPointer = null;
    if (mapTooltipFrame) {
      window.cancelAnimationFrame(mapTooltipFrame);
      mapTooltipFrame = 0;
    }
    const tooltip = $("#hex-hover-card");
    tooltip?.classList.remove("is-visible");
    tooltip?.setAttribute("aria-hidden", "true");
    setMapCalloutsSuppressedByCellHover(false);
  }

  function positionMapCellTooltip(pointer) {
    const tooltip = $("#hex-hover-card");
    const mapStage = $("#world-map-stage");
    if (!tooltip || !mapStage) return;
    const stageRect = mapStage.getBoundingClientRect();
    const scaleX = mapStage.offsetWidth ? stageRect.width / mapStage.offsetWidth : 1;
    const scaleY = mapStage.offsetHeight ? stageRect.height / mapStage.offsetHeight : 1;
    const localX = (pointer.clientX - stageRect.left) / scaleX;
    const localY = (pointer.clientY - stageRect.top) / scaleY;
    const left = clamp(localX + 12, 12, mapStage.offsetWidth - tooltip.offsetWidth - 12);
    const top = clamp(localY - tooltip.offsetHeight - 12, 58, mapStage.offsetHeight - tooltip.offsetHeight - 68);
    tooltip.style.left = `${left.toFixed(1)}px`;
    tooltip.style.top = `${top.toFixed(1)}px`;
  }

  function scheduleMapCellTooltip(event) {
    pendingMapPointer = { clientX: event.clientX, clientY: event.clientY };
    if (mapTooltipFrame) return;
    mapTooltipFrame = window.requestAnimationFrame(() => {
      mapTooltipFrame = 0;
      if (hoveredMapCell && pendingMapPointer) positionMapCellTooltip(pendingMapPointer);
    });
  }

  function showMapCellHover(cell, event) {
    if (!cell || cell.classList.contains("is-muted")) return;
    if (event.pointerType !== "touch") setMapCalloutsSuppressedByCellHover(true);
    if (hoveredMapCell !== cell) {
      hoveredMapCell?.classList.remove("is-hovered");
      hoveredMapCell = cell;
      cell.classList.add("is-hovered");
      const node = state.nodes.find((item) => item.id === cell.dataset.nodeId);
      $("#hex-hover-id").textContent = cell.dataset.cellId;
      $("#hex-hover-status").textContent = node
        ? `${node.name} · 热度 ${cell.dataset.heat}`
        : `未绑定 OEM · 热度 ${cell.dataset.heat}`;
      const tooltip = $("#hex-hover-card");
      tooltip.classList.add("is-visible");
      tooltip.setAttribute("aria-hidden", "false");
    }
    scheduleMapCellTooltip(event);
  }

  function mapCellRegion(x, y) {
    if (x < 410) return y < 275 ? "北美覆盖区" : "南美覆盖区";
    if (x < 620) return y < 205 ? "欧洲覆盖区" : "非洲覆盖区";
    if (x < 825) return y < 305 ? "亚洲覆盖区" : "印度洋覆盖区";
    return y < 300 ? "东亚覆盖区" : "大洋洲覆盖区";
  }

  function activateMapCell(cell) {
    if (!cell || cell.classList.contains("is-muted")) return;
    $$(".world-hex-cell.is-selected").forEach((item) => item.classList.remove("is-selected"));
    cell.classList.add("is-selected");

    if (cell.dataset.nodeId) {
      selectNode(cell.dataset.nodeId);
      openDrawer(cell);
    } else {
      openMapCellDrawer(cell);
    }
  }

  function updateMapSelection() {
    $$(".geo-node").forEach((marker) => {
      const isSelected = marker.dataset.nodeId === state.selectedId;
      marker.classList.toggle("is-active", isSelected);
      marker.setAttribute("aria-pressed", String(isSelected));
    });
  }

  function nodeMatchesMapFilter(node) {
    return Boolean(
      node &&
        (state.filter === "all" ||
          (state.filter === "active" && node.status === "active") ||
          (state.filter === "warning" && node.status === "warning")),
    );
  }

  function shuffled(values) {
    const result = [...values];
    for (let index = result.length - 1; index > 0; index -= 1) {
      const swapIndex = Math.floor(Math.random() * (index + 1));
      [result[index], result[swapIndex]] = [result[swapIndex], result[index]];
    }
    return result;
  }

  function mapCalloutsConflict(leftId, rightId) {
    return MAP_CALLOUT_CONFLICTS.has([leftId, rightId].sort().join(":"));
  }

  function scheduleMapCalloutRotation() {
    window.clearTimeout(mapCalloutTimer);
    if (
      !state.running ||
      !isMapMode() ||
      document.hidden ||
      mapCalloutsSuppressedByCellHover
    ) {
      return;
    }
    const delay = 4200 + Math.round(Math.random() * 2200);
    mapCalloutTimer = window.setTimeout(() => rotateMapCallouts(), delay);
  }

  function setMapCalloutsSuppressedByCellHover(suppressed) {
    const shouldSuppress = Boolean(suppressed);
    if (mapCalloutsSuppressedByCellHover === shouldSuppress) return;

    mapCalloutsSuppressedByCellHover = shouldSuppress;
    const stage = $("#world-map-stage");
    stage?.classList.toggle("is-cell-hovered", shouldSuppress);

    $$(".geo-node").forEach((marker) => {
      const isVisible =
        !marker.classList.contains("is-out-of-scope") &&
        !marker.classList.contains("is-filtered") &&
        (marker.classList.contains("is-callout-visible") || marker.classList.contains("is-active"));
      marker.setAttribute("aria-hidden", String(shouldSuppress || !isVisible));
      marker.tabIndex = shouldSuppress || !isVisible ? -1 : 0;
    });

    if (shouldSuppress) {
      window.clearTimeout(mapCalloutTimer);
    } else {
      scheduleMapCalloutRotation();
    }
  }

  function rotateMapCallouts({ schedule = true } = {}) {
    window.clearTimeout(mapCalloutTimer);
    const markers = $$(".geo-node");
    const eligibleIds = markers
      .filter((marker) => !marker.classList.contains("is-out-of-scope"))
      .map((marker) => marker.dataset.nodeId)
      .filter((id) => nodeMatchesMapFilter(state.nodes.find((node) => node.id === id)));
    const stageWidth = $("#world-map-stage")?.clientWidth || 0;
    const responsiveCount = stageWidth >= 1000 ? 6 : stageWidth >= 760 ? 4 : 3;
    const visibleCount = Math.min(GLOBAL_MAP_CONFIG.calloutCount, responsiveCount, eligibleIds.length);
    const previousIds = new Set(state.mapCalloutIds);
    const pinnedIds = [];
    const selectedId = eligibleIds.includes(state.selectedId) ? state.selectedId : null;

    if (selectedId) pinnedIds.push(selectedId);
    markers.forEach((marker) => {
      const id = marker.dataset.nodeId;
      if (
        eligibleIds.includes(id) &&
        !pinnedIds.includes(id) &&
        (marker.matches(":hover") || marker.matches(":focus-within"))
      ) {
        pinnedIds.push(id);
      }
    });

    const freshIds = shuffled(
      eligibleIds.filter((id) => !pinnedIds.includes(id) && !previousIds.has(id)),
    );
    const repeatIds = shuffled(
      eligibleIds.filter((id) => !pinnedIds.includes(id) && previousIds.has(id)),
    );
    const nextIds = [];
    for (const id of [...pinnedIds, ...freshIds, ...repeatIds]) {
      if (nextIds.length >= visibleCount) break;
      if (nextIds.some((visibleId) => mapCalloutsConflict(id, visibleId))) continue;
      nextIds.push(id);
    }
    const visibleIds = new Set(nextIds);

    state.mapCalloutIds = nextIds;

    markers.forEach((marker) => {
      const isVisible =
        visibleIds.has(marker.dataset.nodeId) &&
        !marker.classList.contains("is-filtered") &&
        !marker.classList.contains("is-out-of-scope");
      marker.classList.toggle("is-callout-visible", isVisible);
      marker.setAttribute("aria-hidden", String(mapCalloutsSuppressedByCellHover || !isVisible));
      marker.tabIndex = mapCalloutsSuppressedByCellHover || !isVisible ? -1 : 0;
    });

    if (schedule) scheduleMapCalloutRotation();
  }

  function updateMapFilters({ rotate = true, schedule = isMapMode() } = {}) {
    const sceneNodeIds = new Set(GLOBAL_MAP_CONFIG.nodeIds);
    $$(".geo-node").forEach((marker) => {
      const node = state.nodes.find((item) => item.id === marker.dataset.nodeId);
      const inScope = sceneNodeIds.has(marker.dataset.nodeId);
      const matches = inScope && nodeMatchesMapFilter(node);
      marker.classList.toggle("is-out-of-scope", !inScope);
      marker.classList.toggle("is-filtered", !matches);
    });

    $$(".world-hex-cell[data-node-id]").forEach((cell) => {
      const node = state.nodes.find((item) => item.id === cell.dataset.nodeId);
      const matches = sceneNodeIds.has(cell.dataset.nodeId) && nodeMatchesMapFilter(node);
      cell.classList.toggle("is-muted", !matches);
    });

    if (hoveredMapCell?.classList.contains("is-muted")) clearMapCellHover();
    if (rotate) rotateMapCallouts({ schedule });
  }

  function switchVisualMode(mode) {
    const normalizedMode = VISUAL_MODES[mode] ? mode : "global";
    const config = visualModeConfig(normalizedMode);
    state.visualMode = normalizedMode;
    const panel = $(".universe-panel");
    const stage = $("#visual-stage");
    panel.dataset.visualMode = normalizedMode;
    panel.dataset.visualKind = config.kind;
    stage.dataset.mode = config.kind;
    $("#world-map-stage").setAttribute("aria-hidden", String(config.kind !== "map"));
    $("#universe-stage").setAttribute("aria-hidden", String(config.kind !== "universe"));
    $("#camera-reset").hidden = config.kind !== "universe";
    $("#visual-eyebrow").textContent = config.eyebrow;
    $("#visual-title").textContent = config.title;

    $$(".visual-switch button").forEach((button) => {
      const isActive = button.dataset.visualMode === normalizedMode;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
    });

    if (config.kind === "universe") {
      window.clearTimeout(mapCalloutTimer);
      clearMapCellHover();
      $$(".geo-node").forEach((marker) => {
        marker.setAttribute("aria-hidden", "true");
        marker.tabIndex = -1;
      });
      window.setTimeout(() => {
        resizeUniverse();
        requestUniverseFrame();
      }, 40);
      canvas.focus({ preventScroll: true });
    } else {
      stopUniverseLoop();
      applyMapScene();
    }
  }

  function renderRanking() {
    const list = $("#ranking-list");
    const sorted = [...state.nodes].sort((a, b) => b.token - a.token);
    list.innerHTML = sorted
      .map(
        (node, index) => `
          <button class="ranking-item ${node.id === state.selectedId ? "is-active" : ""}" type="button" data-node-id="${node.id}">
            <span class="ranking-item__index">${String(index + 1).padStart(2, "0")}</span>
            <span class="ranking-item__planet" style="--planet: ${node.color}"></span>
            <span class="ranking-item__info">
              <strong>${node.name}</strong>
              <small>${node.code} · ${statusText(node.status)}</small>
            </span>
            <span class="ranking-item__value">
              <strong>${node.token.toFixed(2)}${TOKEN_UNIT.label}</strong>
              <small class="${node.delta < 0 ? "negative" : ""}">${node.delta >= 0 ? "+" : ""}${node.delta.toFixed(1)}%</small>
            </span>
          </button>
        `,
      )
      .join("");

    $$(".ranking-item", list).forEach((item) => {
      item.addEventListener("click", () => selectNode(item.dataset.nodeId));
    });
    window.requestAnimationFrame(updateRankingScrollControls);
  }

  function updateRankingScrollControls() {
    const list = $("#ranking-list");
    const upButton = $("#ranking-scroll-up");
    const downButton = $("#ranking-scroll-down");
    if (!list || !upButton || !downButton) return;

    const maximumScroll = Math.max(0, list.scrollHeight - list.clientHeight);
    const scrollable = maximumScroll > 2;
    upButton.disabled = !scrollable || list.scrollTop <= 1;
    downButton.disabled = !scrollable || list.scrollTop >= maximumScroll - 1;
  }

  function scrollRanking(direction) {
    const list = $("#ranking-list");
    if (!list) return;
    const distance = Math.max(76, list.clientHeight * 0.72);
    list.scrollBy({
      top: distance * direction,
      behavior: state.running ? "smooth" : "auto",
    });
  }

  function updateInspector(node, immediate = false) {
    const panel = $("#node-inspector");
    if (!immediate) panel.classList.add("is-updating");

    const update = () => {
      $("#selected-avatar").textContent = node.initials;
      $("#selected-avatar").style.setProperty("--avatar", node.color);
      $("#selected-code").textContent = `OEM · ${node.code}`;
      $("#selected-name").textContent = node.name;
      // 单位跟全局自适应单位走;此前写死 "B" 会把 100M 显示成 100.00B(差 1000 倍)
      $("#selected-token").textContent = `${node.token.toFixed(2)}${TOKEN_UNIT.label}`;
      $("#selected-requests").textContent = node.requests;
      $("#selected-latency").textContent = node.latency;
      $("#selected-models").textContent = `${node.models} 个模型在线`;
      const stateBadge = $("#selected-state");
      stateBadge.textContent = statusText(node.status);
      stateBadge.className = `node-state${node.status === "warning" ? " is-warning" : node.status === "offline" ? " is-offline" : ""}`;
      panel.classList.remove("is-updating");
    };

    if (immediate) update();
    else window.setTimeout(update, 130);
  }

  function selectNode(id) {
    const node = state.nodes.find((item) => item.id === id);
    if (!node) return;
    state.selectedId = id;
    updateInspector(node);
    renderRanking();
    updateMapSelection();
    rotateMapCallouts({ schedule: isMapMode() });
    requestUniverseFrame();
  }

  function showDrawer(trigger = null) {
    state.drawerTrigger = trigger || document.activeElement;
    const drawer = $("#detail-drawer");
    drawer.classList.add("is-open");
    drawer.setAttribute("aria-hidden", "false");
    window.requestAnimationFrame(() => $("#drawer-close").focus({ preventScroll: true }));
  }

  function openDrawer(trigger = null) {
    const node = state.nodes.find((item) => item.id === state.selectedId);
    if (!node) return;

    const drawer = $("#detail-drawer");
    drawer.classList.remove("is-grid-cell");
    $("#drawer-eyebrow").textContent = "NODE PROFILE";
    $("#drawer-name").textContent = node.name;
    $("#drawer-code").textContent = `OEM · ${node.code}`;
    $("#drawer-status").textContent = statusText(node.status);
    $("#drawer-region").textContent = node.region;
    $("#drawer-glyph").textContent = node.initials;
    $("#drawer-token-label").textContent = "累计 Token";
    $("#drawer-token").textContent = `${node.token.toFixed(2)}B`;
    $("#drawer-requests-label").textContent = "今日请求";
    $("#drawer-requests").textContent = node.requests;
    // 峰值:网关分钟桶里的单分钟最大请求数(真实值;今日无请求则显示「—」)
    $("#drawer-requests-meta").textContent = node.peakPerMin
      ? `峰值 ${node.peakPerMin.toLocaleString("en-US")} req/min`
      : "今日无请求";
    $("#drawer-success-label").textContent = "成功率";
    // ⚠️ 成功率**永远不落 0%**——0% 读起来像"全线故障",比不显示更误导。
    // 今日没有任何请求时 successPct 为 null → 显示「—」。
    $("#drawer-success").textContent =
      node.successPct === null ? "—" : `${node.successPct.toFixed(2)}%`;
    $("#drawer-success-meta").textContent =
      node.successPct === null ? "今日无请求" : "网关实测（今日）";
    $("#drawer-latency-label").textContent = "平均延迟";
    $("#drawer-latency").textContent = node.latency;
    // 真实模式下延迟暂未采集（latency="—"），P95 跟着显示占位而不是 NaN
    const latencySeconds = Number.parseFloat(node.latency);
    $("#drawer-latency-meta").textContent = Number.isFinite(latencySeconds)
      ? `P95 ${(latencySeconds * 2).toFixed(2)}s`
      : "P95 —";
    const total = state.nodes.reduce((sum, item) => sum + item.token, 0);
    $("#drawer-share").textContent = `全局占比 ${((node.token / total) * 100).toFixed(1)}%`;
    $("#drawer-planet").style.setProperty("--drawer-color", node.color);
    showDrawer(trigger);
  }

  function openMapCellDrawer(cell) {
    const cellId = cell.dataset.cellId || "HEX-0000";
    const x = Number.parseFloat(cell.dataset.centerX) || 0;
    const y = Number.parseFloat(cell.dataset.centerY) || 0;
    const heat = Number.parseInt(cell.dataset.heat, 10) || 0;
    const cellColor = cell.dataset.cellColor || "#7565e7";
    const accent = ["#ffffff", "#d9d7f4", "#cbc5f1"].includes(cellColor.toLowerCase()) ? "#7565e7" : cellColor;
    const drawer = $("#detail-drawer");

    drawer.classList.add("is-grid-cell");
    $("#drawer-eyebrow").textContent = "MAP CELL DETAIL";
    $("#drawer-name").textContent = `全球网格 ${cellId}`;
    $("#drawer-code").textContent = `CELL · ${cellId}`;
    $("#drawer-status").textContent = "可接入区域";
    $("#drawer-region").textContent = `${mapCellRegion(x, y)} · Natural Earth 110m`;
    $("#drawer-glyph").textContent = "HEX";
    $("#drawer-token-label").textContent = "热度指数";
    $("#drawer-token").textContent = String(heat);
    $("#drawer-share").textContent = "演示热度评分";
    $("#drawer-requests-label").textContent = "Token 消耗";
    $("#drawer-requests").textContent = "0";
    $("#drawer-requests-meta").textContent = "未绑定实时数据";
    $("#drawer-success-label").textContent = "调用状态";
    $("#drawer-success").textContent = "待接入";
    $("#drawer-success-meta").textContent = "暂无 API 请求";
    $("#drawer-latency-label").textContent = "平均延迟";
    $("#drawer-latency").textContent = "—";
    $("#drawer-latency-meta").textContent = "接入 OEM 后可用";
    $("#drawer-cell-coordinates").textContent = `X ${x.toFixed(2)} · Y ${y.toFixed(2)}`;
    $("#drawer-cell-oem").textContent = "暂无绑定";
    $("#drawer-planet").style.setProperty("--drawer-color", accent);
    showDrawer(cell);
  }

  function closeDrawer() {
    const drawer = $("#detail-drawer");
    drawer.classList.remove("is-open");
    drawer.setAttribute("aria-hidden", "true");
    const trigger = state.drawerTrigger;
    state.drawerTrigger = null;
    if (trigger && document.contains(trigger) && typeof trigger.focus === "function") {
      window.requestAnimationFrame(() => trigger.focus({ preventScroll: true }));
    }
  }

  function stopUniverseLoop() {
    if (!universeFrameId) return;
    window.cancelAnimationFrame(universeFrameId);
    universeFrameId = 0;
  }

  function requestUniverseFrame() {
    if (universeFrameId || state.visualMode !== "universe" || document.hidden) return;
    universeFrameId = window.requestAnimationFrame(renderUniverse);
  }

  function resizeUniverse() {
    const rect = canvas.getBoundingClientRect();
    state.width = Math.max(1, rect.width);
    state.height = Math.max(1, rect.height);
    state.dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(state.width * state.dpr);
    canvas.height = Math.round(state.height * state.dpr);
    ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);

    const random = mulberry32(104729);
    const count = Math.floor((state.width * state.height) / 3900);
    state.stars = Array.from({ length: count }, () => ({
      x: random() * state.width,
      y: random() * state.height,
      size: 0.25 + random() * 1.05,
      alpha: 0.14 + random() * 0.5,
      phase: random() * Math.PI * 2,
      depth: 0.25 + random() * 0.9,
    }));
  }

  function projectWorld({ x, y, z }) {
    const centerX = state.width * 0.5;
    const centerY = state.height * 0.46;
    const { yaw, pitch, zoom } = state.camera;
    const cosYaw = Math.cos(yaw);
    const sinYaw = Math.sin(yaw);
    const cosPitch = Math.cos(pitch);
    const sinPitch = Math.sin(pitch);

    const rotatedX = x * cosYaw + z * sinYaw;
    const yawDepth = -x * sinYaw + z * cosYaw;
    const rotatedY = y * cosPitch - yawDepth * sinPitch;
    const depth = y * sinPitch + yawDepth * cosPitch;
    const cameraDistance = Math.max(520, Math.min(state.width, state.height) * 1.65);
    const perspective = clamp(cameraDistance / (cameraDistance - depth), 0.64, 1.55);
    const scale = perspective * zoom;

    return {
      x: centerX + rotatedX * scale,
      y: centerY + rotatedY * scale,
      z: depth,
      depth,
      perspective,
      scale,
      centerX,
      centerY,
    };
  }

  function universeSphereMetrics() {
    const minDimension = Math.min(state.width, state.height);
    return {
      inner: minDimension * 0.285,
      outer: minDimension * 0.39,
    };
  }

  function rotateAroundY(point, angle) {
    const cosine = Math.cos(angle);
    const sine = Math.sin(angle);
    return {
      x: point.x * cosine + point.z * sine,
      y: point.y,
      z: -point.x * sine + point.z * cosine,
    };
  }

  function nodePosition(node, time) {
    const directionX = (node.x - 0.5) * 2;
    const directionY = (node.y - 0.5) * 2;
    const directionZ = (node.z || 0) * 2;
    const directionLength = Math.hypot(directionX, directionY, directionZ) || 1;
    const { inner, outer } = universeSphereMetrics();
    const radius = node.orbit === 1 ? inner : outer;
    const worldPoint = rotateAroundY(
      {
        x: (directionX / directionLength) * radius,
        y: (directionY / directionLength) * radius,
        z: (directionZ / directionLength) * radius,
      },
      state.sphereRotation,
    );
    const position = projectWorld(worldPoint);

    if (state.running) {
      position.x += Math.sin(time * 0.00022 + node.x * 8.1) * 1.15;
      position.y += Math.cos(time * 0.00019 + node.y * 7.7) * 0.95;
    }

    return position;
  }

  function updateCamera(time) {
    const camera = state.camera;
    const elapsed = state.lastRenderTime ? clamp(time - state.lastRenderTime, 0, 32) : 16.67;
    const frameFactor = elapsed / 16.67;
    state.lastRenderTime = time;

    if (state.running) {
      state.sphereRotation = (state.sphereRotation + elapsed * 0.000035) % TAU;
      state.coreRotation = (state.coreRotation + elapsed * 0.00022) % TAU;
    }

    if (!camera.dragging) {
      if (state.running) {
        camera.yaw += camera.velocityYaw * frameFactor;
        camera.pitch += camera.velocityPitch * frameFactor;
        const friction = Math.pow(0.88, frameFactor);
        camera.velocityYaw *= friction;
        camera.velocityPitch *= friction;
        if (Math.abs(camera.velocityYaw) < 0.00005) camera.velocityYaw = 0;
        if (Math.abs(camera.velocityPitch) < 0.00005) camera.velocityPitch = 0;
      } else {
        camera.velocityYaw = 0;
        camera.velocityPitch = 0;
      }
    }

    if (Math.abs(camera.yaw) > TAU) camera.yaw %= TAU;
    camera.pitch = clamp(camera.pitch, -CAMERA_PITCH_LIMIT, CAMERA_PITCH_LIMIT);
    camera.zoom += (camera.targetZoom - camera.zoom) * Math.min(0.22, 0.11 * frameFactor);
    if (Math.abs(camera.targetZoom - camera.zoom) < 0.001) camera.zoom = camera.targetZoom;

  }

  function resetCamera() {
    Object.assign(state.camera, {
      yaw: -0.1,
      pitch: -0.14,
      zoom: 1,
      targetZoom: 1,
      velocityYaw: 0,
      velocityPitch: 0,
    });
    const button = $("#camera-reset");
    button.animate(
      [
        { transform: "rotate(0deg)", borderColor: "rgba(139,124,255,0.16)" },
        { transform: "rotate(-180deg)", borderColor: "rgba(53,217,255,0.46)" },
        { transform: "rotate(-360deg)", borderColor: "rgba(139,124,255,0.16)" },
      ],
      { duration: 420, easing: "cubic-bezier(.2,.8,.2,1)" },
    );
    requestUniverseFrame();
  }

  function drawStarfield(time) {
    ctx.clearRect(0, 0, state.width, state.height);

    const nebulaA = ctx.createRadialGradient(
      state.width * 0.52,
      state.height * 0.44,
      0,
      state.width * 0.52,
      state.height * 0.44,
      state.width * 0.36,
    );
    nebulaA.addColorStop(0, "rgba(117, 101, 231, 0.09)");
    nebulaA.addColorStop(0.35, "rgba(151, 139, 221, 0.035)");
    nebulaA.addColorStop(1, "rgba(117, 101, 231, 0)");
    ctx.fillStyle = nebulaA;
    ctx.fillRect(0, 0, state.width, state.height);

    const nebulaB = ctx.createRadialGradient(
      state.width * 0.72,
      state.height * 0.29,
      0,
      state.width * 0.72,
      state.height * 0.29,
      state.width * 0.19,
    );
    nebulaB.addColorStop(0, "rgba(69, 190, 220, 0.065)");
    nebulaB.addColorStop(1, "rgba(69, 190, 220, 0)");
    ctx.fillStyle = nebulaB;
    ctx.fillRect(0, 0, state.width, state.height);

    for (const star of state.stars) {
      const twinkle = state.running ? Math.sin(time * 0.0012 * star.depth + star.phase) * 0.15 : 0;
      const parallaxX = state.camera.yaw * 38 * star.depth;
      const parallaxY = state.camera.pitch * 28 * star.depth;
      const x = ((star.x + parallaxX) % state.width + state.width) % state.width;
      const y = ((star.y + parallaxY) % state.height + state.height) % state.height;
      ctx.beginPath();
      ctx.arc(x, y, Math.max(0.2, star.size + twinkle * 0.2), 0, Math.PI * 2);
      const starAlpha = clamp((star.alpha + twinkle) * 0.2, 0.025, 0.13);
      ctx.fillStyle = `rgba(105, 96, 170, ${starAlpha})`;
      ctx.fill();
    }
  }

  function sphereCurvePoint(plane, angle, radius) {
    if (plane === "xy") {
      return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius, z: 0 };
    }
    if (plane === "xz") {
      return { x: Math.cos(angle) * radius, y: 0, z: Math.sin(angle) * radius };
    }
    return { x: 0, y: Math.cos(angle) * radius, z: Math.sin(angle) * radius };
  }

  function drawSphereCurve(radius, plane, frontColor, backColor, dashOffset = 0) {
    const segments = 96;
    const points = Array.from({ length: segments + 1 }, (_, index) => {
      const angle = (index / segments) * TAU;
      const point = rotateAroundY(sphereCurvePoint(plane, angle, radius), state.sphereRotation);
      return projectWorld(point);
    });

    ctx.save();
    ctx.setLineDash([2, 7]);
    ctx.lineDashOffset = dashOffset;
    ctx.lineWidth = 0.72;

    const strokeHalf = (front) => {
      ctx.strokeStyle = front ? frontColor : backColor;
      ctx.beginPath();
      for (let index = 1; index < points.length; index += 1) {
        const previous = points[index - 1];
        const current = points[index];
        const isFront = (previous.depth + current.depth) * 0.5 >= 0;
        if (isFront !== front) continue;
        ctx.moveTo(previous.x, previous.y);
        ctx.lineTo(current.x, current.y);
      }
      ctx.stroke();
    };

    strokeHalf(false);
    strokeHalf(true);
    ctx.restore();
  }

  function drawSphereDust(radius) {
    const count = 46;
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));

    for (let index = 0; index < count; index += 1) {
      const vertical = 1 - ((index + 0.5) / count) * 2;
      const horizontalRadius = Math.sqrt(Math.max(0, 1 - vertical * vertical));
      const longitude = index * goldenAngle;
      const localPoint = {
        x: Math.cos(longitude) * horizontalRadius * radius,
        y: vertical * radius,
        z: Math.sin(longitude) * horizontalRadius * radius,
      };
      const point = projectWorld(rotateAroundY(localPoint, state.sphereRotation));
      const depthRatio = clamp(point.depth / radius, -1, 1);
      const alpha = 0.045 + (depthRatio + 1) * 0.042;
      ctx.fillStyle = depthRatio >= 0
        ? `rgba(117, 101, 231, ${alpha})`
        : `rgba(69, 190, 220, ${alpha * 0.55})`;
      ctx.beginPath();
      ctx.arc(point.x, point.y, clamp(point.scale * 0.62, 0.38, 0.9), 0, TAU);
      ctx.fill();
    }
  }

  function drawOrbits(time) {
    const { inner, outer } = universeSphereMetrics();
    const motion = state.running ? state.sphereRotation * 28 : 0;

    ctx.save();
    ctx.strokeStyle = "rgba(117,101,231,0.085)";
    ctx.lineWidth = 0.72;
    ctx.setLineDash([1.5, 7]);
    ctx.beginPath();
    ctx.arc(
      state.width * 0.5,
      state.height * 0.46,
      outer * state.camera.zoom * 1.035,
      0,
      TAU,
    );
    ctx.stroke();
    ctx.restore();

    drawSphereDust(outer);
    drawSphereCurve(outer, "xy", "rgba(117,101,231,0.2)", "rgba(117,101,231,0.06)", -motion);
    drawSphereCurve(outer, "xz", "rgba(69,190,220,0.16)", "rgba(69,190,220,0.05)", motion * 0.62);
    drawSphereCurve(outer, "yz", "rgba(117,101,231,0.15)", "rgba(117,101,231,0.05)", -motion * 0.8);
    drawSphereCurve(inner, "xz", "rgba(160,145,239,0.11)", "rgba(160,145,239,0.035)", motion * 0.45);
  }

  function drawCore(time) {
    const x = state.width * 0.5;
    const y = state.height * 0.46;
    const pulse = state.running ? Math.sin(time * 0.0014) * 2 : 0;
    const minDimension = Math.min(state.width, state.height);
    const coreRadius = clamp(minDimension * 0.055, 28, 38);
    const phase = state.coreRotation + state.camera.yaw * 0.72;
    const tilt = clamp(state.camera.pitch * 0.34, -0.38, 0.38);

    const glowRadius = coreRadius * 2.8 + pulse;
    const glow = ctx.createRadialGradient(x, y, 0, x, y, glowRadius);
    glow.addColorStop(0, "rgba(117,101,231,0.42)");
    glow.addColorStop(0.08, "rgba(185,174,255,0.38)");
    glow.addColorStop(0.32, "rgba(120,98,255,0.12)");
    glow.addColorStop(1, "rgba(90,70,210,0)");
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(x, y, glowRadius, 0, TAU);
    ctx.fill();

    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(phase * 0.34 + tilt);
    ctx.strokeStyle = "rgba(182,170,255,0.2)";
    ctx.lineWidth = 0.8;
    ctx.setLineDash([4, 5]);
    ctx.beginPath();
    ctx.ellipse(0, 0, coreRadius * 2.05, coreRadius * 0.58, -0.27, 0, TAU);
    ctx.stroke();
    ctx.rotate(-phase * 0.67);
    ctx.strokeStyle = "rgba(53,217,255,0.14)";
    ctx.setLineDash([2, 6]);
    ctx.beginPath();
    ctx.ellipse(0, 0, coreRadius * 1.65, coreRadius * 0.46, 0.48, 0, TAU);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.strokeStyle = "rgba(53,217,255,0.14)";
    ctx.beginPath();
    ctx.arc(0, 0, coreRadius * 1.48, 0, TAU);
    ctx.stroke();
    ctx.restore();

    const sphere = ctx.createRadialGradient(
      x - coreRadius * 0.36,
      y - coreRadius * 0.4,
      coreRadius * 0.1,
      x,
      y,
      coreRadius * 1.08,
    );
    sphere.addColorStop(0, "#ffffff");
    sphere.addColorStop(0.16, "#ded8ff");
    sphere.addColorStop(0.45, "#aa9af4");
    sphere.addColorStop(0.78, "#7662dc");
    sphere.addColorStop(1, "#5544a4");
    ctx.fillStyle = sphere;
    ctx.beginPath();
    ctx.arc(x, y, coreRadius + pulse * 0.14, 0, TAU);
    ctx.fill();

    ctx.save();
    ctx.beginPath();
    ctx.arc(x, y, coreRadius - 0.4, 0, TAU);
    ctx.clip();
    ctx.translate(x, y);
    ctx.rotate(tilt);

    for (let index = 0; index < 3; index += 1) {
      const meridianPhase = phase + (index / 3) * TAU;
      const meridianWidth = coreRadius * (0.09 + Math.abs(Math.cos(meridianPhase)) * 0.78);
      const meridianOffset = Math.sin(meridianPhase) * coreRadius * 0.12;
      ctx.strokeStyle = index === 1
        ? "rgba(70,226,255,0.23)"
        : "rgba(241,237,255,0.25)";
      ctx.lineWidth = index === 1 ? 0.75 : 0.58;
      ctx.beginPath();
      ctx.ellipse(meridianOffset, 0, meridianWidth, coreRadius * 1.1, 0, 0, TAU);
      ctx.stroke();
    }

    for (let index = -1; index <= 1; index += 1) {
      const latitudeY = index * coreRadius * 0.38 + Math.sin(phase * 1.3 + index) * coreRadius * 0.035;
      const latitudeScale = Math.sqrt(Math.max(0.18, 1 - (latitudeY / coreRadius) ** 2));
      ctx.strokeStyle = index === 0
        ? "rgba(255,255,255,0.22)"
        : "rgba(158,233,255,0.16)";
      ctx.lineWidth = index === 0 ? 0.72 : 0.52;
      ctx.beginPath();
      ctx.ellipse(0, latitudeY, coreRadius * latitudeScale, coreRadius * 0.15 * latitudeScale, 0, 0, TAU);
      ctx.stroke();
    }

    const sweepX = Math.sin(phase) * coreRadius * 1.1;
    const sweep = ctx.createLinearGradient(sweepX - coreRadius * 0.42, 0, sweepX + coreRadius * 0.42, 0);
    sweep.addColorStop(0, "rgba(255,255,255,0)");
    sweep.addColorStop(0.5, "rgba(255,255,255,0.16)");
    sweep.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = sweep;
    ctx.fillRect(-coreRadius * 1.2, -coreRadius * 1.2, coreRadius * 2.4, coreRadius * 2.4);
    ctx.restore();

    ctx.save();
    ctx.shadowBlur = 15;
    ctx.shadowColor = "rgba(139,124,255,0.7)";
    ctx.strokeStyle = "rgba(209,201,255,0.62)";
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    ctx.arc(x, y, coreRadius + 4 + pulse * 0.2, 0, TAU);
    ctx.stroke();
    ctx.restore();

    ctx.textAlign = "center";
    ctx.fillStyle = "rgba(249,248,255,0.96)";
    ctx.font = `700 ${clamp(coreRadius * 0.29, 8, 11)}px Inter, system-ui, sans-serif`;
    ctx.fillText("NEXUS", x, y + coreRadius * 0.06);
    ctx.fillStyle = "rgba(194,185,255,0.65)";
    ctx.font = `500 ${clamp(coreRadius * 0.18, 5, 7)}px Inter, system-ui, sans-serif`;
    ctx.fillText("CORE", x, y + coreRadius * 0.36);
  }

  function drawConnection(node, position, time) {
    const { x, y, centerX, centerY } = position;
    const isVisible =
      state.filter === "all" ||
      (state.filter === "active" && node.status === "active") ||
      (state.filter === "warning" && node.status === "warning");
    const emphasis = state.hoveredId === node.id || state.selectedId === node.id;
    const depthFactor = clamp(0.5 + position.perspective * 0.48, 0.58, 1.12);
    const alpha = (isVisible ? (emphasis ? 0.54 : 0.2) : 0.02) * depthFactor;

    const gradient = ctx.createLinearGradient(centerX, centerY, x, y);
    gradient.addColorStop(0, `rgba(139,124,255,${alpha * 0.55})`);
    gradient.addColorStop(0.52, hexToRgba(node.color, alpha));
    gradient.addColorStop(1, hexToRgba(node.color, alpha * 0.15));
    ctx.save();
    ctx.strokeStyle = gradient;
    ctx.lineWidth = (emphasis ? 1.15 : 0.7) * clamp(position.scale, 0.72, 1.35);
    ctx.beginPath();
    ctx.moveTo(centerX, centerY);
    const bendX = (centerX + x) / 2 + (y - centerY) * 0.07;
    const bendY = (centerY + y) / 2 - (x - centerX) * 0.035;
    ctx.quadraticCurveTo(bendX, bendY, x, y);
    ctx.stroke();
    ctx.restore();

    if (state.running && isVisible && node.status !== "offline") {
      const progress = (time * 0.00011 + node.x * 1.9) % 1;
      const inverse = 1 - progress;
      const dotX = inverse * inverse * centerX + 2 * inverse * progress * bendX + progress * progress * x;
      const dotY = inverse * inverse * centerY + 2 * inverse * progress * bendY + progress * progress * y;
      ctx.save();
      ctx.shadowBlur = 8;
      ctx.shadowColor = node.color;
      ctx.fillStyle = hexToRgba(node.accent, emphasis ? 0.98 : 0.72);
      ctx.beginPath();
      ctx.arc(dotX, dotY, (emphasis ? 1.8 : 1.25) * clamp(position.scale, 0.75, 1.35), 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
  }

  function drawPlanet(node, position, time) {
    const { x, y } = position;
    const visible =
      state.filter === "all" ||
      (state.filter === "active" && node.status === "active") ||
      (state.filter === "warning" && node.status === "warning");
    const selected = state.selectedId === node.id;
    const hovered = state.hoveredId === node.id;
    const depthAlpha = clamp(0.48 + position.perspective * 0.48, 0.56, 1);
    const alpha = visible ? depthAlpha : 0.12;
    const radius = (node.size + (hovered ? 2 : 0)) * position.scale;
    const fontScale = clamp(Math.sqrt(position.scale), 0.82, 1.18);
    const pulse = state.running ? Math.sin(time * 0.002 + node.x * 11) : 0;

    ctx.save();
    ctx.globalAlpha = alpha;

    if (selected || hovered) {
      ctx.strokeStyle = hexToRgba(node.color, selected ? 0.42 : 0.28);
      ctx.lineWidth = 1;
      ctx.setLineDash(selected ? [3, 4] : []);
      ctx.beginPath();
      ctx.arc(x, y, radius + 9 * position.scale + pulse, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    if (node.status !== "offline") {
      const glow = ctx.createRadialGradient(x, y, 0, x, y, radius * 2.2);
      glow.addColorStop(0, hexToRgba(node.color, 0.26));
      glow.addColorStop(1, hexToRgba(node.color, 0));
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(x, y, radius * 2.2, 0, Math.PI * 2);
      ctx.fill();
    }

    if (node.size >= 14 || selected) {
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(-0.25);
      ctx.strokeStyle = hexToRgba(node.accent, selected ? 0.5 : 0.24);
      ctx.lineWidth = (selected ? 1 : 0.7) * clamp(position.scale, 0.75, 1.3);
      ctx.beginPath();
      ctx.ellipse(0, 0, radius * 1.62, radius * 0.35, 0, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }

    const sphere = ctx.createRadialGradient(x - radius * 0.35, y - radius * 0.38, 1, x, y, radius);
    sphere.addColorStop(0, node.accent);
    sphere.addColorStop(0.18, node.color);
    sphere.addColorStop(0.68, hexToRgba(node.color, 0.6));
    sphere.addColorStop(1, "#4d486b");
    ctx.fillStyle = sphere;
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = hexToRgba(node.accent, 0.32);
    ctx.lineWidth = 0.55 * clamp(position.scale, 0.75, 1.3);
    ctx.beginPath();
    ctx.arc(x, y, radius + 0.7, 0, Math.PI * 2);
    ctx.stroke();

    const statusColor = node.status === "active" ? "#27bd78" : node.status === "warning" ? "#f39a50" : "#a9acbf";
    ctx.shadowBlur = 6;
    ctx.shadowColor = statusColor;
    ctx.fillStyle = statusColor;
    ctx.beginPath();
    ctx.arc(x + radius * 0.78, y - radius * 0.78, 2.2 * clamp(position.scale, 0.75, 1.3), 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;

    const backLabelAlpha = position.depth < 0 && !selected && !hovered ? 0.58 : 1;
    ctx.globalAlpha = alpha * backLabelAlpha;
    ctx.textAlign = "center";
    ctx.fillStyle = selected ? "rgba(51,52,78,0.98)" : "rgba(79,81,108,0.88)";
    ctx.font = `${selected ? 600 : 500} ${(selected ? 9 : 8) * fontScale}px ${canvasFontFamily}`;
    ctx.fillText(node.name, x, y + radius + 14 * fontScale);
    ctx.fillStyle = "rgba(139,142,164,0.9)";
    ctx.font = `500 ${6 * fontScale}px ${canvasFontFamily}`;
    ctx.fillText(node.code, x, y + radius + 23 * fontScale);
    ctx.restore();
  }

  function spawnBirthParticles(node) {
    const random = mulberry32(Date.now() % 100000);
    state.particles = Array.from({ length: 34 }, () => {
      const angle = random() * Math.PI * 2;
      const speed = 0.35 + random() * 1.6;
      return {
        offsetX: 0,
        offsetY: 0,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: 1,
        size: 0.8 + random() * 1.8,
        color: random() > 0.25 ? node.color : "#b9afea",
      };
    });
  }

  function drawBirth(time) {
    if (!state.birth) return;
    const node = state.nodes.find((item) => item.id === state.birth.id);
    if (!node) return;
    const elapsed = time - state.birth.startedAt;
    const progress = Math.min(1, elapsed / 2600);
    const position = nodePosition(node, time);

    ctx.save();
    ctx.globalAlpha = 1 - progress;
    ctx.strokeStyle = hexToRgba(node.color, 0.8);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(position.x, position.y, (10 + progress * 65) * position.scale, 0, Math.PI * 2);
    ctx.stroke();
    ctx.strokeStyle = hexToRgba(node.accent, 0.45);
    ctx.beginPath();
    ctx.arc(position.x, position.y, (5 + progress * 38) * position.scale, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();

    for (const particle of state.particles) {
      particle.offsetX += particle.vx;
      particle.offsetY += particle.vy;
      particle.vx *= 0.985;
      particle.vy *= 0.985;
      particle.life *= 0.974;
      ctx.fillStyle = hexToRgba(particle.color, particle.life);
      ctx.beginPath();
      ctx.arc(
        position.x + particle.offsetX * position.scale,
        position.y + particle.offsetY * position.scale,
        particle.size * particle.life * position.scale,
        0,
        Math.PI * 2,
      );
      ctx.fill();
    }

    state.particles = state.particles.filter((particle) => particle.life > 0.05);
    if (elapsed > 2800) state.birth = null;
  }

  function renderUniverse(time = performance.now()) {
    universeFrameId = 0;
    if (state.visualMode !== "universe" || document.hidden) return;

    if (state.running && time - lastUniverseFrame < UNIVERSE_FRAME_INTERVAL) {
      requestUniverseFrame();
      return;
    }
    lastUniverseFrame = time;

    updateCamera(time);
    drawStarfield(time);
    drawOrbits(time);

    state.projectedNodes = state.nodes
      .map((node) => ({ node, position: nodePosition(node, time) }))
      .sort((left, right) => left.position.depth - right.position.depth);

    for (const item of state.projectedNodes) {
      drawConnection(item.node, item.position, time);
    }
    for (const item of state.projectedNodes) {
      if (item.position.depth < 0) drawPlanet(item.node, item.position, time);
    }
    for (const item of state.projectedNodes) {
      if (item.position.depth >= 0) drawPlanet(item.node, item.position, time);
    }
    drawCore(time);
    drawBirth(time);

    const cameraSettling =
      Math.abs(state.camera.targetZoom - state.camera.zoom) > 0.001 ||
      Math.abs(state.camera.velocityYaw) > 0.00005 ||
      Math.abs(state.camera.velocityPitch) > 0.00005;
    if (state.running || state.camera.dragging || state.birth || cameraSettling) requestUniverseFrame();
  }

  function resizeTrend() {
    const rect = trendCanvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    trendCanvas.width = Math.round(rect.width * dpr);
    trendCanvas.height = Math.round(rect.height * dpr);
    trendCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawTrend(rect.width, rect.height);
  }

  function drawTrend(width, height) {
    // 真实模式：用母舰的 24 小时逐小时消耗；演示模式保持原曲线
    const realMode = REAL_TREND && REAL_TREND.length;
    const values = realMode
      ? REAL_TREND
      : [5.2, 5.8, 5.1, 6.4, 6.2, 7.1, 6.8, 8.4, 8.1, 9.2, 8.8, 10.5, 9.7, 11.1, 10.7, 12.2, 11.8, 13.3, 12.7, 14.2, 13.5, 13.8, 13.2, 13.9];
    const min = realMode ? 0 : 4.4;
    const max = realMode ? Math.max(...values, 1) : 15;
    const points = values.map((value, index) => ({
      x: (index / (values.length - 1)) * width,
      y: height - ((value - min) / (max - min)) * height,
    }));

    trendCtx.clearRect(0, 0, width, height);
    trendCtx.strokeStyle = "rgba(166,175,255,0.06)";
    trendCtx.lineWidth = 1;
    for (let i = 1; i <= 2; i += 1) {
      const y = (height / 3) * i;
      trendCtx.beginPath();
      trendCtx.moveTo(0, y);
      trendCtx.lineTo(width, y);
      trendCtx.stroke();
    }

    const fill = trendCtx.createLinearGradient(0, 0, 0, height);
    fill.addColorStop(0, "rgba(139,124,255,0.22)");
    fill.addColorStop(1, "rgba(139,124,255,0)");
    trendCtx.beginPath();
    trendCtx.moveTo(points[0].x, height);
    for (const point of points) trendCtx.lineTo(point.x, point.y);
    trendCtx.lineTo(points.at(-1).x, height);
    trendCtx.closePath();
    trendCtx.fillStyle = fill;
    trendCtx.fill();

    const line = trendCtx.createLinearGradient(0, 0, width, 0);
    line.addColorStop(0, "#695bd4");
    line.addColorStop(0.7, "#9d8fff");
    line.addColorStop(1, "#35d9ff");
    trendCtx.strokeStyle = line;
    trendCtx.lineWidth = 1.5;
    trendCtx.lineJoin = "round";
    trendCtx.beginPath();
    points.forEach((point, index) => {
      if (index === 0) trendCtx.moveTo(point.x, point.y);
      else trendCtx.lineTo(point.x, point.y);
    });
    trendCtx.stroke();

    const last = points.at(-1);
    trendCtx.shadowBlur = 8;
    trendCtx.shadowColor = "#35d9ff";
    trendCtx.fillStyle = "#baf5ff";
    trendCtx.beginPath();
    trendCtx.arc(last.x - 1.5, last.y, 2.2, 0, Math.PI * 2);
    trendCtx.fill();
    trendCtx.shadowBlur = 0;
  }

  function refreshTotals() {
    const total = state.nodes.reduce((sum, node) => sum + node.token, 0);
    // 配额口径：真实模式=已消耗/总发放(grant+topup)；演示模式维持 34.5B 假配额
    const realTotals = REAL_SUMMARY && REAL_SUMMARY.totals;
    const quota = realTotals
      ? Math.max((realTotals.granted_total || 0) / TOKEN_UNIT.div, total, 0.01)
      : 34.5;
    const percentage = Math.min(100, (total / quota) * 100);
    const formattedNodeCount = String(state.nodes.length).padStart(2, "0");
    const formattedOverviewOemCount = String(state.nodes.length).padStart(7, "0");
    const onlineNodeCount = state.nodes.filter((node) => node.status !== "offline").length;
    const overviewOemTotal = $("#overview-oem-total");
    const totalChanged = overviewOemTotal.textContent !== formattedOverviewOemCount;
    $("#total-token").textContent = total.toFixed(2);
    // 单位标签与今日消耗跟随当前单位（真实模式 K/M/B 自适应；演示模式维持 B）
    const unitEl = $("#total-token").nextElementSibling;
    if (unitEl) unitEl.textContent = TOKEN_UNIT.label;
    const todaySum = state.nodes.reduce((sum, node) => sum + (node.today || 0), 0);
    $("#today-token").textContent = `${todaySum.toFixed(2)}${TOKEN_UNIT.label}`;
    $("#node-count").textContent = formattedNodeCount;
    overviewOemTotal.textContent = formattedOverviewOemCount;
    $("#map-node-summary").textContent = REAL_SUMMARY
      ? `${state.nodes.length} 个接入实例 · 在线 ${onlineNodeCount}`
      : `${state.nodes.length} 个区域节点 · 覆盖 6 大洲`;
    if (totalChanged && state.running) {
      overviewOemTotal.animate(
        [
          { opacity: 0.42, transform: "translateY(4px) scale(0.82)" },
          { opacity: 1, transform: "translateY(-1px) scale(1.08)" },
          { opacity: 1, transform: "translateY(0) scale(1)" },
        ],
        { duration: 420, easing: "cubic-bezier(0.2, 0.82, 0.2, 1)" },
      );
    }
    $("#online-count").textContent = String(onlineNodeCount).padStart(2, "0");
    $("#overview-oem-online").textContent = String(onlineNodeCount).padStart(2, "0");
    $("#overview-oem-online-rate").textContent =
      `${((onlineNodeCount / state.nodes.length) * 100).toFixed(1)}%`;
    $("#quota-percent").textContent = `${Math.round(percentage)}%`;
    $("#quota-bar").style.width = `${percentage.toFixed(1)}%`;
    $("#quota-used").textContent =
      `已使用 ${total.toFixed(2)}${TOKEN_UNIT.label} / ${quota.toFixed(2)}${TOKEN_UNIT.label}`;
  }

  function addActivity(node) {
    const list = $("#activity-list");
    const article = document.createElement("article");
    article.innerHTML = `
      <span class="activity-icon activity-icon--success">
        <svg viewBox="0 0 20 20"><path d="M10 4v12M4 10h12"></path></svg>
      </span>
      <div>
        <p><strong>${node.name}</strong> 新节点完成接入</p>
        <small>刚刚 · ${node.region}</small>
      </div>
    `;
    list.prepend(article);
    while (list.children.length > 3) list.lastElementChild.remove();
  }

  function birthOEM() {
    if (state.birthIndex >= BIRTH_CANDIDATES.length) {
      state.birthIndex = 0;
    }
    const candidate = BIRTH_CANDIDATES[state.birthIndex];
    const uniqueId = `${candidate.code.toLowerCase()}-${Date.now()}`;
    const node = { ...candidate, id: uniqueId };
    state.birthIndex += 1;
    state.nodes.push(node);
    state.filter = "all";
    $$(".view-switch button").forEach((button) => button.classList.toggle("is-active", button.dataset.filter === "all"));
    updateMapFilters();
    switchVisualMode("universe");
    state.birth = { id: uniqueId, startedAt: performance.now() };
    spawnBirthParticles(node);
    state.selectedId = uniqueId;
    requestUniverseFrame();
    updateInspector(node);
    renderRanking();
    refreshTotals();
    addActivity(node);

    $("#birth-toast-name").textContent = `${node.name} 已成为第 ${state.nodes.length} 个节点`;
    const toast = $("#birth-toast");
    toast.classList.add("is-visible");
    window.setTimeout(() => toast.classList.remove("is-visible"), 3200);
  }

  function canvasPointer(event) {
    const rect = canvas.getBoundingClientRect();
    const pointer = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    let hit = null;

    for (let index = state.projectedNodes.length - 1; index >= 0; index -= 1) {
      const item = state.projectedNodes[index];
      const matchesFilter =
        state.filter === "all" ||
        (state.filter === "active" && item.node.status === "active") ||
        (state.filter === "warning" && item.node.status === "warning");
      if (!matchesFilter) continue;
      const distance = Math.hypot(pointer.x - item.position.x, pointer.y - item.position.y);
      if (distance <= (item.node.size + 10) * item.position.scale) {
        hit = item.node;
        break;
      }
    }

    state.hoveredId = hit?.id ?? null;
    canvas.style.cursor = state.camera.dragging ? "grabbing" : hit ? "pointer" : "grab";
    return hit;
  }

  function finishCameraDrag(event, cancelled = false) {
    const camera = state.camera;
    if (!camera.dragging || event.pointerId !== camera.pointerId) return;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    camera.dragging = false;
    camera.pointerId = null;
    canvas.classList.remove("is-dragging");

    if (!state.running || cancelled) {
      camera.velocityYaw = 0;
      camera.velocityPitch = 0;
    }

    if (!camera.moved && !cancelled) {
      const hit = canvasPointer(event);
      if (hit) selectNode(hit.id);
    } else {
      state.hoveredId = null;
      canvas.style.cursor = "grab";
    }
    requestUniverseFrame();
  }

  function initInteractions() {
    canvas.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || state.camera.dragging) return;
      const camera = state.camera;
      camera.dragging = true;
      camera.moved = false;
      camera.pointerId = event.pointerId;
      camera.startX = event.clientX;
      camera.startY = event.clientY;
      camera.lastX = event.clientX;
      camera.lastY = event.clientY;
      camera.velocityYaw = 0;
      camera.velocityPitch = 0;
      state.hoveredId = null;
      canvas.setPointerCapture(event.pointerId);
      canvas.classList.add("is-dragging");
      canvas.focus({ preventScroll: true });
      requestUniverseFrame();
      event.preventDefault();
    });

    canvas.addEventListener("pointermove", (event) => {
      const camera = state.camera;
      if (!camera.dragging || event.pointerId !== camera.pointerId) {
        canvasPointer(event);
        return;
      }

      const deltaX = event.clientX - camera.lastX;
      const deltaY = event.clientY - camera.lastY;
      const yawDelta = deltaX * 0.0042;
      const pitchDelta = deltaY * 0.003;
      camera.yaw += yawDelta;
      camera.pitch = clamp(camera.pitch + pitchDelta, -CAMERA_PITCH_LIMIT, CAMERA_PITCH_LIMIT);
      camera.velocityYaw = clamp(camera.velocityYaw * 0.6 + yawDelta * 0.12, -0.035, 0.035);
      camera.velocityPitch = clamp(camera.velocityPitch * 0.6 + pitchDelta * 0.12, -0.024, 0.024);
      camera.lastX = event.clientX;
      camera.lastY = event.clientY;
      camera.moved ||= Math.hypot(event.clientX - camera.startX, event.clientY - camera.startY) > 5;
      requestUniverseFrame();
      event.preventDefault();
    });

    canvas.addEventListener("pointerup", (event) => finishCameraDrag(event));
    canvas.addEventListener("pointercancel", (event) => finishCameraDrag(event, true));
    canvas.addEventListener("pointerleave", () => {
      if (state.camera.dragging) return;
      state.hoveredId = null;
      canvas.style.cursor = "grab";
      requestUniverseFrame();
    });

    canvas.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        const zoomFactor = Math.exp(-event.deltaY * 0.001);
        state.camera.targetZoom = clamp(state.camera.targetZoom * zoomFactor, 0.74, 1.38);
        requestUniverseFrame();
      },
      { passive: false },
    );

    canvas.addEventListener("keydown", (event) => {
      let handled = true;
      state.camera.velocityYaw = 0;
      state.camera.velocityPitch = 0;
      if (event.key === "ArrowLeft") state.camera.yaw -= 0.12;
      else if (event.key === "ArrowRight") state.camera.yaw += 0.12;
      else if (event.key === "ArrowUp") {
        state.camera.pitch = clamp(state.camera.pitch - 0.1, -CAMERA_PITCH_LIMIT, CAMERA_PITCH_LIMIT);
      } else if (event.key === "ArrowDown") {
        state.camera.pitch = clamp(state.camera.pitch + 0.1, -CAMERA_PITCH_LIMIT, CAMERA_PITCH_LIMIT);
      }
      else if (event.key === "+" || event.key === "=") state.camera.targetZoom = clamp(state.camera.targetZoom + 0.08, 0.74, 1.38);
      else if (event.key === "-" || event.key === "_") state.camera.targetZoom = clamp(state.camera.targetZoom - 0.08, 0.74, 1.38);
      else if (event.key === "0" || event.key.toLowerCase() === "r") resetCamera();
      else handled = false;
      if (handled) {
        requestUniverseFrame();
        event.preventDefault();
      }
    });

    $("#add-oem").addEventListener("click", birthOEM);
    $("#camera-reset").addEventListener("click", resetCamera);
    $("#inspect-detail").addEventListener("click", () => openDrawer());
    $("#drawer-close").addEventListener("click", closeDrawer);
    $("#drawer-backdrop").addEventListener("click", closeDrawer);

    const mapCellLayer = $("#world-hex-cells");
    const mapCellFromTarget = (target) =>
      target instanceof Element ? target.closest(".world-hex-cell") : null;

    mapCellLayer.addEventListener("pointerover", (event) => {
      const cell = mapCellFromTarget(event.target);
      if (cell && mapCellLayer.contains(cell)) showMapCellHover(cell, event);
    });

    mapCellLayer.addEventListener("pointermove", (event) => {
      if (hoveredMapCell) scheduleMapCellTooltip(event);
    });

    mapCellLayer.addEventListener("pointerout", (event) => {
      const cell = mapCellFromTarget(event.target);
      if (!cell || hoveredMapCell !== cell) return;
      const nextCell = mapCellFromTarget(event.relatedTarget);
      if (nextCell && mapCellLayer.contains(nextCell)) return;
      clearMapCellHover();
    });

    mapCellLayer.addEventListener("click", (event) => {
      const cell = mapCellFromTarget(event.target);
      if (!cell || !mapCellLayer.contains(cell)) return;
      activateMapCell(cell);
    });

    $$(".visual-switch button").forEach((button) => {
      button.addEventListener("click", () => switchVisualMode(button.dataset.visualMode));
    });

    $$(".geo-node").forEach((marker) => {
      marker.addEventListener("click", () => selectNode(marker.dataset.nodeId));
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeDrawer();
    });
    window.addEventListener("blur", () => {
      clearMapCellHover();
      if (!state.camera.dragging) return;
      state.camera.dragging = false;
      state.camera.pointerId = null;
      state.camera.velocityYaw = 0;
      state.camera.velocityPitch = 0;
      canvas.classList.remove("is-dragging");
      canvas.style.cursor = "grab";
    });

    $$(".view-switch button").forEach((button) => {
      button.addEventListener("click", () => {
        state.filter = button.dataset.filter;
        $$(".view-switch button").forEach((item) => item.classList.toggle("is-active", item === button));
        updateMapFilters();
      });
    });

    $("#motion-toggle").addEventListener("click", (event) => {
      state.running = !state.running;
      document.body.classList.toggle("motion-paused", !state.running);
      if (state.running) {
        scheduleMapCalloutRotation();
        scheduleOverviewCarousel();
        requestUniverseFrame();
      } else {
        window.clearTimeout(mapCalloutTimer);
        clearOverviewCarouselTimer();
        stopUniverseLoop();
      }
      const button = event.currentTarget;
      button.setAttribute("aria-label", state.running ? "暂停动态效果" : "继续动态效果");
      button.setAttribute("title", state.running ? "暂停动态效果" : "继续动态效果");
      button.innerHTML = state.running
        ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6v12M16 6v12"></path></svg>'
        : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 10 7-10 7Z"></path></svg>';
    });

    $("#fullscreen-toggle").addEventListener("click", async () => {
      try {
        if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
        else await document.exitFullscreen();
      } catch {
        // Fullscreen may be blocked in embedded previews. The rest of the dashboard stays functional.
      }
    });

    $("#ranking-sort").addEventListener("click", () => {
      $("#ranking-list").animate(
        [
          { opacity: 0.55, transform: "translateY(3px)" },
          { opacity: 1, transform: "translateY(0)" },
        ],
        { duration: 260, easing: "ease-out" },
      );
      renderRanking();
    });
    $("#ranking-scroll-up").addEventListener("click", () => scrollRanking(-1));
    $("#ranking-scroll-down").addEventListener("click", () => scrollRanking(1));
    $("#ranking-list").addEventListener("scroll", updateRankingScrollControls, { passive: true });

    $("#capacity-detail").addEventListener("click", () => {
      const card = $(".capacity-card");
      card.animate(
        [
          { borderColor: "rgba(139,124,255,0.12)" },
          { borderColor: "rgba(139,124,255,0.46)" },
          { borderColor: "rgba(139,124,255,0.12)" },
        ],
        { duration: 680, easing: "ease-out" },
      );
    });

    window.addEventListener("resize", () => {
      if (state.visualMode === "universe") {
        resizeUniverse();
        requestUniverseFrame();
      }
      resizeTrend();
      positionMapCallouts();
      if (isMapMode()) rotateMapCallouts({ schedule: false });
      updateRankingScrollControls();
    });

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        stopUniverseLoop();
        window.clearTimeout(mapCalloutTimer);
        clearOverviewCarouselTimer();
      } else {
        if (state.visualMode === "universe") {
          resizeUniverse();
          requestUniverseFrame();
        }
        scheduleMapCalloutRotation();
        scheduleOverviewCarousel();
      }
    });
  }

  function initLiveMetrics() {
    // 真实模式：显示真实的今日网关调用数，不跑随机数动画
    if (REAL_SUMMARY) {
      $("#live-rps").textContent =
        (REAL_SUMMARY.totals.requests_today || 0).toLocaleString("en-US");
      return;
    }
    window.setInterval(() => {
      const rps = 12840 + Math.round(Math.sin(Date.now() / 5700) * 280 + Math.random() * 90);
      $("#live-rps").textContent = rps.toLocaleString("en-US");
    }, 2200);
  }

  async function init() {
    initClock();
    // 先尝试接入真实舰队数据（GuDuu Nexus）；成功则本页进入真实模式并定时刷新
    const usingRealData = await loadFleetData();
    if (usingRealData) startFleetRefresh();
    await renderMapDecorations();
    renderRealGeoMarkers();   // 真实实例接管地图标记（演示件在此被替换掉）
    renderRanking();
    updateInspector(state.nodes[0], true);
    refreshTotals();
    updateMapSelection();
    updateMapFilters();
    initOverviewCarousel();
    initInteractions();
    switchVisualMode("global");
    observeMapStageSize();
    resizeTrend();
    initLiveMetrics();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      void init();
    });
  } else {
    void init();
  }
})();
