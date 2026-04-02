"""
XGBoost 预测模型

思路：
  把"预测未来价格"转化为"预测未来N日的对数收益率"，
  用过去的技术指标作为特征，XGBoost 学习特征→收益率的映射关系。

特征工程（共 30+ 个特征）：
  - 动量类：1/3/5/10/20 日收益率
  - 均线类：价格相对 MA5/10/20/60 的偏离度
  - 波动率类：5/10/20 日历史波动率、ATR
  - 量价类：成交量变化率、量价背离
  - 技术指标：RSI(14)、MACD、布林带宽度
  - 时间特征：星期几（捕捉周内效应）
"""
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")


# ─────────────────────────────────────────
# 特征工程
# ─────────────────────────────────────────

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    输入 df 需包含 close, open, high, low, volume 列
    返回特征 DataFrame（已去除 NaN）
    """
    feat = pd.DataFrame(index=df.index)
    c = df["close"]
    v = df["volume"] if "volume" in df.columns else pd.Series(1, index=df.index)

    # ── 动量特征 ──────────────────────────────────
    for d in [1, 3, 5, 10, 20]:
        feat[f"ret_{d}d"] = c.pct_change(d)

    # ── 均线偏离度 ────────────────────────────────
    # 注意：ma60 需要60条数据才不为 NaN，数据量少时改用 min_periods 保证有值
    for w in [5, 10, 20, 60]:
        ma = c.rolling(w, min_periods=max(w // 2, 5)).mean()
        feat[f"ma{w}_dev"] = (c - ma) / ma  # 价格相对均线的偏离

    # ── 波动率特征 ────────────────────────────────
    log_ret = np.log(c / c.shift(1))
    for w in [5, 10, 20]:
        feat[f"vol_{w}d"] = log_ret.rolling(w, min_periods=max(w // 2, 3)).std()

    # ── ATR（真实波幅）────────────────────────────
    if "high" in df.columns and "low" in df.columns:
        high, low = df["high"], df["low"]
        tr = pd.concat([
            high - low,
            (high - c.shift(1)).abs(),
            (low  - c.shift(1)).abs(),
        ], axis=1).max(axis=1)
        feat["atr_14"] = tr.rolling(14).mean() / c  # 归一化

    # ── RSI(14) ───────────────────────────────────
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / (loss + 1e-9)
    feat["rsi_14"] = 100 - 100 / (1 + rs)

    # ── MACD ─────────────────────────────────────
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    signal_line = macd.ewm(span=9, adjust=False).mean()
    feat["macd"]        = macd / c
    feat["macd_signal"] = signal_line / c
    feat["macd_hist"]   = (macd - signal_line) / c

    # ── 布林带宽度 ────────────────────────────────
    ma20  = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    feat["boll_width"] = (2 * std20) / ma20  # 带宽/均线
    feat["boll_pos"]   = (c - (ma20 - 2*std20)) / (4 * std20 + 1e-9)  # 价格在带内位置 0~1

    # ── 量价特征 ──────────────────────────────────
    feat["vol_chg_5d"]  = v.pct_change(5)
    feat["vol_ma5_dev"] = (v - v.rolling(5).mean()) / (v.rolling(5).mean() + 1e-9)
    # 量价背离：价格涨但量缩 → 负值
    feat["price_vol_corr"] = log_ret.rolling(10).corr(v.pct_change())

    # ── 时间特征 ──────────────────────────────────
    feat["weekday"] = pd.to_datetime(df.index).dayofweek / 4.0  # 0~1

    return feat.dropna()


def build_targets(df: pd.DataFrame, feat_index, horizon: int = 5) -> pd.Series:
    """
    目标变量：未来 horizon 日的累计对数收益率
    只保留与特征对齐的行
    """
    c = df["close"]
    log_ret = np.log(c.shift(-horizon) / c)
    return log_ret.reindex(feat_index).dropna()


# ─────────────────────────────────────────
# 模型训练与预测
# ─────────────────────────────────────────

def train_xgb(close_arr: np.ndarray, ohlcv_df: pd.DataFrame = None, horizon: int = 5):
    """
    训练 XGBoost 模型
    ohlcv_df: 包含 open/high/low/close/volume 的 DataFrame（可选，有则特征更丰富）
    """
    from xgboost import XGBRegressor

    if ohlcv_df is None:
        # 只有收盘价时，构造最小 DataFrame
        ohlcv_df = pd.DataFrame({"close": close_arr},
                                index=pd.date_range("2020-01-01", periods=len(close_arr), freq="B"))

    feat = build_features(ohlcv_df)
    target = build_targets(ohlcv_df, feat.index, horizon=horizon)

    # 对齐
    common_idx = feat.index.intersection(target.index)
    X = feat.loc[common_idx].values
    y = target.loc[common_idx].values

    if len(X) < 20:
        raise ValueError(f"训练数据不足（有效样本 {len(X)} 个，需要至少 20 个）")

    model = XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=42,
        verbosity=0,
    )
    model.fit(X, y)
    return model, feat, horizon


def predict_xgb(close_arr: np.ndarray, n_days: int,
                ohlcv_df: pd.DataFrame = None) -> dict:
    """
    XGBoost 预测未来 n_days 天价格

    策略：
      1. 用全部历史数据训练模型（目标=未来5日收益率）
      2. 用最新特征预测"接下来5日的累计收益率"
      3. 用历史波动率生成置信区间
    """
    last_price = close_arr[-1]

    try:
        model, feat, horizon = train_xgb(close_arr, ohlcv_df, horizon=min(n_days, 5))
    except Exception as e:
        # fallback：返回随机游走
        returns = np.diff(close_arr) / close_arr[:-1]
        mu, sigma = np.mean(returns), np.std(returns)
        pred = last_price * np.exp(np.cumsum(np.full(n_days, mu)))
        vol  = sigma * np.sqrt(np.arange(1, n_days + 1))
        return {
            "prices": [round(float(p), 3) for p in pred],
            "upper":  [round(float(p), 3) for p in pred * np.exp(1.5 * vol)],
            "lower":  [round(float(p), 3) for p in pred * np.exp(-1.5 * vol)],
            "model_info": f"XGBoost(fallback: {e})",
            "feature_importance": {},
        }

    # 用最新一行特征预测
    latest_feat = feat.iloc[[-1]].values
    pred_log_ret_horizon = float(model.predict(latest_feat)[0])

    # 把 horizon 日收益率线性分配到每一天
    daily_log_ret = pred_log_ret_horizon / horizon
    cum_log_rets  = np.cumsum(np.full(n_days, daily_log_ret))
    pred_prices   = last_price * np.exp(cum_log_rets)

    # 置信区间：用历史残差估计不确定性
    returns = np.diff(close_arr) / close_arr[:-1]
    hist_vol = np.std(returns)
    cum_vol  = hist_vol * np.sqrt(np.arange(1, n_days + 1))
    upper = pred_prices * np.exp(1.5 * cum_vol)
    lower = pred_prices * np.exp(-1.5 * cum_vol)

    # 特征重要性（Top 8）
    feat_names = feat.columns.tolist()
    importances = model.feature_importances_
    top_idx = np.argsort(importances)[::-1][:8]
    feat_importance = {feat_names[i]: round(float(importances[i]), 4) for i in top_idx}

    return {
        "prices": [round(float(p), 3) for p in pred_prices],
        "upper":  [round(float(p), 3) for p in upper],
        "lower":  [round(float(p), 3) for p in lower],
        "model_info": f"XGBoost(horizon={horizon}d, features={len(feat_names)})",
        "feature_importance": feat_importance,
    }


def predict_fn_for_validation(train_close: np.ndarray, n_days: int) -> np.ndarray:
    """Walk-Forward 验证用的包装函数"""
    try:
        result = predict_xgb(train_close, n_days)
        return np.array(result["prices"])
    except Exception:
        return None
