/**
 * Widget Registry
 *
 * Central registry for all available widgets.
 * Maps widget types to their definitions and components.
 */

import type{ WidgetDefinition, WidgetType } from './types';

// Import widget components
import MarketIndicesWidget from './components/MarketIndicesWidget';
import SouthboundFlowWidget from './components/SouthboundFlowWidget';
import IndustryFlowWidget from './components/IndustryFlowWidget';
import SectorPerformanceWidget from './components/SectorPerformanceWidget';
import TopListWidget from './components/TopListWidget';
import ForexRatesWidget from './components/ForexRatesWidget';
import MarketSentimentWidget from './components/MarketSentimentWidget';
import GoldMacroWidget from './components/GoldMacroWidget';
import AbnormalMovementsWidget from './components/AbnormalMovementsWidget';
import MainCapitalFlowWidget from './components/MainCapitalFlowWidget';
import SystemStatsWidget from './components/SystemStatsWidget';
import WatchlistWidget from './components/WatchlistWidget';
import NewsWidget from './components/NewsWidget';

// Widget definitions
export const WIDGET_DEFINITIONS: Record<WidgetType, WidgetDefinition> = {
    market_indices: {
        type: 'market_indices',
        name: '市场指数',
        nameEn: 'Market Indices',
        description: '主要市场指数实时行情',
        descriptionEn: 'Real-time major market indices',
        icon: 'ShowChart',
        component: MarketIndicesWidget,
        defaultSize: { w: 6, h: 2 },
        minSize: { w: 4, h: 2 },
        maxSize: { w: 12, h: 3 },
        refreshInterval: 60,
        pointsRequired: 0,
        metadata: {
            category: 'banner',
            priority: 'high',
            smartSize: { w: 6, h: 2 },
            canExpand: true,
        },
    },
    southbound_flow: {
        type: 'southbound_flow',
        name: '南向资金',
        nameEn: 'Southbound Flow',
        description: '港股通南向资金流向',
        descriptionEn: 'HK Connect southbound capital flow',
        icon: 'TrendingUp',
        component: SouthboundFlowWidget,
        defaultSize: { w: 4, h: 6 },
        minSize: { w: 3, h: 3 },
        maxSize: { w: 6, h: 8 },
        refreshInterval: 300,
        pointsRequired: 0,
        metadata: {
            category: 'chart',
            priority: 'medium',
            smartSize: { w: 4, h: 6 },
            canExpand: true,
        },
    },
    industry_flow: {
        type: 'industry_flow',
        name: '行业资金流',
        nameEn: 'Industry Flow',
        description: '同花顺行业资金流向',
        descriptionEn: 'THS industry capital flow',
        icon: 'AccountBalance',
        component: IndustryFlowWidget,
        defaultSize: { w: 4, h: 6 },
        minSize: { w: 3, h: 3 },
        maxSize: { w: 8, h: 8 },
        refreshInterval: 600,
        pointsRequired: 2000,
        metadata: {
            category: 'chart',
            priority: 'medium',
            smartSize: { w: 4, h: 6 },
            canExpand: false,
        },
    },
    sector_performance: {
        type: 'sector_performance',
        name: '板块涨跌',
        nameEn: 'Sector Performance',
        description: '板块涨跌幅排行',
        descriptionEn: 'Sector performance ranking',
        icon: 'BarChart',
        component: SectorPerformanceWidget,
        defaultSize: { w: 4, h: 6 },
        minSize: { w: 4, h: 3 },
        maxSize: { w: 12, h: 8 },
        refreshInterval: 600,
        pointsRequired: 2000,
        metadata: {
            category: 'chart',
            priority: 'medium',
            smartSize: { w: 4, h: 6 },
            canExpand: true,
        },
    },
    top_list: {
        type: 'top_list',
        name: '龙虎榜',
        nameEn: 'Dragon Tiger List',
        description: '龙虎榜上榜股票',
        descriptionEn: 'Dragon Tiger list stocks',
        icon: 'EmojiEvents',
        component: TopListWidget,
        defaultSize: { w: 8, h: 6 },
        minSize: { w: 6, h: 4 },
        maxSize: { w: 12, h: 8 },
        refreshInterval: 3600,
        pointsRequired: 0,
        metadata: {
            category: 'table',
            priority: 'medium',
            smartSize: { w: 8, h: 6 },
            canExpand: true,
        },
    },
    forex_rates: {
        type: 'forex_rates',
        name: '外汇汇率',
        nameEn: 'Forex Rates',
        description: '主要货币汇率',
        descriptionEn: 'Major currency exchange rates',
        icon: 'CurrencyExchange',
        component: ForexRatesWidget,
        defaultSize: { w: 4, h: 4 },
        minSize: { w: 3, h: 3 },
        maxSize: { w: 6, h: 6 },
        refreshInterval: 3600,
        pointsRequired: 100,
        metadata: {
            category: 'table',
            priority: 'medium',
            smartSize: { w: 4, h: 4 },
            canExpand: false,
        },
    },
    market_sentiment: {
        type: 'market_sentiment',
        name: '市场情绪',
        nameEn: 'Market Sentiment',
        description: '涨跌家数、涨停跌停统计',
        descriptionEn: 'Market breadth and limit statistics',
        icon: 'Psychology',
        component: MarketSentimentWidget,
        defaultSize: { w: 4, h: 3 },
        minSize: { w: 3, h: 2 },
        maxSize: { w: 6, h: 4 },
        refreshInterval: 60,
        pointsRequired: 0,
        metadata: {
            category: 'card',
            priority: 'medium',
            smartSize: { w: 4, h: 3 },
            canExpand: false,
        },
    },
    gold_macro: {
        type: 'gold_macro',
        name: '黄金宏观',
        nameEn: 'Gold & Macro',
        description: '黄金价格与美元指数',
        descriptionEn: 'Gold price and DXY index',
        icon: 'Public',
        component: GoldMacroWidget,
        defaultSize: { w: 4, h: 2 },
        minSize: { w: 2, h: 2 },
        maxSize: { w: 4, h: 3 },
        refreshInterval: 300,
        pointsRequired: 0,
        metadata: {
            category: 'card',
            priority: 'medium',
            smartSize: { w: 4, h: 2 },
            canExpand: false,
        },
    },
    abnormal_movements: {
        type: 'abnormal_movements',
        name: '实时异动',
        nameEn: 'Abnormal Movements',
        description: '实时股票异动信号',
        descriptionEn: 'Real-time stock movement signals',
        icon: 'Bolt',
        component: AbnormalMovementsWidget,
        defaultSize: { w: 12, h: 3 },
        minSize: { w: 6, h: 2 },
        maxSize: { w: 12, h: 4 },
        refreshInterval: 30,
        pointsRequired: 0,
        metadata: {
            category: 'stream',
            priority: 'high',
            smartSize: { w: 12, h: 3 },
            canExpand: true,
        },
    },
    main_capital_flow: {
        type: 'main_capital_flow',
        name: '主力资金',
        nameEn: 'Main Capital Flow',
        description: '主力资金净流入排行',
        descriptionEn: 'Main capital net inflow ranking',
        icon: 'Timeline',
        component: MainCapitalFlowWidget,
        defaultSize: { w: 4, h: 6 },
        minSize: { w: 4, h: 3 },
        maxSize: { w: 8, h: 8 },
        refreshInterval: 300,
        pointsRequired: 0,
        metadata: {
            category: 'table',
            priority: 'high',
            smartSize: { w: 4, h: 6 },
            canExpand: true,
        },
    },
    system_stats: {
        type: 'system_stats',
        name: '系统统计',
        nameEn: 'System Stats',
        description: '报告生成统计',
        descriptionEn: 'Report generation statistics',
        icon: 'Storage',
        component: SystemStatsWidget,
        defaultSize: { w: 2, h: 2 },
        minSize: { w: 2, h: 2 },
        maxSize: { w: 4, h: 3 },
        refreshInterval: 300,
        requiresAuth: true,
        pointsRequired: 0,
        metadata: {
            category: 'card',
            priority: 'low',
            smartSize: { w: 2, h: 2 },
            canExpand: false,
        },
    },
    watchlist: {
        type: 'watchlist',
        name: '自选股',
        nameEn: 'Watchlist',
        description: '自选股实时行情',
        descriptionEn: 'Watchlist real-time quotes',
        icon: 'Star',
        component: WatchlistWidget,
        defaultSize: { w: 4, h: 6 },
        minSize: { w: 4, h: 3 },
        maxSize: { w: 8, h: 8 },
        refreshInterval: 60,
        requiresAuth: true,
        pointsRequired: 0,
        metadata: {
            category: 'table',
            priority: 'low',
            smartSize: { w: 4, h: 6 },
            canExpand: true,
        },
    },
    news: {
        type: 'news',
        name: '新闻资讯',
        nameEn: 'News',
        description: '财经新闻资讯',
        descriptionEn: 'Financial news feed',
        icon: 'Article',
        component: NewsWidget,
        defaultSize: { w: 4, h: 6 },
        minSize: { w: 4, h: 4 },
        maxSize: { w: 6, h: 10 },
        refreshInterval: 600,
        pointsRequired: 0,
        metadata: {
            category: 'stream',
            priority: 'medium',
            smartSize: { w: 4, h: 6 },
            canExpand: true,
        },
    },
};

