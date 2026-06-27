/**
 * Southbound Flow Widget
 *
 * Displays southbound capital flow (港股通) data.
 */

import { Box, Typography, Chip } from '@mui/material';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import { useTranslation } from 'react-i18next';
import type{ WidgetProps, SouthboundFlowData } from '../types';
import WidgetContainer from '../WidgetContainer';
import { useWidgetDataFromBundle } from '../useWidgetDataFromBundle';
import { fetchWidgetSouthboundFlow } from '../../api';

export default function SouthboundFlowWidget({ id, config, isEditing }: WidgetProps) {
    const { t, i18n } = useTranslation();
    const isZh = i18n.language === 'zh';

    const { data, loading, error, lastUpdated, refresh } = useWidgetDataFromBundle<SouthboundFlowData>(
        'southbound_flow',
        () => fetchWidgetSouthboundFlow(5),
        config.refreshInterval ? config.refreshInterval * 1000 : 300000
    );

    const formatAmount = (val: number) => {
        const absVal = Math.abs(val);
        return `${val >= 0 ? '+' : ''}${val.toFixed(2)}`;
    };

    return (
        <WidgetContainer
            config={config}
            loading={loading}
            error={error || data?.error}
            onRefresh={refresh}
            lastUpdated={lastUpdated || undefined}
        >
            <Box className="h-full flex flex-col gap-4 overflow-auto">
                {/* Today's Flow */}
                {data?.latest && (
                    <Box className="p-4 rounded-lg bg-gradient-to-r from-amber-50 to-orange-50 border border-amber-100">
                        <Box className="flex justify-between items-start mb-2">
                            <Typography variant="caption" className="text-slate-500 font-bold uppercase">
                                {isZh ? '今日净买额' : "Today's Net Purchase"}
                            </Typography>
                            <Chip
                                label={data.latest.date}
                                size="small"
                                className="h-5 text-[10px] bg-white"
                            />
                        </Box>
                        <Box className="flex items-baseline gap-2">
                            <Typography variant="h4" className={`font-bold ${data.latest.south_money >= 0 ? 'text-red-600' : 'text-green-600'}`}>
                                {formatAmount(data.latest.south_money)}
                            </Typography>
                            <Typography variant="body2" className="text-slate-500">{isZh ? '亿元' : 'B CNY'}</Typography>
                            {data.latest.south_money >= 0 ? (
                                <TrendingUpIcon className="text-red-500" />
                            ) : (
                                <TrendingDownIcon className="text-green-500" />
                            )}
                        </Box>
                        <Box className="flex gap-4 mt-2 text-sm">
                            <span className="text-slate-500">
                                {isZh ? '港股通(沪)' : 'HK Connect (SH)'}: <span className={data.latest.hk_sh_net >= 0 ? 'text-red-600' : 'text-green-600'}>
                                    {formatAmount(data.latest.hk_sh_net)}
                                </span>
                            </span>
                            <span className="text-slate-500">
                                {isZh ? '港股通(深)' : 'HK Connect (SZ)'}: <span className={data.latest.hk_sz_net >= 0 ? 'text-red-600' : 'text-green-600'}>
                                    {formatAmount(data.latest.hk_sz_net)}
                                </span>
                            </span>
                        </Box>
                    </Box>
                )}

                {/* 5-Day Cumulative */}
                <Box className="flex justify-between items-center p-3 rounded-lg bg-slate-50">
                    <Typography variant="body2" className="text-slate-600 font-medium">
                        {isZh ? '5日累计' : '5-Day Total'}
                    </Typography>
                    <Typography variant="h6" className={`font-bold ${(data?.cumulative_5d || 0) >= 0 ? 'text-red-600' : 'text-green-600'}`}>
                        {formatAmount(data?.cumulative_5d || 0)} {isZh ? '亿' : 'B'}
                    </Typography>
                </Box>

                {/* History */}
                {data?.history && data.history.length > 0 && (
                    <Box className="flex-1">
                        <Typography variant="caption" className="text-slate-400 font-bold uppercase mb-2 block">
                            {isZh ? '近期走势' : 'Recent Trend'}
                        </Typography>
                        <Box className="flex gap-1 h-16">
                            {data.history.slice(0, 5).reverse().map((item, idx) => {
                                const maxVal = Math.max(...data.history.map(h => Math.abs(h.south_money)));
                                const height = maxVal > 0 ? (Math.abs(item.south_money) / maxVal) * 100 : 0;
                                return (
                                    <Box key={`${item.date}-${idx}`} className="flex-1 flex flex-col items-center justify-end">
                                        <Box
                                            className={`w-full rounded-t ${item.south_money >= 0 ? 'bg-red-400' : 'bg-green-400'}`}
                                            style={{ height: `${Math.max(height, 5)}%` }}
                                        />
                                        <Typography variant="caption" className="text-[9px] text-slate-400 mt-1">
                                            {item.date.slice(-5)}
                                        </Typography>
                                    </Box>
                                );
                            })}
                        </Box>
                    </Box>
                )}
            </Box>
        </WidgetContainer>
    );
}
