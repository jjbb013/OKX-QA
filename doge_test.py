#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DOGE-USDT-SWAP布林影线策略
定时规则：cron: 1 */5 * * * *
"""

import os
import sys
import math
import csv
import numpy as np
from glob import glob
from typing import List, Dict, Optional

# 添加utils目录
sys.path.append(os.path.join(os.path.dirname(__file__), 'utils'))
from okx_utils import (
    get_shanghai_time, build_order_params, send_bark_notification
)

# 导入OKX API
import okx.Trade as Trade
import okx.MarketData as MarketData

# ---------- 配置参数 ----------
DATA_DIR = '/ql/data/DOGE-BB-DATA/'  # K线数据存储目录
CSV_PREFIX = 'DOGE-5M'              # CSV文件前缀
MAX_ROWS = 1000                     # 单文件最大K线数量
MIN_ROWS = 50                       # 最小有效K线数量
STRATEGY_PARAMS = {                  # 策略核心参数
    'leverage': 20,                  # 杠杆倍数
    'take_profit_perc': 0.03,        # 止盈比例 (3%)
    'stop_loss_perc': 0.02,          # 止损比例 (2%)
    'wick_threshold': 0.003,         # 影线阈值 (0.3%)
    'bb_length': 20,                 # 布林带周期
    'bb_mult': 2.0,                  # 布林带标准差倍数
    'order_value': 10,               # 每单保证金 (USDT)
    'pyramiding': 10                 # 最大叠加仓位
}

# ========================
# 数据管理模块
# ========================
def filter_completed_klines(klines: list) -> list:
    """过滤未完结K线（第9位=1为完结）"""
    return [kline for kline in klines if len(kline) > 8 and kline[8] == '1']

def fetch_kline_from_okx(inst_id: str, bar: str, limit: int, flag: str) -> list:
    """
    从OKX获取K线数据
    :param inst_id: 交易品种 (如DOGE-USDT-SWAP)
    :param bar: K线周期 (如5m)
    :param limit: 获取数量
    :param flag: 账户类型 (0实盘/1模拟盘)
    :return: 已过滤的K线数据列表
    """
    market_api = MarketData.MarketAPI(flag=flag)
    result = market_api.get_candlesticks(instId=inst_id, bar=bar, limit=str(limit))
    if result and result.get('code') == '0':
        return filter_completed_klines(result['data'])  # 仅返回已完结K线
    return []

def get_latest_csv_file(dir_path: str, prefix: str) -> Optional[str]:
    """获取最新的CSV文件路径"""
    files = sorted(glob(os.path.join(dir_path, f"{prefix}-*.csv")))
    return files[-1] if files else None

def load_kline_from_csv(filepath: str) -> list:
    """从CSV加载K线数据"""
    if not filepath or not os.path.exists(filepath):
        return []
    with open(filepath, 'r') as f:
        return list(csv.reader(f))

def save_kline_to_csv(filepath: str, kline_data: list):
    """保存K线到CSV"""
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(filter_completed_klines(kline_data))  # 保存时二次过滤

def append_kline_to_csv(filepath: str, new_kline_data: list):
    """追加新K线到CSV"""
    existing = load_kline_from_csv(filepath)
    existing_ts = {row[0] for row in existing}  # 获取已有时间戳
    # 过滤已存在数据
    new_rows = [row for row in new_kline_data if row[0] not in existing_ts]
    if not new_rows:
        return
    with open(filepath, 'a', newline='') as f:
        csv.writer(f).writerows(new_rows)

def rotate_csv_file(dir_path: str, prefix: str, max_rows: int) -> str:
    """
    文件滚动存储：当文件超过max_rows时创建新文件
    :return: 当前使用的文件路径
    """
    latest_file = get_latest_csv_file(dir_path, prefix)
    if not latest_file:  # 无文件时创建首个文件
        new_file = os.path.join(dir_path, f"{prefix}-1.csv")
        return new_file
        
    # 检查行数是否超限
    if len(load_kline_from_csv(latest_file)) < max_rows:
        return latest_file
        
    # 生成新文件名 (编号+1)
    idx = int(latest_file.split('-')[-1].replace('.csv', '')) + 1
    return os.path.join(dir_path, f"{prefix}-{idx}.csv")

def get_kline_data_with_cache(
    inst_id: str, 
    bar: str, 
    min_rows: int = MIN_ROWS, 
    max_rows: int = MAX_ROWS, 
    flag: str = '0'
) -> list:
    """
    获取K线数据（本地缓存+实时拉取）
    :return: 至少包含min_rows条K线的列表（最新数据在前）
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    latest_csv = get_latest_csv_file(DATA_DIR, CSV_PREFIX)
    kline_data = load_kline_from_csv(latest_csv) if latest_csv else []
    
    # 本地数据不足时从OKX拉取
    if len(kline_data) < min_rows:
        fetch_count = max(min_rows, 100)  # 至少拉取100条
        new_data = fetch_kline_from_okx(inst_id, bar, fetch_count, flag)
        if new_data:
            kline_data = new_data + kline_data  # 新数据在前
            
        # 滚动存储
        csv_path = rotate_csv_file(DATA_DIR, CSV_PREFIX, max_rows)
        save_kline_to_csv(csv_path, kline_data[-max_rows:])
        latest_csv = csv_path
    
    # 增量更新最新数据
    new_data = fetch_kline_from_okx(inst_id, bar, 5, flag)
    if new_data:
        append_kline_to_csv(latest_csv, new_data)
        # 检查是否触发滚动
        if len(load_kline_from_csv(latest_csv)) > max_rows:
            csv_path = rotate_csv_file(DATA_DIR, CSV_PREFIX, max_rows)
            save_kline_to_csv(csv_path, load_kline_from_csv(latest_csv)[-max_rows:])
            latest_csv = csv_path
    
    return load_kline_from_csv(latest_csv)[-min_rows:]