// Get widget definition by type
export function getWidgetDefinition(type: WidgetType): WidgetDefinition | undefined {
    return WIDGET_DEFINITIONS[type];
}

// Get all widget definitions as array
export function getAllWidgetDefinitions(): WidgetDefinition[] {
    return Object.values(WIDGET_DEFINITIONS);
}

// Get widget component by type
export function getWidgetComponent(type: WidgetType) {
    const definition = WIDGET_DEFINITIONS[type];
    return definition?.component;
}

// Check if widget requires authentication
export function widgetRequiresAuth(type: WidgetType): boolean {
    const definition = WIDGET_DEFINITIONS[type];
    return definition?.requiresAuth ?? false;
}

// Get widgets grouped by category
export function getWidgetsByCategory(): Record<string, WidgetDefinition[]> {
    return {
        market: [
            WIDGET_DEFINITIONS.market_indices,
            WIDGET_DEFINITIONS.market_sentiment,
            WIDGET_DEFINITIONS.sector_performance,
        ],
        capital: [
            WIDGET_DEFINITIONS.southbound_flow,
            WIDGET_DEFINITIONS.industry_flow,
            WIDGET_DEFINITIONS.main_capital_flow,
            WIDGET_DEFINITIONS.top_list,
        ],
        macro: [
            WIDGET_DEFINITIONS.gold_macro,
            WIDGET_DEFINITIONS.forex_rates,
        ],
        signals: [
            WIDGET_DEFINITIONS.abnormal_movements,
            WIDGET_DEFINITIONS.news,
        ],
        personal: [
            WIDGET_DEFINITIONS.watchlist,
            WIDGET_DEFINITIONS.system_stats,
        ],
    };
}
