"use strict";
const $ = (id) => document.getElementById(id);
const pct = (v, digits = 2) => `${(Number(v) * 100).toFixed(digits)}%`;
const number = (v, digits = 2) => Number(v).toLocaleString("zh-CN", {maximumFractionDigits: digits, minimumFractionDigits: digits});
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]));
let currentRun = "original", result = null, activeTab = "orders", page = 1, pages = 1;
let catalogLoaded = false, pendingRun = null, tableRequest = 0;
const descriptions = {
  low_vol_60: "按过去 60 日收益波动从低到高选股。原始实验按验证期夏普选中此策略。",
  low_vol_20: "按过去 20 日收益波动从低到高选股。",
  custom: "写出历史数据评分与持仓条件，按评分选前 N 只。支持日线选股和调仓规则。",
  reversal5_lowvol20: "5 日反转与 20 日低波动在当日可投池内的排名等权组合。"
};
const presets = {
  reversal: ["我的反转趋势策略", "-returns(close, 5)", "close > ts_mean(close, 20)"],
  trend: ["我的均线趋势策略", "returns(close, 60)", "ts_mean(close, 10) > ts_mean(close, 30)"],
  blend: ["我的动量低波策略", "rank(returns(close, 20)) + rank(-ts_std(returns(close, 1), 20))", "close > ts_mean(close, 60)"]
};

