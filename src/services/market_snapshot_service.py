"""
Market Snapshot Service

Pre-generates market overview text so AI assistant can answer quickly
without calling multiple tools. Updates periodically via scheduler.
"""
import time
import json
import threading
from datetime import datetime
from typing import Dict, Any, Optional

from src.analysis.dashboard import DashboardService


class MarketSnapshotService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._snapshot = None
                    cls._instance._snapshot_time = None
                    cls._instance._snapshot_data = None
                    cls._instance._cache_ttl = 300  # 5 minutes
        return cls._instance

    def _get_dashboard_service(self) -> DashboardService:
        return DashboardService(".")

    def get_snapshot(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Get current market snapshot (text + raw data)."""
        now = time.time()

        if (not force_refresh
                and self._snapshot is not None
                and self._snapshot_time is not None
                and (now - self._snapshot_time) < self._cache_ttl):
            return self._snapshot

        return self._generate_snapshot()

    def get_snapshot_text(self) -> str:
        """Get market snapshot as text (for AI assistant)."""
        snapshot = self.get_snapshot()
        return snapshot.get("text", "")

    def get_snapshot_data(self) -> Dict[str, Any]:
        """Get raw snapshot data."""
        snapshot = self.get_snapshot()
        return snapshot.get("data", {})

    def _generate_snapshot(self) -> Dict[str, Any]:
        """Generate market snapshot from dashboard data."""
        try:
            service = self._get_dashboard_service()
            dashboard_data = service.get_full_dashboard()

            market_overview = dashboard_data.get("market_overview", {})
            sectors = dashboard_data.get("sectors", {})
            top_flows = dashboard_data.get("top_flows", [])
            abnormal = dashboard_data.get("abnormal_movements", [])

            breadth = market_overview.get("breadth", {})
            turnover = market_overview.get("turnover", {})
            main_flow = market_overview.get("main_flow", 0)

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

            text_parts = [f"【市场快照 - {now_str}】", ""]

            # Market breadth
            up = breadth.get("up", 0)
            down = breadth.get("down", 0)
            flat = breadth.get("flat", 0)
            limit_up = breadth.get("limit_up", 0)
            limit_down = breadth.get("limit_down", 0)
            total_stocks = up + down + flat

            text_parts.append(f"市场涨跌：上涨 {up} 家，下跌 {down} 家，平盘 {flat} 家")
            text_parts.append(f"涨停 {limit_up} 家，跌停 {limit_down} 家")

            if total_stocks > 0:
                up_ratio = round(up / total_stocks * 100, 1)
                text_parts.append(f"上涨比例：{up_ratio}%")

            # Turnover
            turnover_total = turnover.get("total", 0)
            if turnover_total:
                text_parts.append(f"两市成交额：{turnover_total} 亿")

            # Main capital flow
            if main_flow:
                flow_str = f"+{main_flow}" if main_flow > 0 else str(main_flow)
                text_parts.append(f"主力资金净流入：{flow_str} 亿")

            text_parts.append("")

            # Top sectors
            gainers = sectors.get("gainers", [])
            losers = sectors.get("losers", [])

            if gainers:
                text_parts.append("【领涨板块】")
                for i, s in enumerate(gainers[:5]):
                    name = s.get("name", "")
                    change = s.get("change", 0)
                    text_parts.append(f"  {i+1}. {name} +{change}%")
                text_parts.append("")

            if losers:
                text_parts.append("【领跌板块】")
                for i, s in enumerate(losers[:5]):
                    name = s.get("name", "")
                    change = s.get("change", 0)
                    text_parts.append(f"  {i+1}. {name} {change}%")
                text_parts.append("")

            # Top capital flow stocks
            if top_flows:
                text_parts.append("【主力资金净流入 Top5】")
                for i, stock in enumerate(top_flows[:5]):
                    name = stock.get("name", "")
                    code = stock.get("code", "")
                    net_buy = stock.get("net_buy", 0)
                    change_pct = stock.get("change_pct", 0)
                    text_parts.append(f"  {i+1}. {name}({code}) 净流入 {net_buy}亿 涨{change_pct}%")
                text_parts.append("")

            # Abnormal movements summary
            if abnormal:
                limit_up_list = [m for m in abnormal if "涨停" in m.get("type", "")]
                limit_down_list = [m for m in abnormal if "跌停" in m.get("type", "")]
                rocket_list = [m for m in abnormal if "拉升" in m.get("type", "")]
                dive_list = [m for m in abnormal if "跳水" in m.get("type", "")]

                text_parts.append("【异动速递】")
                if limit_up_list:
                    text_parts.append(f"  封涨停：{len(limit_up_list)} 只")
                if limit_down_list:
                    text_parts.append(f"  封跌停：{len(limit_down_list)} 只")
                if rocket_list:
                    text_parts.append(f"  火箭发射：{len(rocket_list)} 只")
                if dive_list:
                    text_parts.append(f"  高台跳水：{len(dive_list)} 只")

            snapshot_text = "\n".join(text_parts)

            snapshot = {
                "text": snapshot_text,
                "data": dashboard_data,
                "generated_at": now_str,
                "timestamp": time.time()
            }

            self._snapshot = snapshot
            self._snapshot_time = time.time()
            self._snapshot_data = dashboard_data

            print(f"[MarketSnapshot] Generated at {now_str}")
            return snapshot

        except Exception as e:
            print(f"[MarketSnapshot] Error generating snapshot: {e}")
            import traceback
            traceback.print_exc()

            fallback = {
                "text": f"【市场快照 - {datetime.now().strftime('%Y-%m-%d %H:%M')}】\n数据加载中...",
                "data": {},
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "timestamp": time.time()
            }
            return fallback

    def refresh(self) -> bool:
        """Force refresh snapshot."""
        try:
            self._generate_snapshot()
            return True
        except Exception as e:
            print(f"[MarketSnapshot] Refresh failed: {e}")
            return False


market_snapshot_service = MarketSnapshotService()
