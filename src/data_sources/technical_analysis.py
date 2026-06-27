"""
Basic Technical Analysis Module
基础技术分析模块 - MA均线、成交量、支撑压力位、MACD、KDJ、RSI、布林带
"""

from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from src.data_sources.akshare_api import get_stock_history


class BasicTechnicalAnalysis:
    """基础技术分析 - MA均线、成交量、支撑压力位"""

    def __init__(self, stock_code: str, days: int = 100):
        self.stock_code = stock_code
        self.history = get_stock_history(stock_code, days=days)

    def analyze(self) -> Dict:
        """返回完整技术分析结果"""
        if not self.history:
            return {"error": "无法获取历史数据"}

        prices = [h['value'] for h in self.history]
        volumes = [h['volume'] for h in self.history]

        return {
            "ma_analysis": self._calculate_ma(prices),
            "volume_analysis": self._analyze_volume(volumes),
            "support_resistance": self._find_support_resistance(prices),
            "trend": self._determine_trend(prices),
            "price_position": self._analyze_price_position(prices)
        }

    def _calculate_ma(self, prices: List[float]) -> Dict:
        """计算MA均线"""
        def ma(data: List[float], period: int) -> Optional[float]:
            if len(data) < period:
                return None
            return round(sum(data[-period:]) / period, 2)

        if not prices:
            return {}

        current = prices[-1]
        ma5 = ma(prices, 5)
        ma10 = ma(prices, 10)
        ma20 = ma(prices, 20)
        ma60 = ma(prices, 60)

        # 判断均线排列
        ma_status = "中性"
        if ma5 and ma10 and ma20:
            if ma5 > ma10 > ma20:
                ma_status = "多头排列"
            elif ma5 < ma10 < ma20:
                ma_status = "空头排列"
            elif ma5 > ma20 and ma10 > ma20:
                ma_status = "偏多排列"
            elif ma5 < ma20 and ma10 < ma20:
                ma_status = "偏空排列"

        # 价格与均线关系
        price_vs_ma = []
        if ma5 and current > ma5:
            price_vs_ma.append("站上MA5")
        elif ma5:
            price_vs_ma.append("跌破MA5")
        if ma20 and current > ma20:
            price_vs_ma.append("站上MA20")
        elif ma20:
            price_vs_ma.append("跌破MA20")
        if ma60 and current > ma60:
            price_vs_ma.append("站上MA60")
        elif ma60:
            price_vs_ma.append("跌破MA60")

        return {
            "current_price": current,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "ma60": ma60,
            "ma_status": ma_status,
            "price_vs_ma": ", ".join(price_vs_ma) if price_vs_ma else "N/A",
            "ma5_distance": round((current - ma5) / ma5 * 100, 2) if ma5 else None,
            "ma20_distance": round((current - ma20) / ma20 * 100, 2) if ma20 else None,
        }

    def _analyze_volume(self, volumes: List[float]) -> Dict:
        """成交量分析"""
        if len(volumes) < 5:
            return {"volume_status": "数据不足"}

        today = volumes[-1]
        avg_5 = sum(volumes[-5:]) / 5
        avg_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else avg_5

        # 量能状态判断
        volume_status = "正常"
        ratio_5 = today / avg_5 if avg_5 else 1
        if ratio_5 > 2.5:
            volume_status = "大幅放量"
        elif ratio_5 > 1.5:
            volume_status = "明显放量"
        elif ratio_5 > 1.2:
            volume_status = "温和放量"
        elif ratio_5 < 0.5:
            volume_status = "大幅缩量"
        elif ratio_5 < 0.7:
            volume_status = "明显缩量"
        elif ratio_5 < 0.85:
            volume_status = "温和缩量"

        # 量能趋势（5日与20日对比）
        volume_trend = "平稳"
        if avg_5 > avg_20 * 1.3:
            volume_trend = "量能上升"
        elif avg_5 < avg_20 * 0.7:
            volume_trend = "量能萎缩"

        return {
            "today_volume": today,
            "avg_5_volume": round(avg_5, 0),
            "avg_20_volume": round(avg_20, 0),
            "volume_ratio_5": round(ratio_5, 2),
            "volume_status": volume_status,
            "volume_trend": volume_trend
        }

    def _find_support_resistance(self, prices: List[float]) -> Dict:
        """识别支撑压力位（简化版：近期高低点）"""
        if len(prices) < 20:
            return {"note": "数据不足"}

        recent_20 = prices[-20:]
        recent_60 = prices[-60:] if len(prices) >= 60 else prices

        current = prices[-1]

        # 近期高低点作为支撑压力
        high_20 = max(recent_20)
        low_20 = min(recent_20)
        high_60 = max(recent_60)
        low_60 = min(recent_60)

        # 整数关口（心理价位）
        round_levels = []
        base = int(current)
        for offset in range(-3, 4):
            level = base + offset
            if level > 0:
                round_levels.append(level)

        # 找出最近的支撑和压力
        nearest_support = low_20
        nearest_resistance = high_20

        # 计算距离
        distance_to_resistance = round((nearest_resistance - current) / current * 100, 2)
        distance_to_support = round((current - nearest_support) / current * 100, 2)

        return {
            "nearest_resistance": nearest_resistance,
            "nearest_support": nearest_support,
            "high_20d": high_20,
            "low_20d": low_20,
            "high_60d": high_60,
            "low_60d": low_60,
            "round_levels": round_levels,
            "distance_to_resistance_pct": distance_to_resistance,
            "distance_to_support_pct": distance_to_support,
            "risk_reward_ratio": round(distance_to_resistance / distance_to_support, 2) if distance_to_support > 0 else None
        }

    def _determine_trend(self, prices: List[float]) -> Dict:
        """判断趋势方向"""
        if len(prices) < 20:
            return {"trend": "数据不足"}

        current = prices[-1]
        price_5_ago = prices[-5] if len(prices) >= 5 else prices[0]
        price_10_ago = prices[-10] if len(prices) >= 10 else prices[0]
        price_20_ago = prices[-20]
        price_60_ago = prices[-60] if len(prices) >= 60 else prices[0]

        # 计算涨跌幅
        change_5d = round((current - price_5_ago) / price_5_ago * 100, 2)
        change_10d = round((current - price_10_ago) / price_10_ago * 100, 2)
        change_20d = round((current - price_20_ago) / price_20_ago * 100, 2)
        change_60d = round((current - price_60_ago) / price_60_ago * 100, 2) if len(prices) >= 60 else None

        # 趋势判断
        trend = "震荡"
        trend_strength = "弱"

        if change_20d > 10 and change_5d > 0:
            trend = "强势上涨"
            trend_strength = "强"
        elif change_20d > 5 and change_5d > -3:
            trend = "上涨趋势"
            trend_strength = "中"
        elif change_20d > 0:
            trend = "偏多震荡"
            trend_strength = "弱"
        elif change_20d < -10 and change_5d < 0:
            trend = "强势下跌"
            trend_strength = "强"
        elif change_20d < -5 and change_5d < 3:
            trend = "下跌趋势"
            trend_strength = "中"
        elif change_20d < 0:
            trend = "偏空震荡"
            trend_strength = "弱"

        return {
            "trend": trend,
            "trend_strength": trend_strength,
            "change_5d": change_5d,
            "change_10d": change_10d,
            "change_20d": change_20d,
            "change_60d": change_60d
        }

    def _analyze_price_position(self, prices: List[float]) -> Dict:
        """分析当前价格在区间内的位置"""
        if len(prices) < 60:
            recent = prices
        else:
            recent = prices[-60:]

        current = prices[-1]
        high = max(recent)
        low = min(recent)

        if high == low:
            position_pct = 50
        else:
            position_pct = round((current - low) / (high - low) * 100, 1)

        # 位置描述
        if position_pct >= 90:
            position_desc = "接近高点"
        elif position_pct >= 70:
            position_desc = "偏高位置"
        elif position_pct >= 50:
            position_desc = "中等偏上"
        elif position_pct >= 30:
            position_desc = "中等偏下"
        elif position_pct >= 10:
            position_desc = "偏低位置"
        else:
            position_desc = "接近低点"

        return {
            "current": current,
            "high_60d": high,
            "low_60d": low,
            "position_pct": position_pct,
            "position_desc": position_desc
        }


