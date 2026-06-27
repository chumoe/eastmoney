"""
Stock Analyst - 个股分析
=========================
复用 StrategyFactory 中的 StockStrategy 完成个股分析。
支持盘前分析 (pre) 和盘后复盘 (post)。
"""

import os
from datetime import datetime
from typing import Dict, Optional

from src.analysis.base_analyst import BaseAnalyst
from src.analysis.strategies.factory import StrategyFactory


class StockAnalyst(BaseAnalyst):
    """
    个股分析师 - 委托给 StockStrategy 完成具体分析。
    """

    SYSTEM_TITLE = "个股分析系统启动"
    FAILURE_SUFFIX = "分析失败"

    def __init__(self):
        # 不调用 super().__init__()，避免加载基金列表
        # 只初始化我们需要的组件
        from src.data_sources.web_search import WebSearch
        from src.llm.client import get_llm_client

        self.web_search = WebSearch()
        self.llm = get_llm_client()
        self.today = datetime.now().strftime("%Y-%m-%d")
        self.sources = []

    def analyze(
        self,
        stock_code: str,
        mode: str = 'pre',
        user_id: int = None,
        stock_name: str = None,
        report_dir: str = None,
    ) -> str:
        """
        分析单只股票。

        Args:
            stock_code: 股票代码
            mode: 分析模式 - 'pre' 盘前 / 'post' 盘后
            user_id: 用户ID（用于报告存储路径）
            stock_name: 股票名称（可选，自动获取）
            report_dir: 报告保存目录（可选，默认按 user_id 计算）

        Returns:
            分析报告 markdown 字符串
        """
        mode_label = "盘前分析" if mode == 'pre' else "盘后复盘"

        # 如果没有股票名称，尝试从行情获取
        if not stock_name:
            stock_name = self._get_stock_name(stock_code)

        print(f"\n{'=' * 60}")
        print(f"🔍 {mode_label}: {stock_name} ({stock_code})")
        print(f"{'=' * 60}")

        stock_info = {
            "code": stock_code,
            "name": stock_name or stock_code,
            "type": "stock",
        }

        try:
            # 1. 获取策略
            strategy = StrategyFactory.get_strategy(stock_info, self.llm, self.web_search)

            # 2. 采集数据
            data = strategy.collect_data(mode=mode)

            # 3. 生成报告
            report = strategy.generate_report(mode=mode, data=data)

            print("  ✅ 分析完成")

            # 4. 保存报告到文件
            if report_dir is None and user_id is not None:
                from app.core.dependencies import get_user_report_dir
                user_dir = get_user_report_dir(user_id)
                report_dir = os.path.join(user_dir, "stocks")

            if report_dir:
                self._save_report(stock_code, stock_name or stock_code, mode, report, report_dir)

            return report

        except Exception as e:
            print(f"  ❌ {self.FAILURE_SUFFIX}: {e}")
            import traceback
            traceback.print_exc()
            return f"## {stock_name or stock_code} {self.FAILURE_SUFFIX}\n\n错误: {str(e)}"

    def _get_stock_name(self, code: str) -> str:
        """从实时行情获取股票名称"""
        try:
            from src.data_sources.akshare_api import get_stock_realtime_quote
            quote = get_stock_realtime_quote(code)
            if quote and quote.get('名称'):
                return str(quote['名称'])
        except Exception:
            pass
        return code

    def _save_report(self, code: str, name: str, mode: str, report: str, report_dir: str):
        """将报告保存为 markdown 文件"""
        try:
            os.makedirs(report_dir, exist_ok=True)
            today = datetime.now().strftime("%Y-%m-%d")
            filename = f"{today}_{mode}_{code}_{name}.md"
            filepath = os.path.join(report_dir, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(report)

            print(f"  💾 报告已保存: {filepath}")
        except Exception as e:
            print(f"  ⚠️  保存报告失败: {e}")
