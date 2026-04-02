"""
Flask 后端 API 服务
"""
import os

# ── 在所有网络库加载前强制禁用代理 ──────────────────────────
_PROXY_KEYS = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
               "all_proxy", "ALL_PROXY", "CURL_CA_BUNDLE"]
for _k in _PROXY_KEYS:
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
os.environ["CURL_IMPERSONATE_NOPROXY"] = "1"

import urllib.request
urllib.request.getproxies = lambda: {}

import requests as _requests
import requests.utils as _ru
_ru.get_environ_proxies = lambda *a, **kw: {}
_ru.select_proxy = lambda url, proxies: None
# ─────────────────────────────────────────────────────────────

from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS
import baostock as bs
import sys
import threading

sys.path.insert(0, os.path.dirname(__file__))
from engine import run_backtest
from predictor import predict_price
from predictor_v2 import predict_price_v2
from recommender import get_recommendations, STOCK_POOL, INDUSTRY_NAMES

app = Flask(__name__, static_folder="../frontend/static")
CORS(app)

# ── 常见港股 / 中概股静态列表（baostock 不覆盖港股，手动内置）──
_HK_STOCKS = [
    {"代码": "03690", "名称": "美团",         "市场": "港股"},
    {"代码": "00700", "名称": "腾讯控股",     "市场": "港股"},
    {"代码": "09988", "名称": "阿里巴巴",     "市场": "港股"},
    {"代码": "09618", "名称": "京东集团",     "市场": "港股"},
    {"代码": "09999", "名称": "网易",         "市场": "港股"},
    {"代码": "01810", "名称": "小米集团",     "市场": "港股"},
    {"代码": "03888", "名称": "金山软件",     "市场": "港股"},
    {"代码": "00941", "名称": "中国移动",     "市场": "港股"},
    {"代码": "00883", "名称": "中国海洋石油", "市场": "港股"},
    {"代码": "02318", "名称": "中国平安",     "市场": "港股"},
    {"代码": "01299", "名称": "友邦保险",     "市场": "港股"},
    {"代码": "02020", "名称": "安踏体育",     "市场": "港股"},
    {"代码": "09961", "名称": "携程集团",     "市场": "港股"},
    {"代码": "06690", "名称": "海尔智家",     "市场": "港股"},
    {"代码": "00175", "名称": "吉利汽车",     "市场": "港股"},
    {"代码": "02015", "名称": "理想汽车",     "市场": "港股"},
    {"代码": "09868", "名称": "小鹏汽车",     "市场": "港股"},
    {"代码": "09866", "名称": "蔚来",         "市场": "港股"},
    {"代码": "06969", "名称": "思摩尔国际",   "市场": "港股"},
    {"代码": "01024", "名称": "快手",         "市场": "港股"},
    {"代码": "00020", "名称": "商汤集团",     "市场": "港股"},
    {"代码": "09626", "名称": "哔哩哔哩",     "市场": "港股"},
    {"代码": "06060", "名称": "众安在线",     "市场": "港股"},
    {"代码": "01211", "名称": "比亚迪股份",   "市场": "港股"},
    {"代码": "00388", "名称": "香港交易所",   "市场": "港股"},
]

# ── 全量股票列表缓存（启动时同步加载，用于模糊搜索）──────────
_stock_cache = []          # [{"代码": "000001", "名称": "平安银行", "市场": "A股"}, ...]
_cache_lock  = threading.Lock()

def _build_stock_cache():
    """
    用 baostock 拉取全量 A 股列表 + 行业分类，再追加港股静态列表。
    每条 A 股记录格式：
      {"代码": "000001", "名称": "平安银行", "市场": "A股",
       "industry": "J66货币金融服务"}
    """
    global _stock_cache
    try:
        print("📋 正在加载股票列表 + 行业分类...")
        lg = bs.login()

        # ── 1. 拉取全量行业分类（一次性，约 5500 条）──────────
        industry_map = {}   # code_short -> industry_str
        rs_ind = bs.query_stock_industry()
        while rs_ind.error_code == "0" and rs_ind.next():
            row = rs_ind.get_row_data()
            # row: [updateDate, code, code_name, industry, industryClassification]
            code_short = row[1].split(".")[-1]
            industry_map[code_short] = row[3]   # e.g. "J66货币金融服务"

        # ── 2. 拉取全量股票基本信息 ──────────────────────────
        rs = bs.query_stock_basic()
        rows = []
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            # row: [code, code_name, ipoDate, outDate, type, status]
            if row[4] == "1" and row[5] == "1":   # 股票 & 上市
                code_short = row[0].split(".")[-1]
                rows.append({
                    "代码":     code_short,
                    "名称":     row[1],
                    "市场":     "A股",
                    "industry": industry_map.get(code_short, ""),
                })
        bs.logout()

        # 追加港股（无行业字段）
        rows.extend(_HK_STOCKS)
        with _cache_lock:
            _stock_cache = rows
        a_cnt = len(rows) - len(_HK_STOCKS)
        ind_cnt = sum(1 for r in rows if r.get("industry"))
        print(f"✅ 股票列表缓存完成，A股 {a_cnt} 只（含行业标签 {ind_cnt} 只）+ 港股 {len(_HK_STOCKS)} 只")
    except Exception as e:
        print(f"⚠️  股票列表缓存失败: {e}")

