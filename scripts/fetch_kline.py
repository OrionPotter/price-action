#!/usr/bin/env python3
"""
获取A股K线数据脚本
使用 akshare（东方财富源）获取指定股票的K线数据，计算技术指标，输出JSON格式供AI分析使用

用法:
    python fetch_kline.py <股票代码> [K线数量] [周期]

参数:
    股票代码: 6位数字或带前缀，如 600000、sh600000、sz000001
    K线数量: 20-250，默认60
    周期:    daily(日K，默认) / weekly(周K) / monthly(月K)

示例:
    python fetch_kline.py 600000              # 日K 60根
    python fetch_kline.py 600000 120          # 日K 120根
    python fetch_kline.py 600000 60 weekly    # 周K 60根
    python fetch_kline.py 000021 80 monthly   # 月K 80根
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta
from typing import Optional

# 清除代理设置（在 import 其他库之前执行）
for proxy_var in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
    os.environ.pop(proxy_var, None)
# 设置 NO_PROXY 绕过所有代理
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'


try:
    import akshare as ak
    import pandas as pd
    # 禁用 requests 的系统代理检测
    import requests.utils
    requests.utils.getproxies = lambda: {}
except ImportError:
    print("错误: 请先安装依赖: pip install akshare pandas", file=sys.stderr)
    sys.exit(1)


# EMA 预热所需的额外K线数量
EMA_WARMUP = 40


def strip_prefix(code: str) -> str:
    """
    去除股票代码前缀，返回纯6位数字代码

    Args:
        code: 股票代码，如 'sh600000', 'sz000001', '600000'

    Returns:
        纯数字代码，如 '600000'
    """
    for prefix in ('sh', 'sz', 'bj'):
        if code.lower().startswith(prefix):
            return code[len(prefix):]
    return code


def get_limit_threshold(code: str, stock_name: str) -> float:
    """
    根据板块和股票类型返回涨跌停阈值百分比

    Args:
        code: 纯6位数字代码
        stock_name: 股票名称

    Returns:
        涨跌停阈值（如 9.8、19.8、4.8）
    """
    if 'ST' in stock_name.upper():
        return 4.8
    if code.startswith('688') or code.startswith('300'):
        return 19.8
    return 9.8


def compute_bar_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算每根K线的结构指标

    新增列: bar_range, body, body_ratio, upper_wick, lower_wick,
            upper_wick_ratio, lower_wick_ratio, close_position
    """
    df = df.copy()
    df['bar_range'] = df['最高'] - df['最低']
    df['body'] = (df['收盘'] - df['开盘']).abs()

    safe_range = df['bar_range'].replace(0, float('nan'))
    df['body_ratio'] = (df['body'] / safe_range).round(2).fillna(0)

    df['upper_wick'] = df['最高'] - df[['开盘', '收盘']].max(axis=1)
    df['lower_wick'] = df[['开盘', '收盘']].min(axis=1) - df['最低']
    df['upper_wick_ratio'] = (df['upper_wick'] / safe_range).round(2).fillna(0)
    df['lower_wick_ratio'] = (df['lower_wick'] / safe_range).round(2).fillna(0)

    df['close_position'] = ((df['收盘'] - df['最低']) / safe_range).round(2).fillna(0.5)

    return df


def classify_bar_type(df: pd.DataFrame) -> pd.Series:
    """
    根据K线结构分类每根K线的类型

    分类规则（优先级从高到低）:
      1. outside_bar: 高 > 前高 且 低 < 前低
      2. inside_bar:  高 < 前高 且 低 > 前低（严格）
      3. trend_bull:  阳线且 body_ratio >= 0.6 且 close_position >= 0.5
      4. trend_bear:  阴线且 body_ratio >= 0.6 且 close_position <= 0.5
      5. signal_bull: lower_wick > body 且 close_position > 0.4
      6. signal_bear: upper_wick > body 且 close_position < 0.6
      7. doji:        body_ratio < 0.1
      8. neutral:     其他
    """
    types = pd.Series('neutral', index=df.index)

    prev_high = df['最高'].shift(1)
    prev_low = df['最低'].shift(1)

    is_bull = df['收盘'] > df['开盘']
    is_bear = df['收盘'] < df['开盘']

    # 按优先级从低到高赋值（高优先级后覆盖）
    types[df['body_ratio'] < 0.1] = 'doji'
    types[(df['upper_wick'] > df['body']) & (df['close_position'] < 0.6)] = 'signal_bear'
    types[(df['lower_wick'] > df['body']) & (df['close_position'] > 0.4)] = 'signal_bull'
    types[is_bear & (df['body_ratio'] >= 0.6) & (df['close_position'] <= 0.5)] = 'trend_bear'
    types[is_bull & (df['body_ratio'] >= 0.6) & (df['close_position'] >= 0.5)] = 'trend_bull'
    types[(df['最高'] < prev_high) & (df['最低'] > prev_low)] = 'inside_bar'
    types[(df['最高'] > prev_high) & (df['最低'] < prev_low)] = 'outside_bar'

    return types