# ========================
# 核心策略类
# ========================
class BollingerStrategy:
    def __init__(self):
        self.inst_id = "DOGE-USDT-SWAP"  # 合约ID
        self.bar = "5m"                 # K线周期
        self.params = STRATEGY_PARAMS    # 策略参数
        self.accounts = self._get_accounts()  # 加载账户配置
        self.position_counters = {acc['name']: 0 for acc in self.accounts}  # 初始化仓位计数器
        self.last_signal_ts = 0          # 上次信号时间戳（防重）

    def _get_accounts(self) -> List[Dict]:
        """从环境变量加载OKX账户配置"""
        accounts = []
        # 账户1配置
        if name := os.environ.get("OKX1_ACCOUNT_NAME"):
            accounts.append({
                'name': name,
                'api_key': os.environ.get("OKX1_API_KEY", ""),
                'secret_key': os.environ.get("OKX1_SECRET_KEY", ""),
                'passphrase': os.environ.get("OKX1_PASSPHRASE", ""),
                'flag': os.environ.get("OKX1_FLAG", "0"),
            })
        # 账户2配置
        if name := os.environ.get("OKX2_ACCOUNT_NAME"):
            accounts.append({
                'name': name,
                'api_key': os.environ.get("OKX2_API_KEY", ""),
                'secret_key': os.environ.get("OKX2_SECRET_KEY", ""),
                'passphrase': os.environ.get("OKX2_PASSPHRASE", ""),
                'flag': os.environ.get("OKX2_FLAG", "0"),
            })
        return accounts

    def init_trade_api(self, account: Dict) -> Trade.TradeAPI:
        """初始化交易API对象"""
        return Trade.TradeAPI(
            api_key=account['api_key'],
            secret_key=account['secret_key'],
            passphrase=account['passphrase'],
            flag=account['flag'],
            debug=False
        )

    def log(self, message: str, account_name: str = ""):
        """记录带时间戳的日志"""
        timestamp = get_shanghai_time()
        prefix = f"[{account_name}] " if account_name else ""
        print(f"[{timestamp}] {prefix}{message}")

    # ---------- 策略计算函数 ----------
    def calculate_bollinger_bands(self, closes: List[float]) -> tuple:
        """
        计算布林带上轨、中轨、下轨
        :param closes: 收盘价列表（最新数据在前）
        :return: (上轨, 中轨, 下轨)
        """
        if len(closes) < self.params['bb_length']:
            return 0.0, 0.0, 0.0
            
        # 使用向量化计算提高性能
        basis = np.mean(closes[-self.params['bb_length']:])  # 中轨(SMA)
        dev = np.std(closes[-self.params['bb_length']:]) * self.params['bb_mult']
        return basis + dev, basis, basis - dev  # (上轨, 中轨, 下轨)

    def adjust_quantity(self, raw_qty: float) -> float:
        """
        ⚠️ 数量精度调整：对齐到0.01的整数倍（DOGE合约要求）
        :param raw_qty: 原始计算数量
        :return: 调整后的合约张数 (0.01的整数倍)
        """
        min_lot = 0.01  # 最小交易单位
        adjusted = math.ceil(raw_qty / min_lot) * min_lot  # 向上取整到最近0.01
        return round(adjusted, 2)  # 保留两位小数

    def format_price(self, price: float) -> float:
        """
        ⚠️ 价格精度调整：限制到小数点后5位（OKX要求）
        :param price: 原始价格
        :return: 格式化后价格
        """
        return round(price, 5)

    def generate_signal(self, kline_data: list) -> Optional[dict]:
        """
        生成交易信号
        :param kline_data: K线数据（最新在前）
        :return: 信号字典（无信号时返回None）
        """
        if len(kline_data) < self.params['bb_length']:
            self.log("K线数据不足，无法计算布林带")
            return None
            
        # 解析最新K线
        latest = kline_data[0]
        ts, o, h, l, c = latest[0], float(latest[1]), float(latest[2]), float(latest[3]), float(latest[4])
        
        # ⚠️ 防重复信号：同一根K线不重复触发
        current_ts = int(ts) // 1000
        if current_ts <= self.last_signal_ts:
            return None
            
        # 计算布林带
        closes = [float(k[4]) for k in kline_data]  # 提取收盘价
        upper, basis, lower = self.calculate_bollinger_bands(closes)
        
        # 计算影线与实体
        upper_wick = h - max(o, c)  # 上影线高度
        lower_wick = min(o, c) - l   # 下影线高度
        body = abs(c - o)            # K线实体高度
        
        # 信号条件判断
        short_signal = (
            upper_wick >= self.params['wick_threshold'] and  # 上影线超过阈值
            h > upper and                                  # 最高价突破上轨
            max(o, c) < upper                              # 收盘价低于上轨
        )
        long_signal = (
            lower_wick >= self.params['wick_threshold'] and  # 下影线超过阈值
            l < lower and                                  # 最低价突破下轨
            min(o, c) > lower                               # 收盘价高于下轨
        )
        
        # 计算入场价（影线顶端/底端+实体）
        entry_short = max(o, c) + body
        entry_long = min(o, c) - body
        
        # 返回信号字典
        return {
            'short_signal': short_signal,
            'long_signal': long_signal,
            'entry_short': entry_short,
            'entry_long': entry_long,
            'tp_short': entry_short * (1 - self.params['take_profit_perc']),  # 空单止盈价
            'sl_short': entry_short * (1 + self.params['stop_loss_perc']),     # 空单止损价
            'tp_long': entry_long * (1 + self.params['take_profit_perc']),    # 多单止盈价
            'sl_long': entry_long * (1 - self.params['stop_loss_perc']),      # 多单止损价
            'timestamp': ts  # K线时间戳
        }

    # ---------- 仓位计算函数 ----------
    def calculate_position_size(self, entry_price: float, account_name: str) -> float:
        """
        ⚠️ 计算合约张数（考虑合约面值）
        :param entry_price: 入场价格
        :param account_name: 账户名（用于日志）
        :return: 调整后的合约张数（0.01的整数倍）
        """
        # 计算公式：合约张数 = (保证金 × 杠杆) / (价格 × 合约面值)
        # ⚠️ DOGE-USDT-SWAP合约面值 = 10（每张合约代表10 DOGE）
        contract_face_value = 10
        raw_size = (self.params['order_value'] * self.params['leverage']) / (entry_price * contract_face_value)
        
        # 精度调整
        adjusted_size = self.adjust_quantity(raw_size)
        
        # 检查是否低于最小交易量
        if adjusted_size < 0.01:
            self.log(f"计算数量{adjusted_size}小于0.01张，跳过下单", account_name)
            return 0.0
            
        return adjusted_size

    # ---------- 交易执行函数 ----------
    def execute_trade(self, signal: dict):
        """执行交易信号"""
        if not signal or ('short_signal' not in signal and 'long_signal' not in signal):
            self.log("无有效信号")
            return
            
        # 更新信号时间戳（防重）
        self.last_signal_ts = int(signal['timestamp']) // 1000
        
        for account in self.accounts:  # 遍历所有账户
            acc_name = account['name']
            try:
                # 检查仓位限制
                if self.position_counters[acc_name] >= self.params['pyramiding']:
                    self.log(f"已达最大仓位数({self.params['pyramiding']})，跳过", acc_name)
                    continue
                    
                # 初始化API
                trade_api = self.init_trade_api(account)
                
                # 处理空单信号
                if signal['short_signal']:
                    # ⚠️ 关键步骤：价格格式化+仓位计算
                    entry = self.format_price(signal['entry_short'])
                    size = self.calculate_position_size(entry, acc_name)
                    if size > 0:
                        self.place_order(
                            trade_api,
                            acc_name,
                            "sell",  # 方向
                            "short", # 仓位
                            entry,
                            self.format_price(signal['tp_short']),
                            self.format_price(signal['sl_short']),
                            size
                        )
                        
                # 处理多单信号
                if signal['long_signal']:
                    entry = self.format_price(signal['entry_long'])
                    size = self.calculate_position_size(entry, acc_name)
                    if size > 0:
                        self.place_order(
                            trade_api,
                            acc_name,
                            "buy", 
                            "long",
                            entry,
                            self.format_price(signal['tp_long']),
                            self.format_price(signal['sl_long']),
                            size
                        )
            except Exception as e:
                self.log(f"账户处理异常: {str(e)}", acc_name)

    def place_order(
        self, 
        api: Trade.TradeAPI, 
        acc_name: str, 
        side: str, 
        pos_side: str, 
        entry: float, 
        tp: float, 
        sl: float,
        size: float
    ):
        """
        ⚠️ 下单执行函数
        :param size: 已调整的合约张数
        """
        # 构建订单参数
        order_params = build_order_params(
            instId=self.inst_id,
            side=side,
            pos_side=pos_side,
            entry_price=entry,
            size=size,
            take_profit=tp,
            stop_loss=sl,
            prefix="DOGE-BB"
        )
        
        # 根据TRADE_MODE决定执行方式
        if os.getenv('TRADE_MODE') == 'real':  # 实盘模式
            result = api.place_order(**order_params)
            if result and result.get('code') == '0':
                self.position_counters[acc_name] += 1  # 更新仓位计数
                self.log(f"{side}单成功: 数量={size}张 @ {entry}", acc_name)
                self.send_notification(acc_name, side, entry, size, tp, sl)
            else:
                err = result.get('msg', '未知错误') if result else '无响应'
                self.log(f"下单失败: {err}", acc_name)
        else:  # 模拟盘模式
            self.log(f"[SIM] 忽略下单: {side} {size}张 @ {entry}", acc_name)

    def send_notification(self, acc_name: str, side: str, price: float, size: float, tp: float, sl: float):
        """发送Bark通知"""
        title = f"DOGE {side.upper()}信号触发"
        content = f"""账户: {acc_name}
操作: {'做空' if side=='sell' else '做多'}
价格: {price:.6f}
数量: {size:.2f}张
止盈: {tp:.6f}
止损: {sl:.6f}
时间: {get_shanghai_time()}"""
        send_bark_notification(title, content)

# ========================
# 主执行流程
# ========================
def main():
    """策略主入口"""
    strategy = BollingerStrategy()
    if not strategy.accounts:
        print("未配置OKX账户，请设置环境变量")
        return
        
    # 加载K线数据（自动缓存）
    klines = get_kline_data_with_cache(
        inst_id=strategy.inst_id,
        bar=strategy.bar,
        min_rows=strategy.params['bb_length'] + 10,
        flag=strategy.accounts[0]['flag']
    )
    
    if not klines:
        print("获取K线数据失败")
        return
        
    # 生成并执行信号
    if signal := strategy.generate_signal(klines):
        strategy.execute_trade(signal)
    else:
        print("未生成交易信号")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        err_msg = f"策略异常: {str(e)}\n{traceback.format_exc()}"
        print(err_msg)
        send_bark_notification("策略崩溃", err_msg)