async function api(url, body) {
  const response = await fetch(url, body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求失败，请稍后重试");
  return data;
}

function errorMessage(message) {
  $("error-banner").textContent = message || "";
  $("error-banner").hidden = !message;
}

function strategyChanged() {
  const strategy = $("strategy").value;
  $("formula-panel").hidden = strategy !== "custom";
  $("strategy-description").textContent = descriptions[strategy] || "根据已定义的历史评分规则选股，下一交易日开盘模拟调仓。";
  $("formula-feedback").textContent = "";
}

async function poll() {
  try {
    const state = await api("/api/state");
    if (!catalogLoaded) {
      $("strategy").replaceChildren(...Object.entries(state.strategies).map(([value, label]) => new Option(label, value)));
      $("strategy").value = "low_vol_60";
      strategyChanged();
      $("start").min = $("end").min = state.data.first_date;
      $("start").max = $("end").max = state.data.last_date;
      $("source-summary").textContent = `${state.data.securities.toLocaleString()} 个代码 · ${state.data.days.toLocaleString()} 个日期 · ${state.data.first_date} — ${state.data.last_date}`;
      catalogLoaded = true;
      await loadResult(state.current_id);
    }
    const status = $("data-status");
    status.classList.toggle("ready", state.ready && !state.busy);
    status.replaceChildren(document.createElement("i"), document.createTextNode(state.busy ? "回测运行中" : state.ready ? "历史数据已就绪" : "正在读取行情"));
    const locked = state.busy || !state.ready;
    $("run-button").disabled = locked;
    $("run-button").textContent = state.busy ? "◌ 回测运行中…" : "▶ 运行回测";
    $("run-feedback").textContent = state.error || (state.busy ? state.phase : state.ready ? "调整参数后运行。自定义回测属于探索性研究。" : state.phase);
    if (state.error) errorMessage(state.error);
    $("run-history").replaceChildren(...state.runs.slice().reverse().map((run) => new Option(run.name, run.id)));
    $("run-history").value = currentRun;
    if (pendingRun && !state.busy) {
      if (state.current_id === pendingRun) {
        await loadResult(pendingRun);
        $("run-history").value = pendingRun;
        errorMessage(null);
      }
      pendingRun = null;
    }
  } catch (error) {
    errorMessage(`无法连接回测服务：${error.message}`);
  }
  setTimeout(poll, 1400);
}

async function loadResult(runId) {
  const data = await api(`/api/result/${encodeURIComponent(runId)}`);
  currentRun = runId;
  result = data;
  $("strategy").value = data.strategy;
  $("start").value = data.start; $("end").value = data.end;
  for (const [id, key] of [["initial-cash","initial_cash"],["top-n","top_n"],["rebalance","rebalance_every"],["commission","commission_bps"],["slippage","slippage_bps"]]) $(id).value = data.config[key];
  $("invested").value = data.config.invested_fraction * 100;
  $("participation").value = data.config.participation * 100;
  if (data.formula) { $("strategy-name").value = data.name; $("formula").value = data.formula; $("condition").value = data.condition; }
  strategyChanged();
  $("run-title").textContent = data.name;
  $("run-range").textContent = `${data.curve[0].date.slice(0, 10)} — ${data.curve.at(-1).date.slice(0, 10)}`;
  $("run-mode").textContent = data.mode === "course" ? "课程规定口径" : data.mode === "frozen" ? "原始冻结实验" : "探索性运行";
  $("run-mode").classList.toggle("exploration", data.mode !== "frozen");
  $("download-daily").href = `/api/export/${currentRun}/daily`;
  const m = data.metrics;
  const items = [
    ["累计净收益", pct(m.total_return), `期末资产 ¥${number(data.curve.at(-1).equity, 0)}`, m.total_return],
    ["年化收益", pct(m.cagr), "按 252 个交易日折算", m.cagr],
    ["最大回撤", pct(m.max_drawdown), "从历史峰值至谷底", m.max_drawdown],
    ["夏普比率", number(m.sharpe), "无风险收益假设为零", m.sharpe],
    ["较等权基准", `${(data.excess * 100).toFixed(2)} pp`, `基准收益 ${pct(data.benchmark_metrics.total_return)}`, data.excess],
    ["累计费用 / 滑点", `${number(m.fees, 0)} / ${number(m.slippage_cost, 0)}`, "人民币元 · 分别列示", 0]
  ];
  $("metrics").innerHTML = items.map(([label, value, note, signed]) => `<article><span>${label}</span><strong class="${signed < 0 ? "negative" : ""}">${value}</strong><small>${note}</small></article>`).join("");
  $("trade-count").textContent = `${m.days} 个交易日${data.elapsed_seconds ? ` · 本次计算 ${data.elapsed_seconds} 秒` : ""}`;
  $("chart-subtitle").textContent = `初始 ¥${number(data.config.initial_cash, 0)} · 每 ${data.config.rebalance_every} 个交易日调仓 · 目标 ${data.config.top_n} 只 / ${pct(data.config.invested_fraction, 0)} 仓位`;
  const note = data.mode.startsWith("course")
    ? `历史非 ST 股票池 · 佣金 ${data.config.commission_bps} bps / 卖出税 5 bps · 末 ${data.config.liquidation_days} 日逐步退出。期末持仓 ${data.terminal_positions} 只，现金 ¥${number(data.terminal_cash, 2)}。等权对照期末持仓 ${data.benchmark_terminal_positions ?? "见账本"} 只，收益按组合估值计算；历史结果不代表有效性已获证明。`
    : data.mode === "frozen"
    ? "原始实验：2023–2024 选择策略，2025 起测试；所选策略未通过预设验证门槛。"
    : "本次为探索性回测。已查看的历史区间不能重新称为未见测试；本次结果不会替换原始冻结实验。";
  $("result-note").replaceChildren();
  const bold = document.createElement("b"); bold.textContent = note;
  $("result-note").append(bold, document.createTextNode(" 研究账本使用小数复权份额；缺真实分红流水、整手与历史涨跌停验证。"));
  if (data.formula) {
    const formula = document.createElement("div");
    formula.textContent = `评分：${data.formula}　｜　持仓条件：${data.condition}`;
    $("result-note").append(formula);
  }
  if (data.empty_trades) $("result-note").append(document.createTextNode(" 本区间未产生成交，可能因预热、条件或可投资池限制；收益由现金或已有持仓决定。"));
  $("holding-date").replaceChildren(...data.holding_dates.map((date) => new Option(date, date)));
  page = 1;
  drawCharts();
  await loadTable();
}

function pathPoints(values, x, y) { return values.map((value, i) => `${x(i).toFixed(2)},${y(value).toFixed(2)}`).join(" "); }

function drawCharts() {
  if (!result) return;
  const data = result.curve;
  const svg = $("nav-chart"), width = Math.max(300, svg.clientWidth), height = svg.clientHeight;
  const pad = {left: 47, right: 17, top: 19, bottom: 27};
  const values = data.flatMap((row) => [row.nav, row.benchmark_nav]);
  let low = Math.min(1, ...values), high = Math.max(1, ...values);
  const margin = Math.max(.03, (high - low) * .13); low -= margin; high += margin;
  const x = (i) => pad.left + i / Math.max(1, data.length - 1) * (width - pad.left - pad.right);
  const y = (value) => height - pad.bottom - (value - low) / (high - low) * (height - pad.top - pad.bottom);
  const ticks = Array.from({length: 5}, (_, i) => low + (high - low) * i / 4);
  let content = ticks.map((value) => `<line x1="${pad.left}" x2="${width - pad.right}" y1="${y(value)}" y2="${y(value)}" stroke="#edf1f6"/><text x="${pad.left - 10}" y="${y(value) + 3}" text-anchor="end" fill="#a0adbe" font-size="9">${value.toFixed(2)}</text>`).join("");
  const tickIndices = [...new Set(Array.from({length: Math.min(6, data.length)}, (_, i) => Math.round(i * (data.length - 1) / Math.max(1, Math.min(6, data.length) - 1))))];
  content += tickIndices.map((i) => `<text x="${x(i)}" y="${height - 7}" text-anchor="${i === 0 ? "start" : i === data.length - 1 ? "end" : "middle"}" fill="#a0adbe" font-size="9">${data[i].date.slice(0, 7)}</text>`).join("");
  content += `<polyline points="${pathPoints(data.map((r) => r.benchmark_nav), x, y)}" fill="none" stroke="#a6b2c5" stroke-width="1.7" stroke-linejoin="round"/><polyline points="${pathPoints(data.map((r) => r.nav), x, y)}" fill="none" stroke="#2864e8" stroke-width="2.2" stroke-linejoin="round"/><g id="crosshair" visibility="hidden"><line stroke="#c4d3ea" stroke-dasharray="3 3"/><circle r="4" fill="#2864e8" stroke="white" stroke-width="2"/></g>`;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = content;
  svg.onpointermove = (event) => {
    const rect = svg.getBoundingClientRect(), mx = (event.clientX - rect.left) * width / rect.width;
    const i = Math.max(0, Math.min(data.length - 1, Math.round((mx - pad.left) / (width - pad.left - pad.right) * (data.length - 1))));
    const row = data[i], cross = $("crosshair");
    cross.setAttribute("visibility", "visible");
    const line = cross.querySelector("line");
    Object.entries({x1:x(i), x2:x(i), y1:pad.top, y2:height - pad.bottom}).forEach(([key, value]) => line.setAttribute(key, value));
    cross.querySelector("circle").setAttribute("cx", x(i)); cross.querySelector("circle").setAttribute("cy", y(row.nav));
    const tip = $("chart-tooltip");
    tip.innerHTML = `<strong>${row.date.slice(0, 10)}</strong>策略净值　<b>${row.nav.toFixed(4)}</b><br>基准净值　${row.benchmark_nav.toFixed(4)}<br>现金　¥${number(row.cash, 0)}<br>持仓　${row.holdings} 只 / ${pct(row.exposure, 1)}`;
    tip.hidden = false; tip.style.left = `${Math.max(3, Math.min(width - 202, x(i) + 14))}px`;
  };
  svg.onpointerleave = () => { $("chart-tooltip").hidden = true; $("crosshair").setAttribute("visibility", "hidden"); };
  const dd = $("drawdown-chart"), ddHeight = dd.clientHeight, ddBottom = ddHeight - 20;
  const minimum = Math.min(-.02, ...data.map((r) => r.drawdown));
  const dy = (value) => 7 + value / minimum * (ddBottom - 7);
  dd.setAttribute("viewBox", `0 0 ${width} ${ddHeight}`);
  const ddPoints = pathPoints(data.map((r) => r.drawdown), x, dy);
  dd.innerHTML = [0, minimum / 2, minimum].map((value) => `<line x1="${pad.left}" x2="${width-pad.right}" y1="${dy(value)}" y2="${dy(value)}" stroke="#f0f3f7"/><text x="${pad.left-10}" y="${dy(value)+3}" text-anchor="end" fill="#a5b0c0" font-size="8">${(value*100).toFixed(1)}</text>`).join("") + `<polygon points="${x(0)},7 ${ddPoints} ${x(data.length-1)},7" fill="#edf3ff"/><polyline points="${ddPoints}" fill="none" stroke="#7b9fe8" stroke-width="1.2"/>`;
}

const statusLabels = {filled:"已成交", missing_open_or_gap_guard:"缺价 / 跳空受阻", partial_capacity_or_cash:"容量 / 资金受限"};
const columns = {
  orders: [["date","成交日"],["signal_date","信号日"],["symbol","股票代码"],["side","方向"],["requested_reference_notional","请求金额"],["notional","成交金额"],["adjusted_units","复权份额"],["fee","费用"],["status","状态"]],
  holdings: [["date","快照日期"],["symbol","股票代码"],["adjusted_units","复权份额"],["mark","复权估值价"],["value","持仓市值"],["stale_days","缺价天数"]],
  daily: [["date","交易日"],["equity","总资产"],["cash","现金"],["return","日收益"],["exposure","持仓比例"],["holdings","股票数"],["fees","费用"],["constrained_orders","受限订单数"]],
  candidates: [["candidate","策略候选"],["total_return","2023–2024 净收益"],["sharpe","夏普"],["max_drawdown","最大回撤"],["annual_one_way_turnover","年化单边换手"]]
};

function cell(key, value, labels) {
  if (value === null || value === undefined) return "—";
  if (key === "side") return `<span class="${value === "BUY" ? "side-buy" : "side-sell"}">${value === "BUY" ? "买入" : "卖出"}</span>`;
  if (key === "status") return `<span class="order-status ${value === "filled" ? "" : "constrained"}">${escapeHTML(statusLabels[value] || value)}</span>`;
  if (key === "candidate") return escapeHTML(labels?.[value] || value);
  if (key.includes("date")) return escapeHTML(String(value).slice(0, 10));
  if (["return","exposure","total_return","max_drawdown"].includes(key)) return pct(value);
  if (["holdings","stale_days","constrained_orders"].includes(key)) return number(value, 0);
  return typeof value === "number" ? number(value, ["mark","adjusted_units"].includes(key) ? 4 : 2) : escapeHTML(value);
}

async function loadTable() {
  const token = ++tableRequest, tab = activeTab;
  $("holding-date").hidden = tab !== "holdings";
  $("table-query").hidden = !["orders", "holdings"].includes(tab);
  $("pagination").hidden = ["candidates", "audit"].includes(tab);
  $("download-table").hidden = ["candidates", "audit"].includes(tab);
  $("download-table").href = `/api/export/${currentRun}/${tab}`;
  $("table-description").textContent = {orders:"包括未成交和部分成交的请求",holdings:"调仓日及期末快照；份额为复权研究单位",daily:"现金、持仓与费用逐日核对",candidates:"原始研究的验证期比较，不使用最终测试排序",audit:"数据质量与回测设定"}[tab];
  try {
    if (tab === "audit") {
      const audit = await api("/api/audit");
      if (token !== tableRequest) return;
      $("table-container").innerHTML = `<div class="audit-content"><h4>数据来源</h4><p>${audit.rows} 个日期 × ${audit.securities} 个代码，${audit.first_date} 至 ${audit.last_date}。原始 ZIP 只读，7 份 Feather 分别核对指纹。</p><h4>需要留意的缺失</h4><p>末日成交笔数全缺失；${audit.present_before_2025_absent_since_2025} 个代码在 2025 年前出现、之后不再出现。未要求证券存续到数据末日。累计复权、金额单位及供应商历史覆盖尚待确认。</p><h4>回测与成交设定</h4><p>信号在前一日收盘后计算，下一交易日开盘模拟；每个开盘先卖隔夜份额再买入，不允许现金借款和做空。使用小数复权份额，未复刻真实送股/现金分红、整手股数或券商交割。固定 4.8% 开盘跳空阻断是研究风控，并非历史涨跌停规则。</p><p>容量采用前 20 日平均金额；当日全日金额是否为零只作事后停牌/交易可行性代理，无法证明开盘深度。连续 20 日无有效观测估值归零，复牌可恢复，不虚构卖出现金。最低佣金、其他规费及实际撮合延迟未建模。</p><h4>研究边界</h4><p>在网页修改公式或参数得到的结果属于探索性回测，不覆盖原始冻结实验，也不能把已查看时期再称为未见测试。分钟级、逐笔执行及盘中止损不在当前日线公式引擎范围内。</p><h4>原始数据 SHA-256</h4><p><code>${audit.sha256}</code></p></div>`;
      return;
    }
    const query = new URLSearchParams({page: String(page), q: $("table-query").value});
    if (tab === "holdings" && $("holding-date").value) query.set("date", $("holding-date").value);
    const data = await api(tab === "candidates" ? "/api/candidates" : `/api/table/${currentRun}/${tab}?${query}`);
    if (token !== tableRequest) return;
    pages = data.pages || 1; page = data.page || 1;
    const cols = columns[tab];
    $("table-container").innerHTML = data.rows.length
      ? `<table><thead><tr>${cols.map(([,label])=>`<th>${label}</th>`).join("")}</tr></thead><tbody>${data.rows.map((row)=>`<tr>${cols.map(([key])=>`<td class="${key === "symbol" ? "symbol" : ""}">${cell(key,row[key],data.labels)}</td>`).join("")}</tr>`).join("")}</tbody></table>`
      : '<p class="empty-state">当前筛选下没有记录。可调整股票代码或日期，查看其他快照。</p>';
    $("table-count").textContent = `共 ${(data.total || data.rows.length).toLocaleString()} 条记录`;
    $("page-number").textContent = `${page} / ${pages}`;
    $("previous-page").disabled = page <= 1;
    $("next-page").disabled = page >= pages;
  } catch (error) { if (token === tableRequest) errorMessage(error.message); }
}

$("strategy").addEventListener("change", strategyChanged);
$("toggle-config").addEventListener("click", () => {
  const collapsed = $("configuration").classList.toggle("mobile-collapsed");
  $("toggle-config").textContent = collapsed ? "展开参数 ↓" : "收起参数 ↑";
  $("toggle-config").setAttribute("aria-expanded", String(!collapsed));
});
document.querySelectorAll("[data-preset]").forEach((button) => button.addEventListener("click", () => {
  const [name, formula, condition] = presets[button.dataset.preset];
  $("strategy-name").value = name; $("formula").value = formula; $("condition").value = condition;
  $("formula-feedback").textContent = "";
}));
$("check-formula").addEventListener("click", async () => {
  try {
    const data = await api("/api/formula/check", {formula: $("formula").value, condition: $("condition").value});
    $("formula-feedback").classList.remove("error"); $("formula-feedback").textContent = data.message;
  } catch (error) { $("formula-feedback").classList.add("error"); $("formula-feedback").textContent = error.message; }
});
$("config-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!$("config-form").reportValidity()) return;
  const body = Object.fromEntries(new FormData(event.target));
  body.invested_fraction = Number(body.invested_percent) / 100;
  body.participation = Number(body.participation_percent) / 100;
  $("run-button").disabled = true; errorMessage(null);
  try { const response = await api("/api/run", body); pendingRun = response.id; $("run-feedback").textContent = "回测已开始，正在计算历史信号…"; }
  catch (error) { errorMessage(error.message); $("run-button").disabled = false; }
});
$("run-history").addEventListener("change", () => loadResult($("run-history").value).catch((error) => errorMessage(error.message)));
document.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => {
  activeTab = button.dataset.tab; page = 1;
  document.querySelectorAll("[data-tab]").forEach((tab) => { tab.classList.toggle("active", tab === button); tab.setAttribute("aria-selected", String(tab === button)); });
  loadTable();
}));
let searchTimer;
$("table-query").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { page = 1; loadTable(); }, 250); });
$("holding-date").addEventListener("change", () => { page = 1; loadTable(); });
$("previous-page").addEventListener("click", () => { if (page > 1) {page--; loadTable();} });
$("next-page").addEventListener("click", () => { if (page < pages) {page++; loadTable();} });
let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(drawCharts, 150); });
poll();
