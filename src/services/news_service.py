"""
News Service - Personalized News Aggregation Center

Provides unified news fetching, personalization, and AI analysis.
Integrates TuShare (primary), AkShare (fallback), and Tavily (research).
"""

import hashlib
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum
import json

# Import data sources
from src.data_sources.tushare_client import (
    tushare_call_with_retry,
    normalize_ts_code,
    denormalize_ts_code,
    format_date_yyyymmdd,
)
from src.data_sources.rate_limiter import rate_limiter
from src.data_sources.circuit_breaker import circuit_breaker

# Import database operations
from src.storage.db import (
    get_news_cache,
    set_news_cache,
    get_news_analysis,
    save_news_analysis,
    get_multiple_news_analysis,
    get_user_read_news_hashes,
    get_user_bookmarked_news,
    mark_news_read,
    toggle_news_bookmark,
    set_news_bookmark,
    get_news_status,
    get_all_stocks,
    get_all_funds,
)

# Import LLM client
from src.llm.client import get_llm_client

# Import settings
from config.settings import TAVILY_API_KEY

# Optional HTTP client for fallback news (used when AkShare fails)
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


def _fetch_news_via_http(url: str, headers: dict = None, timeout: float = 10.0) -> Optional[dict]:
    """
    Fetch JSON data from HTTP endpoint with timeout and error handling.
    Used as fallback when AkShare news functions fail.
    """
    if not HTTPX_AVAILABLE:
        return None
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers or {})
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None


class NewsCategory(str, Enum):
    """News categories for filtering"""
    ALL = "all"
    REALTIME = "realtime"      # 实时快讯 (全球财经快讯)
    MORNING = "morning"        # 财经早餐
    FLASH = "flash"            # 自选股快讯
    FUND = "fund"              # 自选基金
    ANNOUNCEMENT = "announcement"  # 公告公示
    RESEARCH = "research"      # 研报速递
    HOT = "hot"                # 热门资讯
    INDUSTRY = "industry"      # 行业资讯


@dataclass
class NewsCacheConfig:
    """Cache configuration for news types"""
    ttl: int  # Time to live in seconds
    api_name: str


# Cache configurations
NEWS_CACHE_CONFIG = {
    NewsCategory.ALL: NewsCacheConfig(ttl=300, api_name="news_all"),
    NewsCategory.REALTIME: NewsCacheConfig(ttl=180, api_name="news_realtime"),  # 3 min TTL for realtime
    NewsCategory.MORNING: NewsCacheConfig(ttl=3600, api_name="news_morning"),  # 1 hour TTL for daily briefing
    NewsCategory.FLASH: NewsCacheConfig(ttl=300, api_name="news_flash"),
    NewsCategory.FUND: NewsCacheConfig(ttl=600, api_name="news_fund"),
    NewsCategory.ANNOUNCEMENT: NewsCacheConfig(ttl=1800, api_name="news_announcement"),
    NewsCategory.RESEARCH: NewsCacheConfig(ttl=3600, api_name="news_research"),
    NewsCategory.HOT: NewsCacheConfig(ttl=300, api_name="news_hot"),
    NewsCategory.INDUSTRY: NewsCacheConfig(ttl=600, api_name="news_industry"),
}


def generate_news_hash(title: str, source: str, datetime_str: str = None) -> str:
    """Generate a unique hash for a news item"""
    content = f"{title}:{source}"
    if datetime_str:
        content += f":{datetime_str}"
    return hashlib.md5(content.encode()).hexdigest()[:16]


