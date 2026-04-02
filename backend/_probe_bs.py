"""探测 baostock 行业接口"""
import baostock as bs

lg = bs.login()
print("login:", lg.error_code, lg.error_msg)

# 1. 测试 query_stock_industry - 查单只股票行业
rs = bs.query_stock_industry(code="sh.600036")
print("\nquery_stock_industry fields:", rs.fields)
while rs.error_code == "0" and rs.next():
    print("  招商银行:", rs.get_row_data())

# 2. 测试 query_hs300_stocks - 沪深300成分股
rs2 = bs.query_hs300_stocks()
print("\nquery_hs300_stocks fields:", rs2.fields)
rows2 = []
while rs2.error_code == "0" and rs2.next():
    rows2.append(rs2.get_row_data())
print(f"  沪深300成分股数量: {len(rows2)}")
if rows2:
    print("  前3条:", rows2[:3])

# 3. 测试 query_zz500_stocks - 中证500成分股
rs3 = bs.query_zz500_stocks()
print("\nquery_zz500_stocks fields:", rs3.fields)
rows3 = []
while rs3.error_code == "0" and rs3.next():
    rows3.append(rs3.get_row_data())
print(f"  中证500成分股数量: {len(rows3)}")
if rows3:
    print("  前3条:", rows3[:3])

bs.logout()
print("\ndone")