def detect_gaps(df: pd.DataFrame) -> pd.Series:
    """
    检测跳空缺口

    Returns:
        Series: 'gap_up' / 'gap_down' / None
    """
    prev_high = df['最高'].shift(1)
    prev_low = df['最低'].shift(1)

    gaps = pd.Series(None, index=df.index, dtype=object)
    gaps[df['最低'] > prev_high] = 'gap_up'
    gaps[df['最高'] < prev_low] = 'gap_down'

    return gaps


def compute_ema(series: pd.Series, span: int = 20) -> pd.Series:
    """计算指数移动平均线"""
    return series.ewm(span=span, adjust=False).mean()

def stock_individual_info_em(
    symbol: str = "603777", timeout: float = 30
) -> pd.DataFrame:
    """
    东方财富-个股-股票信息
    https://ok.orionpotter.icu/concept/sh603777.html?from=classic
    :param symbol: 股票代码
    :type symbol: str
    :param timeout: choice of None or a positive float number
    :type timeout: float
    :return: 股票信息
    :rtype: pandas.DataFrame
    """
    url = "https://ok.orionpotter.icu/api/qt/stock/get"
    market_code = 1 if symbol.startswith("6") else 0
    params = {
        "fltt": "2",
        "invt": "2",
        "fields": "f120,f121,f122,f174,f175,f59,f163,f43,f57,f58,f169,f170,f46,f44,f51,f168,f47,"
        "f164,f116,f60,f45,f52,f50,f48,f167,f117,f71,f161,f49,f530,f135,f136,f137,f138,"
        "f139,f141,f142,f144,f145,f147,f148,f140,f143,f146,f149,f55,f62,f162,f92,f173,f104,"
        "f105,f84,f85,f183,f184,f185,f186,f187,f188,f189,f190,f191,f192,f107,f111,f86,f177,f78,"
        "f110,f262,f263,f264,f267,f268,f255,f256,f257,f258,f127,f199,f128,f198,f259,f260,f261,"
        "f171,f277,f278,f279,f288,f152,f250,f251,f252,f253,f254,f269,f270,f271,f272,f273,f274,"
        "f275,f276,f265,f266,f289,f290,f286,f285,f292,f293,f294,f295,f43",
        "secid": f"{market_code}.{symbol}",
    }
    r = requests.get(url, params=params, timeout=timeout)
    data_json = r.json()
    temp_df = pd.DataFrame(data_json)
    temp_df.reset_index(inplace=True)
    del temp_df["rc"]
    del temp_df["rt"]
    del temp_df["svr"]
    del temp_df["lt"]
    del temp_df["full"]
    code_name_map = {
        "f57": "股票代码",
        "f58": "股票简称",
        "f84": "总股本",
        "f85": "流通股",
        "f127": "行业",
        "f116": "总市值",
        "f117": "流通市值",
        "f189": "上市时间",
        "f43": "最新",
    }
    temp_df["index"] = temp_df["index"].map(code_name_map)
    temp_df = temp_df[pd.notna(temp_df["index"])]
    if "dlmkts" in temp_df.columns:
        del temp_df["dlmkts"]
    temp_df.columns = [
        "item",
        "value",
    ]
    temp_df.reset_index(inplace=True, drop=True)
    return temp_df

