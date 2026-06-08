#!/usr/bin/env python3
"""
价格行为分析 CLI 工具
基于 Al Brooks《Price Action》理论，对A股K线数据进行专业分析。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import click
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# -------------------------
# 网络请求配置
# -------------------------
THS_KLINE_URL = "https://quota-h.10jqka.com.cn/fuyao/common_hq_aggr/quote/v1/single_kline"
THS_ACCESS_TOKEN_URL = "https://cbasspider.10jqka.com.cn:8443/spider/api/v1/access_token"
THS_ORIGIN = "https://stockpage.10jqka.com.cn"
THS_REFERER = "https://stockpage.10jqka.com.cn/"
THS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)
THS_APP_KEY = "2f33f4f729"
THS_APP_VERSION = "148.0.0.0"
THS_LOG_VERSION = "0.0.2"
THS_AUTH_REFRESH_MARGIN = timedelta(minutes=5)
MARKET_TZ = timezone(timedelta(hours=8))

_FUYAO_AUTH_TOKEN: Optional[str] = None
_FUYAO_AUTH_EXPIRY: Optional[datetime] = None

EMA_WARMUP = 40
FETCH_WINDOW = 400
PERIOD_MAP = {
    "daily": "day_1",
    "weekly": "week_1",
    "monthly": "month_1",
}
VALID_PERIODS = tuple(PERIOD_MAP.keys())


def _build_device_id() -> str:
    raw = "|".join(
        [
            socket.gethostname().strip().lower(),
            os.getenv("USERNAME") or os.getenv("USER") or "unknown",
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


def _decode_jwt_expiry(token: str) -> Optional[datetime]:
    parts = token.split(".")
    if len(parts) < 2:
        return None

    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload + padding).decode("utf-8")
        payload_json = json.loads(decoded)
    except Exception:
        return None

    exp = payload_json.get("exp")
    if exp is None:
        return None

    try:
        return datetime.fromtimestamp(float(exp), tz=timezone.utc)
    except Exception:
        return None


def _token_is_valid(expiry: Optional[datetime]) -> bool:
    if expiry is None:
        return False
    return expiry - THS_AUTH_REFRESH_MARGIN > datetime.now(timezone.utc)


def fetch_fuyao_auth(force_refresh: bool = False) -> str:
    global _FUYAO_AUTH_TOKEN, _FUYAO_AUTH_EXPIRY

    if not force_refresh and _FUYAO_AUTH_TOKEN and _token_is_valid(_FUYAO_AUTH_EXPIRY):
        return _FUYAO_AUTH_TOKEN

    payload = {
        "app_key": THS_APP_KEY,
        "app_version": THS_APP_VERSION,
        "device_id": _build_device_id(),
        "platform": "web",
        "platform_version": "x64",
        "log_version": THS_LOG_VERSION,
    }
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": THS_ORIGIN,
        "referer": THS_REFERER,
        "user-agent": THS_USER_AGENT,
    }

    env_token = (os.getenv("THS_FU_YAO_AUTH") or "").strip()
    try:
        response = requests.post(THS_ACCESS_TOKEN_URL, json=payload, headers=headers, timeout=15)
        response.raise_for_status()

        data_json = response.json()
        token = (((data_json.get("data") or {}).get("token")) or "").strip()
        if not token:
            raise RuntimeError(
                f"无法获取同花顺认证 token: code={data_json.get('code')}, msg={data_json.get('msg', '')}"
            )
    except Exception as exc:
        if not env_token:
            raise RuntimeError("无法自动获取同花顺认证 token，且未设置 THS_FU_YAO_AUTH") from exc
        token = env_token

    _FUYAO_AUTH_TOKEN = token
    _FUYAO_AUTH_EXPIRY = _decode_jwt_expiry(token)
    return token


def refresh_ths_auth_headers() -> None:
    session.headers["x-fuyao-auth"] = fetch_fuyao_auth()
    cookie = os.getenv("THS_COOKIE")
    if cookie:
        session.headers["cookie"] = cookie
    else:
        session.headers.pop("cookie", None)


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "accept": "*/*",
            "content-type": "application/json",
            "origin": THS_ORIGIN,
            "referer": THS_REFERER,
            "user-agent": THS_USER_AGENT,
            "platform": "hxkline",
            "source-id": "hxkline-NEWS_appNewsFlowHome_Page",
            "x-auth-appname": "AINVEST",
            "x-auth-progid": "7047",
            "x-auth-type": "ths",
            "x-auth-version": "1.0",
        }
    )

    cookie = os.getenv("THS_COOKIE")
    if cookie:
        session.headers["cookie"] = cookie

    retry = Retry(
        total=3,
        backoff_factor=0.8,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


session = build_session()


# -------------------------
# 工具函数
# -------------------------
def strip_prefix(code: str) -> str:
    code = code.strip()
    lowered = code.lower()
    for prefix in ("sh", "sz", "bj"):
        if lowered.startswith(prefix):
            return code[len(prefix):]
    return code


def infer_ths_market_code(code: str) -> str:
    if code.startswith("6"):
        return "17"
    if code.startswith(("0", "2", "3")):
        return "33"
    if code.startswith(("4", "8", "9")):
        return "32"
    return "33"


def get_eastmoney_market_code(code: str) -> int:
    return 1 if code.startswith("6") else 0


def get_limit_threshold(code: str, stock_name: str) -> float:
    if "ST" in stock_name.upper():
        return 4.8
    if code.startswith("688") or code.startswith("300"):
        return 19.8
    return 9.8


# -------------------------
# 技术指标计算
# -------------------------
def compute_ema(series: pd.Series, span: int = 20) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def compute_bar_metrics(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["bar_range"] = df["high"] - df["low"]
    df["body"] = (df["close"] - df["open"]).abs()

    safe_range = df["bar_range"].replace(0, float("nan"))
    df["body_ratio"] = (df["body"] / safe_range).round(2).fillna(0)
    df["upper_wick"] = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_wick"] = df[["open", "close"]].min(axis=1) - df["low"]
    df["upper_wick_ratio"] = (df["upper_wick"] / safe_range).round(2).fillna(0)
    df["lower_wick_ratio"] = (df["lower_wick"] / safe_range).round(2).fillna(0)
    df["close_position"] = ((df["close"] - df["low"]) / safe_range).round(2).fillna(0.5)
    return df


def classify_bar_type(df: pd.DataFrame) -> pd.Series:
    types = pd.Series("neutral", index=df.index, dtype=object)

    prev_high = df["high"].shift(1)
    prev_low = df["low"].shift(1)

    is_bull = df["close"] > df["open"]
    is_bear = df["close"] < df["open"]

    types[df["body_ratio"] < 0.1] = "doji"
    types[(df["upper_wick"] > df["body"]) & (df["close_position"] < 0.6)] = "signal_bear"
    types[(df["lower_wick"] > df["body"]) & (df["close_position"] > 0.4)] = "signal_bull"
    types[is_bear & (df["body_ratio"] >= 0.6) & (df["close_position"] <= 0.5)] = "trend_bear"
    types[is_bull & (df["body_ratio"] >= 0.6) & (df["close_position"] >= 0.5)] = "trend_bull"
    types[(df["high"] < prev_high) & (df["low"] > prev_low)] = "inside_bar"
    types[(df["high"] > prev_high) & (df["low"] < prev_low)] = "outside_bar"
    return types


def detect_gaps(df: pd.DataFrame) -> pd.Series:
    prev_high = df["high"].shift(1)
    prev_low = df["low"].shift(1)
    gaps = pd.Series(None, index=df.index, dtype=object)
    gaps[df["low"] > prev_high] = "gap_up"
    gaps[df["high"] < prev_low] = "gap_down"
    return gaps


# -------------------------
# 数据获取
# -------------------------
def fetch_stock_name(code: str) -> str:
    try:
        market_code = get_eastmoney_market_code(code)
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "fltt": "2",
            "invt": "2",
            "fields": "f57,f58",
            "secid": f"{market_code}.{code}",
        }
        r = requests.get(url, params=params, timeout=10)
        data_json = r.json()
        if data_json and data_json.get("data"):
            return data_json["data"].get("f58", code)
    except Exception:
        pass
    return code


def derive_dataframe_from_quote(quote_item: dict) -> Optional[pd.DataFrame]:
    data_fields = quote_item.get("data_fields") or []
    values = quote_item.get("value") or []
    if not values:
        return None

    rows = []
    for row in values:
        if len(row) < 7:
            continue
        field_map = {field: row[idx] for idx, field in enumerate(data_fields[: len(row)])}
        ts = field_map.get("1", row[0])
        rows.append(
            {
                # 行情时间戳按中国市场时区解释，避免 UTC 格式化导致日期回退一天。
                "date": datetime.fromtimestamp(int(ts) / 1000, tz=MARKET_TZ).strftime("%Y-%m-%d"),
                "open": float(field_map.get("7", row[1])),
                "high": float(field_map.get("8", row[2])),
                "low": float(field_map.get("9", row[3])),
                "close": float(field_map.get("11", row[4])),
                "volume": float(field_map.get("13", row[5])),
                "amount": float(field_map.get("19", row[6])),
            }
        )

    if not rows:
        return None
    return pd.DataFrame(rows)


def fetch_kline_raw(code: str, period: str, market_override: Optional[str] = None) -> Optional[pd.DataFrame]:
    market_code = market_override or infer_ths_market_code(code)
    payload = {
        "code_list": [{"codes": [code], "market": market_code}],
        "trade_class": "intraday",
        "time_period": PERIOD_MAP[period],
        "trade_date": -1,
        "begin_time": -FETCH_WINDOW,  # 请求更多数据
        "end_time": 0,
        "adjust_type": "forward",
        "gpid": 1,
    }

    refresh_ths_auth_headers()

    data_json = None
    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            r = session.post(THS_KLINE_URL, json=payload, timeout=20)
            if r.status_code in (401, 403):
                raise RuntimeError(f"THS API HTTP {r.status_code}")
            data_json = r.json()
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                refresh_ths_auth_headers()
                continue
            raise

        if data_json.get("status_code") == 0:
            break

        status_msg = str(data_json.get("status_msg", ""))
        auth_related = any(
            keyword in status_msg.lower()
            for keyword in ("auth", "token", "login", "cookie", "permission", "unauthorized", "forbidden", "expired")
        ) or any(keyword in status_msg for keyword in ("认证", "登录", "权限", "失效", "过期"))
        if attempt == 0 and auth_related:
            refresh_ths_auth_headers()
            continue

        raise RuntimeError(
            f"THS API returned status_code={data_json.get('status_code')}, "
            f"status_msg={data_json.get('status_msg', '')}"
        )

    if data_json is None:
        if last_error is not None:
            raise last_error
        return None

    quote_data = (((data_json.get("data") or {}).get("quote_data")) or [])
    if not quote_data:
        return None

    return derive_dataframe_from_quote(quote_data[0])


def fetch_kline_data(
    code: str,
    count: int = 60,
    period: str = "daily",
    market_override: Optional[str] = None,
) -> Optional[dict]:
    raw_code = strip_prefix(code)
    fetch_count = max(count + EMA_WARMUP, FETCH_WINDOW)

    try:
        df = fetch_kline_raw(raw_code, period, market_override)
        if df is None or df.empty:
            return None

        open_safe = df["open"].replace(0, float("nan"))
        close_safe = df["close"].replace(0, float("nan"))
        df["change_pct"] = (((df["close"] - df["open"]) / open_safe) * 100).round(2).fillna(0)
        df["amplitude"] = (((df["high"] - df["low"]) / close_safe) * 100).round(2).fillna(0)
        df["turnover"] = 0.0

        df["ema20"] = compute_ema(df["close"], span=20).round(2)
        df["ema20_slope"] = (df["ema20"].pct_change() * 100).round(3).fillna(0)
        ema_safe = df["ema20"].replace(0, float("nan"))
        df["ema20_distance"] = (((df["close"] - df["ema20"]) / ema_safe) * 100).round(2).fillna(0)

        df = compute_bar_metrics(df)
        df["bar_type"] = classify_bar_type(df)
        df["gap"] = detect_gaps(df)

        # 裁剪到用户请求的数量（在所有计算完成后）
        if len(df) > count:
            df = df.tail(count).reset_index(drop=True)

        stock_name = fetch_stock_name(raw_code)
        limit_threshold = get_limit_threshold(raw_code, stock_name)

        klines = []
        for _, row in df.iterrows():
            bar = {
                "date": str(row["date"]),
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
                "volume": round(float(row.get("volume", 0))),
                "amount": round(float(row.get("amount", 0)), 2),
                "change_pct": round(float(row.get("change_pct", 0)), 2),
                "turnover": round(float(row.get("turnover", 0)), 2),
                "amplitude": round(float(row.get("amplitude", 0)), 2),
                "ema20": float(row["ema20"]),
                "ema20_slope": float(row["ema20_slope"]),
                "ema20_distance": float(row["ema20_distance"]),
                "body_ratio": float(row["body_ratio"]),
                "upper_wick_ratio": float(row["upper_wick_ratio"]),
                "lower_wick_ratio": float(row["lower_wick_ratio"]),
                "close_position": float(row["close_position"]),
                "bar_type": row["bar_type"],
            }

            if pd.notna(row["gap"]):
                bar["gap"] = row["gap"]

            change_pct = float(row.get("change_pct", 0))
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
            "klines": klines,
        }
    except Exception as exc:
        click.echo(f"获取数据失败: {exc}", err=True)
        return None


# -------------------------
# CLI 入口
# -------------------------
@click.group()
def cli():
    """价格行为分析工具 - 基于 Al Brooks 理论的A股K线分析。

    支持获取A股K线数据、计算技术指标、识别K线形态。
    """
    pass


@cli.command("kline")
@click.argument("code")
@click.option("--count", "-n", default=60, help="K线数量 (20-250)，默认 60")
@click.option(
    "--period", "-p",
    type=click.Choice(VALID_PERIODS),
    default="daily",
    help="周期: daily/weekly/monthly，默认 daily",
)
@click.option("--market", "-m", "market_override", help="手动指定同花顺 market 编号")
@click.option("--compact", "-c", is_flag=True, help="紧凑输出（无缩进）")
def kline_cmd(code: str, count: int, period: str, market_override: Optional[str], compact: bool):
    """获取K线数据。

    CODE: 股票代码，支持 sh/sz/bj 前缀，如 600000、sh600000
    """
    count = max(20, min(count, 250))
    data = fetch_kline_data(code, count=count, period=period, market_override=market_override)

    if data:
        indent = None if compact else 2
        click.echo(json.dumps(data, ensure_ascii=False, indent=indent))
    else:
        click.echo(f"无法获取 {code} 的 K 线数据", err=True)
        raise SystemExit(1)


@cli.command("info")
@click.argument("code")
def info_cmd(code: str):
    """获取股票基本信息。

    CODE: 股票代码
    """
    raw_code = strip_prefix(code)
    name = fetch_stock_name(raw_code)
    market = infer_ths_market_code(raw_code)

    result = {
        "code": raw_code,
        "name": name,
        "market": market,
    }
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cli()
