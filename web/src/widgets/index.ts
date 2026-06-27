/**
 * Widget System Exports
 *
 * Central export point for all widget-related modules.
 */

// Types
export * from './types';

// Registry
export * from './registry';

// Container
export { default as WidgetContainer, useWidgetData } from './WidgetContainer';

// Widget Components
export { default as MarketIndicesWidget } from './components/MarketIndicesWidget';
export { default as SouthboundFlowWidget } from './components/SouthboundFlowWidget';
export { default as IndustryFlowWidget } from './components/IndustryFlowWidget';
export { default as SectorPerformanceWidget } from './components/SectorPerformanceWidget';
export { default as TopListWidget } from './components/TopListWidget';
export { default as ForexRatesWidget } from './components/ForexRatesWidget';
export { default as MarketSentimentWidget } from './components/MarketSentimentWidget';
export { default as GoldMacroWidget } from './components/GoldMacroWidget';
export { default as AbnormalMovementsWidget } from './components/AbnormalMovementsWidget';
export { default as MainCapitalFlowWidget } from './components/MainCapitalFlowWidget';
export { default as SystemStatsWidget } from './components/SystemStatsWidget';
export { default as WatchlistWidget } from './components/WatchlistWidget';
export { default as NewsWidget } from './components/NewsWidget';
