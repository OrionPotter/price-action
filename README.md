# PA-Lens

A股K线数据获取与价格行为分析工具。

## 简介

PA-Lens 从东方财富获取A股K线数据，计算技术指标，输出结构化JSON供AI分析使用。

**核心功能：**
- 获取日K/周K/月K数据
- 计算 EMA20 及其斜率、距离
- 识别K线形态（trend_bull、trend_bear、signal_bull、signal_bear、inside_bar、outside_bar、doji 等）
- 检测跳空缺口
- 标记涨跌停

## 安装

```bash
pip install pandas requests
```

## 使用

```bash
# 基本用法
python scripts/fetch_kline.py <股票代码> [K线数量] [周期]

# 示例
python scripts/fetch_kline.py 600000              # 日K 60根
python scripts/fetch_kline.py 600000 120          # 日K 120根
python scripts/fetch_kline.py 600000 60 weekly    # 周K 60根
python scripts/fetch_kline.py 000021 80 monthly   # 月K 80根
```

**参数说明：**
- `股票代码`: 6位数字或带前缀，如 600000、sh600000、sz000001
- `K线数量`: 20-250，默认 60
- `周期`: daily(日K) / weekly(周K) / monthly(月K)，默认 daily

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

## 目录结构

```
price-action/
├── scripts/
│   └── fetch_kline.py    # K线数据获取脚本
├── references/           # 价格行为分析参考资料
│   ├── candles.md        # K线形态
│   ├── entries.md        # 入场策略
│   ├── risk.md           # 风险管理
│   ├── volume.md         # 成交量分析
│   └── cycles.md         # 市场周期
└── SKILL.md              # 项目说明
```

## 依赖

- Python 3.8+
- pandas
- requests

## License

MIT
