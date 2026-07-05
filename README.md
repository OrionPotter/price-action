---

# price-action

[🌐 简体中文](./README-cn.md) | **English**

An A-share candlestick data retrieval and Price Action analysis tool, optimized for AI agent workflows.

---

## 📝 Introduction

`price-action` fetches A-share K-line data directly from Flush (同花顺), calculates core technical indicators, and outputs structured JSON data specifically optimized for AI agent analysis.

**Core Features:**

* **Multi-Timeframe Retrieval:** Fetch daily, weekly, or monthly candlestick data.
* **Dynamic Trend Moving Averages:** Calculate EMA20 along with its current slope and distance relative to price.
* **Price Action Pattern Recognition:** Automatically classify candlestick types (e.g., `trend_bull`, `trend_bear`, `signal_bull`, `signal_bear`, `inside_bar`, `outside_bar`, `doji`).
* **Gap Detection:** Identify runaway, breakaway, or general market gaps.
* **Limit Moves:** Flag price ceilings and floors (Limit Up / Limit Down).

---

## 🏗️ Architecture

This project strictly follows the **python-tool-skill** architecture pattern. It leverages `uvx` to execute commands seamlessly without requiring manual virtual environment configuration:

```text
price-action/
├── SKILL.md              # Trigger descriptions + Agent specific instructions
├── assets/
│   ├── price_action.py   # Click-based CLI entry point
│   ├── pyproject.toml    # Project configurations & metadata
│   └── uv.lock           # Locked dependencies
└── references/           # Price action educational and reference materials

```

---

## 🚀 Getting Started

### Prerequisites

You need to have [uv](https://docs.astral.sh/uv/getting-started/installation/) installed on your machine:

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

```

### Commands

```bash
# Fetch K-line data (Defaults to 60 daily bars)
uvx --from ./assets pa kline <STOCK_CODE> [OPTIONS]

# Fetch fundamental stock profile information
uvx --from ./assets pa info <STOCK_CODE>

# Access built-in documentation and help menus
uvx --from ./assets pa --help
uvx --from ./assets pa kline --help

```

### Candlestick Command Options

| Option | Description |
| --- | --- |
| `CODE` | Stock code (supports `sh`/`sz`/`bj` prefixes) |
| `--count, -n` | Number of candlesticks (`20`–`250`), default: `60` |
| `--period, -p` | Timeframe interval: `daily`/`weekly`/`monthly`, default: `daily` |
| `--market, -m` | Manually override Flush (同花顺) market ID |
| `--compact, -c` | Minimize and compress JSON output (removes indentation) |

### Usage Examples

```bash
# Default: 60 Daily bars
uvx --from ./assets pa kline 600000

# 120 Daily bars
uvx --from ./assets pa kline 000021 -n 120

# 60 Weekly bars
uvx --from ./assets pa kline 601919 -p weekly

# 80 Monthly bars
uvx --from ./assets pa kline 000021 -n 80 -p monthly

# Minified compact JSON output
uvx --from ./assets pa kline 600000 -c

# Get specific stock information
uvx --from ./assets pa info 600000

```

---

## 📊 JSON Output Schema

```json
{
  "code": "600900",
  "name": "长江电力",
  "period": "daily",
  "count": 20,
  "klines": [
    {
      "date": "2026-03-13",
      "open": 27.5,
      "high": 27.63,
      "low": 27.35,
      "close": 27.42,
      "volume": 942776,
      "amount": 2590387280.0,
      "change_pct": -0.29,
      "turnover": 0.39,
      "amplitude": 1.02,
      "ema20": 26.83,
      "ema20_slope": 0.262,
      "ema20_distance": 2.2,
      "body_ratio": 0.29,
      "upper_wick_ratio": 0.46,
      "lower_wick_ratio": 0.25,
      "close_position": 0.25,
      "bar_type": "signal_bear"
    }
  ]
}

```

### Field Definitions

| Field | Definition |
| --- | --- |
| `ema20` | 20-period Exponential Moving Average |
| `ema20_slope` | EMA20 slope representing percentage rate of change |
| `ema20_distance` | Percentage distance from the closing price to the EMA20 |
| `body_ratio` | Ratio of the candlestick body relative to the entire high-low range |
| `upper_wick_ratio` | Ratio of the upper shadow line |
| `lower_wick_ratio` | Ratio of the lower shadow line |
| `close_position` | Relative closing price position within the bar (`0` = absolute low, `1` = absolute high) |
| `bar_type` | Calculated price action pattern classification |
| `gap` | Dynamic price gaps (`gap_up` / `gap_down`) |
| `limit` | Locked limit board tags (`limit_up` / `limit_down`) |

---

## 🕯️ Price Action Classifications

| Pattern Type | Technical Conditions |
| --- | --- |
| `trend_bull` | **Trend Bullish:** Body $\ge$ 60%, closing position $\ge$ 50% |
| `trend_bear` | **Trend Bearish:** Body $\ge$ 60%, closing position $\le$ 50% |
| `signal_bull` | **Signal Bullish (Pinbar):** Lower wick > body, closing position > 40% |
| `signal_bear` | **Signal Bearish (Pinbar):** Upper wick > body, closing position < 60% |
| `inside_bar` | **Inside Bar:** Current High < Previous High, Current Low > Previous Low |
| `outside_bar` | **Outside Bar:** Current High > Previous High, Current Low < Previous Low |
| `doji` | **Doji Star:** Candlestick body ratio < 10% |
| `neutral` | **Neutral:** Price action does not satisfy any pattern criteria above |

---

## 💡 Why python-tool-skill Architecture?

Inspired by [Al McClelland's framework](https://almcc.me/blog/python-cli-skills/), adopting a native `python-tool-skill` architecture offers massive advantages over typical MCP (Model Context Protocol) servers:

* **Zero Environment Hell:** `uvx` isolates and executes packages dynamically out-of-the-box.
* **Independent Testing Ecosystem:** The core skills are simple CLI commands that can be fully simulated and verified right inside your terminal.
* **Progressive Discovery Optimization:** By querying sub-menus only via `--help` variables, it trims prompt tokens by up to **94%**.
* **Universal Portability:** Works out of the box with any advanced AI agent capable of invoking a standard command-line interface.

---

## 🔗 References

* [An Alternative to MCP: Python CLI-Based Agent Skills](https://almcc.me/blog/python-cli-skills/)
* [Official Astral uv Documentation](https://docs.astral.sh/uv/)