_build_stock_cache()   # 同步加载，启动时执行一次

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "../frontend")


# ─────────────────────────────────────────
# 前端页面
# ─────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "static"), filename)


# ─────────────────────────────────────────
# API 接口
# ─────────────────────────────────────────

@app.route("/api/search_stock", methods=["GET"])
def search_stock():
    """搜索股票名称（本地缓存模糊匹配，不走代理）"""
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return jsonify({"success": False, "error": "请输入关键词"})
    with _cache_lock:
        cache = _stock_cache[:]
    if not cache:
        return jsonify({"success": False, "error": "股票列表加载中，请稍后再试（约10秒）"})
    kw = keyword.upper()
    matched = [s for s in cache if kw in s["名称"] or kw in s["代码"]]
    return jsonify({"success": True, "data": matched[:10]})


@app.route("/api/stock_info", methods=["GET"])
def stock_info():
    """获取股票基本信息（baostock，不走代理）"""
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return jsonify({"success": False, "error": "请输入股票代码"})
    try:
        # 补全交易所前缀
        if symbol.startswith("6"):
            bs_code = f"sh.{symbol}"
        else:
            bs_code = f"sz.{symbol}"

        # 先强制断开旧连接，避免 TCP 状态残留导致"网络接收错误"
        try:
            bs.logout()
        except Exception:
            pass
        lg = bs.login()
        try:
            # 查基本信息
            rs_basic = bs.query_stock_basic(code=bs_code)
            name = symbol
            if rs_basic.error_code == "0" and rs_basic.next():
                row = rs_basic.get_row_data()
                name = row[1]

            # 查最近一日行情
            import datetime
            today = datetime.date.today().strftime("%Y-%m-%d")
            week_ago = (datetime.date.today() - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,close,pctChg,volume,peTTM",
                start_date=week_ago,
                end_date=today,
                frequency="d",
                adjustflag="3",
            )
            last_row = None
            while rs.error_code == "0" and rs.next():
                last_row = rs.get_row_data()
        finally:
            bs.logout()

        if last_row is None:
            return jsonify({"success": False, "error": "未找到该股票行情"})

        info = {
            "代码": symbol,
            "名称": name,
            "最新价": float(last_row[1]) if last_row[1] else None,
            "涨跌幅": float(last_row[2]) if last_row[2] else None,
            "成交量": float(last_row[3]) if last_row[3] else None,
            "市盈率-动态": float(last_row[4]) if last_row[4] else None,
        }
        return jsonify({"success": True, "data": info})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/backtest", methods=["POST"])
def backtest():
    """执行回测"""
    params = request.get_json()
    if not params:
        return jsonify({"success": False, "error": "参数不能为空"})
    result = run_backtest(params)
    return jsonify(result)


@app.route("/api/strategies", methods=["GET"])
def get_strategies():
    """获取支持的策略列表"""
    strategies = [
        {
            "id": "ma_cross",
            "name": "双均线策略",
            "description": "快线上穿慢线买入，下穿卖出",
            "params": [
                {"key": "fast", "label": "快线周期", "default": 5, "min": 2, "max": 60},
                {"key": "slow", "label": "慢线周期", "default": 20, "min": 5, "max": 120},
            ],
        },
        {
            "id": "rsi",
            "name": "RSI 策略",
            "description": "RSI 低于超卖线买入，高于超买线卖出",
            "params": [
                {"key": "period", "label": "RSI 周期", "default": 14, "min": 5, "max": 30},
                {"key": "oversold", "label": "超卖线", "default": 30, "min": 10, "max": 40},
                {"key": "overbought", "label": "超买线", "default": 70, "min": 60, "max": 90},
            ],
        },
        {
            "id": "bollinger",
            "name": "布林带策略",
            "description": "价格跌破下轨买入，回到中轨卖出（均值回归）",
            "params": [
                {"key": "period", "label": "均线周期", "default": 20, "min": 5, "max": 60},
                {"key": "devfactor", "label": "标准差倍数", "default": 2.0, "min": 1.0, "max": 3.0, "step": 0.1},
            ],
        },
    ]
    return jsonify({"success": True, "data": strategies})


