/**
 * Widget System Type Definitions
 *
 * Defines types for the configurable Dashboard widget system.
 */

import type { ComponentType } from 'react';

// Widget types supported by the dashboard
export type WidgetType =
    | 'market_indices'
    | 'southbound_flow'
    | 'industry_flow'
    | 'sector_performance'
    | 'top_list'
    | 'forex_rates'
    | 'market_sentiment'
    | 'gold_macro'
    | 'abnormal_movements'
    | 'main_capital_flow'
    | 'system_stats'
    | 'watchlist'
    | 'news';

// Widget position and size in the grid
export interface WidgetPosition {
    x: number;
    y: number;
    w: number;
    h: number;
}

// Widget metadata for smart layout
export interface WidgetMetadata {
    category: 'card' | 'table' | 'chart' | 'stream' | 'banner';
    priority: 'high' | 'medium' | 'low';
    smartSize?: { w: number; h: number };  // Preferred size for smart layout
    canExpand?: boolean;                    // Whether widget can expand to fill gaps
}

// Widget configuration stored in layout
export interface WidgetConfig {
    id: string;
    type: WidgetType;
    title?: string;
    enabled?: boolean;
    position: WidgetPosition;
    settings?: Record<string, unknown>;
    refreshInterval?: number; // in seconds
}

// Dashboard layout configuration
export interface DashboardLayout {
    id?: number;
    name: string;
    widgets: WidgetConfig[];
    isDefault?: boolean;
    createdAt?: string;
    updatedAt?: string;
}

// Widget definition for registry
export interface WidgetDefinition {
    type: WidgetType;
    name: string;
    nameEn: string;
    description: string;
    descriptionEn: string;
    icon: string; // MUI icon name
    component: ComponentType<WidgetProps>;
    defaultSize: { w: number; h: number };
    minSize: { w: number; h: number };
    maxSize?: { w: number; h: number };
    defaultSettings?: Record<string, unknown>;
    refreshInterval: number; // default refresh interval in seconds
    requiresAuth?: boolean;
    pointsRequired?: number; // TuShare points required
    metadata: WidgetMetadata;
}

// Props passed to widget components
export interface WidgetProps {
    id: string;
    config: WidgetConfig;
    isEditing?: boolean;
    onSettingsChange?: (settings: Record<string, unknown>) => void;
}

// Widget data response types
export interface SouthboundFlowData {
    latest?: {
        date: string;
        south_money: number;
        hk_sh_net: number;
        hk_sz_net: number;
    };
    cumulative_5d: number;
    history: Array<{
        date: string;
        south_money: number;
    }>;
    updated_at: string;
    error?: string;
}

export interface IndustryFlowData {
    trade_date: string;
    gainers: Array<{
        name: string;
        net_inflow: number;
        change_pct: number;
        amount: number;
    }>;
    losers: Array<{
        name: string;
        net_inflow: number;
        change_pct: number;
        amount: number;
    }>;
    updated_at: string;
    error?: string;
}

export interface SectorPerformanceData {
    trade_date: string;
    gainers: Array<{
        name: string;
        change_pct: number;
        net_inflow: number;
        amount: number;
    }>;
    losers: Array<{
        name: string;
        change_pct: number;
        net_inflow: number;
        amount: number;
    }>;
    updated_at: string;
    source?: string;
    error?: string;
}

export interface TopListData {
    trade_date: string;
    data: Array<{
        code: string;
        name: string;
        close: number;
        change_pct: number;
        amount: number;
        net_amount: number;
        l_buy: number;
        l_sell: number;
        turnover_rate: number;
        reason: string;
    }>;
    updated_at: string;
    error?: string;
}

export interface ForexRatesData {
    rates: Array<{
        code: string;
        name: string;
        name_en: string;
        rate: number;
        change: number;
        change_pct: number;
        date: string;
    }>;
    updated_at: string;
    error?: string;
}

export interface WatchlistData {
    stocks: Array<{
        code: string;
        ts_code: string;
        close: number;
        change_pct: number;
        pe: number | null;
        pb: number | null;
        total_mv: number | null;
        turnover_rate: number | null;
    }>;
    trade_date: string;
    updated_at: string;
    error?: string;
}

export interface NewsData {
    news: Array<{
        title: string;
        content: string;
        datetime: string;
        source: string;
    }>;
    updated_at: string;
    error?: string;
}

export interface MainCapitalFlowData {
    top_flows: Array<{
        code: string;
        name: string;
        net_buy: number;
        change_pct: number;
    }>;
    market_overview: {
        main_flow: number;
    };
    updated_at: string;
    error?: string;
}

// Layout preset
export interface LayoutPreset {
    name: string;
    name_en: string;
    description: string;
    widgets: WidgetConfig[];
}

export interface LayoutPresetsResponse {
    presets: Record<string, LayoutPreset>;
}
