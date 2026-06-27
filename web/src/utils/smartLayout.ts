/**
 * Smart Layout Algorithm
 *
 * Automatically generates optimal widget layouts based on:
 * 1. Priority-based sorting (high → medium → low)
 * 2. Category-based ordering (banner → card → chart → table → stream)
 * 3. Greedy placement algorithm (top-left first-fit)
 * 4. Row filling optimization (expand expandable widgets)
 */

import type { WidgetConfig, WidgetType } from '../widgets/types';
import { getWidgetDefinition, WIDGET_DEFINITIONS } from '../widgets/registry';

// Grid configuration
const GRID_COLS = 12;

// Priority order (lower = higher priority)
const PRIORITY_ORDER: Record<string, number> = {
    high: 0,
    medium: 1,
    low: 2,
};

// Category order (lower = placed first)
const CATEGORY_ORDER: Record<string, number> = {
    banner: 0,
    card: 1,
    chart: 2,
    table: 3,
    stream: 4,
};

// Smart size overrides for specific widgets
const SMART_SIZE_MAP: Record<WidgetType, { w: number; h: number }> = {
    market_indices: { w: 6, h: 2 },      // banner - can be 6 or 12 wide
    southbound_flow: { w: 6, h: 4 },     // chart
    industry_flow: { w: 6, h: 4 },       // chart
    sector_performance: { w: 6, h: 4 },  // chart
    top_list: { w: 6, h: 4 },            // table
    forex_rates: { w: 5, h: 4 },         // table
    market_sentiment: { w: 4, h: 3 },    // card
    gold_macro: { w: 2, h: 2 },          // card - small
    abnormal_movements: { w: 12, h: 3 }, // stream - full width
    main_capital_flow: { w: 6, h: 4 },   // table
    system_stats: { w: 2, h: 2 },        // card - small
    watchlist: { w: 6, h: 4 },           // table
    news: { w: 6, h: 4 },                // stream
};

// Widgets that can be expanded to fill row gaps
const EXPANDABLE_WIDGETS: Set<WidgetType> = new Set([
    'market_indices',
    'abnormal_movements',
    'sector_performance',
    'main_capital_flow',
    'southbound_flow',
    'top_list',
    'watchlist',
    'news',
]);

/**
 * Get the smart size for a widget type
 */
export function getSmartSize(type: WidgetType): { w: number; h: number } {
    return SMART_SIZE_MAP[type] || { w: 6, h: 4 };
}

/**
 * Check if a widget can be expanded
 */
export function canExpand(type: WidgetType): boolean {
    return EXPANDABLE_WIDGETS.has(type);
}

/**
 * Sort widget types by priority and category
 */
function sortByPriorityAndCategory(types: WidgetType[]): WidgetType[] {
    return [...types].sort((a, b) => {
        const defA = getWidgetDefinition(a);
        const defB = getWidgetDefinition(b);

        if (!defA || !defB) return 0;

        // First sort by priority
        const priorityA = PRIORITY_ORDER[defA.metadata?.priority || 'medium'] ?? 1;
        const priorityB = PRIORITY_ORDER[defB.metadata?.priority || 'medium'] ?? 1;

        if (priorityA !== priorityB) {
            return priorityA - priorityB;
        }

        // Then sort by category
        const categoryA = CATEGORY_ORDER[defA.metadata?.category || 'chart'] ?? 2;
        const categoryB = CATEGORY_ORDER[defB.metadata?.category || 'chart'] ?? 2;

        return categoryA - categoryB;
    });
}

/**
 * Build a 2D occupancy grid
 */
function createGrid(maxRows: number = 50): boolean[][] {
    return Array(maxRows)
        .fill(null)
        .map(() => Array(GRID_COLS).fill(false));
}

/**
 * Mark cells as occupied in the grid
 */
function markOccupied(
    grid: boolean[][],
    x: number,
    y: number,
    w: number,
    h: number
): void {
    for (let row = y; row < y + h && row < grid.length; row++) {
        for (let col = x; col < x + w && col < GRID_COLS; col++) {
            grid[row][col] = true;
        }
    }
}

/**
 * Check if a position can fit a widget
 */
