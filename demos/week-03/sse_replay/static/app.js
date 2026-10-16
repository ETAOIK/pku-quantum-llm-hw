"use strict";

const $ = (id) => document.getElementById(id);
let state = null;
let busy = false;
let side = "B";
let selectedLedger = "orders";
let playing = false;
let playbackTimer = null;
let playbackGeneration = 0;
let chartHover = null;
let chartGeometry = null;
const REPLAY_END = (15 * 60 + 30) * 60 * 1000;
const amount = (value, digits = 2) => value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toLocaleString("zh-CN", {minimumFractionDigits: digits, maximumFractionDigits: digits});
const count = (value) => amount(value, 0);
const escapeText = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]));
const money = (value) => amount(value);
const statusNames = {ACTIVE:"排队中", PARTIAL:"部分成交", FILLED:"全部成交", CANCELLED:"已撤销", REJECTED:"已拒绝", EXPIRED:"模拟结束"};
const fillKinds = {AGGRESSIVE:"主动成交", PASSIVE_TRADE:"排队成交（历史成交估计）", PASSIVE_NEW_ORDER:"排队成交（新增对手单估计）"};

function notice(message, type = "info") {
  $("notice").hidden = !message;
  $("notice").className = `notice ${type}`;
  $("notice").replaceChildren();
  if (message) {
    const text = document.createElement("span");
    text.textContent = message;
    const close = document.createElement("button");
    close.type = "button";
    close.setAttribute("aria-label", "关闭提示");
    close.textContent = "×";
    close.addEventListener("click", () => $("notice").hidden = true);
    $("notice").append(text, close);
  }
}

function setSide(next) {
  side = next;
  for (const candidate of ["B", "S"]) {
    const button = $(candidate === "B" ? "buy-side" : "sell-side");
    button.classList.toggle("selected", candidate === side);
    button.setAttribute("aria-pressed", String(candidate === side));
  }
  $("order-button").className = `button ${side === "B" ? "buy-submit" : "sell-submit"}`;
  $("order-button").innerHTML = `<svg viewBox="0 0 20 20" aria-hidden="true"><path d="${side === "B" ? "M10 16V4M5 9l5-5 5 5" : "M10 4v12m-5-5 5 5 5-5"}"/></svg><span>提交${side === "B" ? "买入" : "卖出"}委托</span>`;
  updateControls();
}

function updateControls() {
  const hasState = Boolean(state);
  const continuous = hasState && state.phase === "连续竞价";
  const pendingSymbol = hasState && $("symbol").value !== state.symbol;
  const canTrade = continuous && !pendingSymbol;
  document.querySelectorAll("button[data-seconds]").forEach((button) => button.disabled = busy || !hasState);
  $("advance-button").disabled = busy || !hasState;
  $("play-button").disabled = !hasState || pendingSymbol || state.time_ms >= REPLAY_END || (busy && !playing);
  $("reset-button").disabled = busy || !$("symbol").value;
  $("order-button").disabled = busy || !canTrade;
  $("use-ask").disabled = busy || !canTrade || !state?.book?.asks?.[0]?.price;
  $("use-bid").disabled = busy || !canTrade || !state?.book?.bids?.[0]?.price;
  $("buy-side").disabled = busy;
  $("sell-side").disabled = busy;
  document.querySelectorAll(".cancel-button").forEach((button) => button.disabled = busy || !continuous);
  document.querySelectorAll(".export-link").forEach((link) => link.setAttribute("aria-disabled", String(!hasState || busy)));
  $("order-guidance").textContent = !hasState ? "开始回放后，可在连续竞价阶段提交委托。" : pendingSymbol ? `请点击“开始 / 重置回放”切换至 ${$("symbol").value}。当前账户仍属于 ${state.symbol}。` : !continuous ? `当前为${state.phase}，本版仅支持连续竞价限价委托。` : side === "B" ? "买入按限价冻结资金；当日买入的股票不可当日卖出。" : "卖出冻结可卖持仓；仅可卖出期初持有且未被冻结的股票。";
}

function pausePlayback() {
  playing = false;
  playbackGeneration += 1;
  clearTimeout(playbackTimer);
  playbackTimer = null;
  renderPlayback();
}

