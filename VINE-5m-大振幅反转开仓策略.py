"""
任务名称
name: OKX VINE 大振幅反转
定时规则
cron: 1 */5 * * * *
"""
import os
IS_DEVELOPMENT = True
# ====== 自动预加载本地开发环境变量 ======
try:
    from utils.okx_utils import IS_DEVELOPMENT
except ImportError:
    IS_DEVELOPMENT = False
if IS_DEVELOPMENT:
    import utils.okx_utils  # 触发自动加载 .env_dev

import logging
from utils.okx_utils import (
    get_shanghai_time, get_kline_data,
    get_trade_api, get_orders_pending, cancel_pending_open_orders,
    build_order_params, send_bark_notification, get_env_var
)


# ========== 参数设置 ==========
TAKE_PROFIT_PERC = 5.5   # 止盈百分比
STOP_LOSS_PERC = 1.7     # 止损百分比
ORDER_EXPIRE_HOURS = 1   # 订单有效期（小时）
RANGE2_THRESHOLD = 4.2   # 振幅阈值（%）
SLIPPAGE_PERC = 0.5      # 滑点百分比
SYMBOL = "ETH-USDT-SWAP"
QTY_USDT = 100           # 名义下单金额
KLINE_INTERVAL = "5m"
FAKE_KLINE = True  # 测试开关，True 时用假K线数据
CONTRACT_FACE_VALUE = 0.01  # ETH-USDT-SWAP每张合约面值

logger = logging.getLogger("VINE-5m-大振幅反转开仓策略")
logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s] %(message)s')

def main():
    # ========== 初始化日志 ==========
    API_KEY = get_env_var("OKX_API_KEY")
    SECRET_KEY = get_env_var("OKX_SECRET_KEY")
    PASSPHRASE = get_env_var("OKX_PASSPHRASE")
    FLAG = get_env_var("OKX_FLAG", default="0")
    logger.info(f"[DEBUG] API_KEY: {repr(API_KEY)}")
    logger.info(f"[DEBUG] SECRET_KEY: {repr(SECRET_KEY)}")
    logger.info(f"[DEBUG] PASSPHRASE: {repr(PASSPHRASE)}")
    logger.info(f"[DEBUG] FLAG: {repr(FLAG)}")
    try:
        trade_api = get_trade_api()
        logger.info(f"[DEBUG] TradeAPI初始化成功: {trade_api}")
    except Exception as e:
        logger.error(f"[DEBUG] TradeAPI初始化失败: {e}")
        return

    # 1. 获取K线和最新价格
    if FAKE_KLINE:
        # 做多场景：阴线，振幅大，止损价低于开仓价
        # open=110, high=111, low=100, close=101
        # 振幅 = (111-100)/100 = 11%
        # 开仓价 = (close+low)/2 = 100.5
        # 止损价 = 98（低于开仓价），止盈价 = 106（高于开仓价）
        kline_data = [
            ["1751534700000", "110", "111", "100", "101", "10000", "1000", "1000000", "0"],
            ["1751534400000", "110", "111", "109", "110", "8000", "800", "800000", "1"]
        ]
        logger.info("[DEBUG] 使用假K线数据（做多）")
    else:
        kline_data = get_kline_data(API_KEY, SECRET_KEY, PASSPHRASE, SYMBOL, KLINE_INTERVAL, limit=2, flag=FLAG)
    if not kline_data or len(kline_data) < 1:
        logger.error("未获取到K线数据")
        return
    k = kline_data[0]
    # OKX返回格式: [ts, o, h, l, c, ...]
    open_, high, low, close = float(k[1]), float(k[2]), float(k[3]), float(k[4])
    logger.info(f"最新K线: open={open_}, close={close}, high={high}, low={low}")

    # 2. 检查账户委托
    orders = get_orders_pending(trade_api, SYMBOL)
    need_skip = False
    if orders:
        for order in orders:
            side = order.get('side')
            pos_side = order.get('posSide')
            price = float(order.get('px'))
            if side == 'buy' and pos_side == 'long':
                tp_price = price * (1 + TAKE_PROFIT_PERC / 100)
                if close > tp_price:
                    logger.info(f"多头委托已到达止盈价，撤销: {order}")
                    try:
                        cancel_result = cancel_pending_open_orders(trade_api, SYMBOL, order_ids=order.get('ordId'))
                        logger.info(f"撤销多头委托响应: {cancel_result}")
                        if not cancel_result:
                            need_skip = True
                    except Exception as e:
                        logger.error(f"撤销多头委托异常: {e}")
                        need_skip = True
            elif side == 'sell' and pos_side == 'short':
                tp_price = price * (1 - TAKE_PROFIT_PERC / 100)
                if close < tp_price:
                    logger.info(f"空头委托已到达止盈价，撤销: {order}")
                    try:
                        cancel_result = cancel_pending_open_orders(trade_api, SYMBOL, order_ids=order.get('ordId'))
                        logger.info(f"撤销空头委托响应: {cancel_result}")
                        if not cancel_result:
                            need_skip = True
                    except Exception as e:
                        logger.error(f"撤销空头委托异常: {e}")
                        need_skip = True
        if need_skip:
            logger.info("存在未完成委托且撤销失败，跳过本轮开仓")
            return

    # 3. 检查K线形态，准备开仓
    range2 = (high - low) / low * 100
    in_range2 = range2 > RANGE2_THRESHOLD
    is_green = close > open_
    is_red = close < open_
    logger.info(f"振幅={range2:.2f}%, in_range2={in_range2}, is_green={is_green}, is_red={is_red}")

    if in_range2:
        order_price = None
        direction = None
        pos_side = None
        side = None
        if is_green:
            calculated_entry = (close + high) / 2
            order_price = calculated_entry * (1 - SLIPPAGE_PERC / 100)
            direction = "做空"
            pos_side = "short"
            side = "sell"
        elif is_red:
            calculated_entry = (close + low) / 2
            order_price = calculated_entry * (1 + SLIPPAGE_PERC / 100)
            direction = "做多"
            pos_side = "long"
            side = "buy"
        else:
            logger.info("K线无方向，不开仓")
            return
        qty = int(QTY_USDT / order_price / CONTRACT_FACE_VALUE)
        if qty < 1:
            logger.info("下单数量过小，跳过本次开仓")
            return
        tp = order_price * (1 - TAKE_PROFIT_PERC / 100) if direction == '做空' else order_price * (1 + TAKE_PROFIT_PERC / 100)
        sl = order_price * (1 + STOP_LOSS_PERC / 100) if direction == '做空' else order_price * (1 - STOP_LOSS_PERC / 100)
        logger.info(f"准备开仓: 方向={direction}, 价格={order_price:.4f}, 数量={qty}, 止盈={tp:.4f}, 止损={sl:.4f}")

        # 4. 下单
        order_params = build_order_params(
            SYMBOL, side, order_price, qty, pos_side, tp, sl
        )
        try:
            resp = trade_api.place_order(**order_params)
        except Exception as e:
            resp = {"error": str(e)}
        sh_time = get_shanghai_time()
        bark_title = "VINE大振幅反转开仓"
        bark_content = (
            f"时间: {sh_time}\n合约: {SYMBOL}\n方向: {direction}\n数量: {qty}\n"
            f"开仓价: {order_price:.4f}\n止盈: {tp:.4f}\n止损: {sl:.4f}\n"
            f"下单结果: {resp}"
        )
        send_bark_notification(bark_title, bark_content)
        logger.info(f"下单响应: {resp}")
    else:
        logger.info("K线不满足大振幅反转条件，不开仓")

if __name__ == "__main__":
    main() 