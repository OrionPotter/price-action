#!/usr/bin/env python3
"""
获取A股K线数据脚本
使用东方财富源获取指定股票的K线数据，计算技术指标，输出JSON格式供AI分析使用

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
import os
import sys
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# -------------------------
# 创建 Session（全局单例）
# -------------------------
session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Connection": "close"
})

retry = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504]
)

adapter = HTTPAdapter(max_retries=retry)

session.mount("http://", adapter)
session.mount("https://", adapter)

# 访问首页生成 Cookie
try:
    session.get("https://quote.eastmoney.com/", timeout=10)
except Exception:
    pass  # 网络问题时不阻止后续执行


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


def get_market_code(code: str) -> int:
    """
    根据股票代码返回市场代码

    Args:
        code: 纯6位数字代码

    Returns:
        市场代码: 1(沪市) 或 0(深市)
    """
    return 1 if code.startswith('6') else 0


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
    df['bar_range'] = df['high'] - df['low']
    df['body'] = (df['close'] - df['open']).abs()

    safe_range = df['bar_range'].replace(0, float('nan'))
    df['body_ratio'] = (df['body'] / safe_range).round(2).fillna(0)

    df['upper_wick'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['lower_wick'] = df[['open', 'close']].min(axis=1) - df['low']
    df['upper_wick_ratio'] = (df['upper_wick'] / safe_range).round(2).fillna(0)
    df['lower_wick_ratio'] = (df['lower_wick'] / safe_range).round(2).fillna(0)

    df['close_position'] = ((df['close'] - df['low']) / safe_range).round(2).fillna(0.5)

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

    prev_high = df['high'].shift(1)
    prev_low = df['low'].shift(1)

    is_bull = df['close'] > df['open']
    is_bear = df['close'] < df['open']

    # 按优先级从低到高赋值（高优先级后覆盖）
    types[df['body_ratio'] < 0.1] = 'doji'
    types[(df['upper_wick'] > df['body']) & (df['close_position'] < 0.6)] = 'signal_bear'
    types[(df['lower_wick'] > df['body']) & (df['close_position'] > 0.4)] = 'signal_bull'
    types[is_bear & (df['body_ratio'] >= 0.6) & (df['close_position'] <= 0.5)] = 'trend_bear'
    types[is_bull & (df['body_ratio'] >= 0.6) & (df['close_position'] >= 0.5)] = 'trend_bull'
    types[(df['high'] < prev_high) & (df['low'] > prev_low)] = 'inside_bar'
    types[(df['high'] > prev_high) & (df['low'] < prev_low)] = 'outside_bar'

    return types


def detect_gaps(df: pd.DataFrame) -> pd.Series:
    """
    检测跳空缺口

    Returns:
        Series: 'gap_up' / 'gap_down' / None
    """
    prev_high = df['high'].shift(1)
    prev_low = df['low'].shift(1)

    gaps = pd.Series(None, index=df.index, dtype=object)
    gaps[df['low'] > prev_high] = 'gap_up'
    gaps[df['high'] < prev_low] = 'gap_down'

    return gaps


def compute_ema(series: pd.Series, span: int = 20) -> pd.Series:
    """计算指数移动平均线"""
    return series.ewm(span=span, adjust=False).mean()


def fetch_stock_name(code: str) -> str:
    """获取股票名称，失败时返回代码本身"""
    try:
        market_code = get_market_code(code)
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "fltt": "2",
            "invt": "2",
            "fields": "f57,f58",
            "secid": f"{market_code}.{code}",
        }
        r = session.get(url, params=params, timeout=10)
        data_json = r.json()
        
        if data_json and "data" in data_json and data_json["data"]:
            return data_json["data"].get("f58", code)
    except Exception:
        pass
    return code


def fetch_kline_raw(code: str, period: str = "daily", count: int = 100) -> Optional[pd.DataFrame]:
    """
    获取原始K线数据

    Args:
        code: 纯6位数字代码
        period: 周期 daily/weekly/monthly
        count: K线数量

    Returns:
        DataFrame 或 None
    """
    market_code = get_market_code(code)
    period_dict = {"daily": "101", "weekly": "102", "monthly": "103"}
    
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": f"{market_code}.{code}",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "klt": period_dict.get(period, "101"),
        "fqt": "1",  # 前复权
        "beg": "19700101",
        "end": datetime.now().strftime("%Y%m%d"),
        "lmt": count,
    }
    
    r = session.get(url, params=params, timeout=15)
    data_json = r.json()
    
    if not (data_json.get("data") and data_json["data"].get("klines")):
        return None
    
    rows = []
    for line in data_json["data"]["klines"]:
        arr = line.split(",")
        rows.append({
            "date": arr[0],
            "open": float(arr[1]),
            "close": float(arr[2]),
            "high": float(arr[3]),
            "low": float(arr[4]),
            "volume": float(arr[5]),
            "amount": float(arr[6]),
            "amplitude": float(arr[7]),
            "change_pct": float(arr[8]),
            "change": float(arr[9]),
            "turnover": float(arr[10]),
        })
    
    df = pd.DataFrame(rows)
    return df


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

    try:
        df = fetch_kline_raw(raw_code, period, fetch_count)

        if df is None or df.empty:
            return None

        # 计算 EMA20（在裁剪前，用全部数据计算以保证预热充分）
        df['ema20'] = compute_ema(df['close'], span=20).round(2)
        df['ema20_slope'] = (df['ema20'].pct_change() * 100).round(3).fillna(0)
        ema_safe = df['ema20'].replace(0, float('nan'))
        df['ema20_distance'] = (((df['close'] - df['ema20']) / ema_safe) * 100).round(2).fillna(0)

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
                "date": str(row['date']),
                "open": round(float(row['open']), 2),
                "high": round(float(row['high']), 2),
                "low": round(float(row['low']), 2),
                "close": round(float(row['close']), 2),
                "volume": round(float(row.get('volume', 0))),
                "amount": round(float(row.get('amount', 0)), 2),
                "change_pct": round(float(row.get('change_pct', 0)), 2),
                "turnover": round(float(row.get('turnover', 0)), 2),
                "amplitude": round(float(row.get('amplitude', 0)), 2),
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
            change_pct = float(row.get('change_pct', 0))
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