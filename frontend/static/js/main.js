/* ─── 全局状态 ─── */
const API = "http://localhost:5001/api";
let selectedStrategy = null;
let strategyList = [];
let portfolioChart = null;
let klineChart = null;
let predictChart = null;
let modelCompareChart = null;
let featImportanceChart = null;
let recBarChart = null;
let predDays = 7;
let recTopN = 10;
let predMode = "basic";   // "basic" | "advanced"

/* ─── 初始化 ─── */
// main.js 在 </body> 前加载，DOM 已就绪，直接执行无需等待 DOMContentLoaded
function _init() {
  loadStrategies();
  setDefaultDates();
  initCharts();
  loadRecHistory();       // 页面加载时读取历史记录
  loadIndustryHeatmap();  // 行业晴雨表
}
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", _init);
} else {
  _init();
}

/* ─── Tab 切换 ─── */
function switchTab(name) {
  // 隐藏所有 tab 内容（同时移除 hidden，统一用 display 控制）
  document.querySelectorAll(".tab-content").forEach(el => {
    el.classList.remove("active", "hidden");
    el.style.display = "none";
  });
  // 显示目标 tab
  const target = document.getElementById(`tab-${name}`);
  if (target) {
    target.style.display = "flex";
    target.classList.add("active");
  }
  // 更新导航按钮高亮
  document.querySelectorAll(".nav-tab").forEach(el => {
    el.classList.toggle("active", el.dataset.tab === name);
  });
  // 图表 resize（等 DOM 渲染完）
  setTimeout(() => {
    portfolioChart?.resize(); klineChart?.resize();
    predictChart?.resize(); recBarChart?.resize();
    modelCompareChart?.resize(); featImportanceChart?.resize();
  }, 100);
}

