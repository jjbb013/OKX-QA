# 策略名称：DOGE 布林带大振幅反向策略

本文档详细说明了 `doge_test.py` 文件中实现的量化交易策略。该策略基于布林带指标，旨在捕捉DOGE永续合约在价格大幅波动后可能出现的反转机会。

---

## 一、策略核心概述

- **交易标的**: `DOGE-USDT-SWAP`
- **时间周期**: 5分钟 (5m)
- **核心思想**: 均值回归 (Mean Reversion)。策略假设，当价格在短期内剧烈波动并突破布林带通道时，大概率会回归到通道内部。策略通过识别这种突破后的“长影线”形态来捕捉反转信号。

---

## 二、信号生成逻辑

该策略使用 **布林带 (Bollinger Bands)** 作为核心技术指标。

- **布林带参数**:
    - **周期 (Length)**: 20
    - **标准差倍数 (Multiplier)**: 2.0

### 1. 做空 (Short) 信号条件

当以下所有条件同时满足时，生成做空信号：

1.  **突破上轨**: K线的最高价 (`high`) 向上突破布林带上轨。
2.  **收回上轨内**: K线的收盘价 (`close`) 和开盘价 (`open`) 的最高值，最终收于布林带上轨之下。
3.  **长上影线确认**: K线的上影线长度（`最高价 - max(开盘价, 收盘价)`）超过价格的 **0.3%** (`wick_threshold`)，这表明上涨动能被拒绝，空头力量显现。

### 2. 做多 (Long) 信号条件

当以下所有条件同时满足时，生成做多信号：

1.  **跌穿下轨**: K线的最低价 (`low`) 向下跌穿布林带下轨。
2.  **收回下轨内**: K线的收盘价 (`close`) 和开盘价 (`open`) 的最低值，最终收于布林带下轨之上。
3.  **长下影线确认**: K线的下影线长度（`min(开盘价, 收盘价) - 最低价`）超过价格的 **0.3%** (`wick_threshold`)，这表明下跌动能被拒绝，多头力量显现。

### 3. 防重复机制

- 策略会记录上一次触发信号的K线时间戳，确保同一根K线不会重复触发开仓。

---

## 三、仓位与风险管理

- **杠杆倍数**: 20x
- **保证金**: 每单固定使用 **10 USDT** 的保证金。
- **仓位计算**:
    - 合约张数根据 `(保证金 × 杠杆) / (入场价格 × 合约面值)` 的公式计算。
    - DOGE合约面值为10，即每张合约代表10个DOGE。
    - 数量和价格精度会根据OKX的交易规则进行自动调整。
- **止盈 (Take Profit)**: 入场价格的 **3%**。
- **止损 (Stop Loss)**: 入场价格的 **2%**。
- **仓位叠加 (Pyramiding)**: 每个账户最多允许持有 **10** 个由该策略开出的仓位。

---

## 四、执行与技术特性

- **多账户支持**: 策略可以从环境变量中加载多个OKX账户的API凭证，并为每个账户独立执行交易。
- **数据获取**:
    - 策略已移除本地缓存机制，每次运行时均通过OKX API实时获取最新的K线数据。
    - 默认获取100根K线，确保有足够的数据（至少20根）用于计算，并保证数据是最新、最准确的。
    - 策略会自动筛选并只使用 **已完结** 的K线进行计算。
- **执行模式**:
    - 支持 **实盘 (`real`)** 和 **模拟** 两种模式。
    - 模式通过环境变量 `TRADE_MODE` 控制，在模拟模式下只记录日志而不真实下单。
- **通知系统**:
    - 当有信号触发并成功下单时，会通过Bark服务发送实时通知。
    - 策略运行中若发生严重错误，也会发送崩溃通知。