def fetch_stock_name(code: str) -> str:
    """获取股票名称，失败时返回代码本身"""
    try:
        stock_info = stock_individual_info_em(symbol=code)
        if stock_info is not None and not stock_info.empty:
            name_row = stock_info[stock_info['item'] == '股票简称']
            if not name_row.empty:
                return str(name_row['value'].values[0])
    except Exception:
        pass
    return code

def stock_zh_a_hist(
    symbol: str = "000001",
    period: str = "daily",
    start_date: str = "19700101",
    end_date: str = "20500101",
    adjust: str = "",
    timeout: float = 30,
) -> pd.DataFrame:
    """
    东方财富网-行情首页-沪深京 A 股-每日行情
    https://ok.orionpotter.icu/concept/sh603777.html?from=classic
    :param symbol: 股票代码
    :type symbol: str
    :param period: choice of {'daily', 'weekly', 'monthly'}
    :type period: str
    :param start_date: 开始日期
    :type start_date: str
    :param end_date: 结束日期
    :type end_date: str
    :param adjust: choice of {"qfq": "前复权", "hfq": "后复权", "": "不复权"}
    :type adjust: str
    :param timeout: choice of None or a positive float number
    :type timeout: float
    :return: 每日行情
    :rtype: pandas.DataFrame
    """
    market_code = 1 if symbol.startswith("6") else 0
    adjust_dict = {"qfq": "1", "hfq": "2", "": "0"}
    period_dict = {"daily": "101", "weekly": "102", "monthly": "103"}
    url = "https://ok.orionpotter.icu/api/qt/stock/kline/get"
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": period_dict[period],
        "fqt": adjust_dict[adjust],
        "secid": f"{market_code}.{symbol}",
        "beg": start_date,
        "end": end_date,
    }
    r = requests.get(url, params=params, timeout=timeout)
    data_json = r.json()
    if not (data_json["data"] and data_json["data"]["klines"]):
        return pd.DataFrame()
    temp_df = pd.DataFrame([item.split(",") for item in data_json["data"]["klines"]])
    temp_df["股票代码"] = symbol
    temp_df.columns = [
        "日期",
        "开盘",
        "收盘",
        "最高",
        "最低",
        "成交量",
        "成交额",
        "振幅",
        "涨跌幅",
        "涨跌额",
        "换手率",
        "股票代码",
    ]
    temp_df["日期"] = pd.to_datetime(temp_df["日期"], errors="coerce").dt.date
    temp_df["开盘"] = pd.to_numeric(temp_df["开盘"], errors="coerce")
    temp_df["收盘"] = pd.to_numeric(temp_df["收盘"], errors="coerce")
    temp_df["最高"] = pd.to_numeric(temp_df["最高"], errors="coerce")
    temp_df["最低"] = pd.to_numeric(temp_df["最低"], errors="coerce")
    temp_df["成交量"] = pd.to_numeric(temp_df["成交量"], errors="coerce")
    temp_df["成交额"] = pd.to_numeric(temp_df["成交额"], errors="coerce")
    temp_df["振幅"] = pd.to_numeric(temp_df["振幅"], errors="coerce")
    temp_df["涨跌幅"] = pd.to_numeric(temp_df["涨跌幅"], errors="coerce")
    temp_df["涨跌额"] = pd.to_numeric(temp_df["涨跌额"], errors="coerce")
    temp_df["换手率"] = pd.to_numeric(temp_df["换手率"], errors="coerce")
    temp_df = temp_df[
        [
            "日期",
            "股票代码",
            "开盘",
            "收盘",
            "最高",
            "最低",
            "成交量",
            "成交额",
            "振幅",
            "涨跌幅",
            "涨跌额",
            "换手率",
        ]
    ]
    return temp_df