def format_technical_analysis(analysis: Dict) -> str:
    """将技术分析结果格式化为可读字符串"""
    if "error" in analysis:
        return f"技术分析失败: {analysis['error']}"

    output = []

    # 均线分析
    ma = analysis.get('ma_analysis', {})
    if ma:
        output.append("**均线系统:**")
        output.append(f"- 当前价格: {ma.get('current_price')}")
        output.append(f"- MA5: {ma.get('ma5')} | MA10: {ma.get('ma10')} | MA20: {ma.get('ma20')} | MA60: {ma.get('ma60')}")
        output.append(f"- 均线状态: {ma.get('ma_status')}")
        output.append(f"- 价格位置: {ma.get('price_vs_ma')}")

    # 成交量分析
    vol = analysis.get('volume_analysis', {})
    if vol:
        output.append("\n**成交量:**")
        output.append(f"- 今日成交量: {vol.get('today_volume'):,.0f}" if vol.get('today_volume') else "- 今日成交量: N/A")
        output.append(f"- 量比(vs 5日均量): {vol.get('volume_ratio_5')}")
        output.append(f"- 量能状态: {vol.get('volume_status')}")
        output.append(f"- 量能趋势: {vol.get('volume_trend')}")

    # 支撑压力
    sr = analysis.get('support_resistance', {})
    if sr and 'nearest_resistance' in sr:
        output.append("\n**支撑压力位:**")
        output.append(f"- 最近压力位: {sr.get('nearest_resistance')} (距离: +{sr.get('distance_to_resistance_pct')}%)")
        output.append(f"- 最近支撑位: {sr.get('nearest_support')} (距离: -{sr.get('distance_to_support_pct')}%)")
        output.append(f"- 20日高低: {sr.get('high_20d')} / {sr.get('low_20d')}")
        if sr.get('risk_reward_ratio'):
            output.append(f"- 风险收益比: 1:{sr.get('risk_reward_ratio')}")

    # 趋势
    trend = analysis.get('trend', {})
    if trend:
        output.append("\n**趋势判断:**")
        output.append(f"- 趋势方向: {trend.get('trend')} ({trend.get('trend_strength')})")
        output.append(f"- 5日涨跌: {trend.get('change_5d')}% | 20日涨跌: {trend.get('change_20d')}%")

    # 位置
    pos = analysis.get('price_position', {})
    if pos:
        output.append(f"\n**价格位置:** {pos.get('position_desc')} (60日区间内 {pos.get('position_pct')}%)")

    return "\n".join(output)


