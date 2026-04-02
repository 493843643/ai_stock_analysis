"""
量化回测引擎核心模块
"""
import os

# ── 在所有网络库加载前强制禁用代理 ──────────────────────────
# macOS 系统代理（如 Clash/V2Ray）会被 requests/curl_cffi 自动读取，
# 导致访问东方财富等国内数据源失败，这里彻底清除。
_PROXY_KEYS = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
               "all_proxy", "ALL_PROXY", "CURL_CA_BUNDLE"]
for _k in _PROXY_KEYS:
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
os.environ["CURL_IMPERSONATE_NOPROXY"] = "1"

# 禁用 urllib3 / requests 读取系统代理
import urllib.request
# 覆盖 macOS 系统代理探测，返回空代理
urllib.request.getproxies = lambda: {}

import requests
# patch requests 的代理解析，强制返回空
import requests.utils as _ru
_ru.get_environ_proxies = lambda *a, **kw: {}
_ru.select_proxy = lambda url, proxies: None
# ─────────────────────────────────────────────────────────────

import backtrader as bt
import pandas as pd
import numpy as np
import akshare as ak
from datetime import datetime, timedelta
import json
import traceback


# ─────────────────────────────────────────
# 数据获取
# ─────────────────────────────────────────

import baostock as bs
import json as _json

def is_hk_stock(symbol: str) -> bool:
    """判断是否为港股代码（5位数字，如 03690 / 00700）"""
    s = symbol.strip()
    return len(s) == 5 and s.isdigit()

# 市场前缀：沪市 sh.，深市 sz.
def _get_bs_code(symbol: str) -> str:
    if symbol.startswith("6"):
        return f"sh.{symbol}"
    return f"sz.{symbol}"

# 复权：qfq=前复权(2), hfq=后复权(1), 不复权(3)
_ADJUST_MAP = {"qfq": "2", "hfq": "1", "": "3"}


