# price-action

CLI tool for retrieving and structuring K-line data for China A-shares, Hong Kong stocks, and US stocks.

## What It Does

- Fetches `daily`, `weekly`, and `monthly` candles
- Supports `cn`, `hk`, and `us` symbols
- Computes `EMA20`, slope, distance, gap flags, and candlestick classifications
- Outputs JSON suitable for agent workflows

Default source routing:
- `cn`: `ths -> tencent -> eastmoney`
- `hk`: `tencent -> eastmoney`
- `us`: `tencent -> eastmoney`

## Install

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Usage

```bash
uvx --from ./assets pa kline <CODE> [OPTIONS]
uvx --from ./assets pa info <CODE> [OPTIONS]
```

Common examples:

```bash
uvx --from ./assets pa kline 600000
uvx --from ./assets pa kline 000895 --market-type cn
uvx --from ./assets pa kline 01919 --market-type hk
uvx --from ./assets pa kline AAPL --market-type us
uvx --from ./assets pa kline 601919 -p weekly
uvx --from ./assets pa kline MSFT --market-type us --source tencent
uvx --from ./assets pa info AAPL --market-type us
```

## Options

| Option | Description |
| --- | --- |
| `CODE` | Symbol, supports `sh` / `sz` / `bj` / `hk` / `us` prefixes |
| `--count, -n` | Candle count, `20-250`, default `60` |
| `--period, -p` | `daily` / `weekly` / `monthly` |
| `--market-type` | `auto` / `cn` / `hk` / `us` |
| `--source` | `auto` / `ths` / `tencent` / `eastmoney` |
| `--market, -m` | Manual THS market id override for `cn + ths` |
| `--compact, -c` | Compact JSON output |

## Output

Top-level fields:
- `code`
- `name`
- `market`
- `source`
- `period`
- `count`
- `klines`

Per-bar fields:
- `date`, `open`, `high`, `low`, `close`
- `volume`, `amount`, `turnover`
- `change_pct`, `amplitude`
- `ema20`, `ema20_slope`, `ema20_distance`
- `body_ratio`, `upper_wick_ratio`, `lower_wick_ratio`, `close_position`
- `bar_type`
- `gap` when present
- `limit` for China A-shares when present

## Symbol Rules

- `600000`, `000895` -> China A-share
- `700`, `00700`, `01919` -> Hong Kong stock
- `AAPL`, `MSFT` -> US stock
- Prefixed forms also work: `sh600000`, `hk01919`, `usAAPL`

## Notes

- A-shares still include limit up / limit down detection
- Hong Kong and US outputs do not use A-share limit logic
- Some providers do not return turnover or amount, so those values may be `0`
- The analysis behavior and output schema for agents live in `SKILL.md`