@app.route("/api/predict", methods=["GET"])
def predict():
    """价格预测接口"""
    symbol = request.args.get("symbol", "").strip()
    days = int(request.args.get("days", 30))
    if not symbol:
        return jsonify({"success": False, "error": "请输入股票代码"})
    days = max(7, min(days, 60))
    result = predict_price(symbol, days)
    return jsonify(result)


@app.route("/api/predict_v2", methods=["GET"])
def predict_v2():
    """增强版预测接口：三模型集成 + Walk-Forward 动态调权（较慢，约10~30秒）"""
    symbol = request.args.get("symbol", "").strip()
    days   = int(request.args.get("days", 15))
    if not symbol:
        return jsonify({"success": False, "error": "请输入股票代码"})
    days = max(5, min(days, 30))   # v2 限制最多30天，Walk-Forward 需要时间
    result = predict_price_v2(symbol, days)
    return jsonify(result)


@app.route("/api/stock_news", methods=["GET"])
def stock_news():
    """
    获取股票最新资讯并做利好/利空情感分类
    支持 A 股（6位代码）和港股（5位代码）
    """
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return jsonify({"success": False, "error": "请输入股票代码"})
    try:
        import akshare as ak
        import re as _re

        news_list = []

        # ── 港股走东方财富港股新闻 ──────────────────────────
        if len(symbol) == 5 and symbol.isdigit():
            try:
                df = ak.stock_hk_news(symbol=symbol)
                if df is not None and not df.empty:
                    for _, row in df.head(20).iterrows():
                        title = str(row.get("title", row.get("新闻标题", "")))
                        content = str(row.get("content", row.get("新闻内容", "")))
                        pub_time = str(row.get("publish_time", row.get("发布时间", "")))
                        source = str(row.get("source", row.get("新闻来源", "东方财富")))
                        news_list.append({"title": title, "content": content[:120],
                                          "time": pub_time, "source": source})
            except Exception:
                pass

        # ── A 股走东方财富个股新闻（直接用6位代码，不加交易所前缀）────
        if not news_list:
            try:
                df = ak.stock_news_em(symbol=symbol)
                if df is not None and not df.empty:
                    for _, row in df.head(20).iterrows():
                        title = str(row.get("新闻标题", row.get("title", "")))
                        content = str(row.get("新闻内容", row.get("content", "")))
                        pub_time = str(row.get("发布时间", row.get("time", "")))
                        # akshare 列名是"文章来源"，不是"新闻来源"
                        source = str(row.get("文章来源", row.get("新闻来源", row.get("source", "东方财富"))))
                        news_list.append({"title": title, "content": content[:120],
                                          "time": pub_time, "source": source})
            except Exception:
                pass

        # ── 情感分类（关键词规则）────────────────────────────
        BULLISH_KW = [
            "上涨", "涨停", "大涨", "利好", "增长", "盈利", "超预期", "新高", "突破",
            "扩张", "回购", "增持", "分红", "派息", "中标", "获批", "签约", "合作",
            "订单", "营收增", "净利增", "业绩增", "提升", "强势", "看好", "买入",
            "上调", "升级", "创新", "研发成功", "获奖", "入选", "战略", "布局",
        ]
        BEARISH_KW = [
            "下跌", "跌停", "大跌", "利空", "亏损", "下滑", "低于预期", "新低", "破位",
            "收缩", "减持", "质押", "违规", "处罚", "调查", "诉讼", "风险", "警示",
            "退市", "亏损扩大", "营收降", "净利降", "业绩降", "下调", "降级", "卖出",
            "停产", "召回", "负债", "债务", "违约", "暴雷", "爆雷",
        ]

        def classify(title, content):
            text = title + content
            bull = sum(1 for kw in BULLISH_KW if kw in text)
            bear = sum(1 for kw in BEARISH_KW if kw in text)
            if bull > bear:
                return "bullish"
            elif bear > bull:
                return "bearish"
            else:
                return "neutral"

        result_news = []
        for item in news_list:
            sentiment = classify(item["title"], item["content"])
            result_news.append({
                "title":     item["title"],
                "summary":   item["content"],
                "time":      item["time"],
                "source":    item["source"],
                "sentiment": sentiment,   # bullish / bearish / neutral
            })

        # 按情感分组
        bullish = [n for n in result_news if n["sentiment"] == "bullish"]
        bearish = [n for n in result_news if n["sentiment"] == "bearish"]
        neutral = [n for n in result_news if n["sentiment"] == "neutral"]

        return jsonify({
            "success": True,
            "symbol": symbol,
            "total": len(result_news),
            "bullish": bullish[:6],
            "bearish": bearish[:6],
            "neutral": neutral[:4],
            "sentiment_summary": {
                "bullish_count": len(bullish),
                "bearish_count": len(bearish),
                "neutral_count": len(neutral),
            }
        })

    except Exception as e:
        import traceback as _tb
        return jsonify({"success": False, "error": str(e), "traceback": _tb.format_exc()})


