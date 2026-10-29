"use strict";
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const num = (v,d=3) => v == null || !Number.isFinite(Number(v)) ? "—" : Number(v).toFixed(d);
const pct = (v,d=2) => v == null || !Number.isFinite(Number(v)) ? "—" : `${(Number(v)*100).toFixed(d)}%`;
const count = v => Number(v).toLocaleString("zh-CN");
let current = null, horizon = 5, pending = null, backtestPending = null, comparison = [], initialized = false;
const offline = window.FACTOR_SNAPSHOT;
async function api(url, body) {
  const response = await fetch(url, body === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}
function error(message) { $("error").hidden = !message; $("error").textContent = message || ""; }
function table(id, headings, rows) { $(id).innerHTML = `<thead><tr>${headings.map(v=>`<th>${esc(v)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody>`; }
function lineChart(rows) {
  const W=650,H=245,L=44,R=12,T=16,B=30, valid=rows.map(r=>r.rank_ic).filter(v=>v!=null);
  const limit=Math.max(.1,...valid.map(Math.abs))*1.12;
  const x=i=>L+i*(W-L-R)/Math.max(1,rows.length-1), y=v=>T+(limit-v)/(limit*2)*(H-T-B);
  let axes="";
  for (const v of [-limit/1.12,0,limit/1.12]) axes+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="#e8edf1"/><text x="${L-8}" y="${y(v)+3}" text-anchor="end">${v.toFixed(2)}</text>`;
  function path(values) { let connected=false;return values.map((v,i)=>{if(v==null){connected=false;return "";}const p=`${connected?"L":"M"}${x(i)},${y(v)}`;connected=true;return p;}).join(" "); }
  const rolling=rows.map((r,i)=>{const values=rows.slice(Math.max(0,i-19),i+1).map(v=>v.rank_ic).filter(v=>v!=null);return values.length>=10?values.reduce((a,b)=>a+b,0)/values.length:null;});
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Rank IC 每日值和二十日均值">${axes}<path d="${path(rows.map(r=>r.rank_ic))}" fill="none" stroke="#bbd8d3" stroke-width="1"/><path d="${path(rolling)}" fill="none" stroke="#127c76" stroke-width="2"/><text x="${L}" y="${H-5}">${esc(rows[0]?.date||"")}</text><text x="${W-R}" y="${H-5}" text-anchor="end">${esc(rows.at(-1)?.date||"")}</text></svg>`;
}
function barChart(rows) {
  const W=480,H=245,L=45,R=15,T=20,B=30;
  const limit=Math.max(.001,...rows.map(r=>Math.abs(r.mean_return||0)))*1.2;
  const y=v=>T+(limit-v)/(2*limit)*(H-T-B),step=(W-L-R)/rows.length;
  let content=`<line x1="${L}" x2="${W-R}" y1="${y(0)}" y2="${y(0)}" stroke="#d8e2e7"/>`;
  rows.forEach((r,i)=>{const x=L+step*i+step*.2,v=r.mean_return;if(v!=null)content+=`<rect x="${x}" y="${Math.min(y(0),y(v))}" width="${step*.6}" height="${Math.max(.5,Math.abs(y(v)-y(0)))}" rx="3" fill="${v>=0?"#599b91":"#cf8a63"}"/><text x="${x+step*.3}" y="${v>=0?y(v)-7:y(v)+15}" text-anchor="middle">${pct(v)}</text>`;content+=`<text x="${x+step*.3}" y="${H-7}" text-anchor="middle">Q${r.quantile}</text>`;});
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="各分组平均远期毛收益">${content}</svg>`;
}
function renderComparison() {
  const rows=comparison.filter(row=>row.horizon===horizon);
  $("comparison-panel").hidden=!rows.length;
  table("comparison",["因子","Rank IC","95% HAC 区间","高−低组收益","标签覆盖","诊断"],rows.map(r=>[r.name,num(r.rank_ic_mean),`[${num(r.rank_ic_ci_low)}, ${num(r.rank_ic_ci_high)}]`,pct(r.spread_mean),pct(r.label_coverage),r.diagnosis]));
  if(!offline) $("comparison").querySelectorAll("tbody tr").forEach((tr,i)=>{const cell=tr.firstElementChild;cell.replaceChildren();const button=document.createElement("button");button.className="link-button";button.textContent=rows[i].name;button.onclick=()=>load(rows[i].factor).catch(e=>error(e.message));cell.append(button);});
}
function render() {
  if(!current) return;
  const s=current.settings;
  if(!current.summary.some(r=>r.horizon===horizon)) horizon=current.summary[0].horizon;
  const m=current.summary.find(r=>r.horizon===horizon), daily=current.daily.filter(r=>r.horizon===horizon), groups=current.quantiles.filter(r=>r.horizon===horizon);
  $("empty").hidden=true;$("result").hidden=false;
  $("title").textContent=s.name;
  $("subtitle").textContent=`${s.start} — ${s.end} · ${s.quantiles} 组 · 方向 ${s.direction>0?"+1":"−1"} · ${s.preprocess==="raw"?"原值":"截面缩尾标准化"}`;
  $("horizons").replaceChildren(...current.summary.map(r=>{const b=document.createElement("button");b.textContent=`${r.horizon} 日`;b.className=r.horizon===horizon?"active":"";b.onclick=()=>{horizon=r.horizon;render();};return b;}));
  const cards=[["Rank IC 均值",num(m.rank_ic_mean),`Pearson IC ${num(m.pearson_ic_mean)}`,m.rank_ic_mean],["Rank ICIR",num(m.rank_icir),`正 IC 比例 ${pct(m.rank_ic_positive_fraction,1)}`,m.rank_icir],["最高 − 最低组",pct(m.spread_mean),`${horizon} 日重叠毛收益均值`,m.spread_mean],["标签覆盖率",pct(m.label_coverage),`因子覆盖 ${pct(m.factor_coverage,1)}`,1]];
  $("metrics").innerHTML=cards.map(([a,b,c,v])=>`<article><span>${esc(a)}</span><strong class="${v<0?"negative":""}">${esc(b)}</strong><small>${esc(c)}</small></article>`).join("");
  $("diagnosis").textContent=`${m.diagnosis}。Rank IC 95% HAC 区间 [${num(m.rank_ic_ci_low)}, ${num(m.rank_ic_ci_high)}]；有效 ${m.ic_days}/${m.mature_days} 日，尾部未成熟 ${m.signal_days-m.mature_days} 日。最高组日成员换手 ${pct(m.top_turnover,1)}，排名自相关 ${num(m.rank_autocorrelation)}。`;
  $("ic-chart").innerHTML=lineChart(daily);$("group-chart").innerHTML=barChart(groups);$("group-caption").textContent=`${horizon} 日毛收益 · 不复利`;
  table("groups",["分组","平均毛收益","形成样本","有效标签","标签覆盖率"],groups.map(r=>[`Q${r.quantile}`,pct(r.mean_return),count(r.formed_samples),count(r.paired_samples),pct(r.label_coverage)]));
  const years=current.periods.filter(r=>r.horizon===horizon&&r.frequency==="year");
  table("years",["年份","有效日","Rank IC","高−低组","标签覆盖"],years.map(r=>[r.period,r.ic_days,num(r.rank_ic_mean),pct(r.spread_mean),pct(r.label_coverage)]));
  const months=current.periods.filter(r=>r.horizon===horizon&&r.frequency==="month");
  $("months").innerHTML=months.map(r=>`<div style="background:${r.rank_ic_mean==null?"#f0f2f4":r.rank_ic_mean>=0?"#e9f3ef":"#f8eee6"}">${esc(r.period)}<strong>${num(r.rank_ic_mean)}</strong></div>`).join("");
  table("daily",["信号日","开仓日","退出日","可投数","因子数","有效标签","IC","Rank IC","高−低组"],daily.slice(-12).map(r=>[r.date,r.entry_date,r.exit_date,r.universe_count,r.signal_count,r.paired_count,num(r.pearson_ic),num(r.rank_ic),pct(r.spread)]));
  for(const kind of ["daily","quantiles"]) {const a=$("export-"+kind);a.hidden=!!offline;a.href=`/api/factors/export/${current.id}/${kind}`;}
  $("backtest").disabled=!!offline||s.factor.endsWith("control")||s.factor==="negative_low_vol_60";
  renderComparison();
}
async function load(id) {
  current=await api(`/api/factors/result/${encodeURIComponent(id)}`);
  const s=current.settings;$("history").value=id;$("factor").value=s.factor;$("custom").hidden=s.factor!=="custom";
  for(const key of ["start","end","direction","quantiles","preprocess","condition"]) $(key).value=s[key];
  if(s.formula){$("formula").value=s.formula;$("name").value=s.name;}
  document.querySelectorAll('input[name="horizon"]').forEach(input=>{input.checked=s.horizons.includes(Number(input.value));});
  $("backtest-result").hidden=true;render();
}
async function poll() {
  try {
    const state=await api("/api/factors/state");
    if(!initialized) {
      $("factor").replaceChildren(...Object.entries(state.catalog).map(([v,l])=>new Option(l,v)));
      comparison=await api("/api/factors/comparison");initialized=true;
    }
    const selected=current?.id;
    $("history").replaceChildren(...state.runs.slice().reverse().map(r=>new Option(r.name,r.id)));if(selected)$("history").value=selected;
    $("status").textContent=state.busy?state.phase:state.ready?"历史数据已就绪":"正在读取历史数据";
    $("run").disabled=state.busy||!state.ready;$("run").textContent=state.busy?"计算中…":"运行因子评价";
    $("feedback").textContent=state.error||state.phase;
    $("universe").textContent=state.historical_status?"历史非 ST / 正常交易，另沿用历史长度、价格与流动性门禁。状态未知时不入池。":"未提供历史状态：仅为第四课研究池，不声称剔除历史 ST。";
    if(state.first_date){$("start").min=$("end").min=state.first_date;$("start").max=$("end").max=state.last_date;}
    if(state.error)error(state.error);
    if(!current&&state.current_id)await load(state.current_id);
    if(pending&&!state.busy){if(state.current_id===pending){await load(pending);error(null);}pending=null;}
    if(backtestPending&&!state.busy){const base=await api("/api/state");if(base.current_id===backtestPending){$("backtest-result").hidden=false;$("feedback").textContent="扣费回测已完成，可查看资金与成交账本。";}backtestPending=null;}
  } catch(e){error(e.message);}
  setTimeout(poll,1500);
}
$("factor").onchange=()=>{$("custom").hidden=$("factor").value!=="custom";};
$("history").onchange=()=>load($("history").value).catch(e=>error(e.message));
$("form").onsubmit=async event=>{event.preventDefault();error(null);try {const body={factor:$("factor").value,formula:$("formula").value,condition:$("condition").value,start:$("start").value,end:$("end").value,direction:Number($("direction").value),quantiles:Number($("quantiles").value),preprocess:$("preprocess").value,horizons:[...document.querySelectorAll('input[name="horizon"]:checked')].map(input=>Number(input.value))};if(body.factor==="custom")body.name=$("name").value;$("run").disabled=true;pending=(await api("/api/factors/run",body)).id;$("feedback").textContent="正在计算因子评价…";}catch(e){error(e.message);$("run").disabled=false;}};
$("backtest").onclick=async()=>{error(null);try {backtestPending=(await api(`/api/factors/backtest/${current.id}`,{})).id;$("feedback").textContent="正在计算同因子扣费回测…";}catch(e){error(e.message);}};
if(offline){document.body.classList.add("offline");current=offline.result;comparison=offline.comparison;$("status").textContent="已保存的实数据运行";$("universe").textContent="沿用第四课历史非 ST 池，状态未知不入池。交互运行请启动本地服务。";render();}else{poll();}