class NewsService:
    """
    Unified News Aggregation Service

    Features:
    - Multi-source news fetching (TuShare, AkShare, Tavily)
    - Personalized news based on user watchlist
    - AI-powered sentiment analysis and summarization
    - Caching with configurable TTL
    - User read/bookmark status tracking
    """

    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # key -> (data, expiry_time)
        self._cache_lock = threading.Lock()
        self._llm_client = None
        self._tavily_client = None

    def _get_llm_client(self):
        """Lazy initialization of LLM client"""
        if self._llm_client is None:
            try:
                self._llm_client = get_llm_client()
            except Exception as e:
                print(f"Warning: LLM client initialization failed: {e}")
        return self._llm_client

    def _get_tavily_client(self):
        """Lazy initialization of Tavily client"""
        if self._tavily_client is None and TAVILY_API_KEY:
            try:
                from tavily import TavilyClient
                self._tavily_client = TavilyClient(api_key=TAVILY_API_KEY)
            except Exception as e:
                print(f"Warning: Tavily client initialization failed: {e}")
        return self._tavily_client

    def _get_cache(self, key: str) -> Optional[Any]:
        """Get data from memory cache if not expired"""
        with self._cache_lock:
            if key in self._cache:
                data, expiry = self._cache[key]
                if time.time() < expiry:
                    return data
                del self._cache[key]
        return None

    def _set_cache(self, key: str, data: Any, ttl: int):
        """Set data in memory cache with TTL"""
        with self._cache_lock:
            self._cache[key] = (data, time.time() + ttl)

    # =========================================================================
    # Core News Fetching Methods
    # =========================================================================

    def _fetch_hot_news_from_eastmoney(self, limit: int = 30) -> List[Dict]:
        """
        Fetch hot news directly from Eastmoney API.
        Used as fallback when both TuShare and AkShare fail.
        """
        news_list = []

        try:
            # Eastmoney hot news API (global finance)
            url = "https://newsapi.eastmoney.com/kuaixun/v1/getlist_101_ajaxResult_50_1_.html"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://finance.eastmoney.com/",
            }
            data = _fetch_news_via_http(url, headers)
            if data and data.get("LivesList"):
                for item in data["LivesList"][:limit]:
                    title = item.get("title", "")
                    content = item.get("digest", "") or item.get("title", "")
                    pub_time = item.get("showtime", "") or item.get("ctime", "")

                    if not title or len(title) < 5:
                        continue

                    news_list.append({
                        "id": generate_news_hash(title, 'eastmoney', pub_time),
                        "title": title,
                        "content": content[:500],
                        "source": "eastmoney",
                        "source_name": "东方财富",
                        "category": "hot",
                        "published_at": str(pub_time),
                        "url": item.get("url", ""),
                    })
        except Exception as e:
            print(f"Eastmoney news fallback error: {e}")

        return news_list

    def get_hot_news(self, limit: int = 30) -> List[Dict]:
        """
        Get hot/trending news from TuShare major_news.

        Falls back to AkShare stock_info_global_cls if TuShare fails.
        """
        cache_key = f"hot_news:{limit}"
        config = NEWS_CACHE_CONFIG[NewsCategory.HOT]

        # Check memory cache
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        # Check database cache
        db_cached = get_news_cache(cache_key)
        if db_cached and db_cached.get('data'):
            self._set_cache(cache_key, db_cached['data'], 60)  # Short memory cache
            return db_cached['data']

        news_list = []

        # Try TuShare major_news first
        try:
            if not circuit_breaker.is_open("major_news"):
                end_date = format_date_yyyymmdd()
                start_date = format_date_yyyymmdd(datetime.now() - timedelta(days=1))

                df = tushare_call_with_retry('major_news', src='', start_date=start_date, end_date=end_date)

                if df is not None and not df.empty:
                    circuit_breaker.record_success("major_news")
                    for _, row in df.head(limit).iterrows():
                        news_list.append({
                            "id": generate_news_hash(row.get('title', ''), 'tushare', str(row.get('pub_time', ''))),
                            "title": row.get('title', ''),
                            "content": row.get('content', '')[:500] if row.get('content') else '',
                            "source": "tushare",
                            "source_name": row.get('src', '主流媒体'),
                            "category": "hot",
                            "published_at": str(row.get('pub_time', '')),
                            "url": row.get('url', ''),
                        })
                else:
                    circuit_breaker.record_failure("major_news")
        except Exception as e:
            print(f"TuShare major_news error: {e}")
            circuit_breaker.record_failure("major_news")

        # Fallback to AkShare if needed
        if not news_list:
            try:
                import akshare as ak
                df = ak.stock_info_global_cls()
                if df is not None and not df.empty:
                    for _, row in df.head(limit).iterrows():
                        title = str(row.iloc[0]).strip() if len(row) > 0 else ''
                        content = str(row.iloc[1]).strip() if len(row) > 1 else ''
                        pub_time = str(row.iloc[3]).strip() if len(row) > 3 else ''

                        if len(content) < 5:
                            continue

                        news_list.append({
                            "id": generate_news_hash(title, 'akshare', pub_time),
                            "title": title,
                            "content": content[:500],
                            "source": "akshare",
                            "source_name": "财联社",
                            "category": "hot",
                            "published_at": pub_time,
                            "url": "",
                        })
            except Exception as e:
                # Don't print 404 errors - they indicate the external API has changed
                # This is a known issue with AkShare news functions
                if "404" not in str(e):
                    print(f"AkShare news fallback error: {e}")

        # Second fallback: Try Eastmoney directly
        if not news_list:
            news_list = self._fetch_hot_news_from_eastmoney(limit)

        # Cache results
        if news_list:
            self._set_cache(cache_key, news_list, config.ttl)
            set_news_cache(cache_key, news_list, "mixed", config.ttl)

        return news_list

    def _fetch_realtime_news_from_eastmoney(self, limit: int = 50) -> List[Dict]:
        """
        Fetch realtime news directly from Eastmoney API.
        """
        news_list = []
        try:
            # Eastmoney realtime news API
            url = "https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://finance.eastmoney.com/",
            }
            data = _fetch_news_via_http(url, headers)
            if data and data.get("LivesList"):
                for item in data["LivesList"][:limit]:
                    title = item.get("title", "")
                    content = item.get("digest", "") or item.get("title", "")
                    pub_time = item.get("showtime", "") or item.get("ctime", "")

                    if not title or len(title) < 5:
                        continue

                    news_list.append({
                        "id": generate_news_hash(title, 'realtime_eastmoney', pub_time),
                        "title": title,
                        "content": content[:500],
                        "source": "eastmoney",
                        "source_name": "东方财富",
                        "category": "realtime",
                        "published_at": str(pub_time),
                        "url": item.get("url", ""),
                    })
        except Exception as e:
            print(f"Eastmoney realtime news fallback error: {e}")
        return news_list

    def get_realtime_news(self, limit: int = 50) -> List[Dict]:
        """
        Get realtime global financial news.

        Uses AkShare stock_info_global_em first, falls back to Eastmoney direct API.
        """
        cache_key = f"realtime_news:{limit}"
        config = NEWS_CACHE_CONFIG[NewsCategory.REALTIME]

        # Check memory cache
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        news_list = []

        try:
            import akshare as ak

            # Get global financial news (latest 200)
            df = ak.stock_info_global_em()
            if df is not None and not df.empty:
                for _, row in df.head(limit).iterrows():
                    title = str(row.get('标题', '')).strip()
                    content = str(row.get('摘要', '')).strip()
                    pub_time = str(row.get('发布时间', '')).strip()
                    url = str(row.get('链接', '')).strip()

                    if not title or len(title) < 5:
                        continue

                    news_list.append({
                        "id": generate_news_hash(title, 'realtime', pub_time),
                        "title": title,
                        "content": content[:500] if content else '',
                        "source": "akshare",
                        "source_name": "东方财富",
                        "category": "realtime",
                        "published_at": pub_time,
                        "url": url,
                    })
        except Exception as e:
            if "404" not in str(e):
                print(f"Realtime news fetch error: {e}")

        # Fallback to Eastmoney directly if AkShare fails
        if not news_list:
            news_list = self._fetch_realtime_news_from_eastmoney(limit)

        # Cache results
        if news_list:
            self._set_cache(cache_key, news_list, config.ttl)
            set_news_cache(cache_key, news_list, "mixed", config.ttl)

        return news_list

    def get_morning_briefing(self, limit: int = 10) -> List[Dict]:
        """
        Get morning financial briefing from AkShare.
        
        Uses stock_info_cjzc_em (东方财富-财经早餐) and filters to only show today's data.
        This data is updated daily around 6am.
        """
        cache_key = f"morning_briefing:{limit}"
        config = NEWS_CACHE_CONFIG[NewsCategory.MORNING]

        # Check memory cache
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        news_list = []

        try:
            import akshare as ak
            
            # Get morning briefing (returns all historical, need to filter)
            df = ak.stock_info_cjzc_em()
            if df is not None and not df.empty:
                # Filter to today only
                today = datetime.now().strftime('%Y-%m-%d')
                
                for _, row in df.iterrows():
                    title = str(row.get('标题', '')).strip()
                    content = str(row.get('摘要', '')).strip()
                    pub_time = str(row.get('发布时间', '')).strip()
                    url = str(row.get('链接', '')).strip()

                    # Only include today's briefing
                    if not pub_time.startswith(today):
                        continue

                    if not title:
                        continue

                    news_list.append({
                        "id": generate_news_hash(title, 'morning', pub_time),
                        "title": title,
                        "content": content[:2000] if content else '',  # Morning briefing has longer content
                        "source": "akshare",
                        "source_name": "东方财富财经早餐",
                        "category": "morning",
                        "published_at": pub_time,
                        "url": url,
                        "importance": "high",
                    })

                    if len(news_list) >= limit:
                        break

        except Exception as e:
            print(f"Morning briefing fetch error: {e}")

        # Cache results
        if news_list:
            self._set_cache(cache_key, news_list, config.ttl)
            set_news_cache(cache_key, news_list, "akshare", config.ttl)

        return news_list

    def get_stock_news(self, stock_codes: List[str], limit: int = 20) -> List[Dict]:
        """
        Get news related to specific stocks.

        Uses TuShare news API with stock filtering.
        """
        if not stock_codes:
            return []

        cache_key = f"stock_news:{','.join(sorted(stock_codes[:5]))}:{limit}"
        config = NEWS_CACHE_CONFIG[NewsCategory.FLASH]

        cached = self._get_cache(cache_key)
        if cached:
            return cached

        news_list = []

        try:
            # TuShare news API
            if not circuit_breaker.is_open("news"):
                end_date = datetime.now().strftime('%Y%m%d %H:%M:%S')
                start_date = (datetime.now() - timedelta(days=3)).strftime('%Y%m%d %H:%M:%S')

                df = tushare_call_with_retry('news', src='sina', start_date=start_date, end_date=end_date)

                if df is not None and not df.empty:
                    circuit_breaker.record_success("news")

                    # Filter news by stock codes in title/content
                    for _, row in df.iterrows():
                        title = row.get('title', '')
                        content = row.get('content', '')

                        # Check if any stock code or name is mentioned
                        for code in stock_codes:
                            if code in title or code in content:
                                news_list.append({
                                    "id": generate_news_hash(title, 'tushare', str(row.get('datetime', ''))),
                                    "title": title,
                                    "content": content[:500] if content else '',
                                    "source": "tushare",
                                    "source_name": row.get('src', 'sina'),
                                    "category": "flash",
                                    "published_at": str(row.get('datetime', '')),
                                    "url": row.get('url', ''),
                                    "related_stocks": [{"code": code}],
                                })
                                break

                        if len(news_list) >= limit:
                            break
                else:
                    circuit_breaker.record_failure("news")

        except Exception as e:
            print(f"Stock news fetch error: {e}")
            circuit_breaker.record_failure("news")

        # Fallback: try AkShare stock_news_em for individual stocks
        if len(news_list) < limit // 2:
            try:
                import akshare as ak
                for code in stock_codes[:3]:  # Limit to avoid rate limiting
                    try:
                        # Format code for AkShare (remove exchange suffix)
                        plain_code = denormalize_ts_code(code)
                        df = ak.stock_news_em(symbol=plain_code)
                        if df is not None and not df.empty:
                            for _, row in df.head(5).iterrows():
                                title = str(row.get('新闻标题', row.iloc[0] if len(row) > 0 else ''))
                                content = str(row.get('新闻内容', row.iloc[1] if len(row) > 1 else ''))
                                pub_time = str(row.get('发布时间', row.iloc[2] if len(row) > 2 else ''))

                                news_list.append({
                                    "id": generate_news_hash(title, 'akshare', pub_time),
                                    "title": title,
                                    "content": content[:500],
                                    "source": "akshare",
                                    "source_name": "东方财富",
                                    "category": "flash",
                                    "published_at": pub_time,
                                    "url": str(row.get('新闻链接', '')),
                                    "related_stocks": [{"code": code}],
                                })
                    except Exception:
                        continue
            except Exception as e:
                # Don't print 404 errors - they indicate the external API has changed
                if "404" not in str(e):
                    print(f"AkShare stock_news_em fallback error: {e}")

        # Deduplicate and sort
        seen = set()
        unique_news = []
        for item in news_list:
            if item['id'] not in seen:
                seen.add(item['id'])
                unique_news.append(item)

        unique_news = unique_news[:limit]

        if unique_news:
            self._set_cache(cache_key, unique_news, config.ttl)

        return unique_news

    def get_announcements(self, stock_code: str = None, limit: int = 20) -> List[Dict]:
        """
        Get company announcements.

        Uses AkShare as primary source (free), with stock-specific news fallback.
        """
        cache_key = f"announcements:{stock_code or 'all'}:{limit}"
        config = NEWS_CACHE_CONFIG[NewsCategory.ANNOUNCEMENT]

        cached = self._get_cache(cache_key)
        if cached:
            return cached

        news_list = []

        # Use AkShare for announcements (more reliable and free)
        try:
            import akshare as ak

            if stock_code:
                # Get stock-specific announcements via stock_news_em
                try:
                    plain_code = denormalize_ts_code(stock_code)
                    df = ak.stock_news_em(symbol=plain_code)
                    if df is not None and not df.empty:
                        for _, row in df.head(limit).iterrows():
                            title = str(row.get('新闻标题', row.iloc[0] if len(row) > 0 else ''))
                            content = str(row.get('新闻内容', row.iloc[1] if len(row) > 1 else ''))
                            pub_time = str(row.get('发布时间', row.iloc[2] if len(row) > 2 else ''))
                            url = str(row.get('新闻链接', ''))

                            # Filter for announcement-like content
                            is_announcement = any(kw in title for kw in ['公告', '报告', '业绩', '披露', '决议', '通知'])

                            news_list.append({
                                "id": generate_news_hash(title, 'announcement', pub_time),
                                "title": title,
                                "content": content[:500],
                                "source": "akshare",
                                "source_name": "公告" if is_announcement else "资讯",
                                "category": "announcement",
                                "published_at": pub_time,
                                "url": url,
                                "related_stocks": [{"code": stock_code}],
                                "importance": "high" if is_announcement else "medium",
                            })
                except Exception as e:
                    print(f"AkShare stock_news_em error for {stock_code}: {e}")

            # If no stock code or not enough results, get general financial news
            if len(news_list) < limit:
                try:
                    # Try to get general financial announcements
                    df = ak.stock_info_global_cls()
                    if df is not None and not df.empty:
                        for _, row in df.head(limit - len(news_list)).iterrows():
                            title = str(row.iloc[0]).strip() if len(row) > 0 else ''
                            content = str(row.iloc[1]).strip() if len(row) > 1 else ''
                            pub_time = str(row.iloc[3]).strip() if len(row) > 3 else ''

                            # Filter for announcement-related content
                            if any(kw in title or kw in content for kw in ['公告', '公示', '披露', '报告', '决议', '通知', '公布']):
                                news_list.append({
                                    "id": generate_news_hash(title, 'announcement', pub_time),
                                    "title": title,
                                    "content": content[:500],
                                    "source": "akshare",
                                    "source_name": "财联社",
                                    "category": "announcement",
                                    "published_at": pub_time,
                                    "url": "",
                                    "related_stocks": [],
                                    "importance": self._classify_announcement_importance(title),
                                })
                except Exception as e:
                    print(f"AkShare stock_info_global_cls error: {e}")

        except Exception as e:
            print(f"Announcements fetch error: {e}")

        # Deduplicate
        seen = set()
        unique_news = []
        for item in news_list:
            if item['id'] not in seen:
                seen.add(item['id'])
                unique_news.append(item)

        unique_news = unique_news[:limit]

        if unique_news:
            self._set_cache(cache_key, unique_news, config.ttl)
            set_news_cache(cache_key, unique_news, "akshare", config.ttl)

        return unique_news

    def _classify_announcement_importance(self, ann_type: str) -> str:
        """Classify announcement importance based on type"""
        high_importance = ['业绩预告', '业绩快报', '重大事项', '并购重组', '股权变动', '增减持']
        medium_importance = ['定期报告', '董事会决议', '股东大会']

        if ann_type:
            for keyword in high_importance:
                if keyword in ann_type:
                    return 'high'
            for keyword in medium_importance:
                if keyword in ann_type:
                    return 'medium'
        return 'low'

    def search_research_reports(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Search for research reports.

        Uses Tavily if available, falls back to AkShare news filtering.
        """
        cache_key = f"research:{query}:{limit}"
        config = NEWS_CACHE_CONFIG[NewsCategory.RESEARCH]

        cached = self._get_cache(cache_key)
        if cached:
            return cached

        news_list = []
        tavily_failed = False

        # Try Tavily first (if available and not rate limited)
        tavily = self._get_tavily_client()
        if tavily and not circuit_breaker.is_open("tavily"):
            try:
                # Search for research reports
                search_query = f"{query} 研报 研究报告 券商"
                response = tavily.search(
                    query=search_query,
                    search_depth="basic",  # Use basic to conserve quota
                    max_results=limit,
                    include_domains=["eastmoney.com", "10jqka.com.cn", "xueqiu.com", "gelonghui.com"]
                )

                if response and 'results' in response:
                    circuit_breaker.record_success("tavily")
                    for item in response['results']:
                        news_list.append({
                            "id": generate_news_hash(item.get('title', ''), 'tavily', ''),
                            "title": item.get('title', ''),
                            "content": item.get('content', '')[:500],
                            "source": "tavily",
                            "source_name": item.get('url', '').split('/')[2] if item.get('url') else '研报',
                            "category": "research",
                            "published_at": "",
                            "url": item.get('url', ''),
                        })
            except Exception as e:
                error_msg = str(e).lower()
                # Check for rate limit / quota exceeded errors
                if 'limit' in error_msg or 'quota' in error_msg or 'exceeded' in error_msg or 'upgrade' in error_msg:
                    print(f"Tavily rate limited: {e}")
                    circuit_breaker.record_failure("tavily")
                    tavily_failed = True
                else:
                    print(f"Tavily search error: {e}")
                    tavily_failed = True

        # Fallback to AkShare if Tavily failed or unavailable
        if not news_list or tavily_failed:
            try:
                import akshare as ak

                # Get general financial news and filter for research-like content
                df = ak.stock_info_global_cls()
                if df is not None and not df.empty:
                    research_keywords = ['研报', '研究', '券商', '分析师', '评级', '目标价', '买入', '增持', '推荐', '报告']

                    for _, row in df.iterrows():
                        title = str(row.iloc[0]).strip() if len(row) > 0 else ''
                        content = str(row.iloc[1]).strip() if len(row) > 1 else ''
                        pub_time = str(row.iloc[3]).strip() if len(row) > 3 else ''

                        # Check if content matches research keywords or query
                        text = title + content
                        is_research = any(kw in text for kw in research_keywords)
                        matches_query = query.lower() in text.lower() if query else True

                        if is_research or matches_query:
                            news_list.append({
                                "id": generate_news_hash(title, 'research', pub_time),
                                "title": title,
                                "content": content[:500],
                                "source": "akshare",
                                "source_name": "财联社",
                                "category": "research",
                                "published_at": pub_time,
                                "url": "",
                            })

                            if len(news_list) >= limit:
                                break

            except Exception as e:
                # Don't print 404 errors - they indicate the external API has changed
                if "404" not in str(e):
                    print(f"AkShare research fallback error: {e}")

        if news_list:
            self._set_cache(cache_key, news_list, config.ttl)

        return news_list

    # =========================================================================
    # Personalized News Aggregation
    # =========================================================================

    def get_personalized_feed(
        self,
        user_id: int,
        category: str = "all",
        page: int = 1,
        page_size: int = 20,
        since_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get personalized news feed for a user.

        Aggregates news based on user's watchlist (stocks/funds).
        Falls back to hot news if no watchlist.
        """
        # Get user's watchlist
        stocks = get_all_stocks(user_id)
        funds = get_all_funds(user_id)

        stock_codes = [s['code'] for s in stocks] if stocks else []
        fund_codes = [f['code'] for f in funds] if funds else []

        has_watchlist = bool(stock_codes or fund_codes)

        result = {
            "news": [],
            "has_watchlist": has_watchlist,
            "watchlist_summary": {
                "stocks_count": len(stock_codes),
                "funds_count": len(fund_codes),
            },
            "category": category,
            "page": page,
            "page_size": page_size,
            "updated_at": datetime.now().isoformat(),
        }

        news_list = []

        # We paginate in-memory after aggregating and deduplicating. To make paging work,
        # we must fetch more than a single page from upstream sources.
        # Cap to avoid excessive load on data sources.
        end_idx = page * page_size
        fetch_limit = min(200, max(60, end_idx + page_size))

        # Fetch news based on category
        if category == "all":
            # Mix of all categories
            if has_watchlist:
                # Personalized: stock news + hot news
                stock_limit = max(20, fetch_limit // 2)
                hot_limit = max(20, fetch_limit - stock_limit)
                stock_news = self.get_stock_news(stock_codes, limit=stock_limit)
                hot_news = self.get_hot_news(limit=hot_limit)
                news_list = self._merge_and_sort_news(stock_news, hot_news)
            else:
                # No watchlist: hot news only
                news_list = self.get_hot_news(limit=fetch_limit)

        elif category == "flash":
            # Stock-related news
            if stock_codes:
                news_list = self.get_stock_news(stock_codes, limit=fetch_limit)
            else:
                news_list = self.get_hot_news(limit=fetch_limit)

        elif category == "announcement":
            # Company announcements
            if stock_codes:
                codes = stock_codes[:5]
                per_stock_limit = max(10, min(30, fetch_limit // max(1, len(codes))))
                for code in codes:
                    news_list.extend(self.get_announcements(stock_code=code, limit=per_stock_limit))
            else:
                news_list = self.get_announcements(limit=fetch_limit)

        elif category == "research":
            # Research reports (search based on watchlist)
            research_limit = min(50, fetch_limit)
            if stock_codes:
                # Use first few stock names for search
                stock_names = [s.get('name', '') for s in stocks[:3] if s.get('name')]
                if stock_names:
                    query = ' '.join(stock_names)
                    news_list = self.search_research_reports(query, limit=research_limit)
            if not news_list:
                news_list = self.search_research_reports("A股 投资策略", limit=research_limit)

        elif category == "hot":
            news_list = self.get_hot_news(limit=fetch_limit)

        elif category == "realtime":
            # Global realtime financial news (not related to watchlist)
            news_list = self.get_realtime_news(limit=fetch_limit)

        elif category == "morning":
            # Daily morning briefing (today only)
            news_list = self.get_morning_briefing(limit=10)

        # Deduplicate
        seen = set()
        unique_news = []
        for item in news_list:
            if item['id'] not in seen:
                seen.add(item['id'])
                unique_news.append(item)

        # Optional: apply time range filter before adding user status/pagination
        if since_days is not None:
            try:
                days = int(since_days)
            except Exception:
                days = 0

            if days > 0:
                cutoff = datetime.now() - timedelta(days=days)
                unique_news = [
                    item for item in unique_news
                    if self._parse_published_at(item.get('published_at', '')) >= cutoff
                ]

        # Add user status (read/bookmarked)
        read_hashes = get_user_read_news_hashes(user_id)
        for item in unique_news:
            item['is_read'] = item['id'] in read_hashes
            status = get_news_status(user_id, item['id'])
            item['is_bookmarked'] = status.get('is_bookmarked', False) if status else False

        # Always sort by time (newest first) before pagination.
        unique_news.sort(key=lambda x: self._parse_published_at(x.get('published_at', '')), reverse=True)

        # Pagination
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        result["news"] = unique_news[start_idx:end_idx]
        result["total"] = len(unique_news)
        result["has_more"] = end_idx < len(unique_news)

        return result

    def _merge_and_sort_news(self, *news_lists) -> List[Dict]:
        """Merge multiple news lists and sort by time"""
        all_news = []
        for news_list in news_lists:
            all_news.extend(news_list)

        # Sort by published_at (newest first)
        all_news.sort(key=lambda x: self._parse_published_at(x.get('published_at', '')), reverse=True)
        return all_news

    def _parse_published_at(self, dt_str: Any) -> datetime:
        """Parse published_at into datetime. Returns datetime.min if unknown."""
        if not dt_str:
            return datetime.min

        s = str(dt_str).strip()
        if not s:
            return datetime.min

        # Normalize common variants
        s = s.replace('T', ' ').replace('/', '-').replace('Z', '')

        fmts = [
            ('%Y-%m-%d %H:%M:%S', 19),
            ('%Y%m%d %H:%M:%S', 17),
            ('%Y-%m-%d %H:%M', 16),
            ('%Y%m%d %H:%M', 14),
            ('%Y-%m-%d', 10),
            ('%Y%m%d', 8),
        ]

        for fmt, length in fmts:
            try:
                return datetime.strptime(s[:length], fmt)
            except Exception:
                continue

        return datetime.min

    # =========================================================================
    # AI Analysis
    # =========================================================================

    def analyze_news(self, news_id: str, title: str, content: str) -> Dict[str, Any]:
        """
        Analyze a news item with AI.

        Returns sentiment, summary, and key points.
        """
        # Check cache first
        cached = get_news_analysis(news_id)
        if cached:
            return {
                "sentiment": cached.get('sentiment'),
                "sentiment_score": cached.get('sentiment_score'),
                "summary": cached.get('summary'),
                "key_points": cached.get('key_points', []),
                "related_stocks": cached.get('related_stocks', []),
                "cached": True,
            }

        llm = self._get_llm_client()
        if not llm:
            return {"error": "AI analysis not available"}

        prompt = f"""分析以下财经新闻，提供结构化的分析结果。

【新闻标题】
{title}

【新闻内容】
{content[:800]}

【输出要求】
仅输出一个JSON对象，不要有任何其他文字：
{{"sentiment": "positive或negative或neutral", "sentiment_score": 0.5, "summary": "一句话摘要", "key_points": ["要点1", "要点2"], "related_stocks": []}}"""

        try:
            response = llm.generate_content(prompt)

            # Parse JSON response - handle various formats
            result = self._parse_llm_json_response(response)

            if result:
                # Save to cache
                save_news_analysis(
                    news_hash=news_id,
                    sentiment=result.get('sentiment', 'neutral'),
                    sentiment_score=result.get('sentiment_score', 0.5),
                    summary=result.get('summary', ''),
                    key_points=result.get('key_points', []),
                    related_stocks=result.get('related_stocks', []),
                )

                result['cached'] = False
                return result

        except Exception as e:
            print(f"AI analysis error: {e}")

        return {"error": "Analysis failed"}

    def _parse_llm_json_response(self, response: str) -> Optional[Dict]:
        """Parse JSON from LLM response, handling various formats."""
        import re

        if not response:
            return None

        # Clean up the response
        text = response.strip()

        # Remove markdown code blocks if present
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'^```\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        # Try to find JSON object with balanced braces
        try:
            # First, try parsing the whole cleaned text
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON object with balanced braces
        brace_count = 0
        start_idx = None
        for i, char in enumerate(text):
            if char == '{':
                if start_idx is None:
                    start_idx = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx is not None:
                    json_str = text[start_idx:i+1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        # Reset and continue looking
                        start_idx = None
                        continue

        # Fallback: try regex for simple cases
        try:
            json_match = re.search(r'\{[^{}]*\}', text)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

        return None

    def batch_analyze_sentiment(self, news_items: List[Dict]) -> Dict[str, Dict]:
        """
        Batch analyze sentiment for multiple news items.

        Returns a dict mapping news_id to sentiment info.
        """
        if not news_items:
            return {}

        news_ids = [item['id'] for item in news_items]

        # Check cache for all items
        cached = get_multiple_news_analysis(news_ids)

        # Find items that need analysis
        need_analysis = [item for item in news_items if item['id'] not in cached]

        # Analyze missing items (limit to avoid overwhelming LLM)
        for item in need_analysis[:5]:  # Only analyze top 5 at a time
            result = self.analyze_news(item['id'], item.get('title', ''), item.get('content', ''))
            if 'error' not in result:
                cached[item['id']] = result

        return cached

    # =========================================================================
    # User Actions
    # =========================================================================

    def mark_read(self, user_id: int, news_id: str, news_title: str = None,
                  news_source: str = None, news_url: str = None, news_category: str = None):
        """Mark a news item as read"""
        mark_news_read(user_id, news_id, news_title, news_source, news_url, news_category)

    def toggle_bookmark(self, user_id: int, news_id: str, news_title: str = None,
                        news_source: str = None, news_url: str = None,
                        news_category: str = None) -> bool:
        """Toggle bookmark status for a news item. Returns new state."""
        return toggle_news_bookmark(user_id, news_id, news_title, news_source, news_url, news_category)

    def set_bookmark(self, user_id: int, news_id: str, bookmarked: bool,
                     news_title: str = None, news_source: str = None,
                     news_url: str = None, news_category: str = None):
        """Set bookmark status explicitly"""
        set_news_bookmark(user_id, news_id, bookmarked, news_title, news_source, news_url, news_category)

    def get_bookmarks(self, user_id: int, limit: int = 50, offset: int = 0) -> List[Dict]:
        """Get user's bookmarked news"""
        raw_bookmarks = get_user_bookmarked_news(user_id, limit, offset)
        
        # Transform to match NewsItem structure expected by frontend
        result = []
        for b in raw_bookmarks:
            result.append({
                "id": b.get("news_hash", ""),
                "title": b.get("news_title", ""),
                "content": "",  # Content not stored in bookmarks table
                "source": b.get("news_source", "") or "unknown",
                "source_name": b.get("news_source", "") or "收藏",
                "category": b.get("news_category", "") or "hot",
                "published_at": b.get("bookmarked_at", ""),
                "url": b.get("news_url", "") or "",
                "is_read": bool(b.get("is_read", False)),
                "is_bookmarked": True,
            })
        return result

    # =========================================================================
    # Summary & Stats
    # =========================================================================

    def get_watchlist_news_summary(self, user_id: int) -> Dict[str, Any]:
        """
        Get a summary of news related to user's watchlist.

        Used for the sidebar or dashboard widget.
        """
        stocks = get_all_stocks(user_id)
        funds = get_all_funds(user_id)

        stock_codes = [s['code'] for s in stocks] if stocks else []
        fund_codes = [f['code'] for f in funds] if funds else []

        summary = {
            "stocks_count": len(stock_codes),
            "funds_count": len(fund_codes),
            "recent_news_count": 0,
            "unread_count": 0,
            "important_news": [],
            "updated_at": datetime.now().isoformat(),
        }

        if stock_codes:
            news = self.get_stock_news(stock_codes, limit=20)
            summary["recent_news_count"] = len(news)

            read_hashes = get_user_read_news_hashes(user_id)
            summary["unread_count"] = len([n for n in news if n['id'] not in read_hashes])

            # Get important news (with high sentiment score or announcements)
            for item in news[:5]:
                analysis = get_news_analysis(item['id'])
                if analysis and analysis.get('sentiment') != 'neutral':
                    summary["important_news"].append({
                        "id": item['id'],
                        "title": item['title'],
                        "sentiment": analysis.get('sentiment'),
                    })

        return summary


# Singleton instance
news_service = NewsService()