@app.route("/api/industries", methods=["GET"])
def get_industries():
    """获取行业列表（供前端下拉框使用）"""
    return jsonify({"success": True, "data": INDUSTRY_NAMES})


@app.route("/api/industry_heatmap", methods=["GET"])
def industry_heatmap():
    """
    行业晴雨表：获取申万一级行业当日（或最近交易日）涨跌幅
    返回全部31个行业的涨跌幅，按涨跌幅降序排列
    """
    try:
        import akshare as ak
        import datetime as _dt

        # 申万一级行业代码映射（2021版，31个）
        SW1_MAP = {
            "农林牧渔": "801010", "基础化工": "801020", "钢铁":    "801040",
            "有色金属": "801050", "电子":     "801080", "家用电器": "801110",
            "食品饮料": "801120", "纺织服饰": "801130", "轻工制造": "801140",
            "医药生物": "801150", "公用事业": "801160", "交通运输": "801170",
            "房地产":   "801180", "商贸零售": "801200", "社会服务": "801210",
            "综合":     "801230", "建筑材料": "801710", "建筑装饰": "801720",
            "电力设备": "801730", "国防军工": "801740", "计算机":   "801750",
            "传媒":     "801760", "通信":     "801770", "银行":     "801780",
            "非银金融": "801790", "煤炭":     "801800", "汽车":     "801880",
            "机械设备": "801890", "环保":     "801950", "石油石化": "801960",
            "美容护理": "801970",
        }

        results = []
        today = _dt.date.today()
        # 往前取10个自然日，确保能拿到最近交易日数据
        start = (today - _dt.timedelta(days=10)).strftime("%Y%m%d")
        end   = today.strftime("%Y%m%d")

        for name, code in SW1_MAP.items():
            try:
                df = ak.index_hist_sw(symbol=code, period="day")
                if df is None or df.empty:
                    continue
                # 取最近两个交易日计算涨跌幅
                df = df.sort_values("日期").tail(2)
                if len(df) < 2:
                    continue
                prev_close = float(df.iloc[-2]["收盘"])
                last_close = float(df.iloc[-1]["收盘"])
                last_date  = str(df.iloc[-1]["日期"])
                chg_pct = round((last_close - prev_close) / prev_close * 100, 2)
                results.append({
                    "name":     name,
                    "code":     code,
                    "chg_pct":  chg_pct,
                    "close":    round(last_close, 2),
                    "date":     last_date,
                })
            except Exception:
                continue

        if not results:
            return jsonify({"success": False, "error": "暂无行业数据"})

        # 按涨跌幅降序
        results.sort(key=lambda x: x["chg_pct"], reverse=True)
        top3    = results[:3]
        bottom3 = results[-3:][::-1]   # 跌最惨的3个，从大跌到小跌
        last_date = results[0]["date"] if results else ""

        return jsonify({
            "success":   True,
            "date":      last_date,
            "top3":      top3,
            "bottom3":   bottom3,
            "all":       results,
        })

    except Exception as e:
        import traceback as _tb
        return jsonify({"success": False, "error": str(e), "traceback": _tb.format_exc()})


@app.route("/api/recommend", methods=["GET"])
def recommend():
    """股票推荐接口（支持行业筛选，seed 参数可强制换一批）"""
    top_n = int(request.args.get("top_n", 10))
    top_n = max(5, min(top_n, 20))
    seed_raw = request.args.get("seed", None)
    seed = int(seed_raw) if seed_raw else None
    industry = request.args.get("industry", "").strip() or None
    # 传入全量股票缓存，供行业筛选时扩充候选池
    with _cache_lock:
        cache = _stock_cache[:]
    result = get_recommendations(
        top_n=top_n, seed=seed,
        industry_filter=industry,
        full_stock_cache=cache,
    )
    return jsonify(result)


