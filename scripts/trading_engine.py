#!/usr/bin/env python3
"""
台股真实规则模拟交易系统 - 核心引擎
目标：自主执行交易，获益率8%以上
"""

import os
import sys
import json
import time
import random
from datetime import datetime, timedelta
from pathlib import Path

# 配置
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LEDGER_FILE = DATA_DIR / "台股模拟交易_交易台账.md"
DECISION_FILE = DATA_DIR / "交易决策记录.md"
CONFIG_FILE = DATA_DIR / "交易配置.json"

# 交易费率
BROKERAGE_FEE_RATE = 0.001425  # 0.1425%
TAX_RATE = 0.003  # 0.3% 仅卖出

# 初始资金
INITIAL_CAPITAL = 50000

# 交易规则
MAX_POSITION_RATIO = 0.6  # 最大仓位60%
MIN_CASH_RESERVE = 10000  # 最低现金储备
STOP_LOSS_RATIO = -0.07  # 止损线 -7%
TAKE_PROFIT_RATIO = 0.15  # 止盈线 +15%

class TradingEngine:
    def __init__(self):
        self.ledger = self._load_ledger()
        self.current_capital = self.ledger.get('current_capital', INITIAL_CAPITAL)
        self.positions = self.ledger.get('positions', {})
        self.trade_history = self.ledger.get('trade_history', [])
        
    def _load_ledger(self):
        """加载台账数据"""
        # 这里从文件读取或初始化
        return {
            'current_capital': 31774,
            'positions': {
                '2408': {
                    'name': '矽统',
                    'shares': 1000,
                    'avg_cost': 18.20,
                    'current_price': 18.20
                }
            },
            'trade_history': [],
            'total_asset': 49974
        }
    
    def _save_ledger(self):
        """保存台账"""
        # 保存到文件
        pass
    
    def get_market_data(self):
        """获取市场数据 - 这里应该连接真实API"""
        # 模拟获取台股数据
        # 实际应该使用 TaiwanStockAPI 或类似库
        return {
            '2408': {'price': 18.50, 'change': 1.65, 'volume': 1500000},
            '2610': {'price': 18.80, 'change': 1.08, 'volume': 2000000},
            '2002': {'price': 19.50, 'change': 1.56, 'volume': 800000},
            '2812': {'price': 21.00, 'change': 0.48, 'volume': 500000},
            '2883': {'price': 20.50, 'change': 0.74, 'volume': 3000000},
            '2409': {'price': 15.20, 'change': 1.33, 'volume': 1200000},
            '2884': {'price': 34.00, 'change': 0.89, 'volume': 2500000},
        }
    
    def analyze_stock(self, symbol, market_data):
        """分析个股"""
        stock = market_data.get(symbol, {})
        price = stock.get('price', 0)
        change = stock.get('change', 0)
        
        if symbol in self.positions:
            position = self.positions[symbol]
            cost = position['avg_cost']
            pnl_ratio = (price - cost) / cost
            
            return {
                'symbol': symbol,
                'price': price,
                'change': change,
                'pnl_ratio': pnl_ratio,
                'should_sell': pnl_ratio <= STOP_LOSS_RATIO or pnl_ratio >= TAKE_PROFIT_RATIO,
                'should_hold': -STOP_LOSS_RATIO < pnl_ratio < TAKE_PROFIT_RATIO
            }
        
        return {
            'symbol': symbol,
            'price': price,
            'change': change,
            'pnl_ratio': 0,
            'should_buy': True,
            'can_buy': price <= (self.current_capital * MAX_POSITION_RATIO / 1000)
        }
    
    def calculate_buy_cost(self, price, shares):
        """计算买入成本"""
        amount = price * shares
        fee = amount * BROKERAGE_FEE_RATE
        return amount + fee
    
    def calculate_sell_proceeds(self, price, shares):
        """计算卖出所得"""
        amount = price * shares
        fee = amount * BROKERAGE_FEE_RATE
        tax = amount * TAX_RATE
        return amount - fee - tax
    
    def execute_buy(self, symbol, name, price, shares):
        """执行买入"""
        cost = self.calculate_buy_cost(price, shares)
        
        if cost > self.current_capital:
            return {'success': False, 'reason': '资金不足'}
        
        self.current_capital -= cost
        
        if symbol in self.positions:
            old_shares = self.positions[symbol]['shares']
            old_cost = self.positions[symbol]['avg_cost'] * old_shares
            new_shares = old_shares + shares
            new_cost = (old_cost + price * shares) / new_shares
            self.positions[symbol] = {
                'name': name,
                'shares': new_shares,
                'avg_cost': new_cost,
                'current_price': price
            }
        else:
            self.positions[symbol] = {
                'name': name,
                'shares': shares,
                'avg_cost': price,
                'current_price': price
            }
        
        self.trade_history.append({
            'time': datetime.now().isoformat(),
            'symbol': symbol,
            'action': 'BUY',
            'price': price,
            'shares': shares,
            'amount': cost
        })
        
        return {'success': True, 'cost': cost}
    
    def execute_sell(self, symbol, price, shares=None):
        """执行卖出"""
        if symbol not in self.positions:
            return {'success': False, 'reason': '无持仓'}
        
        position = self.positions[symbol]
        sell_shares = shares or position['shares']
        
        proceeds = self.calculate_sell_proceeds(price, sell_shares)
        self.current_capital += proceeds
        
        new_shares = position['shares'] - sell_shares
        if new_shares > 0:
            self.positions[symbol] = {
                'name': position['name'],
                'shares': new_shares,
                'avg_cost': position['avg_cost'],
                'current_price': price
            }
        else:
            del self.positions[symbol]
        
        self.trade_history.append({
            'time': datetime.now().isoformat(),
            'symbol': symbol,
            'action': 'SELL',
            'price': price,
            'shares': sell_shares,
            'proceeds': proceeds
        })
        
        return {'success': True, 'proceeds': proceeds}
    
    def get_total_assets(self, market_data):
        """计算总资产"""
        position_value = 0
        for symbol, position in self.positions.items():
            price = market_data.get(symbol, {}).get('price', position['current_price'])
            position_value += position['shares'] * price
        return self.current_capital + position_value
    
    def make_trading_decision(self):
        """做出交易决策"""
        market_data = self.get_market_data()
        total_assets = self.get_total_assets(market_data)
        pnl_ratio = (total_assets - INITIAL_CAPITAL) / INITIAL_CAPITAL
        
        decisions = []
        
        # 1. 检查是否需要止损/止盈
        for symbol, position in list(self.positions.items()):
            analysis = self.analyze_stock(symbol, market_data)
            if analysis['should_sell']:
                proceeds = self.execute_sell(symbol, analysis['price'])
                if proceeds['success']:
                    decisions.append(f"卖出 {symbol}，收益率: {analysis['pnl_ratio']*100:.2f}%")
        
        # 2. 检查是否需要加仓
        position_ratio = (total_assets - self.current_capital) / total_assets
        if position_ratio < MAX_POSITION_RATIO and self.current_capital > MIN_CASH_RESERVE:
            # 寻找可买入的标的
            available_stocks = [s for s in market_data.keys() if s not in self.positions]
            if available_stocks:
                # 简单策略：选择涨幅居中且成交量较大的
                candidate = random.choice(available_stocks[:3])
                price = market_data[candidate]['price']
                max_shares = int((self.current_capital - MIN_CASH_RESERVE) / price / 1000) * 1000
                if max_shares >= 1000:
                    result = self.execute_buy(candidate, f"股票{candidate}", price, 1000)
                    if result['success']:
                        decisions.append(f"买入 {candidate} 1张 @ {price}")
        
        return {
            'total_assets': total_assets,
            'pnl_ratio': pnl_ratio,
            'decisions': decisions,
            'positions': self.positions,
            'cash': self.current_capital
        }
    
    def run_daily_check(self):
        """每日运行检查"""
        now = datetime.now()
        
        # 检查是否为交易时间（台股交易时段：9:00-13:30）
        if now.hour < 9 or now.hour > 14:
            return {'status': 'outside_trading_hours'}
        
        decision = self.make_trading_decision()
        return decision


def main():
    engine = TradingEngine()
    result = engine.run_daily_check()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
