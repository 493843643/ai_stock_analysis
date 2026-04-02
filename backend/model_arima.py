"""
ARIMA + GARCH 预测模型

ARIMA（自回归积分滑动平均）：
  - 捕捉价格序列的自相关性（今天涨了，明天更可能继续涨）
  - auto_arima 自动选择最优 p,d,q 参数

GARCH（广义自回归条件异方差）：
  - 捕捉波动率聚集效应：大涨/大跌之后波动率会持续偏高
  - 用于生成更真实的置信区间（而非固定宽度）
"""
import numpy as np
import warnings
warnings.filterwarnings("ignore")


def _fit_arima(close: np.ndarray):
    """用 pmdarima auto_arima 自动选参并拟合"""
    from pmdarima import auto_arima
    returns = np.diff(np.log(close))   # 对数收益率，更平稳
    model = auto_arima(
        returns,
        start_p=0, max_p=3,
        start_q=0, max_q=3,
        d=0,                  # 已经差分过了
        seasonal=False,
        information_criterion="aic",
        stepwise=True,
        suppress_warnings=True,
        error_action="ignore",
    )
    return model, returns


def _fit_garch(returns: np.ndarray):
    """用 arch 库拟合 GARCH(1,1) 模型"""
    from arch import arch_model
    model = arch_model(returns * 100, vol="Garch", p=1, q=1, dist="normal")
    res = model.fit(disp="off", show_warning=False)
    return res


def predict_arima_garch(close: np.ndarray, n_days: int) -> dict:
    """
    ARIMA + GARCH 联合预测

    返回：
        {
          "prices": [float, ...],   # 预测价格（中位数路径）
          "upper": [float, ...],    # 置信上轨（GARCH 波动率）
          "lower": [float, ...],    # 置信下轨
          "model_info": str,        # 模型参数说明
        }
    """
    last_price = close[-1]

    # ── ARIMA 预测对数收益率 ──────────────────────
    try:
        arima_model, returns = _fit_arima(close)
        pred_returns = arima_model.predict(n_periods=n_days)
    except Exception:
        # fallback：用历史均值
        returns = np.diff(np.log(close))
        pred_returns = np.full(n_days, np.mean(returns))

    # ── GARCH 预测波动率 ──────────────────────────
    try:
        garch_res = _fit_garch(returns)
        forecasts = garch_res.forecast(horizon=n_days, reindex=False)
        # 预测方差（单位：(return*100)^2），转回标准差
        pred_vol = np.sqrt(forecasts.variance.values[-1]) / 100
        # 随时间扩大（累积不确定性）
        cum_vol = np.array([np.sqrt(np.sum(pred_vol[:i+1]**2)) for i in range(n_days)])
    except Exception:
        # fallback：用历史波动率
        hist_vol = np.std(returns)
        cum_vol = hist_vol * np.sqrt(np.arange(1, n_days + 1))

    # ── 从对数收益率还原价格 ──────────────────────
    cum_log_returns = np.cumsum(pred_returns)
    pred_prices = last_price * np.exp(cum_log_returns)

    # ── 置信区间（1.5σ，约86%置信度）────────────
    upper = last_price * np.exp(cum_log_returns + 1.5 * cum_vol)
    lower = last_price * np.exp(cum_log_returns - 1.5 * cum_vol)

    # 模型信息
    try:
        order = arima_model.order
        model_info = f"ARIMA{order} + GARCH(1,1)"
    except Exception:
        model_info = "ARIMA(均值回归) + GARCH(1,1)"

    return {
        "prices": [round(float(p), 3) for p in pred_prices],
        "upper":  [round(float(p), 3) for p in upper],
        "lower":  [round(float(p), 3) for p in lower],
        "model_info": model_info,
    }


def predict_fn_for_validation(train_close: np.ndarray, n_days: int) -> np.ndarray:
    """Walk-Forward 验证用的包装函数"""
    try:
        result = predict_arima_garch(train_close, n_days)
        return np.array(result["prices"])
    except Exception:
        return None
