# price-action

[English](./README.md) | **简体中文**

支持 A 股、港股、美股的 K 线数据获取与价格行为分析工具。

## 简介

`price-action` 会从多个公开数据源获取 K 线数据，计算核心技术指标，并输出适合 AI 代理进一步分析的结构化 JSON。

当前默认数据源策略：
- A 股：优先同花顺，失败时回退到腾讯和东财
- 港股：优先腾讯，失败时回退到东财
- 美股：优先腾讯，失败时回退到东财

**核心能力：**
- 获取日线、周线、月线 K 线
- 自动识别 A 股、港股、美股代码，也支持手动指定市场
- 计算 `EMA20`、斜率、价格偏离度
- 识别趋势棒、信号棒、内包柱、外包柱、十字星
- 检测跳空缺口
- 仅对 A 股标记涨跌停

## 架构

本项目采用 `python-tool-skill` 架构，基于 `uvx` 运行，无需手动维护虚拟环境：

```text
price-action/
├── SKILL.md              # 触发描述 + agent 指令
├── assets/
│   ├── price_action.py   # Click CLI 入口
│   ├── pyproject.toml    # 项目配置
│   └── uv.lock           # 锁定依赖
└── references/           # 价格行为分析参考资料
```

## 使用

### 前置要求

需要先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)：

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 命令

```bash
# 获取 K 线数据，默认日线 60 根
uvx --from ./assets pa kline <证券代码> [选项]

# 获取证券基本信息
uvx --from ./assets pa info <证券代码>

# 查看帮助
uvx --from ./assets pa --help
uvx --from ./assets pa kline --help
```

### K 线命令参数

| 参数 | 说明 |
|------|------|
| `CODE` | 证券代码，支持 `sh`/`sz`/`bj`/`hk`/`us` 前缀 |
| `--count, -n` | K 线数量，范围 `20-250`，默认 `60` |
| `--period, -p` | 周期：`daily`/`weekly`/`monthly` |
| `--market-type` | 市场类型：`auto`/`cn`/`hk`/`us` |
| `--source` | 数据源：`auto`/`ths`/`tencent`/`eastmoney` |
| `--market, -m` | 手动指定同花顺 market 编号，仅 `cn + ths` 生效 |
| `--compact, -c` | 紧凑输出（无缩进） |

### 示例

```bash
# A股：默认自动识别
uvx --from ./assets pa kline 600000

# A股：120 根日线
uvx --from ./assets pa kline 000895 -n 120

# A股：周线
uvx --from ./assets pa kline 601919 -p weekly

# 港股：腾讯控股
uvx --from ./assets pa kline 00700 --market-type hk

# 港股：中远海控
uvx --from ./assets pa kline 01919 --market-type hk

# 美股：苹果
uvx --from ./assets pa kline AAPL --market-type us

# 强制使用腾讯数据源
uvx --from ./assets pa kline MSFT --market-type us --source tencent

# 获取证券信息
uvx --from ./assets pa info 600000
uvx --from ./assets pa info 01919 --market-type hk
uvx --from ./assets pa info AAPL --market-type us
```

## 输出示例

```json
{
  "code": "000895",
  "name": "双汇发展",
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

## 返回字段

顶层字段：
- `code`：证券代码
- `name`：证券名称
- `market`：市场类型，`cn`/`hk`/`us`
- `source`：实际命中的数据源
- `period`：周期
- `count`：实际返回的 K 线数量
- `klines`：K 线数组

K 线字段：
- `date`：交易日期
- `open` / `high` / `low` / `close`：开高低收
- `volume`：成交量
- `amount`：成交额
- `change_pct`：单根 K 线涨跌幅
- `turnover`：换手率，部分数据源可能为 `0`
- `amplitude`：振幅
- `ema20`：20 周期指数移动平均
- `ema20_slope`：EMA20 斜率
- `ema20_distance`：收盘价相对 EMA20 的偏离百分比
- `body_ratio`：实体占比
- `upper_wick_ratio`：上影线占比
- `lower_wick_ratio`：下影线占比
- `close_position`：收盘在全 K 线中的相对位置
- `bar_type`：K 线形态分类
- `gap`：跳空缺口，仅有缺口时返回
- `limit`：涨跌停标记，仅 A 股可能返回

## K 线形态分类

| 形态 | 说明 |
|------|------|
| `trend_bull` | 多头趋势棒：实体 >= 60%，收盘位置 >= 50% |
| `trend_bear` | 空头趋势棒：实体 >= 60%，收盘位置 <= 50% |
| `signal_bull` | 多头信号棒：下影线长于实体，收盘位置 > 40% |
| `signal_bear` | 空头信号棒：上影线长于实体，收盘位置 < 60% |
| `inside_bar` | 内包柱：当前高点低于前高，低点高于前低 |
| `outside_bar` | 外包柱：当前高点高于前高，低点低于前低 |
| `doji` | 十字星：实体占比 < 10% |
| `neutral` | 中性 K 线 |

## 市场与代码规则

- A 股默认识别 6 位数字代码，如 `600000`、`000895`
- 港股默认识别 5 位数字代码，内部会自动补零，如 `700` 会转成 `00700`
- 美股默认识别字母代码，如 `AAPL`、`MSFT`
- 你也可以显式加前缀：`sh600000`、`hk01919`、`usAAPL`

## 说明

- A 股仍然保留涨跌停判断逻辑
- 港股和美股不计算涨跌停标记
- 不同数据源的成交额、换手率口径可能不完全一致
- 当主数据源不可用时，程序会自动回退到后备数据源

## 参考

- [An Alternative to MCP: Python CLI-Based Agent Skills](https://almcc.me/blog/python-cli-skills/)
- [uv 官方文档](https://docs.astral.sh/uv/)
