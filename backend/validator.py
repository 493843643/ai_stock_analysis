"""
Walk-Forward 验证模块
用于评估预测模型的历史准确性：
- 方向准确率：预测涨跌方向正确的比例
- MAE：平均绝对误差（价格）
- MAPE：平均绝对百分比误差
- 信号胜率：基于预测信号做交易的盈利比例
"""
import numpy as np
import pandas as pd
from typing import Callable, Dict, List


def walk_forward_validate(
    close: np.ndarray,
    predict_fn: Callable[[np.ndarray, int], np.ndarray],
    train_size: int = 120,
    test_size: int = 5,
    step: int = 5,
) -> Dict:
    """
    时间序列 Walk-Forward 交叉验证

    参数：
        close       : 收盘价序列（numpy array）
        predict_fn  : 预测函数，签名 fn(train_close, n_days) -> predicted_close (length=n_days)
        train_size  : 每次训练用的历史数据长度（交易日）
        test_size   : 每次预测的天数
        step        : 窗口滑动步长

    返回：
        {
          "direction_acc": float,   # 方向准确率 0~1
          "mae": float,             # 平均绝对误差
          "mape": float,            # 平均绝对百分比误差 %
          "win_rate": float,        # 信号胜率（预测涨且真实涨 / 所有预测涨）
          "n_windows": int,         # 验证窗口数
          "details": List[dict],    # 每个窗口的详细结果
        }
    """
    n = len(close)
    details = []
    direction_correct = 0
    direction_total = 0
    abs_errors = []
    pct_errors = []
    signal_win = 0
    signal_total = 0

    start = train_size
    while start + test_size <= n:
        train = close[start - train_size: start]
        actual = close[start: start + test_size]

        try:
            predicted = predict_fn(train, test_size)
            if predicted is None or len(predicted) < test_size:
                start += step
                continue

            predicted = np.array(predicted[:test_size])
            last_train_price = train[-1]

            # 逐日评估
            for i in range(test_size):
                pred_p = predicted[i]
                real_p = actual[i]
                prev_p = train[-1] if i == 0 else actual[i - 1]

                # 方向准确率
                pred_dir = pred_p > prev_p
                real_dir = real_p > prev_p
                if pred_dir == real_dir:
                    direction_correct += 1
                direction_total += 1

                # 误差
                abs_errors.append(abs(pred_p - real_p))
                if real_p != 0:
                    pct_errors.append(abs(pred_p - real_p) / real_p * 100)

                # 信号胜率：预测涨时买入，看实际是否涨
                if pred_dir:  # 预测涨
                    signal_total += 1
                    if real_dir:
                        signal_win += 1

            details.append({
                "window_start": start,
                "pred_end_price": round(float(predicted[-1]), 2),
                "real_end_price": round(float(actual[-1]), 2),
                "pred_change_pct": round((predicted[-1] - last_train_price) / last_train_price * 100, 2),
                "real_change_pct": round((actual[-1] - last_train_price) / last_train_price * 100, 2),
                "direction_correct": (predicted[-1] > last_train_price) == (actual[-1] > last_train_price),
            })

        except Exception:
            pass

        start += step

    if direction_total == 0:
        return {"error": "验证窗口不足，请使用更长的历史数据"}

    return {
        "direction_acc": round(direction_correct / direction_total, 4),
        "mae": round(float(np.mean(abs_errors)), 4) if abs_errors else None,
        "mape": round(float(np.mean(pct_errors)), 4) if pct_errors else None,
        "win_rate": round(signal_win / signal_total, 4) if signal_total > 0 else None,
        "n_windows": len(details),
        "details": details,
    }


def compute_metrics_summary(results: Dict[str, Dict]) -> pd.DataFrame:
    """
    汇总多个模型的验证结果，返回对比 DataFrame
    results: {"模型名": walk_forward_validate 返回值, ...}
    """
    rows = []
    for name, r in results.items():
        if "error" in r:
            continue
        rows.append({
            "模型": name,
            "方向准确率": f"{r['direction_acc']*100:.1f}%",
            "MAE": r["mae"],
            "MAPE": f"{r['mape']:.2f}%" if r["mape"] else "-",
            "信号胜率": f"{r['win_rate']*100:.1f}%" if r["win_rate"] else "-",
            "验证窗口数": r["n_windows"],
        })
    return pd.DataFrame(rows)