function renderPlayback() {
  $("play-button").innerHTML = playing ? '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7 4v12M13 4v12"/></svg><span>暂停回放</span>' : '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m7 4 9 6-9 6Z"/></svg><span>自动回放</span>';
  $("play-button").setAttribute("aria-pressed", String(playing));
  $("play-status").textContent = playing ? "播放中" : state?.time_ms >= REPLAY_END ? "回放已结束" : "已暂停";
  $("play-status").classList.toggle("playing", playing);
  updateControls();
}

async function startPlayback() {
  if (!state || busy || state.time_ms >= REPLAY_END) return;
  const generation = ++playbackGeneration;
  const synced = await request("/api/state");
  if (generation !== playbackGeneration) return;
  if (!synced || !state || state.time_ms >= REPLAY_END) {renderPlayback(); return;}
  if ($("symbol").value !== state.symbol) {
    notice(`当前会话股票已变更为 ${state.symbol}，请选择该代码或重置回放后再开始。`, "info");
    return;
  }
  playing = true;
  renderPlayback();
  const schedule = () => {
    playbackTimer = setTimeout(async () => {
      if (!playing || generation !== playbackGeneration) return;
      if (!busy) {
        const result = await request("/api/advance", {seconds:Number($("replay-speed").value)});
        if (!result) return;
        if (state.time_ms >= REPLAY_END) {
          pausePlayback();
          notice("已到达 15:30，自动回放停止。", "info");
          return;
        }
      }
      if (playing && generation === playbackGeneration) schedule();
    }, 1000);
  };
  schedule();
}

function updateEstimate() {
  const price = Number($("order-price").value);
  const qty = Number($("order-qty").value);
  $("order-estimate").textContent = price > 0 && qty > 0 ? money(price * qty) : "—";
}