def fetch_hk_stock_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    通过腾讯财经接口获取港股日线数据（前复权）
    symbol: 5位港股代码，如 03690
    """
    # 腾讯财经最多返回 1000 条，按需调整
    url = (
        f"https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get"
        f"?_var=kline_dayqfq&param=hk{symbol},day,{start_date},{end_date},1000,qfq&r=0.5"
    )
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    resp.raise_for_status()

    text = resp.text
    prefix = "kline_dayqfq="
    if not text.startswith(prefix):
        raise ValueError(f"港股数据格式异常: {text[:100]}")

    data = _json.loads(text[len(prefix):])
    key = f"hk{symbol}"
    # 优先取复权数据 qfqday，否则取 day
    klines = (data.get("data", {}).get(key, {}).get("qfqday")
              or data.get("data", {}).get(key, {}).get("day"))
    if not klines:
        raise ValueError(f"未获取到港股 {symbol} 数据，请检查代码是否正确")

    # 每条格式: [date, open, close, high, low, volume, ...]
    rows = []
    for k in klines:
        date_str = k[0]
        try:
            rows.append({
                "date":   pd.to_datetime(date_str),
                "open":   float(k[1]),
                "close":  float(k[2]),
                "high":   float(k[3]),
                "low":    float(k[4]),
                "volume": float(k[5]),
            })
        except (ValueError, IndexError):
            continue

    if not rows:
        raise ValueError(f"港股 {symbol} 数据解析失败")

    df = pd.DataFrame(rows).set_index("date").sort_index()
    # 按日期范围过滤
    df = df[df.index >= pd.to_datetime(start_date)]
    df = df[df.index <= pd.to_datetime(end_date)]
    return df


def fetch_stock_data(symbol: str, start_date: str, end_date: str, adjust: str = "qfq") -> pd.DataFrame:
    """
    获取股票日线数据：
    - A股（6位）：baostock TCP 协议
    - 港股（5位）：腾讯财经 HTTP 接口
    """
    if is_hk_stock(symbol):
        return fetch_hk_stock_data(symbol, start_date, end_date)

    # A 股走 baostock，加重试机制应对 TCP 连接状态异常
    bs_code = _get_bs_code(symbol)
    adjustflag = _ADJUST_MAP.get(adjust, "2")

    last_err = None
    for attempt in range(3):
        try:
            # 每次先强制断开旧连接，再重新登录，避免 TCP 状态残留
            try:
                bs.logout()
            except Exception:
                pass

            import time as _time
            if attempt > 0:
                _time.sleep(1)  # 重试前稍等

            lg = bs.login()
            if lg.error_code != "0":
                raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")
            try:
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,open,high,low,close,volume",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag=adjustflag,
                )
                if rs.error_code != "0":
                    raise RuntimeError(f"数据查询失败: {rs.error_msg}")
                rows = []
                while rs.error_code == "0" and rs.next():
                    rows.append(rs.get_row_data())
            finally:
                bs.logout()

            if not rows:
                raise ValueError(f"未获取到数据，请检查股票代码 {symbol} 和日期范围")

            df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
            df = df.replace("", np.nan).dropna()
            df = df.astype(float)
            return df

        except (RuntimeError, ValueError) as e:
            last_err = e
            # "网络接收错误" 等连接类错误才重试，数据不存在直接抛出
            if "网络" not in str(e) and "连接" not in str(e) and "socket" not in str(e).lower():
                raise
            continue

    raise RuntimeError(f"baostock 查询失败（已重试3次）: {last_err}")


# ─────────────────────────────────────────
# 策略定义
# ─────────────────────────────────────────

class MACrossStrategy(bt.Strategy):
    """双均线金叉/死叉策略"""
    params = (("fast", 5), ("slow", 20),)

    def __init__(self):
        self.ma_fast = bt.ind.SMA(period=self.p.fast)
        self.ma_slow = bt.ind.SMA(period=self.p.slow)
        self.crossover = bt.ind.CrossOver(self.ma_fast, self.ma_slow)
        self.trades = []
        self._pending_buy = {}   # order ref -> buy info

    def next(self):
        if self.crossover > 0 and not self.position:
            self.buy()
        elif self.crossover < 0 and self.position:
            self.sell()

    def notify_order(self, order):
        if order.status == order.Completed:
            date_str = bt.num2date(order.executed.dt).strftime("%Y-%m-%d")
            size = int(abs(order.executed.size))
            price = round(order.executed.price, 3)
            value = round(abs(order.executed.value), 2)
            if order.isbuy():
                self._pending_buy[id(order)] = {
                    "open_date": date_str,
                    "buy_price": price,
                    "buy_size": size,
                    "buy_value": value,
                }

    def notify_trade(self, trade):
        if trade.isclosed:
            # 找最近一笔买入记录（按插入顺序取最后一个）
            buy_info = {}
            if self._pending_buy:
                last_key = list(self._pending_buy.keys())[-1]
                buy_info = self._pending_buy.pop(last_key)
            close_date = bt.num2date(trade.dtclose).strftime("%Y-%m-%d")
            sell_price = round(trade.price, 3)
            sell_size = int(abs(trade.size))
            sell_value = round(abs(trade.value), 2)
            self.trades.append({
                "open_date": buy_info.get("open_date", bt.num2date(trade.dtopen).strftime("%Y-%m-%d")),
                "close_date": close_date,
                "buy_price": buy_info.get("buy_price", "-"),
                "buy_size": buy_info.get("buy_size", sell_size),
                "buy_value": buy_info.get("buy_value", "-"),
                "sell_price": sell_price,
                "sell_size": sell_size,
                "sell_value": sell_value,
                "pnl": round(trade.pnl, 2),
                "pnlcomm": round(trade.pnlcomm, 2),
            })


class RSIStrategy(bt.Strategy):
    """RSI 超买超卖策略"""
    params = (("period", 14), ("oversold", 30), ("overbought", 70),)

    def __init__(self):
        self.rsi = bt.ind.RSI(period=self.p.period)
        self.trades = []
        self._pending_buy = {}

    def next(self):
        if self.rsi < self.p.oversold and not self.position:
            self.buy()
        elif self.rsi > self.p.overbought and self.position:
            self.sell()

    def notify_order(self, order):
        if order.status == order.Completed:
            date_str = bt.num2date(order.executed.dt).strftime("%Y-%m-%d")
            size = int(abs(order.executed.size))
            price = round(order.executed.price, 3)
            value = round(abs(order.executed.value), 2)
            if order.isbuy():
                self._pending_buy[id(order)] = {
                    "open_date": date_str,
                    "buy_price": price,
                    "buy_size": size,
                    "buy_value": value,
                }

    def notify_trade(self, trade):
        if trade.isclosed:
            buy_info = {}
            if self._pending_buy:
                last_key = list(self._pending_buy.keys())[-1]
                buy_info = self._pending_buy.pop(last_key)
            close_date = bt.num2date(trade.dtclose).strftime("%Y-%m-%d")
            sell_price = round(trade.price, 3)
            sell_size = int(abs(trade.size))
            sell_value = round(abs(trade.value), 2)
            self.trades.append({
                "open_date": buy_info.get("open_date", bt.num2date(trade.dtopen).strftime("%Y-%m-%d")),
                "close_date": close_date,
                "buy_price": buy_info.get("buy_price", "-"),
                "buy_size": buy_info.get("buy_size", sell_size),
                "buy_value": buy_info.get("buy_value", "-"),
                "sell_price": sell_price,
                "sell_size": sell_size,
                "sell_value": sell_value,
                "pnl": round(trade.pnl, 2),
                "pnlcomm": round(trade.pnlcomm, 2),
            })


class BollingerStrategy(bt.Strategy):
    """布林带均值回归策略：跌破下轨买入，回到中轨卖出"""
    params = (("period", 20), ("devfactor", 2.0),)

    def __init__(self):
        self.bb = bt.ind.BollingerBands(period=self.p.period, devfactor=self.p.devfactor)
        self.trades = []
        self._pending_buy = {}

    def next(self):
        if self.data.close < self.bb.lines.bot and not self.position:
            self.buy()
        elif self.data.close > self.bb.lines.mid and self.position:
            self.sell()

    def notify_order(self, order):
        if order.status == order.Completed:
            date_str = bt.num2date(order.executed.dt).strftime("%Y-%m-%d")
            size = int(abs(order.executed.size))
            price = round(order.executed.price, 3)
            value = round(abs(order.executed.value), 2)
            if order.isbuy():
                self._pending_buy[id(order)] = {
                    "open_date": date_str,
                    "buy_price": price,
                    "buy_size": size,
                    "buy_value": value,
                }

    def notify_trade(self, trade):
        if trade.isclosed:
            buy_info = {}
            if self._pending_buy:
                last_key = list(self._pending_buy.keys())[-1]
                buy_info = self._pending_buy.pop(last_key)
            close_date = bt.num2date(trade.dtclose).strftime("%Y-%m-%d")
            sell_price = round(trade.price, 3)
            sell_size = int(abs(trade.size))
            sell_value = round(abs(trade.value), 2)
            self.trades.append({
                "open_date": buy_info.get("open_date", bt.num2date(trade.dtopen).strftime("%Y-%m-%d")),
                "close_date": close_date,
                "buy_price": buy_info.get("buy_price", "-"),
                "buy_size": buy_info.get("buy_size", sell_size),
                "buy_value": buy_info.get("buy_value", "-"),
                "sell_price": sell_price,
                "sell_size": sell_size,
                "sell_value": sell_value,
                "pnl": round(trade.pnl, 2),
                "pnlcomm": round(trade.pnlcomm, 2),
            })


STRATEGIES = {
    "ma_cross": MACrossStrategy,
    "rsi": RSIStrategy,
    "bollinger": BollingerStrategy,
}


# ─────────────────────────────────────────
# 回测结果分析器
# ─────────────────────────────────────────

class PortfolioValueAnalyzer(bt.Analyzer):
    def start(self):
        self.values = []

    def next(self):
        self.values.append({
            "date": self.datas[0].datetime.date(0).strftime("%Y-%m-%d"),
            "value": round(self.strategy.broker.getvalue(), 2),
        })

    def get_analysis(self):
        return self.values


# ─────────────────────────────────────────
# 主回测函数
# ─────────────────────────────────────────

def run_backtest(params: dict) -> dict:
    """
    执行回测，返回结构化结果
    params 示例:
    {
        "symbol": "000001",
        "start_date": "2022-01-01",
        "end_date": "2024-01-01",
        "strategy": "ma_cross",
        "cash": 100000,
        "commission": 0.001,
        "strategy_params": {"fast": 5, "slow": 20}
    }
    """
    try:
        symbol = params.get("symbol", "000001")
        start_date = params.get("start_date", "2022-01-01")
        end_date = params.get("end_date", "2024-01-01")
        strategy_name = params.get("strategy", "ma_cross")
        cash = float(params.get("cash", 100000))
        commission = float(params.get("commission", 0.001))
        strategy_params = params.get("strategy_params", {})

        # 获取数据
        df = fetch_stock_data(symbol, start_date, end_date)
        if df.empty:
            return {"success": False, "error": "未获取到数据，请检查股票代码和日期范围"}

        # 构建 cerebro
        cerebro = bt.Cerebro()

        # 添加策略
        StrategyClass = STRATEGIES.get(strategy_name, MACrossStrategy)
        if strategy_params:
            cerebro.addstrategy(StrategyClass, **strategy_params)
        else:
            cerebro.addstrategy(StrategyClass)

        # 添加数据
        data = bt.feeds.PandasData(dataname=df)
        cerebro.adddata(data)

        # 设置资金和手续费
        cerebro.broker.setcash(cash)
        cerebro.broker.setcommission(commission)

        # 每次买入使用可用资金的 95%（留 5% 应对手续费和零头）
        cerebro.addsizer(bt.sizers.PercentSizer, percents=95)

        # 添加分析器
        cerebro.addanalyzer(PortfolioValueAnalyzer, _name="portfolio")
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.03)
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

        # 运行
        initial_value = cerebro.broker.getvalue()
        results = cerebro.run()
        final_value = cerebro.broker.getvalue()
        strat = results[0]

        # 提取分析结果
        portfolio_values = strat.analyzers.portfolio.get_analysis()
        sharpe = strat.analyzers.sharpe.get_analysis()
        drawdown = strat.analyzers.drawdown.get_analysis()
        returns = strat.analyzers.returns.get_analysis()
        trade_analysis = strat.analyzers.trades.get_analysis()

        # 计算指标
        total_return = (final_value - initial_value) / initial_value * 100
        sharpe_ratio = sharpe.get("sharperatio", None)
        max_drawdown = drawdown.get("max", {}).get("drawdown", 0)
        annual_return = returns.get("rnorm100", 0)

        # 交易记录
        trade_records = getattr(strat, "trades", [])

        # 基准（买入持有）收益
        benchmark_return = (df["close"].iloc[-1] - df["close"].iloc[0]) / df["close"].iloc[0] * 100

        # 原始价格数据（用于图表）
        price_data = []
        for date, row in df.iterrows():
            price_data.append({
                "date": date.strftime("%Y-%m-%d"),
                "open": round(row["open"], 2),
                "high": round(row["high"], 2),
                "low": round(row["low"], 2),
                "close": round(row["close"], 2),
                "volume": int(row["volume"]),
            })

        return {
            "success": True,
            "summary": {
                "symbol": symbol,
                "strategy": strategy_name,
                "start_date": start_date,
                "end_date": end_date,
                "initial_cash": round(initial_value, 2),
                "final_value": round(final_value, 2),
                "total_return": round(total_return, 2),
                "annual_return": round(annual_return, 2) if annual_return else None,
                "sharpe_ratio": round(sharpe_ratio, 3) if sharpe_ratio else None,
                "max_drawdown": round(max_drawdown, 2),
                "benchmark_return": round(benchmark_return, 2),
                "total_trades": len(trade_records),
            },
            "portfolio_values": portfolio_values,
            "trade_records": trade_records,
            "price_data": price_data,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
