import { createContext, useContext } from 'react';
import type {
    SouthboundFlowData,
    IndustryFlowData,
    SectorPerformanceData,
    TopListData,
    MainCapitalFlowData,
    ForexRatesData,
    NewsData,
} from './types';

export interface DashboardBundleData {
    southbound_flow?: SouthboundFlowData;
    industry_flow?: IndustryFlowData;
    sector_performance?: SectorPerformanceData;
    top_list?: TopListData;
    main_capital_flow?: MainCapitalFlowData;
    forex_rates?: ForexRatesData;
    news?: NewsData;
    updated_at?: string;
}

export const DashboardBundleContext = createContext<DashboardBundleData | null>(null);

export function useDashboardBundle(): DashboardBundleData | null {
    return useContext(DashboardBundleContext);
}
