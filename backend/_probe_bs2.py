"""测试批量查行业分类的速度"""
import baostock as bs
import time

lg = bs.login()

# 拉沪深300+中证500
all_codes = set()
for fn in [bs.query_hs300_stocks, bs.query_zz500_stocks]:
    rs = fn()
    while rs.error_code == "0" and rs.next():
        row = rs.get_row_data()
        all_codes.add(row[1])  # row[1] = code like "sh.600036"

print(f"合并去重后: {len(all_codes)} 只")

# 测试批量查行业分类速度（只查前50只）
sample = list(all_codes)[:50]
t0 = time.time()
results = {}
for code in sample:
    rs = bs.query_stock_industry(code=code)
    while rs.error_code == "0" and rs.next():
        row = rs.get_row_data()
        results[code] = row[3]  # industry字段
t1 = time.time()
print(f"查50只行业分类耗时: {t1-t0:.1f}s，预计全量{len(all_codes)}只需: {(t1-t0)/50*len(all_codes):.0f}s")
print("示例:", list(results.items())[:5])

bs.logout()