def fetch_kline_data(code: str, count: int = 60, period: str = "daily") -> Optional[dict]:
    """
    获取K线数据并计算技术指标

    Args:
        code: 股票代码（支持带前缀或纯数字）
        count: 需要的K线数量
        period: 周期 daily/weekly/monthly

    Returns:
        包含K线数据和计算指标的字典，失败返回 None
    """

    raw_code = strip_prefix(code)

    # 多取 EMA_WARMUP 根用于 EMA 预热
    fetch_count = count + EMA_WARMUP
    days_multiplier = {'daily': 3, 'weekly': 10, 'monthly': 35}
    buffer_days = fetch_count * days_multiplier.get(period, 3)

    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=buffer_days)).strftime('%Y%m%d')

    try:
        df = stock_zh_a_hist(
            symbol=raw_code,
            period=period,
            start_date=start_date,
            end_date=end_date,
            adjust="qfq"
        )

        if df is None or df.empty:
            return None

        # stock_zh_a_hist 返回列: 日期,股票代码,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
        # 确保数值列为 float
        numeric_cols = ['开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        df = df.sort_values('日期').reset_index(drop=True)

        # 计算 EMA20（在裁剪前，用全部数据计算以保证预热充分）
        df['ema20'] = compute_ema(df['收盘'], span=20).round(2)
        df['ema20_slope'] = (df['ema20'].pct_change() * 100).round(3).fillna(0)
        ema_safe = df['ema20'].replace(0, float('nan'))
        df['ema20_distance'] = (((df['收盘'] - df['ema20']) / ema_safe) * 100).round(2).fillna(0)

        # 计算K线结构指标
        df = compute_bar_metrics(df)

        # 分类K线类型
        df['bar_type'] = classify_bar_type(df)

        # 检测缺口
        df['gap'] = detect_gaps(df)

        # 裁剪到用户请求的数量
        if len(df) > count:
            df = df.tail(count).reset_index(drop=True)

        # 获取股票名称
        stock_name = fetch_stock_name(raw_code)

        # 计算涨跌停阈值
        limit_threshold = get_limit_threshold(raw_code, stock_name)

        # 构建返回数据
        klines = []
        for _, row in df.iterrows():
            bar = {
                "date": str(row['日期']),
                "open": round(float(row['开盘']), 2),
                "high": round(float(row['最高']), 2),
                "low": round(float(row['最低']), 2),
                "close": round(float(row['收盘']), 2),
                "volume": round(float(row.get('成交量', 0))),
                "amount": round(float(row.get('成交额', 0)), 2),
                "change_pct": round(float(row.get('涨跌幅', 0)), 2),
                "turnover": round(float(row.get('换手率', 0)), 2),
                "amplitude": round(float(row.get('振幅', 0)), 2),
                "ema20": float(row['ema20']),
                "ema20_slope": float(row['ema20_slope']),
                "ema20_distance": float(row['ema20_distance']),
                "body_ratio": float(row['body_ratio']),
                "upper_wick_ratio": float(row['upper_wick_ratio']),
                "lower_wick_ratio": float(row['lower_wick_ratio']),
                "close_position": float(row['close_position']),
                "bar_type": row['bar_type'],
            }

            # 缺口（仅非空时输出）
            if pd.notna(row['gap']):
                bar["gap"] = row['gap']

            # 涨跌停标记
            change_pct = float(row.get('涨跌幅', 0))
            if change_pct >= limit_threshold:
                bar["limit"] = "limit_up"
            elif change_pct <= -limit_threshold:
                bar["limit"] = "limit_down"

            klines.append(bar)

        return {
            "code": raw_code,
            "name": stock_name,
            "period": period,
            "count": len(klines),
            "klines": klines
        }

    except Exception as e:
        print(f"获取数据失败: {str(e)}", file=sys.stderr)
        return None


def main():
    if len(sys.argv) < 2:
        print("用法: python fetch_kline.py <股票代码> [K线数量] [周期]")
        print("周期: daily(默认) / weekly / monthly")
        print()
        print("示例:")
        print("  python fetch_kline.py 600000              # 日K 60根")
        print("  python fetch_kline.py 600000 120          # 日K 120根")
        print("  python fetch_kline.py 600000 60 weekly    # 周K 60根")
        sys.exit(1)

    code = sys.argv[1]
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    period = sys.argv[3] if len(sys.argv) > 3 else "daily"

    # 验证周期参数
    valid_periods = ("daily", "weekly", "monthly")
    if period not in valid_periods:
        print(f"错误: 周期必须是 {'/'.join(valid_periods)}，当前值: {period}", file=sys.stderr)
        sys.exit(1)

    # 限制K线数量范围
    count = max(20, min(count, 250))

    data = fetch_kline_data(code, count, period)

    if data:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"无法获取 {code} 的K线数据", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