# ============================================================================
# 技术指标计算模块 - MACD, KDJ, RSI, BOLL
# ============================================================================

def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """
    计算RSI（相对强弱指标）

    Args:
        prices: 收盘价序列
        period: RSI周期，默认14

    Returns:
        RSI值序列
    """
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))

    return rsi


def calculate_macd(
    prices: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    计算MACD（指数平滑异同移动平均线）

    Args:
        prices: 收盘价序列
        fast_period: 快速EMA周期，默认12
        slow_period: 慢速EMA周期，默认26
        signal_period: 信号线周期，默认9

    Returns:
        (DIF, DEA, MACD) 元组
    """
    ema_fast = prices.ewm(span=fast_period, adjust=False).mean()
    ema_slow = prices.ewm(span=slow_period, adjust=False).mean()

    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal_period, adjust=False).mean()
    macd = (dif - dea) * 2

    return dif, dea, macd


def calculate_kdj(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 9,
    m1: int = 3,
    m2: int = 3
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    计算KDJ（随机指标）

    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        n: RSV周期，默认9
        m1: K值平滑周期，默认3
        m2: D值平滑周期，默认3

    Returns:
        (K, D, J) 元组
    """
    lowest_low = low.rolling(window=n, min_periods=1).min()
    highest_high = high.rolling(window=n, min_periods=1).max()

    rsv = (close - lowest_low) / (highest_high - lowest_low) * 100
    rsv = rsv.fillna(50)

    k = rsv.ewm(com=m1 - 1, adjust=False).mean()
    d = k.ewm(com=m2 - 1, adjust=False).mean()
    j = 3 * k - 2 * d

    return k, d, j


def calculate_bollinger_bands(
    prices: pd.Series,
    period: int = 20,
    num_std: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    计算布林带（BOLL）

    Args:
        prices: 收盘价序列
        period: 中轨周期，默认20
        num_std: 标准差倍数，默认2

    Returns:
        (upper, mid, lower) 元组
    """
    mid = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std

    return upper, mid, lower


def compute_technical_factors_from_history(
    code: str,
    days: int = 60
) -> Optional[pd.DataFrame]:
    """
    从历史K线数据计算技术指标（MACD, KDJ, RSI, BOLL）
    作为TuShare stk_factor API的备用方案

    Args:
        code: 股票代码
        days: 获取的交易日天数，默认60

    Returns:
        DataFrame，格式与TuShare stk_factor一致：
        ts_code, trade_date, close, macd_dif, macd_dea, macd,
        kdj_k, kdj_d, kdj_j, rsi_6, rsi_12, rsi_24, boll_upper, boll_mid, boll_lower
    """
    try:
        import akshare as ak
        from datetime import datetime, timedelta

        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days + 50)).strftime('%Y%m%d')

        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq"
        )

        if df is None or df.empty or len(df) < 30:
            return None

        df = df.sort_values('日期').reset_index(drop=True)

        close = pd.to_numeric(df['收盘'], errors='coerce')
        high = pd.to_numeric(df['最高'], errors='coerce')
        low = pd.to_numeric(df['最低'], errors='coerce')

        dif, dea, macd = calculate_macd(close)
        k, d, j = calculate_kdj(high, low, close)
        rsi_6 = calculate_rsi(close, 6)
        rsi_12 = calculate_rsi(close, 12)
        rsi_24 = calculate_rsi(close, 24)
        boll_upper, boll_mid, boll_lower = calculate_bollinger_bands(close)

        result = pd.DataFrame({
            'ts_code': code,
            'trade_date': df['日期'].astype(str).str.replace('-', ''),
            'close': close,
            'macd_dif': dif,
            'macd_dea': dea,
            'macd': macd,
            'kdj_k': k,
            'kdj_d': d,
            'kdj_j': j,
            'rsi_6': rsi_6,
            'rsi_12': rsi_12,
            'rsi_24': rsi_24,
            'boll_upper': boll_upper,
            'boll_mid': boll_mid,
            'boll_lower': boll_lower,
        })

        result = result.sort_values('trade_date', ascending=False).head(days).reset_index(drop=True)

        return result

    except Exception as e:
        print(f"Error computing technical factors from history for {code}: {e}")
        import traceback
        traceback.print_exc()
        return None
