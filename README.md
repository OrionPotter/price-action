# price-action

[🌐 简体中文](./README-cn.md) | **English**

An A-share, Hong Kong stock, and US stock candlestick retrieval and Price Action analysis tool, optimized for AI agent workflows.

---

## Introduction

`price-action` fetches K-line data from multiple public market data providers, calculates core technical indicators, and outputs structured JSON that is easy for agents to consume.

Default source routing:
- China A-shares: `ths -> tencent -> eastmoney`
- Hong Kong stocks: `tencent -> eastmoney`
- US stocks: `tencent -> eastmoney`

Core capabilities:
- Fetch daily, weekly, and monthly candles
- Auto-detect `cn` / `hk` / `us` symbols or force a market explicitly
- Compute `EMA20`, slope, and price distance from EMA
- Classify candlestick patterns such as `trend_bull`, `signal_bear`, `inside_bar`, and `outside_bar`
- Detect gap bars
- Mark limit up / limit down only for China A-shares

---

## Architecture

This project follows the `python-tool-skill` pattern and is designed to run through `uvx` without manual virtual environment setup.

```text
price-action/
├── SKILL.md              # Trigger descriptions + agent instructions
├── assets/
│   ├── price_action.py   # Click CLI entrypoint
│   ├── pyproject.toml    # Project metadata
│   └── uv.lock           # Locked dependencies
└── references/           # Price action reference material
```

---

## Getting Started

### Prerequisites

Install [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Commands

```bash
# Fetch K-line data, default: 60 daily bars
uvx --from ./assets pa kline <SYMBOL> [OPTIONS]

# Fetch security profile information
uvx --from ./assets pa info <SYMBOL>

# Help
uvx --from ./assets pa --help
uvx --from ./assets pa kline --help
```

### `kline` Options

| Option | Description |
| --- | --- |
| `CODE` | Symbol, supports `sh` / `sz` / `bj` / `hk` / `us` prefixes |
| `--count, -n` | Number of candles, range `20-250`, default `60` |
| `--period, -p` | `daily` / `weekly` / `monthly` |
| `--market-type` | `auto` / `cn` / `hk` / `us` |
| `--source` | `auto` / `ths` / `tencent` / `eastmoney` |
| `--market, -m` | Manual Flush market id override, only valid for `cn + ths` |
| `--compact, -c` | Compact JSON output |

### Examples

```bash
# China A-share
uvx --from ./assets pa kline 600000

# China A-share weekly candles
uvx --from ./assets pa kline 601919 -p weekly

# Hong Kong stock: Tencent
uvx --from ./assets pa kline 00700 --market-type hk

# Hong Kong stock: COSCO SHIPPING Holdings
uvx --from ./assets pa kline 01919 --market-type hk

# US stock: Apple
uvx --from ./assets pa kline AAPL --market-type us

# Force Tencent as the provider
uvx --from ./assets pa kline MSFT --market-type us --source tencent

# Security info
uvx --from ./assets pa info 600000
uvx --from ./assets pa info 01919 --market-type hk
uvx --from ./assets pa info AAPL --market-type us
```

---

## JSON Output

```json
{
  "code": "000895",
  "name": "Shuanghui Development",
  "market": "cn",
  "source": "ths",
  "period": "daily",
  "count": 20,
  "klines": [
    {
      "date": "2026-07-03",
      "open": 25.78,
      "high": 26.10,
      "low": 25.72,
      "close": 26.02,
      "volume": 845321,
      "amount": 219845340.0,
      "change_pct": 0.93,
      "turnover": 0.0,
      "amplitude": 1.46,
      "ema20": 25.61,
      "ema20_slope": 0.188,
      "ema20_distance": 1.6,
      "body_ratio": 0.63,
      "upper_wick_ratio": 0.21,
      "lower_wick_ratio": 0.16,
      "close_position": 0.79,
      "bar_type": "trend_bull"
    }
  ]
}
```

Top-level fields:
- `code`: normalized symbol
- `name`: security name
- `market`: `cn`, `hk`, or `us`
- `source`: provider actually used
- `period`: timeframe
- `count`: number of returned bars
- `klines`: candle array

Per-bar fields:
- `date`: trading date
- `open` / `high` / `low` / `close`
- `volume`
- `amount`
- `change_pct`
- `turnover`
- `amplitude`
- `ema20`
- `ema20_slope`
- `ema20_distance`
- `body_ratio`
- `upper_wick_ratio`
- `lower_wick_ratio`
- `close_position`
- `bar_type`
- `gap`: only present when a gap exists
- `limit`: only present for China A-shares

---

## Pattern Classification

| Pattern | Rule |
| --- | --- |
| `trend_bull` | body >= 60%, close position >= 50% |
| `trend_bear` | body >= 60%, close position <= 50% |
| `signal_bull` | lower wick > body, close position > 40% |
| `signal_bear` | upper wick > body, close position < 60% |
| `inside_bar` | current high < previous high and current low > previous low |
| `outside_bar` | current high > previous high and current low < previous low |
| `doji` | body ratio < 10% |
| `neutral` | none of the above |

---

## Symbol Rules

- China A-shares are usually 6-digit numeric symbols such as `600000` or `000895`
- Hong Kong symbols are usually 5-digit numeric symbols; short inputs like `700` are zero-padded to `00700`
- US symbols are typically alphabetic tickers such as `AAPL` or `MSFT`
- Explicit prefixed forms also work: `sh600000`, `hk01919`, `usAAPL`

---

## Notes

- Limit up / limit down detection is only applied to China A-shares
- Turnover and amount values depend on the provider and may be unavailable for some markets
- The CLI automatically falls back to alternate providers when the preferred source fails

---

## References

- [An Alternative to MCP: Python CLI-Based Agent Skills](https://almcc.me/blog/python-cli-skills/)
- [Official Astral uv Documentation](https://docs.astral.sh/uv/)
