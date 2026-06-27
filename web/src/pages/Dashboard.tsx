import { useEffect, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
    Box,
    Typography,
    Chip,
    IconButton,
    CircularProgress,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import GridLayout from 'react-grid-layout';
import type { Layout } from 'react-grid-layout';

import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';

import type { WidgetConfig } from '../widgets/types';
import { getWidgetComponent } from '../widgets/registry';
import { DashboardBundleContext, type DashboardBundleData } from '../widgets/DashboardBundleContext';
import { fetchDashboardBundle } from '../api';

// Fixed layout with widgets (compact view)
const DEFAULT_WIDGETS: WidgetConfig[] = [
    // Row 0: Header - Market Overview (compact)
    { id: 'indices', type: 'market_indices', position: { x: 0, y: 0, w: 6, h: 1 } },
    { id: 'sentiment', type: 'market_sentiment', position: { x: 6, y: 0, w: 4, h: 1 } },
    { id: 'stats', type: 'system_stats', position: { x: 10, y: 0, w: 2, h: 1 } },

    // Row 1-6: Main Data - Capital Flow (increased height)
    { id: 'mainflow', type: 'main_capital_flow', position: { x: 0, y: 1, w: 4, h: 6 } },
    { id: 'sectors', type: 'sector_performance', position: { x: 4, y: 1, w: 4, h: 6 } },
    { id: 'southbound', type: 'southbound_flow', position: { x: 8, y: 1, w: 4, h: 6 } },

    // Row 7-9: Alert Banner (stream)
    { id: 'abnormal', type: 'abnormal_movements', position: { x: 0, y: 7, w: 12, h: 3 } },

    // Row 10-15: Top List (full width)
    { id: 'toplist', type: 'top_list', position: { x: 0, y: 10, w: 12, h: 6 } },
];

export default function DashboardPage() {
    const { t } = useTranslation();
    const [containerWidth, setContainerWidth] = useState(1200);
    const [refreshKey, setRefreshKey] = useState(0);
    const [bundleData, setBundleData] = useState<DashboardBundleData | null>(null);
    const [bundleLoading, setBundleLoading] = useState(true);

    // Load dashboard bundle (aggregated data)
    const loadBundle = useCallback(async () => {
        try {
            const data = await fetchDashboardBundle();
            setBundleData(data);
        } catch (err) {
            console.error('Failed to load dashboard bundle:', err);
        } finally {
            setBundleLoading(false);
        }
    }, []);

    useEffect(() => {
        loadBundle();
        // Auto refresh every 60s during market hours
        const timer = setInterval(loadBundle, 60000);
        return () => clearInterval(timer);
    }, [loadBundle, refreshKey]);

    // Handle container resize
    useEffect(() => {
        const updateWidth = () => {
            const container = document.getElementById('dashboard-container');
            if (container) {
                setContainerWidth(container.offsetWidth);
            }
        };

        updateWidth();
        window.addEventListener('resize', updateWidth);
        return () => window.removeEventListener('resize', updateWidth);
    }, []);

    // Convert widgets to react-grid-layout format (static layout)
    const layoutItems = DEFAULT_WIDGETS.map((w) => ({
        i: w.id,
        x: w.position.x,
        y: w.position.y,
        w: w.position.w,
        h: w.position.h,
        static: true, // Make all widgets static (non-draggable, non-resizable)
    }));

    // Refresh all data
    const handleRefresh = () => {
        setBundleLoading(true);
        setRefreshKey(prev => prev + 1);
    };

    return (
        <Box id="dashboard-container" className="flex flex-col gap-6 w-full h-full pb-10">
            {/* Header */}
            <Box className="flex justify-between items-center">
                <Box className="flex items-center gap-3">
                    <Typography variant="h5" className="font-extrabold text-slate-800 tracking-tight">
                        {t('dashboard.title')}
                    </Typography>
                    <Chip
                        label={t('common.live')}
                        size="small"
                        color="success"
                        className="h-5 text-[10px] font-bold"
                    />
                    {bundleLoading && (
                        <CircularProgress size={14} thickness={4} className="text-slate-400" />
                    )}
                </Box>
                <Box className="flex items-center gap-2">
                    <IconButton
                        size="small"
                        onClick={handleRefresh}
                        className="bg-white border border-slate-200 shadow-sm hover:bg-slate-50"
                    >
                        <RefreshIcon fontSize="small" />
                    </IconButton>
                </Box>
            </Box>

            {/* Widget Grid */}
            <Box className="relative">
                <DashboardBundleContext.Provider value={bundleData}>
                    <GridLayout
                        className="layout"
                        layout={layoutItems}
                        width={containerWidth}
                        gridConfig={{
                            cols: 12,
                            rowHeight: 70,
                            margin: [12, 12],
                        }}
                        dragConfig={{
                            enabled: false,
                        }}
                        resizeConfig={{
                            enabled: false,
                        }}
                    >
                        {DEFAULT_WIDGETS.map((widget) => {
                            const WidgetComponent = getWidgetComponent(widget.type);
                            if (!WidgetComponent) return null;

                            return (
                                <div key={widget.id} className="relative">
                                    <WidgetComponent
                                        key={refreshKey}
                                        id={widget.id}
                                        config={widget}
                                        isEditing={false}
                                    />
                                </div>
                            );
                        })}
                    </GridLayout>
                </DashboardBundleContext.Provider>
            </Box>
        </Box>
    );
}