@app.route("/api/recommend_stream", methods=["GET"])
def recommend_stream():
    """
    SSE 流式推荐接口
    每评完一只股票推送一条进度事件，最后推送完整结果。
    事件格式（text/event-stream）：
      data: {"type":"progress","step":"fetch","current":5,"total":100,"msg":"拉取行情 贵州茅台(600519)"}
      data: {"type":"done","result":{...}}
      data: {"type":"error","error":"..."}
    """
    import json as _json
    import queue as _queue

    top_n = int(request.args.get("top_n", 10))
    top_n = max(5, min(top_n, 20))
    seed_raw = request.args.get("seed", None)
    seed = int(seed_raw) if seed_raw else None
    industry = request.args.get("industry", "").strip() or None
    sample_size_raw = request.args.get("sample_size", None)
    sample_size = max(20, min(200, int(sample_size_raw))) if sample_size_raw else None

    with _cache_lock:
        cache = _stock_cache[:]

    q = _queue.Queue()

    def progress_cb(step, current, total, msg=""):
        q.put({"type": "progress", "step": step,
               "current": current, "total": total, "msg": msg})

    def worker():
        try:
            result = get_recommendations(
                top_n=top_n, seed=seed,
                industry_filter=industry,
                full_stock_cache=cache,
                progress_cb=progress_cb,
                sample_size=sample_size,
            )
            q.put({"type": "done", "result": result})
        except Exception as e:
            import traceback as _tb
            q.put({"type": "error", "error": str(e), "traceback": _tb.format_exc()})

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    def generate():
        while True:
            try:
                item = q.get(timeout=120)
            except _queue.Empty:
                yield "data: {\"type\":\"error\",\"error\":\"超时\"}\n\n"
                break
            yield f"data: {_json.dumps(item, ensure_ascii=False)}\n\n"
            if item.get("type") in ("done", "error"):
                break

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.route("/api/stock_pool", methods=["GET"])
def stock_pool():
    """获取候选股票池列表"""
    data = [{"symbol": s, "name": n} for s, n in STOCK_POOL]
    return jsonify({"success": True, "data": data})


# ─────────────────────────────────────────
# 推荐历史记录（本地 JSON 持久化）
# ─────────────────────────────────────────

import json as _json_mod
import uuid as _uuid

_REC_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "../data/rec_history.json")

def _load_rec_history() -> list:
    """从本地 JSON 文件读取历史记录"""
    try:
        if os.path.exists(_REC_HISTORY_FILE):
            with open(_REC_HISTORY_FILE, "r", encoding="utf-8") as f:
                return _json_mod.load(f)
    except Exception:
        pass
    return []

def _save_rec_history(records: list):
    """将历史记录写入本地 JSON 文件"""
    os.makedirs(os.path.dirname(_REC_HISTORY_FILE), exist_ok=True)
    with open(_REC_HISTORY_FILE, "w", encoding="utf-8") as f:
        _json_mod.dump(records, f, ensure_ascii=False, indent=2)


@app.route("/api/rec_history", methods=["GET"])
def get_rec_history():
    """读取所有推荐历史记录（按时间倒序）"""
    records = _load_rec_history()
    records_sorted = sorted(records, key=lambda r: r.get("saved_at", ""), reverse=True)
    return jsonify({"success": True, "data": records_sorted, "total": len(records_sorted)})


@app.route("/api/rec_history", methods=["POST"])
def save_rec_history():
    """保存一条推荐记录"""
    payload = request.get_json()
    if not payload:
        return jsonify({"success": False, "error": "参数为空"})
    records = _load_rec_history()
    record = {
        "id":         str(_uuid.uuid4())[:8],
        "saved_at":   payload.get("saved_at", ""),
        "top_n":      payload.get("top_n", 10),
        "total_scanned": payload.get("total_scanned", 0),
        "index_return_20d": payload.get("index_return_20d", 0),
        "algo_note":  payload.get("algo_note", ""),
        "results":    payload.get("results", []),
        "industry_dist": payload.get("industry_dist", {}),
    }
    records.append(record)
    # 最多保留 100 条，超出时删除最旧的
    if len(records) > 100:
        records = sorted(records, key=lambda r: r.get("saved_at", ""), reverse=True)[:100]
    _save_rec_history(records)
    return jsonify({"success": True, "id": record["id"]})


@app.route("/api/rec_history/<record_id>", methods=["DELETE"])
def delete_rec_history(record_id):
    """删除指定 id 的历史记录"""
    records = _load_rec_history()
    new_records = [r for r in records if r.get("id") != record_id]
    if len(new_records) == len(records):
        return jsonify({"success": False, "error": "记录不存在"})
    _save_rec_history(new_records)
    return jsonify({"success": True})


if __name__ == "__main__":
    print("🚀 量化平台启动中...")
    print("📊 访问地址: http://localhost:5001")
    app.run(host="0.0.0.0", port=5001, debug=False)