function canFit(
    grid: boolean[][],
    x: number,
    y: number,
    w: number,
    h: number
): boolean {
    if (x < 0 || x + w > GRID_COLS || y < 0 || y + h > grid.length) {
        return false;
    }

    for (let row = y; row < y + h; row++) {
        for (let col = x; col < x + w; col++) {
            if (grid[row][col]) {
                return false;
            }
        }
    }

    return true;
}

/**
 * Find the first position where a widget can fit (top-left first)
 */
function findFirstFit(
    grid: boolean[][],
    w: number,
    h: number
): { x: number; y: number } | null {
    for (let y = 0; y < grid.length - h; y++) {
        for (let x = 0; x <= GRID_COLS - w; x++) {
            if (canFit(grid, x, y, w, h)) {
                return { x, y };
            }
        }
    }
    return null;
}

/**
 * Optimize layout by expanding widgets to fill row gaps
 */
function optimizeRowFilling(
    widgets: WidgetConfig[],
    grid: boolean[][]
): WidgetConfig[] {
    const result = [...widgets];

    // Find widgets that can be expanded
    for (let i = 0; i < result.length; i++) {
        const widget = result[i];
        if (!canExpand(widget.type)) continue;

        const { x, y, w, h } = widget.position;
        const def = getWidgetDefinition(widget.type);
        if (!def) continue;

        // Check if widget is at the end of its row and can expand
        const maxW = def.maxSize?.w || GRID_COLS;

        // Calculate how much we can expand
        let expandBy = 0;
        for (let col = x + w; col < Math.min(x + maxW, GRID_COLS); col++) {
            // Check if this column is free for all rows the widget occupies
            let canUse = true;
            for (let row = y; row < y + h; row++) {
                if (grid[row][col]) {
                    canUse = false;
                    break;
                }
            }
            if (canUse) {
                expandBy++;
            } else {
                break;
            }
        }

        // Expand if we found extra space
        if (expandBy > 0) {
            result[i] = {
                ...widget,
                position: {
                    ...widget.position,
                    w: w + expandBy,
                },
            };

            // Update grid
            markOccupied(grid, x + w, y, expandBy, h);
        }
    }

    return result;
}

/**
 * Generate a smart layout from selected widget types
 */
export function generateSmartLayout(selectedTypes: WidgetType[]): WidgetConfig[] {
    if (selectedTypes.length === 0) {
        return [];
    }

    // 1. Sort by priority and category
    const sortedTypes = sortByPriorityAndCategory(selectedTypes);

    // 2. Create occupancy grid
    const grid = createGrid();

    // 3. Place widgets using greedy algorithm
    const result: WidgetConfig[] = [];

    for (const type of sortedTypes) {
        const size = getSmartSize(type);
        const pos = findFirstFit(grid, size.w, size.h);

        if (pos) {
            const widget: WidgetConfig = {
                id: `${type}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                type,
                position: {
                    x: pos.x,
                    y: pos.y,
                    w: size.w,
                    h: size.h,
                },
                enabled: true,
            };

            result.push(widget);
            markOccupied(grid, pos.x, pos.y, size.w, size.h);
        }
    }

    // 4. Optimize by filling gaps
    const optimized = optimizeRowFilling(result, grid);

    return optimized;
}

/**
 * Get all available widget types
 */
export function getAllWidgetTypes(): WidgetType[] {
    return Object.keys(WIDGET_DEFINITIONS) as WidgetType[];
}

/**
 * Group widgets by their metadata category for display
 */
export function getWidgetTypesByDisplayCategory(): Record<string, WidgetType[]> {
    const categories: Record<string, WidgetType[]> = {
        market: [],   // 行情
        capital: [],  // 资金
        macro: [],    // 宏观
        signals: [],  // 信号
        personal: [], // 个人
    };

    // Use the existing category grouping from registry
    categories.market = ['market_indices', 'market_sentiment', 'sector_performance'];
    categories.capital = ['southbound_flow', 'industry_flow', 'main_capital_flow', 'top_list'];
    categories.macro = ['gold_macro', 'forex_rates'];
    categories.signals = ['abnormal_movements', 'news'];
    categories.personal = ['watchlist', 'system_stats'];

    return categories;
}
