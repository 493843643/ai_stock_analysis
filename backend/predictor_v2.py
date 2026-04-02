"""
增强版预测模块 v2
集成三种模型 + Walk-Forward 动态调权 + 历史准确率评估

模型权重分配策略：
  1. 先用 Walk-Forward 验证各模型的历史方向准确率
  2. 准确率越高的模型权重越大（softmax 归一化）
  3. 最终预测 = 加权平均

模型组合：
  - Monte Carlo（基线）：捕捉随机波动
  - ARIMA + GARCH（统计）：捕捉自相关 + 波动率聚集
  - XGBoost（机器学习）：捕捉技术指标非线性关系
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
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(__file__))
from engine import fetch_stock_data, is_hk_stock
from validator import walk_forward_validate


# ─────────────────────────────────────────
# Monte Carlo 预测函数（复用原有逻辑）
# ─────────────────────────────────────────

def _predict_monte_carlo(close: np.ndarray, n_days: int, seed: int = 42) -> dict:
    returns = np.diff(close) / close[:-1]
    mu, sigma = np.mean(returns), np.std(returns)
    last_price = close[-1]

    # 趋势修正
    x = np.arange(len(close))
    slope = np.polyfit(x, close, 1)[0]
    trend_daily = slope / last_price
    blended_mu = 0.7 * mu + 0.3 * trend_daily

    np.random.seed(seed)
    rand_ret = np.random.normal(blended_mu, sigma, size=(500, n_days))
    paths = last_price * np.cumprod(1 + rand_ret, axis=1)

    return {
        "prices": np.median(paths, axis=0),
        "upper":  np.percentile(paths, 85, axis=0),
        "lower":  np.percentile(paths, 15, axis=0),
        "model_info": "Monte Carlo(500路径)",
    }


def _predict_mc_fn(train_close, n_days):
    try:
        return _predict_monte_carlo(train_close, n_days)["prices"]
    except Exception:
        return None


# ─────────────────────────────────────────
# 集成预测主函数
# ─────────────────────────────────────────

def predict_price_v2(symbol: str, days: int = 30) -> dict:
    """
    增强版预测：三模型集成 + Walk-Forward 动态调权

    返回字段（在 v1 基础上新增）：
      model_weights   : 各模型权重
      model_results   : 各模型独立预测结果
      validation      : Walk-Forward 验证指标
      feature_importance: XGBoost 特征重要性
    """
    try:
        # ── 拉取历史数据 ──────────────────────────
        end   = pd.Timestamp.today()
        start = end - timedelta(days=500)   # 约2年，Walk-Forward 需要更多数据
        df = fetch_stock_data(
            symbol,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )
        if len(df) < 60:
            return {"success": False, "error": "历史数据不足（需要至少60个交易日）"}

        close = df["close"].values
        n = len(close)

        # ── 市场信息 ──────────────────────────────
        hk = is_hk_stock(symbol)
        market_label = "港股" if hk else "A股"
        currency = "HK$" if hk else "¥"

        # ── 各模型预测 ────────────────────────────
        model_results = {}
        errors = {}

        # 1. Monte Carlo
        mc_res = _predict_monte_carlo(close, days)
        model_results["Monte Carlo"] = mc_res

        # 2. ARIMA + GARCH
        try:
            from model_arima import predict_arima_garch
            ag_res = predict_arima_garch(close, days)
            model_results["ARIMA+GARCH"] = ag_res
        except Exception as e:
            errors["ARIMA+GARCH"] = str(e)

        # 3. XGBoost
        try:
            from model_xgb import predict_xgb
            xgb_res = predict_xgb(close, days, ohlcv_df=df)
            model_results["XGBoost"] = xgb_res
        except Exception as e:
            errors["XGBoost"] = str(e)

        # ── Walk-Forward 验证（用近 300 日数据）────
        val_close = close[-min(300, n):]
        validation_results = {}

        # MC 验证
        mc_val = walk_forward_validate(val_close, _predict_mc_fn,
                                       train_size=80, test_size=days, step=10)
        validation_results["Monte Carlo"] = mc_val

        # ARIMA 验证
        if "ARIMA+GARCH" in model_results:
            try:
                from model_arima import predict_fn_for_validation as arima_fn
                ag_val = walk_forward_validate(val_close, arima_fn,
                                               train_size=80, test_size=days, step=10)
                validation_results["ARIMA+GARCH"] = ag_val
            except Exception as e:
                validation_results["ARIMA+GARCH"] = {"error": str(e)}

        # XGBoost 验证
        if "XGBoost" in model_results:
            try:
                from model_xgb import predict_fn_for_validation as xgb_fn
                xgb_val = walk_forward_validate(val_close, xgb_fn,
                                                train_size=80, test_size=days, step=10)
                validation_results["XGBoost"] = xgb_val
            except Exception as e:
                validation_results["XGBoost"] = {"error": str(e)}

        # ── 动态权重：基于方向准确率 softmax ────────
        weights = {}
        for name in model_results:
            val = validation_results.get(name, {})
            if "error" not in val and "direction_acc" in val:
                weights[name] = val["direction_acc"]
            else:
                weights[name] = 0.5   # 无验证数据时给默认权重

        # Softmax 归一化（放大差异）
        names = list(weights.keys())
        accs  = np.array([weights[n] for n in names])
        # 温度参数 T=5，T 越小权重越集中在最优模型
        T = 5.0
        exp_accs = np.exp(accs * T)
        softmax_w = exp_accs / exp_accs.sum()
        final_weights = {n: round(float(w), 4) for n, w in zip(names, softmax_w)}

        # ── 集成预测：加权平均 ────────────────────
        pred_prices = np.zeros(days)
        upper_prices = np.zeros(days)
        lower_prices = np.zeros(days)

        for name, w in final_weights.items():
            res = model_results[name]
            pred_prices  += w * np.array(res["prices"][:days])
            upper_prices += w * np.array(res["upper"][:days])
            lower_prices += w * np.array(res["lower"][:days])

        # ── 历史数据（展示用）────────────────────
        hist_close = close[-60:]
        hist_dates = [d.strftime("%Y-%m-%d") for d in df.index[-60:]]
        hist_prices = [round(float(p), 3) for p in hist_close]

        ma5  = pd.Series(close).rolling(5).mean().values
        ma20 = pd.Series(close).rolling(20).mean().values

        # ── 未来交易日 ────────────────────────────
        future_dates = []
        cur = pd.Timestamp.today()
        while len(future_dates) < days:
            cur += timedelta(days=1)
            if cur.weekday() < 5:
                future_dates.append(cur.strftime("%Y-%m-%d"))

        # ── 趋势判断 ──────────────────────────────
        last_price = close[-1]
        returns = np.diff(close) / close[:-1]
        mu = np.mean(returns)
        sigma = np.std(returns)
        slope = np.polyfit(np.arange(n), close, 1)[0]

        trend_score = 0
        if close[-1] > ma5[-1]:  trend_score += 1
        if close[-1] > ma20[-1]: trend_score += 1
        if ma5[-1] > ma20[-1]:   trend_score += 1
        if slope > 0:            trend_score += 1

        trend_label = {0: "强烈下跌", 1: "偏弱", 2: "震荡", 3: "偏强", 4: "强烈上涨"}.get(trend_score, "震荡")
        trend_color = {0: "red", 1: "orange", 2: "gray", 3: "lightgreen", 4: "green"}.get(trend_score, "gray")
        pred_change = (pred_prices[-1] - last_price) / last_price * 100

        # ── 最优模型 ──────────────────────────────
        best_model = max(final_weights, key=lambda k: final_weights[k])
        best_acc = validation_results.get(best_model, {}).get("direction_acc", 0)

        # ── 验证摘要（前端展示用）────────────────
        val_summary = []
        for name in model_results:
            val = validation_results.get(name, {})
            val_summary.append({
                "model": name,
                "weight": final_weights.get(name, 0),
                "direction_acc": val.get("direction_acc"),
                "mape": val.get("mape"),
                "win_rate": val.get("win_rate"),
                "n_windows": val.get("n_windows", 0),
                "model_info": model_results[name].get("model_info", ""),
                "error": val.get("error"),
            })

        # ── 说明文字 ──────────────────────────────
        weight_str = "、".join([f"{n}({w*100:.0f}%)" for n, w in final_weights.items()])
        explain = (
            f"【{market_label} · 集成模型】{weight_str}加权预测。"
            f"最优模型：{best_model}（历史方向准确率 {best_acc*100:.1f}%）。"
            f"日均波动率 {sigma*100:.2f}%，"
            f"中位数预测 {days} 日后价格 {currency}{pred_prices[-1]:.2f}，"
            f"置信区间 {currency}{lower_prices[-1]:.2f}~{currency}{upper_prices[-1]:.2f}。"
        )

        # 各模型独立预测结果（前端对比用）
        model_compare = {}
        for name, res in model_results.items():
            model_compare[name] = {
                "prices": [round(float(p), 3) for p in res["prices"][:days]],
                "end_price": round(float(res["prices"][days-1]), 3),
                "end_change": round((res["prices"][days-1] - last_price) / last_price * 100, 2),
                "weight": final_weights.get(name, 0),
            }

        # XGBoost 特征重要性
        feat_importance = {}
        if "XGBoost" in model_results:
            feat_importance = model_results["XGBoost"].get("feature_importance", {})

        return {
            "success": True,
            "symbol": symbol,
            "market": market_label,
            "currency": currency,
            "last_price": round(last_price, 3),
            "pred_days": days,
            "pred_change": round(pred_change, 2),
            "trend_label": trend_label,
            "trend_color": trend_color,
            "daily_vol": round(sigma * 100, 2),
            "explain": explain,
            "model_weights": final_weights,
            "best_model": best_model,
            "model_compare": model_compare,
            "validation": val_summary,
            "feature_importance": feat_importance,
            "errors": errors,
            "hist": {
                "dates": hist_dates,
                "prices": hist_prices,
                "ma5":  [round(float(v), 3) if not np.isnan(v) else None for v in ma5[-60:]],
                "ma20": [round(float(v), 3) if not np.isnan(v) else None for v in ma20[-60:]],
            },
            "forecast": {
                "dates":  future_dates,
                "prices": [round(float(p), 3) for p in pred_prices],
                "upper":  [round(float(p), 3) for p in upper_prices],
                "lower":  [round(float(p), 3) for p in lower_prices],
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
