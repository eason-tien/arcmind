#!/usr/bin/env python3
"""
台股模拟交易 - 增强版交易策略
目标：每周目标收益 2%，每月 8%+
"""

import json
import random
from datetime import datetime, time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LEDGER_FILE = BASE_DIR / "台股模拟交易_交易台账.md"
LOG_FILE = BASE_DIR / "logs" / f"trading_enhanced_{datetime.now().strftime('%Y%m%d')}.log"

# 交易费率
BROKERAGE_FEE = 0.001425  # 0.1425%
TAX_RATE = 0.003  # 0.3%

# 止盈止损线
STOP_LOSS = -5.0   # 止损线 -5%
TAKE_PROFIT = 8.0  # 止盈线 8%
TRAILING_STOP = 6.0  # 移动止损 6%

INITIAL_CAPITAL = 50000


def get_current_state():
    """读取当前状态"""
    try:
        with open(LEDGER_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 解析现金余额
        cash = 31774  # 默认值
        positions = {}
        
        lines = content.split('\n')
        in_positions = False
        
        for line in lines:
            if '持仓明细' in line:
                in_positions = True
                continue
            if in_positions and '|' in line and '---' not in line:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 7 and parts[1] and parts[1] != '代码':
                    try:
                        symbol = parts[1]
                        name = parts[2]
                        shares = int(parts[3].replace(',', ''))
                        avg_cost = float(parts[5].replace('TWD', '').replace(',', ''))
                        positions[symbol] = {
                            'name': name,
                            'shares': shares,
                            'avg_cost': avg_cost
                        }
                    except:
                        pass
        
        return {'cash': cash, 'positions': positions}
    except Exception as e:
        print(f"读取状态错误: {e}")
        return {'cash': 31774, 'positions': {'2408': {'name': '矽统', 'shares': 1000, 'avg_cost': 18.20}}}


def get_market_data():
    """获取市场数据 - 使用更真实的模拟"""
    # 台湾股市热门标的
    stocks = {
        # 铜板股 (50元以下)
        '2408': {'name': '矽统', 'base': 18.50, 'vol': 0.035},
        '2610': {'name': '華航', 'base': 18.80, 'vol': 0.025},
        '2002': {'name': '中鋼', 'base': 19.50, 'vol': 0.022},
        '2812': {'name': '台中銀', 'base': 21.00, 'vol': 0.018},
        '2883': {'name': '開發金', 'base': 20.50, 'vol': 0.020},
        '2884': {'name': '玉山金', 'base': 34.00, 'vol': 0.018},
        '2409': {'name': '友達', 'base': 15.20, 'vol': 0.030},
        '2340': {'name': '台亞', 'base': 45.00, 'vol': 0.025},
        '2485': {'name': '兆赫', 'base': 28.00, 'vol': 0.028},
        '3019': {'name': '亞光', 'base': 98.00, 'vol': 0.030},
        
        # 中价位股
        '2317': {'name': '鴻海', 'base': 160.00, 'vol': 0.022},
        '2454': {'name': '聯發科', 'base': 1450.00, 'vol': 0.025},
        '3034': {'name': '聯詠', 'base': 580.00, 'vol': 0.028},
        '3443': {'name': '創意', 'base': 1280.00, 'vol': 0.032},
        
        # 高价股
        '3008': {'name': '大立光', 'base': 2950.00, 'vol': 0.030},
        '6666': {'name': '牧德', 'base': 420.00, 'vol': 0.028},
    }
    
    market = {}
    for code, info in stocks.items():
        # 加入时间因素 - 开盘波动大
        hour = datetime.now().hour
        time_factor = 1.0 if 9 <= hour <= 13 else 0.5
        
        change = random.gauss(0, info['vol'] * time_factor)
        price = info['base'] * (1 + change)
        
        market[code] = {
            'name': info['name'],
            'price': round(price, 2),
            'change': round(change * 100, 2),
            'volume': random.randint(500000, 8000000)
        }
    
    return market


def calculate_total_assets(state, market):
    """计算总资产"""
    position_value = 0
    for code, pos in state['positions'].items():
        if code in market:
            position_value += pos['shares'] * market[code]['price']
    return state['cash'] + position_value


def analyze_and_trade():
    """执行交易分析并决策"""
    state = get_current_state()
    market = get_market_data()
    
    # 计算当前资产
    total = calculate_total_assets(state, market)
    pnl = total - INITIAL_CAPITAL
    pnl_pct = (pnl / INITIAL_CAPITAL) * 100
    
    decisions = []
    trades = []
    
    # 1. 检查持仓 - 止盈止损
    for code, pos in list(state['positions'].items()):
        if code not in market:
            continue
            
        current_price = market[code]['price']
        avg_cost = pos['avg_cost']
        shares = pos['shares']
        pos_pnl_pct = ((current_price - avg_cost) / avg_cost) * 100
        
        # 止盈止损判断
        should_sell = False
        reason = ""
        
        if pos_pnl_pct <= STOP_LOSS:
            should_sell = True
            reason = f"止损 ({pos_pnl_pct:.2f}%)"
        elif pos_pnl_pct >= TAKE_PROFIT:
            should_sell = True
            reason = f"止盈 ({pos_pnl_pct:.2f}%)"
        
        if should_sell:
            proceeds = shares * current_price * (1 - BROKERAGE_FEE - TAX_RATE)
            state['cash'] += proceeds
            del state['positions'][code]
            decisions.append(f"卖出 {code} {market[code]['name']} {shares}股 @ {current_price} ({reason})")
            trades.append({
                'action': 'SELL',
                'code': code,
                'price': current_price,
                'shares': shares,
                'reason': reason
            })
    
    # 2. 寻找买入机会
    # 资金使用率目标 60-70%
    target_position_ratio = 0.65
    current_position_value = total - state['cash']
    target_position_value = total * target_position_ratio
    available_cash = state['cash']
    
    # 筛选候选股票
    candidates = []
    for code, data in market.items():
        if code in state['positions']:
            continue
        
        price = data['price']
        
        # 只选买得起的股票 (1张 = 1000股)
        if price <= 50:  # 铜板股
            cost_per_lot = price * 1000 * (1 + BROKERAGE_FEE)
            if cost_per_lot <= available_cash:
                # 评分
                score = 0
                
                # 涨幅适中 (+1% ~ +3%) 有上涨动能
                if 1 <= data['change'] <= 3:
                    score += 3
                elif 0 <= data['change'] < 1:
                    score += 1
                
                # 成交量活跃
                if data['volume'] > 2000000:
                    score += 2
                elif data['volume'] > 1000000:
                    score += 1
                
                # 股价适中 (20-40元)
                if 20 <= price <= 40:
                    score += 1
                
                if score >= 2:
                    candidates.append({
                        'code': code,
                        'name': data['name'],
                        'price': price,
                        'change': data['change'],
                        'volume': data['volume'],
                        'score': score
                    })
    
    # 按评分排序，买入最好的
    candidates.sort(key=lambda x: (-x['score'], -x['change']))
    
    if candidates and available_cash > 15000:
        best = candidates[0]
        shares = 1000  # 1张
        cost = shares * best['price'] * (1 + BROKERAGE_FEE)
        
        if cost <= available_cash:
            state['cash'] -= cost
            state['positions'][best['code']] = {
                'name': best['name'],
                'shares': shares,
                'avg_cost': best['price']
            }
            decisions.append(f"买入 {best['code']} {best['name']} {shares}股 @ {best['price']}")
            trades.append({
                'action': 'BUY',
                'code': best['code'],
                'price': best['price'],
                'shares': shares,
                'cost': cost
            })
    
    # 3. 输出结果
    final_total = calculate_total_assets(state, market)
    final_pnl = final_total - INITIAL_CAPITAL
    final_pnl_pct = (final_pnl / INITIAL_CAPITAL) * 100
    
    result = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_assets': int(final_total),
        'cash': int(state['cash']),
        'position_value': int(final_total - state['cash']),
        'pnl': int(final_pnl),
        'pnl_pct': round(final_pnl_pct, 2),
        'positions': [
            {
                'code': code,
                'name': pos['name'],
                'shares': pos['shares'],
                'avg_cost': pos['avg_cost'],
                'current_price': market[code]['price'] if code in market else 0,
                'pnl_pct': round(((market[code]['price'] - pos['avg_cost']) / pos['avg_cost']) * 100, 2) if code in market else 0
            }
            for code, pos in state['positions'].items()
        ],
        'decisions': decisions,
        'trades': trades,
        'status': '完成'
    }
    
    # 记录日志
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"\n{'='*50}\n")
        f.write(f"时间: {result['timestamp']}\n")
        f.write(f"总资产: {result['total_assets']} | 现金: {result['cash']} | 持仓: {result['position_value']}\n")
        f.write(f"损益: {result['pnl']} ({result['pnl_pct']}%)\n")
        f.write(f"决策: {decisions}\n")
    
    return result


def run_trading_cycle():
    """运行交易周期"""
    print("\n" + "="*60)
    print("       台股模拟交易 - 增强策略")
    print("="*60)
    
    result = analyze_and_trade()
    
    print(f"时间: {result['timestamp']}")
    print(f"总资产: TWD {result['total_assets']:,}")
    print(f"现金: TWD {result['cash']:,}")
    print(f"持仓: TWD {result['position_value']:,}")
    print(f"损益: TWD {result['pnl']:,} ({result['pnl_pct']}%)")
    print()
    
    if result['positions']:
        print("持仓明细:")
        for p in result['positions']:
            print(f"  {p['code']} {p['name']}: {p['shares']}股 @ 成本{p['avg_cost']} | 现价{p['current_price']} (损益 {p['pnl_pct']}%)")
        print()
    
    if result['decisions']:
        print("执行决策:")
        for d in result['decisions']:
            print(f"  ✓ {d}")
    else:
        print("决策: 持有观望")
    
    print()
    print(f"状态: {result['status']}")
    print("="*60)
    
    return result


if __name__ == '__main__':
    run_trading_cycle()
