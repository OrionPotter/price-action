#!/usr/bin/env python3
"""
价格行为分析 CLI 工具
基于 Al Brooks《Price Action》理论，对多市场 K 线数据进行专业分析。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
from dataclasses import dataclass
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
THS_MARKET_TZ = timezone(timedelta(hours=8))

EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
EASTMONEY_SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
EASTMONEY_SEARCH_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

_FUYAO_AUTH_TOKEN: Optional[str] = None
_FUYAO_AUTH_EXPIRY: Optional[datetime] = None

EMA_WARMUP = 40
FETCH_WINDOW = 400

PERIOD_MAP = {
    "daily": "day_1",
    "weekly": "week_1",
    "monthly": "month_1",
}
EASTMONEY_KLT_MAP = {
    "daily": "101",
    "weekly": "102",
    "monthly": "103",
}
TENCENT_PERIOD_MAP = {
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
}
VALID_PERIODS = tuple(PERIOD_MAP.keys())
VALID_MARKETS = ("auto", "cn", "hk", "us")
VALID_SOURCES = ("auto", "ths", "tencent", "eastmoney")


@dataclass(frozen=True)
class SecurityIdentity:
    code: str
    market: str


@dataclass
class FetchResult:
    df: pd.DataFrame
    name: str
    source: str
    market: str
    secid: Optional[str] = None


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
    client = requests.Session()
    client.headers.update(
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
        client.headers["cookie"] = cookie

    retry = Retry(
        total=3,
        backoff_factor=0.8,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    client.mount("http://", adapter)
    client.mount("https://", adapter)
    return client


session = build_session()

eastmoney_session = requests.Session()
eastmoney_session.trust_env = False

tencent_session = requests.Session()
tencent_session.trust_env = False


# -------------------------
# 代码与市场解析
# -------------------------
def normalize_market_hint(market: str) -> str:
    market = market.strip().lower()
    if market not in VALID_MARKETS:
        raise ValueError(f"不支持的市场: {market}")
    return market


def strip_known_prefix(code: str) -> tuple[str, Optional[str]]:
    code = code.strip()
    lowered = code.lower()
    prefix_map = {
        "sh": "cn",
        "sz": "cn",
        "bj": "cn",
        "cn": "cn",
        "hk": "hk",
        "us": "us",
    }
    for prefix, market in prefix_map.items():
        if lowered.startswith(prefix):
            return code[len(prefix) :], market
    return code, None


def infer_market_from_code(code: str) -> str:
    if code.isdigit():
        if len(code) == 5:
            return "hk"
        if len(code) == 6:
            return "cn"
    return "us"


def parse_security_identity(code: str, market_hint: str = "auto") -> SecurityIdentity:
    stripped_code, prefix_market = strip_known_prefix(code)
    market = normalize_market_hint(market_hint)
    if market == "auto":
        market = prefix_market or infer_market_from_code(stripped_code)

    normalized_code = stripped_code.strip().upper() if market == "us" else stripped_code.strip()
    if market == "hk" and normalized_code.isdigit():
        normalized_code = normalized_code.zfill(5)
    return SecurityIdentity(code=normalized_code, market=market)


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


def build_eastmoney_secid_candidates(identity: SecurityIdentity) -> list[str]:
    if identity.market == "cn":
        return [f"{get_eastmoney_market_code(identity.code)}.{identity.code}"]
    if identity.market == "hk":
        return [f"116.{identity.code.zfill(5)}"]
    if identity.market == "us":
        return [f"105.{identity.code.upper()}", f"106.{identity.code.upper()}"]
    raise ValueError(f"不支持的市场: {identity.market}")


def get_limit_threshold(code: str, stock_name: str, market: str) -> Optional[float]:
    if market != "cn":
        return None
    if "ST" in stock_name.upper():
        return 4.8
    if code.startswith(("688", "300")):
        return 19.8
    return 9.8


def build_tencent_symbol_candidates(identity: SecurityIdentity) -> list[str]:
    if identity.market == "cn":
        if identity.code.startswith("6"):
            return [f"sh{identity.code}"]
        if identity.code.startswith(("4", "8", "9")):
            return [f"bj{identity.code}"]
        return [f"sz{identity.code}"]
    if identity.market == "hk":
        return [f"hk{identity.code.zfill(5)}"]
    if identity.market == "us":
        return [f"us{identity.code}", f"us{identity.code}.OQ", f"us{identity.code}.N"]
    raise ValueError(f"不支持的市场: {identity.market}")


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
# 东财数据源
# -------------------------
def search_eastmoney_quote_ids(identity: SecurityIdentity) -> list[str]:
    params = {
        "input": identity.code,
        "type": "14",
        "token": EASTMONEY_SEARCH_TOKEN,
    }
    headers = {"user-agent": THS_USER_AGENT}
    response = eastmoney_session.get(EASTMONEY_SEARCH_URL, params=params, headers=headers, timeout=15)
    response.raise_for_status()
    data = (((response.json() or {}).get("QuotationCodeTable") or {}).get("Data")) or []

    expected_code = identity.code.upper() if identity.market == "us" else identity.code
    market_to_mktnum = {"hk": "116", "us": {"105", "106"}}
    quote_ids: list[str] = []
    for item in data:
        quote_id = str(item.get("QuoteID") or "").strip()
        item_code = str(item.get("Code") or "").strip().upper()
        unified_code = str(item.get("UnifiedCode") or "").strip().upper()
        if item_code != expected_code.upper() and unified_code != expected_code.upper():
            continue

        if identity.market == "hk" and str(item.get("MktNum")) != market_to_mktnum["hk"]:
            continue
        if identity.market == "us" and str(item.get("MktNum")) not in market_to_mktnum["us"]:
            continue

        if quote_id and quote_id not in quote_ids:
            quote_ids.append(quote_id)
    return quote_ids


def parse_eastmoney_klines(klines: list[str]) -> pd.DataFrame:
    rows = []
    for item in klines:
        parts = item.split(",")
        if len(parts) < 11:
            continue
        rows.append(
            {
                "date": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]),
                "turnover": float(parts[10]),
            }
        )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def fetch_stock_name_from_eastmoney(identity: SecurityIdentity) -> str:
    secid_candidates = build_eastmoney_secid_candidates(identity)
    if identity.market in {"hk", "us"}:
        try:
            resolved = search_eastmoney_quote_ids(identity)
            if resolved:
                secid_candidates = resolved
        except Exception:
            pass

    for secid in secid_candidates:
        try:
            params = {
                "fltt": "2",
                "invt": "2",
                "fields": "f57,f58",
                "secid": secid,
            }
            response = eastmoney_session.get(EASTMONEY_QUOTE_URL, params=params, timeout=10)
            data_json = response.json()
            if data_json and data_json.get("data"):
                return data_json["data"].get("f58", identity.code)
        except Exception:
            continue
    return identity.code


# -------------------------
# 腾讯数据源
# -------------------------
def extract_tencent_kline_rows(data: dict) -> list[list]:
    for key in ("qfqday", "qfqweek", "qfqmonth", "day", "week", "month"):
        rows = data.get(key)
        if rows:
            return rows
    return []


def parse_tencent_klines(rows: list[list]) -> pd.DataFrame:
    parsed_rows = []
    for row in rows:
        if len(row) < 6:
            continue
        parsed_rows.append(
            {
                "date": str(row[0]),
                "open": float(row[1]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "volume": float(row[5]),
                "amount": 0.0,
                "turnover": 0.0,
            }
        )
    if not parsed_rows:
        return pd.DataFrame()
    return pd.DataFrame(parsed_rows)


def fetch_tencent_payload(symbol: str, period: str, count: int) -> dict:
    response = tencent_session.get(
        TENCENT_KLINE_URL,
        params={"param": f"{symbol},{TENCENT_PERIOD_MAP[period]},,,{count},qfq"},
        headers={"user-agent": THS_USER_AGENT, "referer": "https://gu.qq.com/"},
        timeout=20,
    )
    response.raise_for_status()
    data_json = response.json()
    return ((data_json.get("data") or {}).get(symbol)) or {}


def fetch_kline_raw_tencent(identity: SecurityIdentity, period: str, count: int) -> FetchResult:
    last_error: Optional[Exception] = None
    requested_count = max(count, 60)
    for symbol in build_tencent_symbol_candidates(identity):
        try:
            payload = fetch_tencent_payload(symbol, period, requested_count)
            rows = extract_tencent_kline_rows(payload)

            # 腾讯美股简写有时只给极少量点位，优先回退到带交易所后缀的正式代码。
            if identity.market == "us" and len(rows) < min(10, requested_count):
                qt = payload.get("qt") or {}
                quote_row = qt.get(symbol) or []
                full_symbol = quote_row[2] if len(quote_row) > 2 else ""
                if full_symbol:
                    normalized_full_symbol = full_symbol if full_symbol.startswith("us") else f"us{full_symbol}"
                    if normalized_full_symbol != symbol:
                        payload = fetch_tencent_payload(normalized_full_symbol, period, requested_count)
                        rows = extract_tencent_kline_rows(payload)
                        symbol = normalized_full_symbol

            if not rows:
                continue

            df = parse_tencent_klines(rows)
            if df.empty:
                continue

            qt = payload.get("qt") or {}
            quote_row = qt.get(symbol) or []
            name = quote_row[1] if len(quote_row) > 1 else identity.code
            if identity.market in {"hk", "us"}:
                name = fetch_stock_name_from_eastmoney(identity) or name
            return FetchResult(df=df, name=name, source="tencent", market=identity.market, secid=symbol)
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"腾讯未返回 {identity.code} 的 {identity.market} 市场 K 线数据")


def fetch_kline_raw_eastmoney(identity: SecurityIdentity, period: str) -> FetchResult:
    quote_ids = []
    if identity.market in {"hk", "us"}:
        try:
            quote_ids.extend(search_eastmoney_quote_ids(identity))
        except Exception:
            pass

    for secid in build_eastmoney_secid_candidates(identity):
        if secid not in quote_ids:
            quote_ids.append(secid)

    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": EASTMONEY_KLT_MAP[period],
        "fqt": "1",
        "end": "20500101",
        "lmt": str(FETCH_WINDOW),
    }

    last_error: Optional[Exception] = None
    for secid in quote_ids:
        try:
            response = eastmoney_session.get(
                EASTMONEY_KLINE_URL,
                params={**params, "secid": secid},
                headers={"user-agent": THS_USER_AGENT, "referer": "https://quote.eastmoney.com/"},
                timeout=20,
            )
            response.raise_for_status()
            data_json = response.json()
            data = data_json.get("data") or {}
            klines = data.get("klines") or []
            if not klines:
                continue

            df = parse_eastmoney_klines(klines)
            if df.empty:
                continue

            return FetchResult(
                df=df,
                name=str(data.get("name") or identity.code),
                source="eastmoney",
                market=identity.market,
                secid=secid,
            )
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"东财未返回 {identity.code} 的 {identity.market} 市场 K 线数据")


# -------------------------
# 同花顺数据源
# -------------------------
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
                # 同花顺时间戳按中国市场时区解释，避免格式化时回退一天。
                "date": datetime.fromtimestamp(int(ts) / 1000, tz=THS_MARKET_TZ).strftime("%Y-%m-%d"),
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


def fetch_kline_raw_ths(code: str, period: str, market_override: Optional[str] = None) -> pd.DataFrame:
    market_code = market_override or infer_ths_market_code(code)
    payload = {
        "code_list": [{"codes": [code], "market": market_code}],
        "trade_class": "intraday",
        "time_period": PERIOD_MAP[period],
        "trade_date": -1,
        "begin_time": -FETCH_WINDOW,
        "end_time": 0,
        "adjust_type": "forward",
        "gpid": 1,
    }

    refresh_ths_auth_headers()

    data_json = None
    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            response = session.post(THS_KLINE_URL, json=payload, timeout=20)
            if response.status_code in (401, 403):
                raise RuntimeError(f"THS API HTTP {response.status_code}")
            data_json = response.json()
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
        raise RuntimeError(f"同花顺未返回 {code} 的 K 线数据")

    quote_data = (((data_json.get("data") or {}).get("quote_data")) or [])
    if not quote_data:
        raise RuntimeError(f"同花顺未返回 {code} 的 quote_data")

    df = derive_dataframe_from_quote(quote_data[0])
    if df is None or df.empty:
        raise RuntimeError(f"同花顺未返回 {code} 的有效 K 线数据")
    return df


def fetch_kline_via_ths(identity: SecurityIdentity, period: str, market_override: Optional[str] = None) -> FetchResult:
    if identity.market != "cn":
        raise ValueError("同花顺数据源当前仅用于 A 股")
    df = fetch_kline_raw_ths(identity.code, period, market_override)
    return FetchResult(
        df=df,
        name=fetch_stock_name_from_eastmoney(identity),
        source="ths",
        market=identity.market,
    )


def choose_sources(market: str, source: str) -> list[str]:
    if source not in VALID_SOURCES:
        raise ValueError(f"不支持的数据源: {source}")
    if source == "ths":
        if market != "cn":
            raise ValueError("同花顺数据源仅支持 A 股")
        return ["ths"]
    if source == "tencent":
        return ["tencent"]
    if source == "eastmoney":
        return ["eastmoney"]
    if market == "cn":
        return ["ths", "tencent", "eastmoney"]
    return ["tencent", "eastmoney"]


def fetch_market_data(
    identity: SecurityIdentity,
    period: str,
    count: int,
    source: str = "auto",
    market_override: Optional[str] = None,
) -> FetchResult:
    last_error: Optional[Exception] = None
    for candidate in choose_sources(identity.market, source):
        try:
            if candidate == "ths":
                return fetch_kline_via_ths(identity, period, market_override)
            if candidate == "tencent":
                return fetch_kline_raw_tencent(identity, period, count)
            return fetch_kline_raw_eastmoney(identity, period)
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"无法获取 {identity.code} 的市场数据")


# -------------------------
# 统一数据输出
# -------------------------
def fetch_kline_data(
    code: str,
    count: int = 60,
    period: str = "daily",
    market: str = "auto",
    source: str = "auto",
    market_override: Optional[str] = None,
) -> Optional[dict]:
    identity = parse_security_identity(code, market)

    try:
        result = fetch_market_data(
            identity,
            period=period,
            count=max(count + EMA_WARMUP, FETCH_WINDOW),
            source=source,
            market_override=market_override,
        )
        df = result.df.copy()
        if df.empty:
            return None

        open_safe = df["open"].replace(0, float("nan"))
        close_safe = df["close"].replace(0, float("nan"))
        if "turnover" not in df:
            df["turnover"] = 0.0

        df["change_pct"] = (((df["close"] - df["open"]) / open_safe) * 100).round(2).fillna(0)
        df["amplitude"] = (((df["high"] - df["low"]) / close_safe) * 100).round(2).fillna(0)
        df["ema20"] = compute_ema(df["close"], span=20).round(2)
        df["ema20_slope"] = (df["ema20"].pct_change() * 100).round(3).fillna(0)
        ema_safe = df["ema20"].replace(0, float("nan"))
        df["ema20_distance"] = (((df["close"] - df["ema20"]) / ema_safe) * 100).round(2).fillna(0)

        df = compute_bar_metrics(df)
        df["bar_type"] = classify_bar_type(df)
        df["gap"] = detect_gaps(df)

        if len(df) > count:
            df = df.tail(count).reset_index(drop=True)

        limit_threshold = get_limit_threshold(identity.code, result.name, result.market)

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

            if limit_threshold is not None:
                change_pct = float(row.get("change_pct", 0))
                if change_pct >= limit_threshold:
                    bar["limit"] = "limit_up"
                elif change_pct <= -limit_threshold:
                    bar["limit"] = "limit_down"

            klines.append(bar)

        return {
            "code": identity.code,
            "name": result.name,
            "market": result.market,
            "source": result.source,
            "period": period,
            "count": len(klines),
            "klines": klines,
        }
    except Exception as exc:
        click.echo(f"获取数据失败: {exc}", err=True)
        return None


def fetch_stock_info(code: str, market: str = "auto") -> dict:
    identity = parse_security_identity(code, market)
    name = fetch_stock_name_from_eastmoney(identity)
    secids = build_eastmoney_secid_candidates(identity)
    if identity.market in {"hk", "us"}:
        try:
            resolved_secids = search_eastmoney_quote_ids(identity)
            if resolved_secids:
                secids = resolved_secids
        except Exception:
            pass

    return {
        "code": identity.code,
        "name": name,
        "market": identity.market,
        "secid": secids[0] if secids else None,
    }


# -------------------------
# CLI 入口
# -------------------------
@click.group()
def cli():
    """价格行为分析工具 - 支持 A 股、港股、美股的 K 线分析。"""
    pass


@cli.command("kline")
@click.argument("code")
@click.option("--count", "-n", default=60, help="K线数量 (20-250)，默认 60")
@click.option(
    "--period",
    "-p",
    type=click.Choice(VALID_PERIODS),
    default="daily",
    help="周期: daily/weekly/monthly，默认 daily",
)
@click.option(
    "--market-type",
    type=click.Choice(VALID_MARKETS),
    default="auto",
    help="市场类型: auto/cn/hk/us，默认 auto",
)
@click.option(
    "--source",
    type=click.Choice(VALID_SOURCES),
    default="auto",
    help="数据源: auto/ths/eastmoney，默认 auto",
)
@click.option("--market", "-m", "market_override", help="手动指定同花顺 market 编号，仅 A 股 + ths 有效")
@click.option("--compact", "-c", is_flag=True, help="紧凑输出（无缩进）")
def kline_cmd(
    code: str,
    count: int,
    period: str,
    market_type: str,
    source: str,
    market_override: Optional[str],
    compact: bool,
):
    """获取 K 线数据。

    CODE: 支持 600000、00700、MSFT，也支持 sh/sz/bj/hk/us 前缀。
    """
    count = max(20, min(count, 250))
    data = fetch_kline_data(
        code,
        count=count,
        period=period,
        market=market_type,
        source=source,
        market_override=market_override,
    )

    if data:
        indent = None if compact else 2
        click.echo(json.dumps(data, ensure_ascii=False, indent=indent))
    else:
        click.echo(f"无法获取 {code} 的 K 线数据", err=True)
        raise SystemExit(1)


@cli.command("info")
@click.argument("code")
@click.option(
    "--market-type",
    type=click.Choice(VALID_MARKETS),
    default="auto",
    help="市场类型: auto/cn/hk/us，默认 auto",
)
def info_cmd(code: str, market_type: str):
    """获取证券基本信息。"""
    click.echo(json.dumps(fetch_stock_info(code, market=market_type), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cli()
