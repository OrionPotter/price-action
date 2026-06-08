# price-action

A股K线数据获取与价格行为分析工具。

## 简介

price-action 从同花顺获取A股K线数据，计算技术指标，输出结构化JSON供AI分析使用。

**核心功能：**
- 获取日K/周K/月K数据
- 计算 EMA20 及其斜率、距离
- 识别K线形态（trend_bull、trend_bear、signal_bull、signal_bear、inside_bar、outside_bar、doji 等）
- 检测跳空缺口
- 标记涨跌停

## 架构

本项目采用 **python-tool-skill** 架构，基于 uvx 运行，无需管理虚拟环境：

```
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

需要安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)：

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 命令

```bash
# 获取K线数据，默认日线 60 根
uvx --from ./assets pa kline <股票代码> [选项]

# 获取股票基本信息
uvx --from ./assets pa info <股票代码>

# 查看帮助
uvx --from ./assets pa --help
uvx --from ./assets pa kline --help
```

### K线命令参数

| 参数 | 说明 |
|------|------|
| `CODE` | 股票代码，支持 sh/sz/bj 前缀 |
| `--count, -n` | K线数量 (20-250)，默认 60 根 |
| `--period, -p` | 周期: daily/weekly/monthly，默认 daily（日线） |
| `--market, -m` | 手动指定同花顺 market 编号 |
| `--compact, -c` | 紧凑输出（无缩进） |

### 示例

```bash
# 默认：日K 60根
uvx --from ./assets pa kline 600000

# 日K 120根
uvx --from ./assets pa kline 000021 -n 120

# 周K 60根
uvx --from ./assets pa kline 601919 -p weekly

# 月K 80根
uvx --from ./assets pa kline 000021 -n 80 -p monthly

# 紧凑输出
uvx --from ./assets pa kline 600000 -c

# 获取股票信息
uvx --from ./assets pa info 600000
```

## 输出示例

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

## 字段说明

| 字段 | 说明 |
|------|------|
| `ema20` | 20日指数移动平均线 |
| `ema20_slope` | EMA20 斜率（百分比变化） |
| `ema20_distance` | 收盘价距EMA20的距离（百分比） |
| `body_ratio` | 实体占K线总长度的比例 |
| `upper_wick_ratio` | 上影线占比 |
| `lower_wick_ratio` | 下影线占比 |
| `close_position` | 收盘价在K线中的位置（0=最低，1=最高） |
| `bar_type` | K线形态分类 |
| `gap` | 跳空缺口（gap_up / gap_down） |
| `limit` | 涨跌停标记（limit_up / limit_down） |

## K线形态分类

| 形态 | 说明 |
|------|------|
| `trend_bull` | 趋势阳线：实体>=60%，收盘位置>=50% |
| `trend_bear` | 趋势阴线：实体>=60%，收盘位置<=50% |
| `signal_bull` | 看涨信号：下影线>实体，收盘位置>40% |
| `signal_bear` | 看跌信号：上影线>实体，收盘位置<60% |
| `inside_bar` | 内包线：高点<前高，低点>前低 |
| `outside_bar` | 外包线：高点>前高，低点<前低 |
| `doji` | 十字星：实体占比<10% |
| `neutral` | 中性：不符合以上条件 |

## 为什么选择 python-tool-skill 架构？

基于 [Al McClelland 的文章](https://almcc.me/blog/python-cli-skills/)，python-tool-skill 相比 MCP 服务器有以下优势：

- **无需管理虚拟环境**：uvx 自动处理包隔离
- **可独立测试**：工具就是 CLI，可直接在终端运行
- **渐进式发现**：通过 `--help` 按需加载，节省 ~94% tokens
- **可移植**：任何支持 CLI 的 agent 都能使用

## 参考

- [An Alternative to MCP: Python CLI-Based Agent Skills](https://almcc.me/blog/python-cli-skills/)
- [uv 官方文档](https://docs.astral.sh/uv/)
