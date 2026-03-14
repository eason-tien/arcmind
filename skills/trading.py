#!/usr/bin/env python3
"""
台股交易 Skill 实现
"""

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any

# 配置文件路径
BASE_DIR = Path(__file__).resolve().parent.parent
LEDGER_FILE = BASE_DIR / "台股模拟交易_交易台账.md"

# 交易费率
BROKERAGE_FEE_RATE = 0.001425  # 0.1425%
TAX_RATE = 0.003  # 0.3% 仅卖出

# 初始资金
INITIAL_CAPITAL = 50000


def get_current_state():
    """获取当前账户状态"""
    # 读取台账获取当前状态
    try:
        with open(LEDGER_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 解析当前现金
        lines = content.split('\n')
        cash = None
        total_asset = None
        
        for line in lines:
            if '现金' in line and 'TWD' in line:
                parts = line.split('|')
                for p in parts:
                    if 'TWD' in p:
                        cash = int(p.replace('TWD', '').replace(',', '').strip())
            if '总资产' in line and 'TWD' in line:
                parts = line.split('|')
                for p in parts:
                    if 'TWD' in p:
                        total_asset = int(p.replace('TWD', '').replace(',', '').strip())
        
        # 解析持仓
        positions = {}
        in_positions = False
        for line in lines:
            if '持仓明细' in line:
                in_positions = True
                continue
            if in_positions and '|' in line and '---' not in line:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 6 and parts[1] and parts[1] != '代码':
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
        
        return {
            'cash': cash or 31774,
            'total_asset': total_asset or 49974,
            'positions': positions
        }
    except Exception as e:
        print(f"读取台账错误: {e}")
        return {
            'cash': 31774,
            'total_asset': 49974,
            'positions': {
                '2408': {'name': '矽统', 'shares': 1000, 'avg_cost': 18.20}
            }
        }


def get_market_data():
    """获取市场数据 - 模拟真实数据"""
    # 模拟台股数据（实际应该连接真实API）
    # 价格波动基于随机漫步 + 行业趋势
    base_stocks = {
        '2408': {'name': '矽统', 'base_price': 18.20, 'volatility': 0.03},
        '2610': {'name': '華航', 'base_price': 18.60, 'volatility': 0.025},
        '2002': {'name': '中鋼', 'base_price': 19.20, 'volatility': 0.02},
        '2812': {'name': '台中銀', 'base_price': 20.90, 'volatility': 0.015},
        '2883': {'name': '開發金', 'base_price': 20.35, 'volatility': 0.02},
        '2884': {'name': '玉山金', 'base_price': 33.70, 'volatility': 0.018},
        '2409': {'name': '友達', 'base_price': 15.00, 'volatility': 0.028},
        '2317': {'name': '鴻海', 'base_price': 158.00, 'volatility': 0.022},
        '2454': {'name': '聯發科', 'base_price': 1420.00, 'volatility': 0.025},
        '3008': {'name': '大立光', 'base_price': 2890.00, 'volatility': 0.03},
    }
    
    market_data = {}
    for symbol, data in base_stocks.items():
        # 随机波动
        change_pct = random.gauss(0, data['volatility'])
        price = data['base_price'] * (1 + change_pct)
        market_data[symbol] = {
            'name': data['name'],
            'price': round(price, 2),
            'change': round(change_pct * 100, 2),
            'volume': random.randint(500000, 5000000)
        }
    
    return market_data


def calculate_pnl(state, market_data):
    """计算损益"""
    position_value = 0
    for symbol, pos in state['positions'].items():
        if symbol in market_data:
            price = market_data[symbol]['price']
            position_value += pos['shares'] * price
    
    total = state['cash'] + position_value
    pnl = total - INITIAL_CAPITAL
    pnl_pct = (pnl / INITIAL_CAPITAL) * 100
    
    return {
        'position_value': position_value,
        'total': total,
        'pnl': pnl,
        'pnl_pct': pnl_pct
    }


def analyze_positions(state, market_data):
    """分析持仓"""
    signals = []
    
    for symbol, pos in state['positions'].items():
        if symbol in market_data:
            current_price = market_data[symbol]['price']
            avg_cost = pos['avg_cost']
            pnl_pct = ((current_price - avg_cost) / avg_cost) * 100
            
            signal = {
                'symbol': symbol,
                'name': pos['name'],
                'shares': pos['shares'],
                'avg_cost': avg_cost,
                'current_price': current_price,
                'pnl_pct': pnl_pct,
                'action': 'HOLD'
            }
            
            # 止损/止盈判断
            if pnl_pct <= -7:
                signal['action'] = 'SELL (止损)'
            elif pnl_pct >= 15:
                signal['action'] = 'SELL (止盈)'
            elif pnl_pct >= 8:
                signal['action'] = '考虑卖出'
            
            signals.append(signal)
    
    return signals


def select_buy_candidates(state, market_data):
    """选择买入候选"""
    candidates = []
    available_cash = state['cash'] - 10000  # 保留10000现金
    
    for symbol, data in market_data.items():
        if symbol in state['positions']:
            continue  # 已持仓
            
        price = data['price']
        
        # 只考虑买得起的股票（每股价格 * 1000股 = 1张）
        if price <= 50:  # 铜板股
            max_shares = int(available_cash / price / 1000) * 1000
            if max_shares >= 1000:
                # 评分
                score = 0
                # 涨幅适中（不是大涨就是买）
                if 0 < data['change'] < 3:
                    score += 2
                # 成交量适中
                if 1000000 < data['volume'] < 3000000:
                    score += 1
                    
                candidates.append({
                    'symbol': symbol,
                    'name': data['name'],
                    'price': price,
                    'change': data['change'],
                    'max_shares': max_shares,
                    'score': score
                })
    
    # 按评分排序
    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:3]


