"""
价格预测模块
使用 Monte Carlo 随机游走 + 趋势修正综合预测未来走势：
- 基于历史日收益率的均值/波动率，模拟 500 条价格路径
- 取中位数作为预测价格，5%/95% 分位数作为置信区间
- 叠加线性趋势修正，避免纯随机游走忽略趋势
"""
import os
_PROXY_KEYS = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]
for _k in _PROXY_KEYS:
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

import numpy as np
import pandas as pd
from datetime import timedelta
import traceback
import sys
sys.path.insert(0, os.path.dirname(__file__))
from engine import fetch_stock_data, is_hk_stock


def predict_price(symbol: str, days: int = 30) -> dict:
    """
    预测未来 N 天的价格走势
    返回历史数据 + 预测数据 + 置信区间
    """
    try:
        # 拉取近 250 天历史数据（约一年交易日）
        end = pd.Timestamp.today()
        start = end - timedelta(days=365)
        df = fetch_stock_data(
            symbol,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )
        if len(df) < 30:
            return {"success": False, "error": "历史数据不足，无法预测"}

        close = df["close"].values
        n = len(close)

        # ── 日收益率统计 ──────────────────────────────
        returns = np.diff(close) / close[:-1]
        mu = np.mean(returns)          # 日均收益率
        sigma = np.std(returns)        # 日收益率标准差（波动率）
        daily_vol = sigma

        # ── 线性趋势（用于修正，权重较低）──────────────
        x = np.arange(n)
        coeffs = np.polyfit(x, close, 1)
        slope = coeffs[0]
        # 趋势日均涨幅（相对值）
        trend_daily = slope / close[-1]

        # ── Monte Carlo 随机游走（500 条路径）──────────
        N_SIM = 500
        last_price = close[-1]
        np.random.seed(42)

        # shape: (N_SIM, days)
        rand_returns = np.random.normal(mu, sigma, size=(N_SIM, days))

        # 叠加趋势修正（权重 0.3，避免趋势主导）
        trend_weight = 0.3
        blended_mu = (1 - trend_weight) * mu + trend_weight * trend_daily
        rand_returns = rand_returns - mu + blended_mu  # 平移均值

        # 累乘得到价格路径
        cum_returns = np.cumprod(1 + rand_returns, axis=1)  # (N_SIM, days)
        price_paths = last_price * cum_returns               # (N_SIM, days)

        # 取分位数
        pred_prices = np.median(price_paths, axis=0)         # 中位数
        upper = np.percentile(price_paths, 85, axis=0)       # 85% 分位
        lower = np.percentile(price_paths, 15, axis=0)       # 15% 分位

        # ── 生成未来交易日日期（跳过周末）──────────────
        future_dates = []
        cur = pd.Timestamp.today()
        while len(future_dates) < days:
            cur += timedelta(days=1)
            if cur.weekday() < 5:
                future_dates.append(cur.strftime("%Y-%m-%d"))

        # ── 历史数据（最近 60 条用于展示）──────────────
        hist_close = close[-60:]
        hist_dates = [d.strftime("%Y-%m-%d") for d in df.index[-60:]]
        hist_prices = [round(float(p), 2) for p in hist_close]

        # 技术指标
        ma5  = pd.Series(close).rolling(5).mean().values
        ma20 = pd.Series(close).rolling(20).mean().values

        # ── 趋势判断（综合多个信号）──────────────────
        trend_score = 0
        if close[-1] > ma5[-1]:  trend_score += 1
        if close[-1] > ma20[-1]: trend_score += 1
        if ma5[-1] > ma20[-1]:   trend_score += 1
        if slope > 0:            trend_score += 1

        trend_label = {0: "强烈下跌", 1: "偏弱", 2: "震荡", 3: "偏强", 4: "强烈上涨"}.get(trend_score, "震荡")
        trend_color = {0: "red", 1: "orange", 2: "gray", 3: "lightgreen", 4: "green"}.get(trend_score, "gray")

        # 预期涨跌幅（中位数路径）
        pred_change = (pred_prices[-1] - last_price) / last_price * 100

        # ── 市场类型 & 货币符号 ───────────────────────
        hk = is_hk_stock(symbol)
        market_label = "港股" if hk else "A股"
        currency = "HK$" if hk else "¥"

        # ── 预测说明文字 ──────────────────────────────
        explain = (
            f"【{market_label}】基于近 {len(returns)} 个交易日数据，"
            f"日均收益率 {mu*100:+.3f}%，日波动率 {sigma*100:.2f}%。"
            f"通过 {N_SIM} 条 Monte Carlo 路径模拟，"
            f"中位数预测 {days} 日后价格为 {currency}{pred_prices[-1]:.2f}，"
            f"15%~85% 置信区间为 {currency}{lower[-1]:.2f} ~ {currency}{upper[-1]:.2f}。"
            f"趋势修正权重 {int(trend_weight*100)}%（{'上行' if slope>0 else '下行'}趋势）。"
        )

        return {
            "success": True,
            "symbol": symbol,
            "market": market_label,
            "currency": currency,
            "last_price": round(last_price, 2),
            "pred_days": days,
            "pred_change": round(pred_change, 2),
            "trend_label": trend_label,
            "trend_color": trend_color,
            "daily_vol": round(daily_vol * 100, 2),
            "explain": explain,
            "hist": {
                "dates": hist_dates,
                "prices": hist_prices,
                "ma5":  [round(float(v), 2) if not np.isnan(v) else None for v in ma5[-60:]],
                "ma20": [round(float(v), 2) if not np.isnan(v) else None for v in ma20[-60:]],
            },
            "forecast": {
                "dates":  future_dates,
                "prices": [round(float(p), 2) for p in pred_prices],
                "upper":  [round(float(p), 2) for p in upper],
                "lower":  [round(float(p), 2) for p in lower],
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