async function request(url, payload, trigger) {
  if (busy) return null;
  busy = true;
  updateControls();
  if (trigger) trigger.classList.add("is-loading");
  try {
    const response = await fetch(url, payload === undefined ? {cache:"no-store"} : {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || `请求失败（${response.status}）`);
    if (Object.hasOwn(result, "state")) {
      state = result.state;
      renderState();
    }
    const rejectedOrder = url === "/api/order" && result.state?.orders?.at(-1)?.status === "REJECTED";
    if (result.message) notice(result.message, rejectedOrder ? "error" : "success");
    return result;
  } catch (error) {
    pausePlayback();
    notice(error.message === "Failed to fetch" ? "无法连接本地服务，请确认服务仍在运行，然后重试。" : error.message, "error");
    return null;
  } finally {
    busy = false;
    if (trigger) trigger.classList.remove("is-loading");
    updateControls();
  }
}

function renderBook(book = {bids:[], asks:[]}) {
  const bids = book.bids || [];
  const asks = book.asks || [];
  const maxVolume = Math.max(1, ...bids.map((level) => level.volume), ...asks.map((level) => level.volume));
  $("depth-body").innerHTML = Array.from({length:10}, (_, index) => {
    const bid = bids[index];
    const ask = asks[index];
    const volumeCell = (level, isBid) => level ? `<span class="volume-bar${isBid ? " bid" : ""}" style="width:${Math.max(0, level.volume / maxVolume * 86)}%"></span><span>${count(level.volume)}</span>` : "<span>—</span>";
    return `<tr><td>${index + 1}</td><td><span>${money(bid?.price)}</span></td><td>${volumeCell(bid, true)}</td><td><span>${money(ask?.price)}</span></td><td>${volumeCell(ask, false)}</td></tr>`;
  }).join("");
  $("quote-ask").textContent = money(asks[0]?.price);
  $("quote-bid").textContent = money(bids[0]?.price);
}

function renderLedgers() {
  const orders = state?.orders || [];
  const fills = state?.fills || [];
  $("orders-count").textContent = count(orders.length);
  $("fills-count").textContent = count(fills.length);
  $("orders-body").innerHTML = orders.length ? [...orders].reverse().map((order) => {
    const active = ["ACTIVE", "PARTIAL"].includes(order.status);
    return `<tr><td>${escapeText(order.created_time)}</td><td>${escapeText(order.order_id)}</td><td class="side-cell ${order.side === "B" ? "positive" : "negative"}">${order.side === "B" ? "买入" : "卖出"}</td><td>${money(order.price)}</td><td>${count(order.qty)}</td><td>${count(order.filled)}</td><td>${count(order.remaining)}</td><td>${active ? count(order.queue_ahead) : "—"}</td><td><span class="status-tag ${escapeText(order.status.toLowerCase())}" title="${escapeText(order.reject_reason || "")}">${escapeText(statusNames[order.status] || order.status)}</span></td><td>${active ? `<button type="button" class="cancel-button" data-order-id="${escapeText(order.order_id)}">撤单</button>` : "—"}</td></tr>`;
  }).join("") : '<tr><td colspan="10" class="empty-state">尚无模拟委托。开始回放，提交第一笔限价单。</td></tr>';
  $("fills-body").innerHTML = fills.length ? [...fills].reverse().map((fill) => `<tr><td>${escapeText(fill.time)}</td><td>${escapeText(fill.fill_id)}</td><td>${escapeText(fill.order_id)}</td><td class="side-cell ${fill.side === "B" ? "positive" : "negative"}">${fill.side === "B" ? "买入" : "卖出"}</td><td>${money(fill.price)}</td><td>${count(fill.qty)}</td><td>${money(fill.price * fill.qty)}</td><td>${escapeText(fillKinds[fill.kind] || fill.kind)}</td></tr>`).join("") : '<tr><td colspan="8" class="empty-state">尚无模拟成交。成交后将同步更新账户账本。</td></tr>';
}

function setSigned(id, value, digits = 2, suffix = "") {
  $(id).textContent = value == null ? "—" : `${value > 0 ? "+" : ""}${amount(value, digits)}${suffix}`;
  $(id).classList.toggle("positive", value > 0);
  $(id).classList.toggle("negative", value < 0);
}

function renderValidation(validation) {
  const complete = validation?.status === "complete";
  $("validation-status").textContent = complete ? "校验已完成" : state ? "待校验 / 校验中" : "待回放";
  $("validation-description").textContent = validation?.description || "使用真实行情快照核对重建十档；结果与覆盖范围将在回放开始后显示。";
  $("validation-stats").hidden = !validation || validation.total == null;
  if (validation?.total != null) {
    const stats = [["已检查股票", count(validation.symbols_checked)], ["同秒匹配", `${count(validation.matched)} / ${count(validation.total)}`], ["同秒匹配率", validation.ratio == null ? "—" : `${amount(validation.ratio * 100, 2)}%`], ["字面时刻匹配率", `${amount(validation.literal_matched / validation.total * 100, 2)}%`], ["未知被动订单", count(validation.unknown_passive)], ["超量扣减", count(validation.negative)]];
    $("validation-stats").innerHTML = stats.map(([name, value]) => `<span>${name}<strong>${escapeText(value)}</strong></span>`).join("");
  }
}

function renderState() {
  if (!state) { renderBook(); renderLedgers(); renderValidation(); renderChart(); updateControls(); return; }
  $("trade-date").textContent = state.date || "—";
  $("active-symbol").textContent = state.symbol;
  $("ticket-symbol").textContent = `当前 ${state.symbol}`;
  $("clock").textContent = state.clock;
  $("phase").textContent = state.phase;
  $("processed-events").textContent = count(state.processed_events);
  $("last-price").textContent = money(state.last_price);
  $("preclose").textContent = money(state.preclose);
  const delta = state.last_price != null && state.preclose > 0 ? (state.last_price / state.preclose - 1) * 100 : null;
  setSigned("price-change", delta, 2, "%");
  $("last-price").classList.toggle("positive", delta > 0);
  $("last-price").classList.toggle("negative", delta < 0);
  renderBook(state.book);
  const metrics = state.metrics || {};
  $("spread").textContent = money(metrics.spread);
  $("mid").textContent = amount(metrics.mid, 3);
  const bidVolume = metrics.total_bid_volume ?? (state.book.bids || []).reduce((sum, level) => sum + level.volume, 0);
  const askVolume = metrics.total_ask_volume ?? (state.book.asks || []).reduce((sum, level) => sum + level.volume, 0);
  const bidShare = bidVolume + askVolume > 0 ? bidVolume / (bidVolume + askVolume) * 100 : 50;
  $("imbalance").textContent = bidVolume + askVolume > 0 ? `${amount(bidShare, 0)} : ${amount(100 - bidShare, 0)}` : "—";
  $("bid-total").textContent = count(bidVolume);
  $("ask-total").textContent = count(askVolume);
  $("bid-balance").style.width = `${bidShare}%`;
  const account = state.account || {};
  for (const [id, key, digits] of [["equity","equity",2],["cash-available","cash_available",2],["cash-frozen","cash_frozen",2],["position","position",0],["sellable","sellable",0],["bought-today","bought_today",0],["sell-frozen","sell_frozen",0]]) $(id).textContent = amount(account[key], digits);
  setSigned("pnl", account.pnl);
  renderLedgers();
  renderValidation(state.validation);
  renderChart();
  renderPlayback();
  updateControls();
}

function candles() {
  return (state?.candles || []).filter((bar) => bar.time_ms <= state.time_ms);
}

function candleLegend(bar) {
  for (const key of ["open", "high", "low", "close"]) $("candle-" + key).textContent = money(bar?.[key]);
  $("candle-time").textContent = bar?.time?.slice(0, 5) || "—";
  $("candle-volume").textContent = count(bar?.volume);
}

function candleTooltip(bar) {
  return `<strong>${escapeText(bar.time.slice(0, 5))} · 1 分钟</strong><div>开 ${money(bar.open)}　高 ${money(bar.high)}</div><div>低 ${money(bar.low)}　收 ${money(bar.close)}</div><div>成交量 ${count(bar.volume)} 股</div>`;
}

function renderChart() {
  const bars = candles();
  const canvas = $("candle-chart");
  const container = $("chart-container");
  const width = container.clientWidth;
  const height = container.clientHeight;
  if (!width || !height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);
  $("candle-count").textContent = `${bars.length} 根`;
  $("chart-empty").hidden = bars.length > 0;
  canvas.setAttribute("aria-label", `截至 ${state?.clock || "当前回放时间"} 的一分钟 K 线，共 ${bars.length} 根，仅包含已处理成交`);
  if (!bars.length) {chartGeometry = null; candleLegend(); $("chart-tooltip").hidden = true; return;}

  const left = 13;
  const right = width - 58;
  const top = 18;
  const priceBottom = height * .69;
  const volumeTop = priceBottom + 19;
  const volumeBottom = height - 28;
  const plotWidth = right - left;
  const maxPrice = Math.max(...bars.map((bar) => bar.high));
  const minPrice = Math.min(...bars.map((bar) => bar.low));
  const padding = Math.max((maxPrice - minPrice) * .12, .02);
  const upper = maxPrice + padding;
  const lower = minPrice - padding;
  const y = (price) => top + (upper - price) / (upper - lower) * (priceBottom - top);
  const slots = Math.max(15, bars.length);
  const step = plotWidth / slots;
  const x = (index) => left + (index + .5) * step;
  const candleWidth = Math.max(1.4, Math.min(10, step * .6));
  const maxVolume = Math.max(1, ...bars.map((bar) => bar.volume));
  context.font = '10px "SFMono-Regular", Consolas, monospace';
  context.lineWidth = 1;
  context.textAlign = "left";
  context.textBaseline = "middle";
  for (let index = 0; index <= 4; index++) {
    const value = upper - (upper - lower) * index / 4;
    const lineY = y(value);
    context.strokeStyle = "#edf1f5";
    context.beginPath(); context.moveTo(left, lineY); context.lineTo(right, lineY); context.stroke();
    context.fillStyle = "#8492a3";
    context.fillText(value.toFixed(2), right + 9, lineY);
  }
  context.fillStyle = "#96a2af";
  context.fillText("成交量（股）", left, volumeTop + 3);
  context.fillText(maxVolume >= 10000 ? `${(maxVolume / 10000).toFixed(1)}万` : String(maxVolume), right + 9, volumeTop + 3);
  context.strokeStyle = "#edf1f5";
  context.beginPath(); context.moveTo(left, volumeBottom); context.lineTo(right, volumeBottom); context.stroke();
  const noonIndex = bars.findIndex((bar, index) => index > 0 && bars[index - 1].time_ms < 13 * 3600000 && bar.time_ms >= 13 * 3600000);
  if (noonIndex >= 0) {
    const noonX = left + noonIndex * step;
    context.save(); context.strokeStyle = "#bfcbd6"; context.setLineDash([3, 4]);
    context.beginPath(); context.moveTo(noonX, top); context.lineTo(noonX, volumeBottom); context.stroke(); context.restore();
    context.fillStyle = "#7b8da0"; context.textAlign = "center";
    context.fillText("午休后", Math.min(right - 20, Math.max(left + 20, noonX)), top - 8);
  }
  bars.forEach((bar, index) => {
    const barX = x(index);
    context.fillStyle = context.strokeStyle = bar.close >= bar.open ? "#cc5557" : "#29967f";
    context.beginPath(); context.moveTo(barX, y(bar.high)); context.lineTo(barX, y(bar.low)); context.stroke();
    const bodyTop = Math.min(y(bar.open), y(bar.close));
    context.fillRect(barX - candleWidth / 2, bodyTop, candleWidth, Math.max(1, Math.abs(y(bar.open) - y(bar.close))));
    const volumeHeight = bar.volume / maxVolume * Math.max(5, volumeBottom - volumeTop - 12);
    context.globalAlpha = .5;
    context.fillRect(barX - candleWidth / 2, volumeBottom - volumeHeight, candleWidth, volumeHeight);
    context.globalAlpha = 1;
  });
  const labels = new Set([0, bars.length - 1]);
  const labelCount = Math.max(2, Math.floor(plotWidth / 100));
  for (let index = 1; index < labelCount; index++) labels.add(Math.round(index * (bars.length - 1) / labelCount));
  context.fillStyle = "#8492a3"; context.textAlign = "center";
  let lastLabelX = -100;
  [...labels].sort((a, b) => a - b).forEach((index) => {
    const labelX = Math.min(right - 16, Math.max(left + 18, x(index)));
    if (labelX - lastLabelX < 53) return;
    context.fillText(bars[index].time.slice(0, 5), labelX, height - 11);
    lastLabelX = labelX;
  });
  chartGeometry = {left, right, top, priceBottom, volumeBottom, step, bars};
  const selected = chartHover == null ? bars.length - 1 : Math.min(chartHover, bars.length - 1);
  candleLegend(bars[selected]);
  if (chartHover != null) {
    $("chart-tooltip").innerHTML = candleTooltip(bars[selected]);
    const barX = x(selected);
    context.save(); context.strokeStyle = "#8d9fb1"; context.setLineDash([3, 3]);
    context.beginPath(); context.moveTo(barX, top); context.lineTo(barX, volumeBottom); context.stroke(); context.restore();
    context.fillStyle = "#243b53"; context.beginPath(); context.arc(barX, y(bars[selected].close), 2.5, 0, Math.PI * 2); context.fill();
  }
}

$("candle-chart").addEventListener("pointermove", (event) => {
  if (!chartGeometry) return;
  const bounds = $("candle-chart").getBoundingClientRect();
  const pointerX = event.clientX - bounds.left;
  const pointerY = event.clientY - bounds.top;
  const index = Math.floor((pointerX - chartGeometry.left) / chartGeometry.step);
  if (pointerX < chartGeometry.left || pointerX > chartGeometry.right || index < 0 || index >= chartGeometry.bars.length || pointerY > chartGeometry.volumeBottom) {
    chartHover = null; $("chart-tooltip").hidden = true; renderChart(); return;
  }
  chartHover = index;
  const bar = chartGeometry.bars[index];
  const tooltip = $("chart-tooltip");
  tooltip.innerHTML = candleTooltip(bar);
  tooltip.hidden = false;
  tooltip.style.left = `${Math.min(Math.max(6, pointerX + 15), bounds.width - 205)}px`;
  tooltip.style.top = `${Math.min(Math.max(8, pointerY + 12), bounds.height - 109)}px`;
  renderChart();
});
$("candle-chart").addEventListener("pointerleave", () => {chartHover = null; $("chart-tooltip").hidden = true; renderChart();});
new ResizeObserver(() => renderChart()).observe($("chart-container"));

function setLedger(next) {
  selectedLedger = next;
  for (const kind of ["orders", "fills"]) {
    $(kind + "-tab").classList.toggle("selected", kind === next);
    $(kind + "-tab").setAttribute("aria-selected", String(kind === next));
    $(kind + "-pane").hidden = kind !== next;
  }
  $("ledger-export").href = `/api/export?kind=${selectedLedger}`;
}

$("reset-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  pausePlayback();
  chartHover = null;
  $("chart-tooltip").hidden = true;
  const cash = Number($("initial-cash").value);
  const initialPosition = Number($("initial-position").value);
  if (!Number.isFinite(cash) || cash < 0 || !Number.isInteger(initialPosition) || initialPosition < 0) {notice("请输入非负初始资金和整数持仓数量。", "error"); return;}
  notice("正在读取逐笔数据并恢复开盘订单簿，首次载入可能需要几秒…", "info");
  const result = await request("/api/reset", {symbol:$("symbol").value, cash, initial_position:initialPosition}, $("reset-button"));
  if (result) {
    if (!result.message) notice(`已开始 ${state.symbol} 的历史回放。可推进时间或提交模拟限价委托。`, "success");
    $("order-price").value = state.book.asks?.[0]?.price?.toFixed(2) || state.last_price?.toFixed(2) || "";
    updateEstimate();
  }
});
document.querySelectorAll("button[data-seconds]").forEach((button) => button.addEventListener("click", () => {pausePlayback(); request("/api/advance", {seconds:Number(button.dataset.seconds)}, button);}));
$("advance-form").addEventListener("submit", (event) => {
  event.preventDefault();
  pausePlayback();
  const target = $("target-time").value;
  if (!target) return;
  request("/api/advance", {target:target.length === 5 ? target + ":00" : target}, $("advance-button"));
});
$("play-button").addEventListener("click", () => playing ? pausePlayback() : startPlayback());
$("replay-speed").addEventListener("change", renderPlayback);
$("buy-side").addEventListener("click", () => {pausePlayback(); setSide("B");});
$("sell-side").addEventListener("click", () => {pausePlayback(); setSide("S");});
$("use-ask").addEventListener("click", () => {pausePlayback(); setSide("B"); $("order-price").value = state.book.asks[0].price.toFixed(2); updateEstimate();});
$("use-bid").addEventListener("click", () => {pausePlayback(); setSide("S"); $("order-price").value = state.book.bids[0].price.toFixed(2); updateEstimate();});
$("order-price").addEventListener("input", updateEstimate);
$("order-qty").addEventListener("input", updateEstimate);
for (const id of ["symbol", "initial-cash", "initial-position", "order-price", "order-qty", "target-time"]) $(id).addEventListener("focus", pausePlayback);
$("symbol").addEventListener("change", () => {pausePlayback(); updateControls();});
$("order-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  pausePlayback();
  const price = Number($("order-price").value);
  const qty = Number($("order-qty").value);
  if (!(price > 0) || !Number.isInteger(qty) || qty < 1) {notice("请输入有效限价与正整数股数。", "error"); return;}
  const result = await request("/api/order", {side, price, qty}, $("order-button"));
  if (result && !result.message) notice("模拟委托已提交，成交与排队状态见下方委托记录。", "success");
});
$("orders-body").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-order-id]");
  if (!button) return;
  pausePlayback();
  const result = await request("/api/cancel", {order_id:Number(button.dataset.orderId)}, button);
  if (result && !result.message) notice("委托已撤销，未成交部分冻结的资金或持仓已释放。", "success");
});
$("orders-tab").addEventListener("click", () => setLedger("orders"));
$("fills-tab").addEventListener("click", () => setLedger("fills"));
document.querySelectorAll(".export-link").forEach((link) => link.addEventListener("click", (event) => {
  if (link.getAttribute("aria-disabled") === "true") event.preventDefault();
}));

async function boot() {
  renderBook();
  renderChart();
  updateControls();
  const catalog = await request("/api/catalog");
  if (!catalog) {$("symbol").innerHTML = '<option value="">股票列表读取失败</option>'; return;}
  $("symbol").innerHTML = catalog.symbols.map((symbol) => `<option value="${escapeText(symbol)}">${escapeText(symbol)}</option>`).join("");
  if (catalog.symbols.includes("601688")) $("symbol").value = "601688";
  $("trade-date").textContent = catalog.date;
  notice("正在读取历史行情并恢复开盘订单簿，首次载入可能需要几秒…", "info");
  const result = await request("/api/state");
  if (result && state) {
    $("symbol").value = state.symbol;
    $("order-price").value = state.book.asks?.[0]?.price?.toFixed(2) || state.last_price?.toFixed(2) || "";
    updateEstimate();
    if (!result.message) notice("");
  }
  updateControls();
}
boot();