/* ─── 预测天数 / 推荐数量 ─── */
function setPredDays(n, btn) {
  predDays = n;
  document.querySelectorAll(".pred-day-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
}
function setPredMode(mode, btn) {
  predMode = mode;
  document.querySelectorAll(".mode-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
}
function setTopN(n, btn) {
  recTopN = n;
  document.querySelectorAll(".rec-n-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
}

function setDefaultDates() {
  const end = new Date();
  const start = new Date();
  start.setFullYear(start.getFullYear() - 2);
  document.getElementById("end-date").value = formatDate(end);
  document.getElementById("start-date").value = formatDate(start);
}

function setDateRange(years) {
  const end = new Date();
  const start = new Date();
  start.setFullYear(start.getFullYear() - years);
  document.getElementById("end-date").value = formatDate(end);
  document.getElementById("start-date").value = formatDate(start);
}

function formatDate(d) {
  return d.toISOString().split("T")[0];
}

/* ─── 策略加载 ─── */
async function loadStrategies() {
  try {
    const res = await fetch(`${API}/strategies`);
    const data = await res.json();
    if (!data.success) return;
    strategyList = data.data;
    renderStrategyList();
    selectStrategy(strategyList[0].id);
  } catch (e) {
    document.getElementById("strategy-list").innerHTML =
      '<div class="loading-text" style="color:#e74c3c">策略加载失败</div>';
  }
}

function renderStrategyList() {
  const el = document.getElementById("strategy-list");
  el.innerHTML = strategyList.map(s => `
    <div class="strategy-item" id="strategy-${s.id}" onclick="selectStrategy('${s.id}')">
      <div class="sname">${s.name}</div>
      <div class="sdesc">${s.description}</div>
    </div>
  `).join("");
}

function selectStrategy(id) {
  selectedStrategy = strategyList.find(s => s.id === id);
  document.querySelectorAll(".strategy-item").forEach(el => el.classList.remove("active"));
  const el = document.getElementById(`strategy-${id}`);
  if (el) el.classList.add("active");
  renderStrategyParams();
}

function renderStrategyParams() {
  if (!selectedStrategy) return;
  const el = document.getElementById("strategy-params");
  if (!selectedStrategy.params || selectedStrategy.params.length === 0) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = selectedStrategy.params.map(p => `
    <div class="param-item">
      <label>${p.label}（默认 ${p.default}）</label>
      <input type="number" id="param-${p.key}" value="${p.default}"
        min="${p.min}" max="${p.max}" step="${p.step || 1}" />
    </div>
  `).join("");
}

/* ─── 股票搜索 ─── */
async function searchStock() {
  const raw = document.getElementById("symbol-input").value.trim();
  if (!raw) return;

  // 优先用 data-code（已选中过的股票）
  const savedCode = document.getElementById("symbol-input").dataset.code;
  if (savedCode) {
    fetchStockInfo(savedCode);
    return;
  }

  // 纯6位数字直接查询
  if (/^\d{6}$/.test(raw)) {
    fetchStockInfo(raw);
    return;
  }

  // 否则走模糊搜索（支持中文/拼音/代码前缀）
  const keyword = raw;

  try {
    const res = await fetch(`${API}/search_stock?keyword=${encodeURIComponent(keyword)}`);
    const data = await res.json();
    if (!data.success || !data.data.length) {
      showSearchResults([]);
      return;
    }
    showSearchResults(data.data);
  } catch (e) {
    console.error(e);
  }
}

function showSearchResults(stocks) {
  const el = document.getElementById("search-results");
  if (!stocks.length) {
    el.innerHTML = '<div class="search-item no-result">未找到相关股票</div>';
    el.classList.remove("hidden");
    return;
  }
  el.innerHTML = stocks.map(s => {
    const isHK = s["市场"] === "港股";
    const marketTag = isHK
      ? `<span class="market-tag hk">港股</span>`
      : ``;
    return `<div class="search-item" onclick="selectStock('${s["代码"]}', '${s["名称"]}', '${s["市场"] || "A股"}')">` +
      `<span class="name">${s["名称"]}</span>` +
      `<span style="display:flex;align-items:center;gap:5px">${marketTag}<span class="code">${s["代码"]}</span></span>` +
      `</div>`;
  }).join("");
  el.classList.remove("hidden");
}

function selectStock(code, name, market) {
  // 输入框显示「名称 代码」，方便识别；实际用 code 查询
  document.getElementById("symbol-input").value = name ? `${name}  ${code}` : code;
  const inp = document.getElementById("symbol-input");
  inp.dataset.code = code;      // 存真实代码
  inp.dataset.market = market || "A股";  // 存市场类型
  document.getElementById("search-results").classList.add("hidden");
  // 港股：显示提示，不查行情（baostock 不支持）
  if (market === "港股") {
    document.getElementById("stock-info").innerHTML =
      `<div class="sname">${name} <span style="color:var(--text2);font-size:12px">${code}</span></div>` +
      `<div style="color:var(--yellow);font-size:11px;margin-top:4px">⚠️ 港股暂不支持回测，仅供搜索参考</div>`;
    document.getElementById("stock-info").classList.remove("hidden");
    return;
  }
  fetchStockInfo(code);
}

async function fetchStockInfo(symbol) {
  try {
    const res = await fetch(`${API}/stock_info?symbol=${symbol}`);
    const data = await res.json();
    if (!data.success) return;
    const info = data.data;
    const change = parseFloat(info["涨跌幅"] || 0);
    const changeClass = change >= 0 ? "up" : "down";
    const changeSign = change >= 0 ? "+" : "";
    document.getElementById("stock-info").innerHTML = `
      <div class="sname">${info["名称"]} <span style="color:var(--text2);font-size:12px">${info["代码"]}</span></div>
      <div>
        <span class="sprice">${info["最新价"]}</span>
        <span class="schange ${changeClass}">${changeSign}${change}%</span>
      </div>
    `;
    document.getElementById("stock-info").classList.remove("hidden");
  } catch (e) {
    console.error(e);
  }
}

// 回车搜索 & 手动输入时清除已选代码
document.addEventListener("DOMContentLoaded", () => {
  const inp = document.getElementById("symbol-input");
  inp.addEventListener("keydown", e => {
    if (e.key === "Enter") searchStock();
  });
  // 用户手动改内容时清除 data-code，避免用旧代码查询
  inp.addEventListener("input", () => {
    inp.dataset.code = "";
    // 隐藏搜索结果（重新输入时关闭旧列表）
    document.getElementById("search-results").classList.add("hidden");
  });
});

/* ─── 回测执行 ─── */
async function runBacktest() {
  const inp = document.getElementById("symbol-input");
  // 优先用 data-code（从搜索结果选中的），否则取输入框纯数字部分
  const symbol = (inp.dataset.code || inp.value.trim().match(/\d{6}/)?.[0] || "").trim();

  // 参数校验必须在禁用按钮之前，否则 return 后按钮永远卡住
  if (!symbol) { alert("请先搜索并选择股票"); return; }
  if (!selectedStrategy) { alert("请选择策略"); return; }

  // UI 状态（校验通过后再禁用）
  const btn = document.getElementById("run-btn");
  const btnText = document.getElementById("run-btn-text");
  btn.disabled = true;
  btnText.innerHTML = '<span class="spinner"></span>回测中...';

  const params = {
    symbol,
    start_date: document.getElementById("start-date").value,
    end_date: document.getElementById("end-date").value,
    strategy: selectedStrategy.id,
    cash: parseFloat(document.getElementById("cash-input").value),
    commission: parseFloat(document.getElementById("commission-input").value),
    strategy_params: {},
  };

  // 收集策略参数
  if (selectedStrategy.params) {
    selectedStrategy.params.forEach(p => {
      const el = document.getElementById(`param-${p.key}`);
      if (el) params.strategy_params[p.key] = parseFloat(el.value);
    });
  }
  hideAll();

  try {
    const res = await fetch(`${API}/backtest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    const data = await res.json();

    if (!data.success) {
      showError(data.error || "回测失败");
      return;
    }

    renderResults(data);
  } catch (e) {
    showError("请求失败：" + e.message);
  } finally {
    btn.disabled = false;
    btnText.textContent = "▶ 开始回测";
  }
}

/* ─── 结果渲染 ─── */
function renderResults(data) {
  const { summary, portfolio_values, trade_records, price_data } = data;

  // 显示结果区（必须先显示，ECharts 才能拿到正确容器尺寸）
  document.getElementById("result-area").classList.remove("hidden");

  // 指标卡片
  renderMetrics(summary);

  // 交易记录
  renderTradeTable(trade_records);

  // 等 DOM 渲染完成后再 resize + 绘图，避免容器从 hidden 变为可见时尺寸为 0
  setTimeout(() => {
    portfolioChart?.resize();
    klineChart?.resize();
    renderPortfolioChart(portfolio_values, summary, price_data);
    renderKlineChart(price_data, trade_records);
  }, 50);
}

function renderMetrics(s) {
  const totalReturnClass = s.total_return >= 0 ? "up" : "down";
  const benchmarkClass = s.benchmark_return >= 0 ? "up" : "down";
  const sign = v => v >= 0 ? "+" : "";

  const metrics = [
    { label: "总收益率", value: `${sign(s.total_return)}${s.total_return}%`, cls: totalReturnClass },
    { label: "年化收益率", value: s.annual_return != null ? `${sign(s.annual_return)}${s.annual_return}%` : "N/A", cls: s.annual_return >= 0 ? "up" : "down" },
    { label: "夏普比率", value: s.sharpe_ratio != null ? s.sharpe_ratio : "N/A", cls: "accent" },
    { label: "最大回撤", value: `-${s.max_drawdown}%`, cls: "down" },
    { label: "基准收益", value: `${sign(s.benchmark_return)}${s.benchmark_return}%`, cls: benchmarkClass },
    { label: "总交易次数", value: s.total_trades, cls: "neutral" },
    { label: "初始资金", value: `¥${s.initial_cash.toLocaleString()}`, cls: "neutral" },
    { label: "最终资产", value: `¥${s.final_value.toLocaleString()}`, cls: totalReturnClass },
  ];

  document.getElementById("metrics-grid").innerHTML = metrics.map(m => `
    <div class="metric-card">
      <div class="metric-label">${m.label}</div>
      <div class="metric-value ${m.cls}">${m.value}</div>
    </div>
  `).join("");
}

function renderPortfolioChart(portfolioValues, summary, priceData) {
  if (!portfolioChart) return;

  const dates = portfolioValues.map(v => v.date);
  const values = portfolioValues.map(v => v.value);
  const initial = summary.initial_cash;

  // 基准：买入持有 —— 用真实每日收盘价构建，而非线性插值
  // priceData 与 portfolioValues 日期一一对应（均来自同一 df）
  const priceMap = {};
  if (priceData) {
    priceData.forEach(p => { priceMap[p.date] = p.close; });
  }
  const firstClose = priceData && priceData.length > 0 ? priceData[0].close : null;
  const benchmarkValues = dates.map(d => {
    if (!firstClose || !priceMap[d]) return null;
    return +(initial * (priceMap[d] / firstClose)).toFixed(2);
  });

  portfolioChart.setOption({
    backgroundColor: "transparent",
    tooltip: { trigger: "axis", formatter: params => {
      return params.map(p => `${p.seriesName}: ¥${p.value.toLocaleString()}`).join("<br/>");
    }},
    legend: { data: ["策略净值", "基准（买入持有）"], textStyle: { color: "#8892a4" }, top: 0 },
    grid: { left: 60, right: 20, top: 36, bottom: 30 },
    xAxis: { type: "category", data: dates, axisLabel: { color: "#8892a4", fontSize: 11 }, axisLine: { lineStyle: { color: "#2e3350" } } },
    yAxis: { type: "value", axisLabel: { color: "#8892a4", fontSize: 11, formatter: v => `¥${(v/10000).toFixed(1)}w` }, splitLine: { lineStyle: { color: "#2e3350" } } },
    series: [
      { name: "策略净值", type: "line", data: values, smooth: true, symbol: "none", lineStyle: { color: "#4f8ef7", width: 2 }, areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(79,142,247,0.3)" }, { offset: 1, color: "rgba(79,142,247,0)" }] } } },
      { name: "基准（买入持有）", type: "line", data: benchmarkValues, smooth: true, symbol: "none", lineStyle: { color: "#8892a4", width: 1.5, type: "dashed" } },
    ],
  });
}

function renderKlineChart(priceData, trades) {
  if (!klineChart) return;

  const dates = priceData.map(d => d.date);
  const ohlc = priceData.map(d => [d.open, d.close, d.low, d.high]);
  const volumes = priceData.map(d => d.volume);

  // 标记买卖点
  const buyPoints = [], sellPoints = [];
  trades.forEach(t => {
    const buyIdx = dates.indexOf(t.open_date);
    const sellIdx = dates.indexOf(t.close_date);
    if (buyIdx >= 0) buyPoints.push({ coord: [t.open_date, priceData[buyIdx]?.low * 0.98], value: "买" });
    if (sellIdx >= 0) sellPoints.push({ coord: [t.close_date, priceData[sellIdx]?.high * 1.02], value: "卖" });
  });

  klineChart.setOption({
    backgroundColor: "transparent",
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    grid: [
      { left: 60, right: 20, top: 10, bottom: 80 },
      { left: 60, right: 20, top: "75%", bottom: 20 },
    ],
    xAxis: [
      { type: "category", data: dates, axisLabel: { color: "#8892a4", fontSize: 10 }, axisLine: { lineStyle: { color: "#2e3350" } }, gridIndex: 0 },
      { type: "category", data: dates, axisLabel: { show: false }, gridIndex: 1 },
    ],
    yAxis: [
      { type: "value", axisLabel: { color: "#8892a4", fontSize: 11 }, splitLine: { lineStyle: { color: "#2e3350" } }, gridIndex: 0 },
      { type: "value", axisLabel: { color: "#8892a4", fontSize: 10, formatter: v => (v/10000).toFixed(0)+"w" }, splitLine: { lineStyle: { color: "#2e3350" } }, gridIndex: 1 },
    ],
    series: [
      {
        type: "candlestick", data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
        itemStyle: { color: "#e74c3c", color0: "#26c281", borderColor: "#e74c3c", borderColor0: "#26c281" },
        markPoint: {
          data: [
            ...buyPoints.map(p => ({ ...p, symbol: "arrow", symbolSize: 12, symbolRotate: 180, itemStyle: { color: "#e74c3c" }, label: { color: "#fff", fontSize: 10 } })),
            ...sellPoints.map(p => ({ ...p, symbol: "arrow", symbolSize: 12, itemStyle: { color: "#26c281" }, label: { color: "#fff", fontSize: 10 } })),
          ]
        }
      },
      {
        type: "bar", data: volumes, xAxisIndex: 1, yAxisIndex: 1,
        itemStyle: { color: params => {
          const d = priceData[params.dataIndex];
          return d.close >= d.open ? "#e74c3c" : "#26c281";
        }},
      },
    ],
  });
}

function renderTradeTable(trades) {
const wrap = document.getElementById("trade-table-wrap");
if (!trades || trades.length === 0) {
wrap.innerHTML = '<div class="no-trades">本次回测无交易记录</div>';
return;
}
const fmt = (v) => (v === undefined || v === null || v === "-") ? "-" : v;
const rows = trades.map((t, i) => `
<tr>
<td>${i + 1}</td>
<td>${t.open_date}</td>
<td style="font-size:11px;color:var(--text2)">${fmt(t.buy_price)}</td>
<td style="font-size:11px;color:var(--text2)">${fmt(t.buy_size)}</td>
<td style="font-size:11px;color:var(--text2)">${fmt(t.buy_value)}</td>
<td>${t.close_date}</td>
<td style="font-size:11px;color:var(--text2)">${fmt(t.sell_price)}</td>
<td style="font-size:11px;color:var(--text2)">${fmt(t.sell_size)}</td>
<td style="font-size:11px;color:var(--text2)">${fmt(t.sell_value)}</td>
<td class="${t.pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${t.pnl >= 0 ? "+" : ""}${t.pnl}</td>
<td class="${t.pnlcomm >= 0 ? "pnl-pos" : "pnl-neg"}">${t.pnlcomm >= 0 ? "+" : ""}${t.pnlcomm}</td>
</tr>
`).join("");
wrap.innerHTML = `
<table class="trade-table">
<thead>
<tr>
  <th>#</th>
  <th>买入日期</th><th>买入价</th><th>买入股数</th><th>买入金额</th>
  <th>卖出日期</th><th>卖出价</th><th>卖出股数</th><th>卖出金额</th>
  <th>盈亏（元）</th><th>扣费后盈亏</th>
</tr>
</thead>
<tbody>${rows}</tbody>
</table>
`;
}

/* ─── 图表初始化 ─── */
function initCharts() {
  portfolioChart = echarts.init(document.getElementById("chart-portfolio"), "dark");
  klineChart = echarts.init(document.getElementById("chart-kline"), "dark");
  window.addEventListener("resize", () => {
    portfolioChart?.resize();
    klineChart?.resize();
  });
}

/* ─── 工具函数 ─── */
function hideAll() {
  document.getElementById("empty-state").classList.add("hidden");
  document.getElementById("result-area").classList.add("hidden");
  document.getElementById("error-area").classList.add("hidden");
}

function showError(msg) {
  document.getElementById("error-msg").textContent = msg;
  document.getElementById("error-area").classList.remove("hidden");
}

/* ══════════════════════════════════════════
   预测功能
══════════════════════════════════════════ */
async function runPredict() {
  const symbol = document.getElementById("pred-symbol").value.trim();
  if (!symbol) { alert("请输入股票代码"); return; }

  const btn = document.getElementById("pred-btn");
  const btnText = document.getElementById("pred-btn-text");
  btn.disabled = true;

  const isAdvanced = predMode === "advanced";
  const days = isAdvanced ? Math.min(predDays, 30) : predDays;
  btnText.innerHTML = isAdvanced
    ? '<span class="spinner"></span>集成预测中（约30秒）...'
    : '<span class="spinner"></span>预测中...';

  document.getElementById("pred-empty").classList.add("hidden");
  document.getElementById("pred-result").classList.add("hidden");
  document.getElementById("pred-error").classList.add("hidden");

  try {
    const endpoint = isAdvanced ? "predict_v2" : "predict";
    const res = await fetch(`${API}/${endpoint}?symbol=${symbol}&days=${days}`);
    const data = await res.json();
    if (!data.success) {
      document.getElementById("pred-error-msg").textContent = data.error;
      document.getElementById("pred-error").classList.remove("hidden");
      return;
    }
    renderPredictResult(data, isAdvanced);
  } catch(e) {
    document.getElementById("pred-error-msg").textContent = "请求失败：" + e.message;
    document.getElementById("pred-error").classList.remove("hidden");
  } finally {
    btn.disabled = false;
    btnText.textContent = "🔮 开始预测";
  }
}

function renderPredictResult(data, isAdvanced = false) {
  document.getElementById("pred-result").classList.remove("hidden");

  // ── 指标卡片 ──────────────────────────────────────────
  const sign = v => v >= 0 ? "+" : "";
  const changeClass = data.pred_change >= 0 ? "up" : "down";
  const cur = data.currency || "¥";
  const marketBadge = data.market === "港股"
    ? `<span style="font-size:11px;color:#f39c12;background:rgba(243,156,18,0.12);border:1px solid rgba(243,156,18,0.3);border-radius:3px;padding:1px 6px;margin-left:6px">港股</span>`
    : "";
  const modeBadge = isAdvanced
    ? `<span style="font-size:11px;color:#26c281;background:rgba(38,194,129,0.12);border:1px solid rgba(38,194,129,0.3);border-radius:3px;padding:1px 6px;margin-left:6px">集成</span>`
    : "";
  // 增强模式额外显示最优模型和权重
  const bestModelCard = isAdvanced && data.best_model ? `
    <div class="metric-card">
      <div class="metric-label">最优模型</div>
      <div class="metric-value neutral" style="font-size:13px">${data.best_model}</div>
    </div>` : "";

  document.getElementById("pred-metrics").innerHTML = `
    <div class="metric-card">
      <div class="metric-label">当前价格${marketBadge}${modeBadge}</div>
      <div class="metric-value neutral">${cur}${data.last_price}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">预测${data.pred_days}日涨跌</div>
      <div class="metric-value ${changeClass}">${sign(data.pred_change)}${data.pred_change}%</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">趋势判断</div>
      <div class="metric-value" style="color:${data.trend_color === 'green' ? 'var(--green)' : data.trend_color === 'red' ? 'var(--red)' : 'var(--text2)'}">${data.trend_label}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">日均波动率</div>
      <div class="metric-value neutral">${data.daily_vol}%</div>
    </div>
    ${bestModelCard}
  `;

  // ── 主预测图表 ────────────────────────────────────────
  if (!predictChart) {
    predictChart = echarts.init(document.getElementById("chart-predict"), "dark");
  }
  const hist = data.hist;
  const fc   = data.forecast;
  const joinPrice = hist.prices[hist.prices.length - 1];
  const nullHist  = new Array(hist.dates.length - 1).fill(null);

  predictChart.setOption({
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" },
    legend: { data: ["历史价格", "MA5", "MA20", "集成预测"], textStyle: { color: "#8892a4" }, top: 0 },
    grid: { left: 60, right: 20, top: 36, bottom: 30 },
    xAxis: { type: "category", data: [...hist.dates, ...fc.dates], axisLabel: { color: "#8892a4", fontSize: 10 }, axisLine: { lineStyle: { color: "#2e3350" } } },
    yAxis: { type: "value", axisLabel: { color: "#8892a4", fontSize: 11 }, splitLine: { lineStyle: { color: "#2e3350" } } },
    series: [
      { name: "历史价格", type: "line", symbol: "none",
        data: [...hist.prices, ...new Array(fc.dates.length).fill(null)],
        lineStyle: { color: "#4f8ef7", width: 2 } },
      { name: "MA5", type: "line", symbol: "none",
        data: [...hist.ma5, ...new Array(fc.dates.length).fill(null)],
        lineStyle: { color: "#f39c12", width: 1, type: "dashed" } },
      { name: "MA20", type: "line", symbol: "none",
        data: [...hist.ma20, ...new Array(fc.dates.length).fill(null)],
        lineStyle: { color: "#7c5cfc", width: 1, type: "dashed" } },
      { name: "集成预测", type: "line", symbol: "none",
        data: [...nullHist, joinPrice, ...fc.prices],
        lineStyle: { color: "#26c281", width: 2, type: "dashed" },
        itemStyle: { color: "#26c281" } },
      { name: "置信上轨", type: "line", symbol: "none",
        data: [...nullHist, joinPrice, ...fc.upper],
        lineStyle: { color: "rgba(38,194,129,0.4)", width: 1 },
        areaStyle: { color: "rgba(38,194,129,0.12)", origin: "auto" },
        stack: "band", tooltip: { show: false } },
      { name: "置信下轨", type: "line", symbol: "none",
        data: [...nullHist, 0, ...fc.upper.map((u, i) => +(u - fc.lower[i]).toFixed(3))],
        lineStyle: { color: "rgba(38,194,129,0.4)", width: 1 },
        areaStyle: { color: "#1a2035" },
        stack: "band", tooltip: { show: false } },
    ],
  });

  // ── 增强模式：模型对比 + 验证表 + 特征重要性 ──────────
  const compareEl = document.getElementById("pred-model-compare");
  if (isAdvanced && data.model_compare) {
    compareEl.classList.remove("hidden");

    // 1. 各模型预测对比折线图
    if (!modelCompareChart) {
      modelCompareChart = echarts.init(document.getElementById("chart-model-compare"), "dark");
    }
    const modelColors = { "Monte Carlo": "#4f8ef7", "ARIMA+GARCH": "#f39c12", "XGBoost": "#e74c3c" };
    const compareSeries = Object.entries(data.model_compare).map(([name, res]) => ({
      name: `${name}(${(res.weight * 100).toFixed(0)}%)`,
      type: "line", symbol: "none",
      data: [...nullHist, joinPrice, ...res.prices],
      lineStyle: { color: modelColors[name] || "#aaa", width: 1.5, type: "dashed" },
    }));
    // 加上集成结果
    compareSeries.unshift({
      name: "集成结果", type: "line", symbol: "none",
      data: [...nullHist, joinPrice, ...fc.prices],
      lineStyle: { color: "#26c281", width: 2.5 },
    });
    modelCompareChart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#8892a4" }, top: 0, type: "scroll" },
      grid: { left: 60, right: 20, top: 36, bottom: 30 },
      xAxis: { type: "category", data: [...hist.dates, ...fc.dates], axisLabel: { color: "#8892a4", fontSize: 10 } },
      yAxis: { type: "value", axisLabel: { color: "#8892a4", fontSize: 11 }, splitLine: { lineStyle: { color: "#2e3350" } } },
      series: compareSeries,
    });

    // 2. Walk-Forward 验证表
    if (data.validation && data.validation.length) {
      const rows = data.validation.map(v => {
        const acc = v.direction_acc != null ? `${(v.direction_acc * 100).toFixed(1)}%` : "-";
        const mape = v.mape != null ? `${v.mape.toFixed(2)}%` : "-";
        const wr = v.win_rate != null ? `${(v.win_rate * 100).toFixed(1)}%` : "-";
        const w = `${(v.weight * 100).toFixed(1)}%`;
        const isErr = !!v.error;
        const accColor = !isErr && v.direction_acc >= 0.55 ? "var(--green)" : v.direction_acc >= 0.5 ? "var(--yellow)" : "var(--red)";
        return `<tr>
          <td><strong>${v.model}</strong><br><span style="font-size:10px;color:var(--text2)">${v.model_info || ""}</span></td>
          <td style="color:${accColor};font-weight:600">${isErr ? `<span style="color:var(--text2)">失败</span>` : acc}</td>
          <td>${isErr ? "-" : mape}</td>
          <td>${isErr ? "-" : wr}</td>
          <td style="color:var(--accent);font-weight:600">${w}</td>
          <td>${v.n_windows || 0} 窗口</td>
        </tr>`;
      }).join("");
      document.getElementById("pred-validation-table").innerHTML = `
        <table class="val-table">
          <thead><tr><th>模型</th><th>方向准确率</th><th>MAPE</th><th>信号胜率</th><th>权重</th><th>验证量</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>`;
    }

    // 3. XGBoost 特征重要性横向柱状图
    const fi = data.feature_importance || {};
    const fiEntries = Object.entries(fi).sort((a, b) => b[1] - a[1]).slice(0, 8);
    if (fiEntries.length > 0) {
      if (!featImportanceChart) {
        featImportanceChart = echarts.init(document.getElementById("chart-feat-importance"), "dark");
      }
      const fiNames = fiEntries.map(([k]) => k).reverse();
      const fiVals  = fiEntries.map(([, v]) => +(v * 100).toFixed(2)).reverse();
      featImportanceChart.setOption({
        backgroundColor: "transparent",
        tooltip: { trigger: "axis", formatter: p => `${p[0].name}: ${p[0].value}%` },
        grid: { left: 120, right: 30, top: 10, bottom: 20 },
        xAxis: { type: "value", axisLabel: { color: "#8892a4", formatter: v => v + "%" }, splitLine: { lineStyle: { color: "#2e3350" } } },
        yAxis: { type: "category", data: fiNames, axisLabel: { color: "#cdd6f4", fontSize: 11 } },
        series: [{ type: "bar", data: fiVals, barMaxWidth: 18,
          itemStyle: { color: p => `rgba(79,142,247,${0.4 + p.dataIndex / fiNames.length * 0.6})` },
          label: { show: true, position: "right", color: "#8892a4", fontSize: 10, formatter: p => p.value + "%" } }],
      });
    } else {
      const xgbErr = (data.errors && data.errors["XGBoost"]) ? data.errors["XGBoost"] : "";
      document.getElementById("chart-feat-importance").innerHTML =
        `<div style="color:var(--text2);padding:20px;text-align:center;font-size:12px">XGBoost 未成功运行，无特征重要性数据${xgbErr ? `<br><span style="color:var(--red);font-size:11px">${xgbErr}</span>` : ""}</div>`;
    }
  } else {
    compareEl.classList.add("hidden");
  }

  // ── 说明文字 ──────────────────────────────────────────
  document.getElementById("pred-explain").innerHTML =
    (data.explain || `基于 Monte Carlo 随机游走模拟，预测未来 ${data.pred_days} 个交易日走势。`) +
    `<br><span style="color:var(--yellow)">⚠️ 预测仅供参考，不构成投资建议，实际走势受多种因素影响。</span>`;

  // ── 交易建议 ──────────────────────────────────────────
  renderTradingAdvice(data);

  // ── 资讯（异步加载，不阻塞主流程）────────────────────
  fetchStockNews(data.symbol || document.getElementById("pred-symbol").value.trim());
}

/* ── 交易建议：买入 / 止损 / 止盈 ─────────────────────── */
function renderTradingAdvice(data) {
  const adviceEl = document.getElementById("pred-advice");
  const cardsEl  = document.getElementById("advice-cards");
  if (!adviceEl || !cardsEl) return;

  const cur       = data.currency || "¥";
  const price     = data.last_price;
  const vol       = (data.daily_vol || 1) / 100;          // 日波动率（小数）
  const fc        = data.forecast || {};
  const predPrices = fc.prices || [];
  const upper      = fc.upper  || [];
  const lower      = fc.lower  || [];
  const days       = data.pred_days || 30;
  const trendLabel = data.trend_label || "震荡";
  const trendColor = data.trend_color || "gray";

  // ── 计算建议价位 ──────────────────────────────────────
  // 买入区间：当前价 ± 0.5 个日波动率（约 1 个标准差的一半，给一点缓冲）
  const buyLow  = +(price * (1 - vol * 0.5)).toFixed(2);
  const buyHigh = +(price * (1 + vol * 0.3)).toFixed(2);

  // 止损：当前价下方 1.5 个日波动率（约 3% 左右，视波动率而定）
  const stopLoss = +(price * (1 - vol * 1.5)).toFixed(2);
  const stopLossPct = +((price - stopLoss) / price * 100).toFixed(1);

  // 止盈：取预测中位数末端价格，但不超过置信上轨末端
  const predEnd  = predPrices.length ? predPrices[predPrices.length - 1] : price;
  const upperEnd = upper.length ? upper[upper.length - 1] : predEnd * 1.05;
  const takeProfit1 = +predEnd.toFixed(2);                          // 保守止盈（中位数）
  const takeProfit2 = +(price + (upperEnd - price) * 0.6).toFixed(2); // 激进止盈（60% 上轨）
  const tp1Pct = +((takeProfit1 - price) / price * 100).toFixed(1);
  const tp2Pct = +((takeProfit2 - price) / price * 100).toFixed(1);

  // ── 综合建议文字 ──────────────────────────────────────
  const trendMap = {
    "强烈上涨": { action: "积极买入", actionCls: "advice-action--buy", icon: "🚀" },
    "偏强":     { action: "逢低买入", actionCls: "advice-action--buy", icon: "📈" },
    "震荡":     { action: "观望为主", actionCls: "advice-action--hold", icon: "⚖️" },
    "偏弱":     { action: "谨慎持有", actionCls: "advice-action--hold", icon: "⚠️" },
    "强烈下跌": { action: "建议回避", actionCls: "advice-action--sell", icon: "🔻" },
  };
  const advice = trendMap[trendLabel] || { action: "观望为主", actionCls: "advice-action--hold", icon: "⚖️" };

  cardsEl.innerHTML = `
    <!-- 综合操作建议 -->
    <div class="advice-card advice-card--action">
      <div class="advice-card-icon">${advice.icon}</div>
      <div class="advice-card-body">
        <div class="advice-card-label">综合操作建议</div>
        <div class="advice-card-value ${advice.actionCls}">${advice.action}</div>
        <div class="advice-card-sub">趋势：${trendLabel} · 预测${days}日涨跌 ${data.pred_change >= 0 ? "+" : ""}${data.pred_change}%</div>
      </div>
    </div>

    <!-- 买入区间 -->
    <div class="advice-card advice-card--buy">
      <div class="advice-card-icon">🎯</div>
      <div class="advice-card-body">
        <div class="advice-card-label">建议买入区间</div>
        <div class="advice-card-value advice-action--buy">${cur}${buyLow} ~ ${cur}${buyHigh}</div>
        <div class="advice-card-sub">当前价 ${cur}${price}，基于日波动率 ${data.daily_vol}% 计算</div>
      </div>
    </div>

    <!-- 止损 -->
    <div class="advice-card advice-card--stop">
      <div class="advice-card-icon">🛡️</div>
      <div class="advice-card-body">
        <div class="advice-card-label">建议止损价</div>
        <div class="advice-card-value advice-action--sell">${cur}${stopLoss}</div>
        <div class="advice-card-sub">较当前价下方 ${stopLossPct}%，触及时建议止损离场</div>
      </div>
    </div>

    <!-- 止盈（保守） -->
    <div class="advice-card advice-card--tp1">
      <div class="advice-card-icon">💰</div>
      <div class="advice-card-body">
        <div class="advice-card-label">保守止盈（中位数预测）</div>
        <div class="advice-card-value advice-action--buy">${cur}${takeProfit1}</div>
        <div class="advice-card-sub">较当前价 ${tp1Pct >= 0 ? "+" : ""}${tp1Pct}%，${days}日预测中位数</div>
      </div>
    </div>

    <!-- 止盈（激进） -->
    <div class="advice-card advice-card--tp2">
      <div class="advice-card-icon">🎆</div>
      <div class="advice-card-body">
        <div class="advice-card-label">激进止盈（置信上轨60%）</div>
        <div class="advice-card-value advice-action--buy">${cur}${takeProfit2}</div>
        <div class="advice-card-sub">较当前价 ${tp2Pct >= 0 ? "+" : ""}${tp2Pct}%，乐观情景目标</div>
      </div>
    </div>
  `;

  adviceEl.classList.remove("hidden");
}

/* ── 资讯：异步拉取并渲染利好/利空 ────────────────────── */
async function fetchStockNews(symbol) {
  const newsEl    = document.getElementById("pred-news");
  const loadingEl = document.getElementById("news-loading");
  const colsEl    = document.getElementById("news-columns");
  const barEl     = document.getElementById("news-sentiment-bar");
  if (!newsEl || !colsEl) return;

  // 先显示加载态
  newsEl.classList.remove("hidden");
  loadingEl.classList.remove("hidden");
  colsEl.innerHTML = "";
  barEl.innerHTML  = "";

  try {
    const res  = await fetch(`${API}/stock_news?symbol=${symbol}`);
    const data = await res.json();
    loadingEl.classList.add("hidden");

    if (!data.success || data.total === 0) {
      colsEl.innerHTML = `<div class="news-empty">暂未获取到相关资讯</div>`;
      return;
    }

    // ── 情感比例条 ────────────────────────────────────
    const { bullish_count, bearish_count, neutral_count } = data.sentiment_summary;
    const total = bullish_count + bearish_count + neutral_count || 1;
    const bPct  = +(bullish_count / total * 100).toFixed(0);
    const rPct  = +(bearish_count / total * 100).toFixed(0);
    const nPct  = 100 - bPct - rPct;
    barEl.innerHTML = `
      <div class="sentiment-bar-wrap" title="利好 ${bullish_count} 条 / 利空 ${bearish_count} 条 / 中性 ${neutral_count} 条">
        <div class="sentiment-seg sentiment-seg--bull" style="width:${bPct}%"></div>
        <div class="sentiment-seg sentiment-seg--bear" style="width:${rPct}%"></div>
        <div class="sentiment-seg sentiment-seg--neutral" style="width:${nPct}%"></div>
      </div>
      <span class="sentiment-label sentiment-label--bull">利好 ${bullish_count}</span>
      <span class="sentiment-label sentiment-label--bear">利空 ${bearish_count}</span>
      <span class="sentiment-label sentiment-label--neutral">中性 ${neutral_count}</span>
    `;

    // ── 渲染两列：利好 / 利空 ─────────────────────────
    const renderNewsItems = (list, cls, emptyText) => {
      if (!list || list.length === 0) {
        return `<div class="news-empty-col">${emptyText}</div>`;
      }
      return list.map(n => `
        <div class="news-item news-item--${cls}">
          <div class="news-item-title">${n.title}</div>
          ${n.summary ? `<div class="news-item-summary">${n.summary}</div>` : ""}
          <div class="news-item-meta">
            <span class="news-item-source">${n.source || ""}</span>
            <span class="news-item-time">${n.time || ""}</span>
          </div>
        </div>
      `).join("");
    };

    colsEl.innerHTML = `
      <div class="news-col news-col--bull">
        <div class="news-col-header news-col-header--bull">📈 利好资讯（${bullish_count}）</div>
        ${renderNewsItems(data.bullish, "bull", "暂无明显利好资讯")}
      </div>
      <div class="news-col news-col--bear">
        <div class="news-col-header news-col-header--bear">📉 利空资讯（${bearish_count}）</div>
        ${renderNewsItems(data.bearish, "bear", "暂无明显利空资讯")}
      </div>
    `;

  } catch(e) {
    loadingEl.classList.add("hidden");
    colsEl.innerHTML = `<div class="news-empty">资讯加载失败：${e.message}</div>`;
  }
}

/* ══════════════════════════════════════════
   推荐功能
══════════════════════════════════════════ */
let _recSeed = null;       // null = 随机，数字 = 固定种子
let _recIndustry = "石油石化"; // 当前选中的行业（默认第一个申万行业）

// 行业下拉框变化
function onIndustryChange(val) {
  _recIndustry = val;
  const hint = document.getElementById("rec-industry-hint");
  if (hint) {
    hint.classList.remove("hidden");
  }
}

// ── 进度条辅助函数 ──────────────────────────────────────
function _showProgress(show) {
  const wrap = document.getElementById("rec-progress-wrap");
  if (!wrap) return;
  if (show) wrap.classList.remove("hidden");
  else wrap.classList.add("hidden");
}

function _updateProgress(step, current, total, msg) {
  const stepEl = document.getElementById("rec-progress-step");
  const pctEl  = document.getElementById("rec-progress-pct");
  const barEl  = document.getElementById("rec-progress-bar");
  const msgEl  = document.getElementById("rec-progress-msg");

  const stepLabels = {
    sample: "采样候选股",
    index:  "获取大盘基准",
    fetch:  "拉取行情数据",
    score:  "多因子评分",
  };
  if (stepEl) stepEl.textContent = stepLabels[step] || step;

  const pct = total > 0 ? Math.round((current / total) * 100) : 0;
  if (pctEl) pctEl.textContent = pct + "%";
  if (barEl) barEl.style.width = pct + "%";
  if (msgEl) msgEl.textContent = msg || "";
}

function runRecommend(forceRefresh = false) {
  const btn = document.getElementById("rec-btn");
  const btnText = document.getElementById("rec-btn-text");
  const refreshBtn = document.getElementById("rec-refresh-btn");
  btn.disabled = true;
  if (refreshBtn) refreshBtn.disabled = true;

  // 换一批时用新的随机种子（时间戳），否则用 null（后端自动按分钟变化）
  if (forceRefresh) {
    _recSeed = Date.now();
    btnText.innerHTML = '<span class="spinner"></span>重新采样中...';
  } else {
    _recSeed = null;
    btnText.innerHTML = '<span class="spinner"></span>筛选中...';
  }

  document.getElementById("rec-empty").classList.add("hidden");
  document.getElementById("rec-result").classList.add("hidden");
  document.getElementById("rec-error").classList.add("hidden");

  // 显示进度条，初始化为 0
  _showProgress(true);
  _updateProgress("sample", 0, 1, "正在连接服务器...");

  const seedParam = _recSeed ? `&seed=${_recSeed}` : "";
  const industryParam = _recIndustry
    ? `&industry=${encodeURIComponent(_recIndustry)}` : "";
  const sampleSizeRaw = parseInt(document.getElementById("rec-sample-size")?.value || "100", 10);
  const sampleSize = Math.max(20, Math.min(200, isNaN(sampleSizeRaw) ? 100 : sampleSizeRaw));
  const sampleParam = `&sample_size=${sampleSize}`;
  const url = `${API}/recommend_stream?top_n=${recTopN}${seedParam}${industryParam}${sampleParam}`;

  const es = new EventSource(url);

  es.onmessage = async (e) => {
    let item;
    try { item = JSON.parse(e.data); } catch { return; }

    if (item.type === "progress") {
      _updateProgress(item.step, item.current, item.total, item.msg);

    } else if (item.type === "done") {
      es.close();
      _showProgress(false);
      btn.disabled = false;
      if (refreshBtn) refreshBtn.disabled = false;
      btnText.textContent = "⭐ 开始筛选";

      const data = item.result;
      if (!data.success) {
        document.getElementById("rec-error-msg").textContent = data.error;
        document.getElementById("rec-error").classList.remove("hidden");
        return;
      }
      renderRecommendResult(data);
      try {
        await saveRecHistory(data);
        loadRecHistory();
      } catch(_) {}

    } else if (item.type === "error") {
      es.close();
      _showProgress(false);
      btn.disabled = false;
      if (refreshBtn) refreshBtn.disabled = false;
      btnText.textContent = "⭐ 开始筛选";
      document.getElementById("rec-error-msg").textContent = item.error || "请求失败";
      document.getElementById("rec-error").classList.remove("hidden");
    }
  };

  es.onerror = () => {
    es.close();
    _showProgress(false);
    btn.disabled = false;
    if (refreshBtn) refreshBtn.disabled = false;
    btnText.textContent = "⭐ 开始筛选";
    document.getElementById("rec-error-msg").textContent = "SSE 连接失败，请检查后端服务";
    document.getElementById("rec-error").classList.remove("hidden");
  };
}

function renderRecommendResult(data) {
  document.getElementById("rec-result").classList.remove("hidden");

  // ── 头部信息 ──────────────────────────────────────
  const idxSign = data.index_return_20d >= 0 ? "+" : "";
  const sampledCount = data.sampled_count ?? data.total_scanned;
  const scoredCount  = data.scored_count  ?? data.total_scanned;
  const errorsCount  = data.errors_count  ?? 0;
  const failBadge = errorsCount > 0
    ? ` <span style="color:var(--orange,#f39c12);font-size:11px">（${errorsCount}只失败）</span>`
    : "";
  document.getElementById("rec-header").innerHTML =
    `本次采样 <strong>${sampledCount}</strong> 只 → 成功评分 <strong>${scoredCount}</strong> 只${failBadge}，筛出 Top <strong>${data.top_n}</strong> 推荐 · ` +
    `沪深300近20日 <strong style="color:${data.index_return_20d>=0?'var(--green)':'var(--red)'}">${idxSign}${data.index_return_20d}%</strong> · ` +
    `更新时间：${data.update_time}`;

  // ── 算法说明 ──────────────────────────────────────
  const noteEl = document.getElementById("rec-algo-note");
  if (noteEl && data.algo_note) {
    noteEl.textContent = "💡 " + data.algo_note;
    noteEl.style.display = "block";
  }

  // ── 评分柱状图 ────────────────────────────────────
  if (!recBarChart) {
    recBarChart = echarts.init(document.getElementById("chart-rec-bar"), "dark");
  }
  const names  = data.results.map(r => r.name);
  const scores = data.results.map(r => r.score);
  const colors = data.results.map(r => r.signal_color);

  recBarChart.setOption({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      formatter: p => {
        const r = data.results.find(x => x.name === p[0].name);
        if (!r) return `${p[0].name}: ${p[0].value}`;
        const factors = r.factors || {};
        const fStr = Object.entries(factors).map(([k,v]) => `${k}: ${v}`).join(" | ");
        return `<strong>${r.name}</strong> (${r.industry || ""})<br>综合评分：${p[0].value}<br><span style="font-size:11px;color:#8892a4">${fStr}</span>`;
      }
    },
    grid: { left: 80, right: 20, top: 10, bottom: 30 },
    xAxis: { type: "value", max: 100, axisLabel: { color: "#8892a4" }, splitLine: { lineStyle: { color: "#2e3350" } } },
    yAxis: { type: "category", data: [...names].reverse(), axisLabel: { color: "#e2e8f0", fontSize: 12 } },
    series: [{
      type: "bar", data: [...scores].reverse(),
      itemStyle: { color: p => colors[data.results.length - 1 - p.dataIndex] || "#4f8ef7", borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: "right", color: "#8892a4", fontSize: 11, formatter: p => p.value.toFixed(1) },
    }],
  });

  // ── 初始化详解面板（默认显示指标说明）────────────
  renderDetailDefault();

  // ── 详细表格 ──────────────────────────────────────
  // 保存当前推荐结果供点击详解使用
  _recCurrentResults = data.results;

  const rows = data.results.map((r, i) => {
    const change5Class = r.change_5d >= 0 ? "pnl-pos" : "pnl-neg";
    const sign = r.change_5d >= 0 ? "+" : "";
    const factors = r.factors || {};
    const factorJson = JSON.stringify(factors).replace(/"/g, "&quot;");
    const rJson = JSON.stringify(r).replace(/"/g, "&quot;");
    return `
      <tr class="rec-score-row" data-idx="${i}" data-factors="${factorJson}" data-name="${r.name}" data-score="${r.score}" data-signal="${r.signal}" data-signal-color="${r.signal_color}" data-row="${rJson}">
        <td>${i + 1}</td>
        <td>
          <strong>${r.name}</strong>
          <br><span style="color:var(--text2);font-size:11px">${r.symbol}</span>
        </td>
        <td><span class="industry-tag">${r.industry || "-"}</span></td>
        <td>¥${r.last_price}</td>
        <td class="${change5Class}">${sign}${r.change_5d}%</td>
        <td>${r.rsi}</td>
        <td>
          <div class="score-bar-wrap">
            <div class="score-bar" style="width:${r.score}%"></div>
            <span class="score-num">${r.score}</span>
          </div>
        </td>
        <td><span class="signal-badge" style="color:${r.signal_color}">${r.signal}</span></td>
      </tr>
    `;
  }).join("");

  document.getElementById("rec-table-wrap").innerHTML = `
    <table class="rec-table">
      <thead>
        <tr><th>#</th><th>股票</th><th>行业</th><th>现价</th><th>5日涨跌</th><th>RSI</th><th>综合评分</th><th>信号</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    <div style="font-size:11px;color:var(--text2);margin-top:8px;padding:0 4px">
      💡 点击股票行查看详细得分规则 · 绝对值评分（0~100），≥72强烈推荐，≥58推荐关注
    </div>
  `;

  // 绑定表格行点击（选中 → 详解）
  bindRecRowClick();
  // 绑定 hover tooltip
  bindRecTooltip();
}

// ── 自定义因子 tooltip（鼠标右侧显示）──────────────────
let _recTooltipEl = null;

function getRecTooltip() {
  if (!_recTooltipEl) {
    _recTooltipEl = document.createElement("div");
    _recTooltipEl.className = "rec-factor-tooltip";
    _recTooltipEl.style.display = "none";
    document.body.appendChild(_recTooltipEl);
  }
  return _recTooltipEl;
}

function bindRecTooltip() {
  const tooltip = getRecTooltip();
  const rows = document.querySelectorAll(".rec-score-row");

  rows.forEach(row => {
    row.addEventListener("mouseenter", (e) => {
      try {
        const factors = JSON.parse(row.dataset.factors || "{}");
        const name = row.dataset.name || "";
        const score = row.dataset.score || "";
        const signal = row.dataset.signal || "";
        const signalColor = row.dataset.signalColor || "#8892a4";

        // 构建 tooltip 内容（换行展示）
        const factorLines = Object.entries(factors).map(([k, v]) => {
          const bar = Math.round(v / 100 * 12);
          const filled = "█".repeat(bar) + "░".repeat(12 - bar);
          return `<div class="rec-tip-row">
            <span class="rec-tip-key">${k}</span>
            <span class="rec-tip-bar">${filled}</span>
            <span class="rec-tip-val">${v}</span>
          </div>`;
        }).join("");

        tooltip.innerHTML = `
          <div class="rec-tip-header">
            <span class="rec-tip-name">${name}</span>
            <span class="rec-tip-score" style="color:${signalColor}">综合 ${score}</span>
          </div>
          <div class="rec-tip-signal" style="color:${signalColor}">● ${signal}</div>
          <div class="rec-tip-divider"></div>
          <div class="rec-tip-factors">${factorLines}</div>
          <div class="rec-tip-note">绝对值评分 · 0~100分</div>
        `;
        tooltip.style.display = "block";
      } catch(err) {
        tooltip.style.display = "none";
      }
    });

    row.addEventListener("mousemove", (e) => {
      const tooltip = getRecTooltip();
      if (tooltip.style.display === "none") return;
      const offset = 14;
      const tw = tooltip.offsetWidth;
      const th = tooltip.offsetHeight;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      let left = e.clientX + offset;
      let top  = e.clientY + offset;
      // 防止超出右边界
      if (left + tw > vw - 8) left = e.clientX - tw - offset;
      // 防止超出下边界
      if (top + th > vh - 8) top = e.clientY - th - offset;
      tooltip.style.left = left + "px";
      tooltip.style.top  = top  + "px";
    });

    row.addEventListener("mouseleave", () => {
      const tooltip = getRecTooltip();
      tooltip.style.display = "none";
    });
  });
}

/* ══════════════════════════════════════════
   股票详解面板
══════════════════════════════════════════ */

let _recCurrentResults = [];   // 当前推荐结果缓存
let _recSelectedIdx = -1;      // 当前选中行索引

// 每个因子的详细说明（未选中时展示）
const REC_FACTOR_DOCS = [
  {
    key: "动量(20日)",
    icon: "📈",
    weight: "30%",
    desc: "近20个交易日的涨跌幅，衡量股票的中期趋势动能。",
    rule: [
      { range: "> +10%",        score: 100, label: "强势上涨" },
      { range: "+5% ~ +10%",   score: 80,  label: "温和上涨" },
      { range: "0% ~ +5%",     score: 60,  label: "小幅上涨" },
      { range: "-5% ~ 0%",     score: 40,  label: "小幅下跌" },
      { range: "-10% ~ -5%",   score: 20,  label: "明显下跌" },
      { range: "< -10%",       score: 0,   label: "大幅下跌" },
    ],
  },
  {
    key: "相对强弱",
    icon: "💪",
    weight: "20%",
    desc: "个股20日涨幅 vs 同期沪深300涨幅的差值，衡量跑赢/跑输大盘的程度。此因子在候选池内做截面排名（百分位），确保横向可比。",
    rule: null,  // 截面排名，无固定阈值
    ruleNote: "截面排名百分位：候选池内排名越靠前得分越高（0~100）。",
  },
  {
    key: "趋势加速度",
    icon: "🚀",
    weight: "15%",
    desc: "近5日日均涨幅 − 近20日日均涨幅。正值表示近期涨速加快（加速上涨），负值表示涨速放缓或加速下跌。",
    rule: [
      { range: "> +0.8%/日",       score: 100, label: "强力加速" },
      { range: "+0.3% ~ +0.8%",   score: 85,  label: "温和加速" },
      { range: "0 ~ +0.3%",       score: 60,  label: "轻微加速" },
      { range: "-0.5% ~ 0",       score: 30,  label: "轻微减速" },
      { range: "< -0.5%",         score: 0,   label: "明显减速" },
    ],
  },
  {
    key: "均线多头",
    icon: "📊",
    weight: "15%",
    desc: "均线多头排列程度：MA5 > MA10 > MA20，且价格在MA5之上。每满足一个条件得30分基础分，再根据价格偏离MA20的适度程度加0~10分。",
    rule: [
      { range: "3条均线全多头 + 偏离≤2%",  score: "100", label: "完美多头" },
      { range: "3条均线全多头",             score: "90~97", label: "强多头" },
      { range: "2条均线多头",               score: "60~67", label: "中等多头" },
      { range: "1条均线多头",               score: "30~37", label: "弱多头" },
      { range: "0条均线多头",               score: "0~10",  label: "空头排列" },
    ],
  },
  {
    key: "稳定性",
    icon: "🎯",
    weight: "10%",
    desc: "近20日日收益率的标准差（日波动率%）。波动率越低，走势越稳健，持仓体验越好。",
    rule: [
      { range: "< 1%/日",   score: 100, label: "极低波动" },
      { range: "1% ~ 2%",  score: 80,  label: "低波动" },
      { range: "2% ~ 3%",  score: 50,  label: "中等波动" },
      { range: "3% ~ 4%",  score: 20,  label: "高波动" },
      { range: "> 4%",     score: 0,   label: "极高波动" },
    ],
  },
  {
    key: "量价配合",
    icon: "📦",
    weight: "5%",
    desc: "近5日成交量均值 vs 前5日成交量均值，结合价格方向判断量价是否配合。放量上涨或缩量下跌均视为配合。",
    rule: [
      { range: "价涨量增 或 价跌量缩", score: 70, label: "量价配合" },
      { range: "价涨量缩 或 价跌量增", score: 30, label: "量价背离" },
    ],
  },
  {
    key: "RSI",
    icon: "🔢",
    weight: "5%",
    desc: "14日相对强弱指数（RSI）。40~65为健康区间，过高（超买）或过低（超卖）均扣分。",
    rule: [
      { range: "40 ~ 65",  score: 100, label: "健康区间" },
      { range: "30 ~ 40",  score: 60,  label: "偏弱但未超卖" },
      { range: "65 ~ 75",  score: 60,  label: "偏强但未超买" },
      { range: "< 30 或 > 75", score: 20, label: "超卖/超买区" },
    ],
  },
];

// 渲染默认状态（指标说明）
function renderDetailDefault() {
  const titleEl = document.getElementById("rec-detail-title");
  const hintEl  = document.getElementById("rec-detail-hint");
  const bodyEl  = document.getElementById("rec-detail-body");
  if (!bodyEl) return;

  if (titleEl) titleEl.textContent = "📖 指标说明";
  if (hintEl)  hintEl.textContent  = "点击下方股票查看得分详情";

  bodyEl.innerHTML = REC_FACTOR_DOCS.map(f => `
    <div class="rd-factor-card">
      <div class="rd-factor-head">
        <span class="rd-factor-icon">${f.icon}</span>
        <span class="rd-factor-name">${f.key}</span>
        <span class="rd-factor-weight">${f.weight}</span>
      </div>
      <div class="rd-factor-desc">${f.desc}</div>
    </div>
  `).join("");
}

// 渲染选中股票的得分详情（指标名 · 具体值 · 得分）
function renderDetailStock(r) {
  const titleEl = document.getElementById("rec-detail-title");
  const hintEl  = document.getElementById("rec-detail-hint");
  const bodyEl  = document.getElementById("rec-detail-body");
  if (!bodyEl) return;

  const factors     = r.factors      || {};   // 各因子得分 0~100
  const factorVals  = r.factor_values || {};  // 各因子原始值（带单位字符串）

  if (titleEl) titleEl.innerHTML =
    `<span style="color:var(--text)">${r.name}</span>
     <span style="color:${r.signal_color};font-size:12px;margin-left:8px">● ${r.signal}</span>`;
  if (hintEl) hintEl.innerHTML =
    `综合评分 <strong style="color:${r.signal_color};font-size:15px">${r.score}</strong>
     &nbsp;·&nbsp; ${r.industry || ""} &nbsp;·&nbsp; ¥${r.last_price}`;

  // 因子展示顺序与图标
  const FACTOR_META = [
    { key: "动量(20日)",  icon: "📈" },
    { key: "相对强弱",    icon: "💪" },
    { key: "趋势加速度",  icon: "🚀" },
    { key: "均线多头",    icon: "📊" },
    { key: "稳定性",      icon: "🎯" },
    { key: "量价配合",    icon: "📦" },
    { key: "RSI",         icon: "🔢" },
  ];

  // 规则解释映射（根据因子得分区间生成文字说明）
  function getRuleDesc(key, score) {
    if (key === "动量(20日)") {
      if (score >= 80) return "近20日涨幅强劲（>10%）";
      if (score >= 60) return "近20日温和上涨（0~10%）";
      if (score >= 40) return "近20日小幅下跌（-5~0%）";
      if (score >= 20) return "近20日明显下跌（-10~-5%）";
      return "近20日大幅下跌（<-10%）";
    }
    if (key === "相对强弱") {
      if (score >= 80) return "跑赢大盘，截面排名前20%";
      if (score >= 60) return "略强于大盘，排名前40%";
      if (score >= 40) return "与大盘持平，排名中段";
      return "跑输大盘，排名靠后";
    }
    if (key === "趋势加速度") {
      if (score >= 85) return "趋势加速明显（>0.8%/日）";
      if (score >= 60) return "趋势温和加速（0~0.8%/日）";
      if (score >= 30) return "趋势轻微减速（-0.5~0%/日）";
      return "趋势明显减速（<-0.5%/日）";
    }
    if (key === "均线多头") {
      if (score >= 80) return "均线多头排列，趋势健康";
      if (score >= 50) return "均线部分多头，趋势偏强";
      return "均线空头排列，趋势偏弱";
    }
    if (key === "稳定性") {
      if (score >= 80) return "波动率低（<1%），走势稳健";
      if (score >= 50) return "波动率适中（1~3%）";
      return "波动率偏高（>3%），风险较大";
    }
    if (key === "量价配合") {
      if (score >= 60) return "量价配合良好，上涨有量支撑";
      return "量价背离，上涨缺乏量能";
    }
    if (key === "RSI") {
      if (score >= 80) return "RSI处于合理区间（40~65），不超买不超卖";
      if (score >= 50) return "RSI略偏高或偏低（30~40 或 65~75）";
      return "RSI超买或超卖，需谨慎";
    }
    return score >= 60 ? "表现良好" : "表现一般";
  }

  bodyEl.innerHTML = FACTOR_META.map(f => {
    const scoreNum = parseFloat(factors[f.key] ?? 0);
    const rawVal   = factorVals[f.key] ?? "-";
    const ruleDesc = getRuleDesc(f.key, scoreNum);

    // 进度条颜色
    let barColor = "#4f8ef7";
    if (scoreNum >= 80)      barColor = "#26c281";
    else if (scoreNum >= 60) barColor = "#4f8ef7";
    else if (scoreNum >= 40) barColor = "#f39c12";
    else                     barColor = "#e74c3c";

    return `
      <div class="rd-factor-row" style="align-items:flex-start;padding:7px 10px">
        <span class="rd-factor-icon" style="margin-top:2px">${f.icon}</span>
        <div style="flex:1;min-width:0">
          <div style="display:flex;align-items:center;gap:6px">
            <span class="rd-factor-name">${f.key}</span>
            <span class="rd-factor-rawval" style="font-size:12px;font-weight:700;color:${barColor};min-width:auto">${rawVal}</span>
            <div class="rd-score-bar-wrap rd-score-bar-wrap--inline" style="flex:1">
              <div class="rd-score-bar" style="width:${scoreNum}%;background:${barColor}"></div>
            </div>
            <span class="rd-score-badge" style="color:${barColor}">${scoreNum.toFixed(0)}</span>
          </div>
          <div style="font-size:11px;color:#8899aa;margin-top:2px;line-height:1.4">${ruleDesc}</div>
        </div>
      </div>
    `;
  }).join("");
}

// 绑定表格行点击 → 选中 + 渲染详解
function bindRecRowClick() {
  document.querySelectorAll(".rec-score-row").forEach(row => {
    row.addEventListener("click", () => {
      const idx = parseInt(row.dataset.idx ?? "-1");
      // 再次点击同一行 → 取消选中，回到默认
      if (_recSelectedIdx === idx) {
        _recSelectedIdx = -1;
        document.querySelectorAll(".rec-score-row").forEach(r => r.classList.remove("rec-row-selected"));
        renderDetailDefault();
        return;
      }
      _recSelectedIdx = idx;
      document.querySelectorAll(".rec-score-row").forEach(r => r.classList.remove("rec-row-selected"));
      row.classList.add("rec-row-selected");
      try {
        const r = (_recCurrentResults && _recCurrentResults[idx]) || JSON.parse(row.dataset.row || "{}");
        renderDetailStock(r);
      } catch(e) {
        renderDetailDefault();
      }
    });
  });
}

/* ══════════════════════════════════════════
   推荐历史记录
══════════════════════════════════════════ */

// 保存一条推荐记录到后端
async function saveRecHistory(data) {
  try {
    const now = new Date();
    // 用本地时间格式化，避免 toISOString() 返回 UTC 导致时区偏差
    const pad = n => String(n).padStart(2, "0");
    const saved_at = `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    await fetch(`${API}/rec_history`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        saved_at,
        top_n:            data.top_n,
        total_scanned:    data.total_scanned,
        index_return_20d: data.index_return_20d,
        algo_note:        data.algo_note || "",
        results:          data.results,
        industry_dist:    data.industry_dist || {},
      }),
    });
  } catch(e) {
    console.warn("保存历史记录失败:", e);
  }
}

// 读取并渲染历史记录列表
async function loadRecHistory() {
  try {
    const res = await fetch(`${API}/rec_history`);
    const data = await res.json();
    if (!data.success) return;
    renderRecHistoryList(data.data);
  } catch(e) {
    console.warn("读取历史记录失败:", e);
  }
}

// 渲染历史记录列表
function renderRecHistoryList(records) {
  const listEl = document.getElementById("rec-history-list");
  const countEl = document.getElementById("rec-history-count");
  if (!listEl) return;

  if (countEl) {
    countEl.textContent = records.length > 0 ? `共 ${records.length} 条` : "";
  }

  if (!records || records.length === 0) {
    listEl.innerHTML = '<div class="rec-history-empty">暂无历史记录，完成一次推荐后自动保存</div>';
    return;
  }

  listEl.innerHTML = records.map(rec => {
    const topNames = rec.results.slice(0, 5).map(r => r.name).join("、");
    const moreCount = rec.results.length - 5;
    const idxSign = rec.index_return_20d >= 0 ? "+" : "";
    const idxColor = rec.index_return_20d >= 0 ? "var(--green)" : "var(--red)";
    const indTags = Object.keys(rec.industry_dist || {}).slice(0, 4)
      .map(k => `<span class="industry-tag" style="font-size:10px">${k}</span>`).join(" ");

    return `
      <div class="rec-history-item" id="hist-${rec.id}">
        <div class="rec-history-item-header" onclick="toggleHistoryItem('${rec.id}')">
          <div class="rec-history-item-left">
            <span class="rec-history-time">${rec.saved_at}</span>
            <span class="rec-history-badge">Top ${rec.top_n}</span>
            <span style="font-size:11px;color:${idxColor};margin-left:6px">沪深300 ${idxSign}${rec.index_return_20d}%</span>
          </div>
          <div class="rec-history-item-right">
            <span class="rec-history-preview">${topNames}${moreCount > 0 ? ` 等${moreCount}只` : ""}</span>
            <button class="rec-history-del" onclick="deleteHistoryItem(event,'${rec.id}')" title="删除">✕</button>
            <span class="rec-history-arrow" id="arrow-${rec.id}">▶</span>
          </div>
        </div>
        <div class="rec-history-item-body hidden" id="body-${rec.id}">
          <div style="margin-bottom:8px;display:flex;flex-wrap:wrap;gap:4px">${indTags}</div>
          ${renderHistoryTable(rec.results)}
          <div style="font-size:11px;color:var(--text2);margin-top:6px">
            📊 采样 ${rec.total_scanned} 只候选股 · ${rec.algo_note ? rec.algo_note.slice(0, 60) + "…" : ""}
          </div>
        </div>
      </div>
    `;
  }).join("");
}

// 渲染历史记录内的股票表格（紧凑版）
function renderHistoryTable(results) {
  const rows = results.map((r, i) => {
    const chgClass = r.change_5d >= 0 ? "pnl-pos" : "pnl-neg";
    const sign = r.change_5d >= 0 ? "+" : "";
    return `<tr>
      <td style="color:var(--text2)">${i + 1}</td>
      <td><strong>${r.name}</strong> <span style="color:var(--text2);font-size:10px">${r.symbol}</span></td>
      <td><span class="industry-tag" style="font-size:10px">${r.industry || "-"}</span></td>
      <td>¥${r.last_price}</td>
      <td class="${chgClass}">${sign}${r.change_5d}%</td>
      <td style="color:var(--accent)">${r.score}</td>
      <td><span style="color:${r.signal_color};font-size:11px">${r.signal}</span></td>
    </tr>`;
  }).join("");
  return `
    <table class="val-table" style="font-size:12px">
      <thead><tr>
        <th>#</th><th>股票</th><th>行业</th><th>现价</th><th>5日涨跌</th><th>评分</th><th>信号</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// 展开/折叠历史记录条目
function toggleHistoryItem(id) {
  const body  = document.getElementById(`body-${id}`);
  const arrow = document.getElementById(`arrow-${id}`);
  if (!body) return;
  const isHidden = body.classList.contains("hidden");
  body.classList.toggle("hidden", !isHidden);
  if (arrow) arrow.textContent = isHidden ? "▼" : "▶";
}

// 删除历史记录条目
async function deleteHistoryItem(event, id) {
  event.stopPropagation();
  if (!confirm("确认删除这条历史记录？")) return;
  try {
    const res = await fetch(`${API}/rec_history/${id}`, { method: "DELETE" });
    const data = await res.json();
    if (data.success) {
      const el = document.getElementById(`hist-${id}`);
      if (el) {
        el.style.transition = "opacity 0.3s";
        el.style.opacity = "0";
        setTimeout(() => { el.remove(); loadRecHistory(); }, 300);
      }
    }
  } catch(e) {
    console.warn("删除失败:", e);
  }
}

/* ══════════════════════════════════════════
   行业晴雨表
══════════════════════════════════════════ */
async function loadIndustryHeatmap() {
  const bodyEl = document.getElementById("heatmap-body");
  const dateEl = document.getElementById("heatmap-date");
  if (!bodyEl) return;

  try {
    const res  = await fetch(`${API}/industry_heatmap`);
    const data = await res.json();

    if (!data.success) {
      bodyEl.innerHTML = `<div class="heatmap-error">暂无数据</div>`;
      return;
    }

    if (dateEl && data.date) {
      const d = new Date(data.date);
      const today = new Date();
      const isToday = d.getFullYear() === today.getFullYear()
                   && d.getMonth()    === today.getMonth()
                   && d.getDate()     === today.getDate();
      const mm = String(d.getMonth() + 1).padStart(2, "0");
      const dd = String(d.getDate()).padStart(2, "0");
      dateEl.textContent = isToday
        ? `今日 ${mm}-${dd}`
        : `${mm}-${dd} · 收盘后更新`;
    }

    const renderRow = (item, rank) => {
      const isUp   = item.chg_pct >= 0;
      const sign   = isUp ? "+" : "";
      const cls    = isUp ? "heatmap-row--up" : "heatmap-row--down";
      const barW   = Math.min(Math.abs(item.chg_pct) / 5 * 100, 100); // 5% 对应满格
      const barCls = isUp ? "heatmap-bar--up" : "heatmap-bar--down";
      return `
        <div class="heatmap-row ${cls}">
          <span class="heatmap-rank">${rank}</span>
          <span class="heatmap-name">${item.name}</span>
          <div class="heatmap-bar-wrap">
            <div class="heatmap-bar ${barCls}" style="width:${barW}%"></div>
          </div>
          <span class="heatmap-pct">${sign}${item.chg_pct}%</span>
        </div>`;
    };

    const top3Html    = data.top3.map((item, i) => renderRow(item, ["🥇","🥈","🥉"][i])).join("");
    const bottom3Html = data.bottom3.map((item, i) => renderRow(item, ["💀","📉","⬇️"][i])).join("");

    bodyEl.innerHTML = `
      <div class="heatmap-section">
        <div class="heatmap-section-title heatmap-section-title--up">📈 涨幅前三</div>
        ${top3Html}
      </div>
      <div class="heatmap-divider"></div>
      <div class="heatmap-section">
        <div class="heatmap-section-title heatmap-section-title--down">📉 跌幅前三</div>
        ${bottom3Html}
      </div>
    `;
  } catch(e) {
    if (bodyEl) bodyEl.innerHTML = `<div class="heatmap-error">加载失败</div>`;
  }
}