def execute_trade(state, market_data):
    """执行交易决策"""
    pnl_info = calculate_pnl(state, market_data)
    position_signals = analyze_positions(state, market_data)
    
    decisions = []
    
    # 1. 检查是否需要卖出
    for signal in position_signals:
        if 'SELL' in signal['action']:
            # 模拟卖出
            proceeds = signal['shares'] * signal['current_price'] * (1 - BROKERAGE_FEE_RATE - TAX_RATE)
            decisions.append(f"卖出 {signal['symbol']} {signal['name']} {signal['shares']}股 @ {signal['current_price']}, 预估收入: {int(proceeds)}")
    
    # 2. 检查是否可以买入
    position_ratio = (pnl_info['position_value'] / pnl_info['total']) if pnl_info['total'] > 0 else 0
    
    if position_ratio < 0.6 and pnl_info['position_value'] + 10000 < INITIAL_CAPITAL * 0.6:
        candidates = select_buy_candidates(state, market_data)
        if candidates:
            best = candidates[0]
            shares = 1000  # 买1张
            cost = shares * best['price'] * (1 + BROKERAGE_FEE_RATE)
            decisions.append(f"买入 {best['symbol']} {best['name']} {shares}股 @ {best['price']}, 预估成本: {int(cost)}")
    
    return {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_assets': int(pnl_info['total']),
        'cash': state['cash'],
        'position_value': int(pnl_info['position_value']),
        'pnl': int(pnl_info['pnl']),
        'pnl_pct': round(pnl_info['pnl_pct'], 2),
        'position_ratio': round(position_ratio * 100, 1),
        'positions': position_signals,
        'decisions': decisions,
        'status': '交易完成'
    }


def trading_skill(input_data: dict = None) -> dict:
    """台股交易 Skill 主函数"""
    input_data = input_data or {}
    action = input_data.get('action', 'trade')
    
    # 获取当前状态
    state = get_current_state()
    market_data = get_market_data()
    
    if action == 'summary':
        pnl = calculate_pnl(state, market_data)
        return {
            'action': 'summary',
            'total_assets': int(pnl['total']),
            'cash': state['cash'],
            'position_value': int(pnl['position_value']),
            'pnl': int(pnl['pnl']),
            'pnl_pct': round(pnl['pnl_pct'], 2)
        }
    
    elif action == 'check_positions':
        signals = analyze_positions(state, market_data)
        return {
            'action': 'check_positions',
            'positions': signals
        }
    
    elif action == 'analyze':
        candidates = select_buy_candidates(state, market_data)
        signals = analyze_positions(state, market_data)
        pnl = calculate_pnl(state, market_data)
        return {
            'action': 'analyze',
            'market_snapshot': market_data,
            'positions': signals,
            'buy_candidates': candidates,
            'pnl': pnl
        }
    
    else:  # trade
        result = execute_trade(state, market_data)
        
        # 记录日志
        log_file = BASE_DIR / "logs" / f"trading_{datetime.now().strftime('%Y%m%d')}.log"
        log_file.parent.mkdir(exist_ok=True)
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n=== {result['timestamp']} ===\n")
            f.write(f"总资产: {result['total_assets']} | 现金: {result['cash']} | 持仓: {result['position_value']}\n")
            f.write(f"损益: {result['pnl']} ({result['pnl_pct']}%)\n")
            f.write(f"决策: {result['decisions']}\n")
        
        return result


if __name__ == '__main__':
    import sys
    
    # 解析命令行参数
    action = 'trade'
    if len(sys.argv) > 1:
        action = sys.argv[1]
    
    result = trading_skill({'action': action})
    print(json.dumps(result, ensure_ascii=False, indent=2))
