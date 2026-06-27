import { useState, useEffect } from 'react';
import {
  Box,
  Paper,
  Typography,
  Grid,
  Chip,
  Tooltip,
  IconButton,
  Skeleton,
} from '@mui/material';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import RefreshIcon from '@mui/icons-material/Refresh';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet';
import NorthIcon from '@mui/icons-material/North';
import SouthIcon from '@mui/icons-material/South';
import BarChartIcon from '@mui/icons-material/BarChart';

import {
  fetchMarketIndicesData,
  fetchMarketSectors,
  fetchSouthboundFlow,
  fetchMarketSentiment,
} from '../../api';
import type {
  MarketIndicesResponse,
  MarketSectorsResponse,
  SouthboundFlowResponse,
  MarketSentiment,
  MarketIndex,
  SectorItem,
} from '../../api';

export default function FundMarketOverview() {
  const [indices, setIndices] = useState<MarketIndicesResponse | null>(null);
  const [sectors, setSectors] = useState<MarketSectorsResponse | null>(null);
  const [southbound, setSouthbound] = useState<SouthboundFlowResponse | null>(null);
  const [sentiment, setSentiment] = useState<MarketSentiment | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [indicesRes, sectorsRes, southboundRes, sentimentRes] = await Promise.all([
        fetchMarketIndicesData().catch(() => null),
        fetchMarketSectors(5).catch(() => null),
        fetchSouthboundFlow().catch(() => null),
        fetchMarketSentiment().catch(() => null),
      ]);
      setIndices(indicesRes);
      setSectors(sectorsRes);
      setSouthbound(southboundRes);
      setSentiment(sentimentRes);
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : '加载市场数据失败';
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const formatNumber = (num: number, unit: string = '') => {
    if (Math.abs(num) >= 100000000) {
      return `${(num / 100000000).toFixed(2)}亿${unit}`;
    } else if (Math.abs(num) >= 10000) {
      return `${(num / 10000).toFixed(2)}万${unit}`;
    }
    return `${num.toFixed(2)}${unit}`;
  };

  const renderChangeValue = (value: number, suffix: string = '%', showIcon: boolean = true) => {
    const isPositive = value > 0;
    const color = isPositive ? '#22c55e' : value < 0 ? '#ef4444' : '#64748b';

    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.3 }}>
        {showIcon && (isPositive ? (
          <TrendingUpIcon sx={{ fontSize: 14, color }} />
        ) : value < 0 ? (
          <TrendingDownIcon sx={{ fontSize: 14, color }} />
        ) : null)}
        <Typography
          sx={{
            color,
            fontWeight: 700,
            fontSize: '0.85rem',
            fontFamily: 'JetBrains Mono',
          }}
        >
          {isPositive ? '+' : ''}{value.toFixed(2)}{suffix}
        </Typography>
      </Box>
    );
  };

  // 渲染主要指数卡片
  const renderIndexCard = (index: MarketIndex) => {
    const isPositive = index.change_pct > 0;
    const color = isPositive ? '#22c55e' : index.change_pct < 0 ? '#ef4444' : '#64748b';
    const bgColor = isPositive ? '#f0fdf4' : index.change_pct < 0 ? '#fef2f2' : '#f8fafc';

    return (
      <Paper
        key={index.code}
        elevation={0}
        sx={{
          p: 2,
          borderRadius: '12px',
          border: `1px solid ${color}30`,
          bgcolor: bgColor,
          minWidth: 160,
        }}
      >
        <Typography sx={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600 }}>
          {index.name}
        </Typography>
        <Typography
          sx={{
            fontSize: '1.4rem',
            fontWeight: 800,
            color: '#1e293b',
            fontFamily: 'JetBrains Mono',
            my: 0.5,
          }}
        >
          {index.price.toFixed(2)}
        </Typography>
        <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'center' }}>
          {renderChangeValue(index.change_pct)}
          <Typography
            sx={{
              fontSize: '0.7rem',
              color,
              fontFamily: 'JetBrains Mono',
            }}
          >
            {index.change_val > 0 ? '+' : ''}{index.change_val.toFixed(2)}
          </Typography>
        </Box>
        <Box sx={{ mt: 1.5, display: 'flex', gap: 2 }}>
          <Box>
            <Typography sx={{ fontSize: '0.6rem', color: '#94a3b8' }}>成交额</Typography>
            <Typography sx={{ fontSize: '0.7rem', color: '#475569', fontFamily: 'JetBrains Mono' }}>
              {formatNumber(index.amount)}
            </Typography>
          </Box>
          <Box>
            <Typography sx={{ fontSize: '0.6rem', color: '#94a3b8' }}>振幅</Typography>
            <Typography sx={{ fontSize: '0.7rem', color: '#475569', fontFamily: 'JetBrains Mono' }}>
              {((index.high - index.low) / index.prev_close * 100).toFixed(2)}%
            </Typography>
          </Box>
        </Box>
      </Paper>
    );
  };

  // 渲染行业板块
  const renderSectorItem = (sector: SectorItem, isGainer: boolean) => {
    const color = isGainer ? '#22c55e' : '#ef4444';
    return (
      <Box
        key={sector.name}
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          py: 1,
          px: 1.5,
          borderRadius: '8px',
          '&:hover': { bgcolor: '#f8fafc' },
        }}
      >
        <Box sx={{ flex: 1 }}>
          <Typography sx={{ fontSize: '0.8rem', fontWeight: 600, color: '#1e293b' }}>
            {sector.name}
          </Typography>
          <Typography sx={{ fontSize: '0.65rem', color: '#94a3b8' }}>
            领涨: {sector.leading_stock}
          </Typography>
        </Box>
        <Box sx={{ textAlign: 'right' }}>
          <Typography
            sx={{
              fontSize: '0.85rem',
              fontWeight: 700,
              color,
              fontFamily: 'JetBrains Mono',
            }}
          >
            {sector.change_pct > 0 ? '+' : ''}{sector.change_pct.toFixed(2)}%
          </Typography>
          <Typography sx={{ fontSize: '0.6rem', color: '#94a3b8' }}>
            换手率: {sector.turnover_rate.toFixed(2)}%
          </Typography>
        </Box>
      </Box>
    );
  };

  // 渲染市场情绪
  const renderSentimentBar = () => {
    if (!sentiment) return null;
    const total = sentiment.up_count + sentiment.down_count + sentiment.flat_count;
    const upPct = (sentiment.up_count / total) * 100;
    const downPct = (sentiment.down_count / total) * 100;

    return (
      <Box sx={{ mt: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: '#22c55e' }} />
            <Typography sx={{ fontSize: '0.7rem', color: '#22c55e', fontWeight: 600 }}>
              上涨 {sentiment.up_count}
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: '#94a3b8' }} />
            <Typography sx={{ fontSize: '0.7rem', color: '#94a3b8', fontWeight: 600 }}>
              平盘 {sentiment.flat_count}
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: '#ef4444' }} />
            <Typography sx={{ fontSize: '0.7rem', color: '#ef4444', fontWeight: 600 }}>
              下跌 {sentiment.down_count}
            </Typography>
          </Box>
        </Box>
        <Box
          sx={{
            height: 8,
            borderRadius: 4,
            overflow: 'hidden',
            display: 'flex',
            bgcolor: '#f1f5f9',
          }}
        >
          <Box sx={{ width: `${upPct}%`, bgcolor: '#22c55e', transition: 'width 0.3s' }} />
          <Box sx={{ width: `${100 - upPct - downPct}%`, bgcolor: '#94a3b8', transition: 'width 0.3s' }} />
          <Box sx={{ width: `${downPct}%`, bgcolor: '#ef4444', transition: 'width 0.3s' }} />
        </Box>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 1.5 }}>
          <Chip
            icon={<NorthIcon sx={{ fontSize: 12 }} />}
            label={`涨停 ${sentiment.limit_up}`}
            size="small"
            sx={{
              bgcolor: '#dcfce7',
              color: '#16a34a',
              fontWeight: 600,
              fontSize: '0.7rem',
            }}
          />
          <Chip
            icon={<SouthIcon sx={{ fontSize: 12 }} />}
            label={`跌停 ${sentiment.limit_down}`}
            size="small"
            sx={{
              bgcolor: '#fee2e2',
              color: '#dc2626',
              fontWeight: 600,
              fontSize: '0.7rem',
            }}
          />
        </Box>
      </Box>
    );
  };

  // 渲染南向资金
  const renderSouthboundFlow = () => {
    if (!southbound?.today) return null;
    const { today } = southbound;
    const isInflow = today.south_money > 0;
    const color = isInflow ? '#ef4444' : '#22c55e';

    return (
      <Box>
        <Box sx={{ textAlign: 'center', mb: 2 }}>
          <Typography sx={{ fontSize: '0.7rem', color: '#64748b', mb: 0.5 }}>
            南向资金净流入
          </Typography>
          <Typography
            sx={{
              fontSize: '1.8rem',
              fontWeight: 800,
              color,
              fontFamily: 'JetBrains Mono',
            }}
          >
            {formatNumber(today.south_money)}
          </Typography>
        </Box>
        <Grid container spacing={2}>
          <Grid size={6}>
            <Paper
              elevation={0}
              sx={{
                p: 1.5,
                borderRadius: '10px',
                bgcolor: '#fef3c7',
                textAlign: 'center',
              }}
            >
              <Typography sx={{ fontSize: '0.65rem', color: '#92400e' }}>
                港股通(沪)
              </Typography>
              <Typography
                sx={{
                  fontSize: '1rem',
                  fontWeight: 700,
                  color: today.hk_sh_net > 0 ? '#ef4444' : '#22c55e',
                  fontFamily: 'JetBrains Mono',
                }}
              >
                {formatNumber(today.hk_sh_net)}
              </Typography>
            </Paper>
          </Grid>
          <Grid size={6}>
            <Paper
              elevation={0}
              sx={{
                p: 1.5,
                borderRadius: '10px',
                bgcolor: '#dbeafe',
                textAlign: 'center',
              }}
            >
              <Typography sx={{ fontSize: '0.65rem', color: '#1e40af' }}>
                港股通(深)
              </Typography>
              <Typography
                sx={{
                  fontSize: '1rem',
                  fontWeight: 700,
                  color: today.hk_sz_net > 0 ? '#ef4444' : '#22c55e',
                  fontFamily: 'JetBrains Mono',
                }}
              >
                {formatNumber(today.hk_sz_net)}
              </Typography>
            </Paper>
          </Grid>
        </Grid>
      </Box>
    );
  };

  if (loading) {
    return (
      <Box sx={{ mb: 4 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Skeleton variant="text" width={150} height={32} />
        </Box>
        <Grid container spacing={2}>
          {[1, 2, 3, 4].map((i) => (
            <Grid size={{ xs: 12, sm: 6, md: 3 }} key={i}>
              <Skeleton variant="rounded" height={140} sx={{ borderRadius: '12px' }} />
            </Grid>
          ))}
        </Grid>
      </Box>
    );
  }

  if (error) {
    return (
      <Paper
        elevation={0}
        sx={{
          p: 4,
          textAlign: 'center',
          borderRadius: '16px',
          border: '1px solid #fecaca',
          bgcolor: '#fef2f2',
          mb: 4,
        }}
      >
        <Typography sx={{ color: '#ef4444', mb: 2 }}>{error}</Typography>
        <IconButton onClick={loadData} sx={{ color: '#6366f1' }}>
          <RefreshIcon />
        </IconButton>
      </Paper>
    );
  }

  return (
    <Box sx={{ mb: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2.5 }}>
        <Box>
          <Typography variant="h6" sx={{ fontWeight: 700, color: '#1e293b' }}>
            📊 市场概览
          </Typography>
          <Typography sx={{ fontSize: '0.75rem', color: '#94a3b8' }}>
            A股主要指数、行业板块、资金流向
          </Typography>
        </Box>
        <Tooltip title="刷新数据">
          <IconButton
            onClick={loadData}
            size="small"
            sx={{ color: '#94a3b8', '&:hover': { color: '#6366f1' } }}
          >
            <RefreshIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>

      {/* 主要指数 */}
      {indices?.indices && indices.indices.length > 0 && (
        <Box sx={{ mb: 3 }}>
          <Typography sx={{ fontSize: '0.8rem', fontWeight: 600, color: '#64748b', mb: 1.5, display: 'flex', alignItems: 'center', gap: 1 }}>
            <ShowChartIcon sx={{ fontSize: 16 }} /> 主要指数
          </Typography>
          <Box
            sx={{
              display: 'flex',
              gap: 2,
              overflowX: 'auto',
              pb: 1,
              '&::-webkit-scrollbar': { height: 4 },
              '&::-webkit-scrollbar-thumb': { bgcolor: '#e2e8f0', borderRadius: 2 },
            }}
          >
            {indices.indices.map(renderIndexCard)}
          </Box>
        </Box>
      )}

      <Grid container spacing={3}>
        {/* 行业板块 */}
        {sectors && (
          <Grid size={{ xs: 12, md: 6 }}>
            <Paper
              elevation={0}
              sx={{
                p: 2.5,
                borderRadius: '16px',
                border: '1px solid #f1f5f9',
                height: '100%',
              }}
            >
              <Typography sx={{ fontSize: '0.85rem', fontWeight: 700, color: '#1e293b', mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
                <BarChartIcon sx={{ fontSize: 18, color: '#6366f1' }} /> 行业板块
              </Typography>
              
              <Grid container spacing={2}>
                <Grid size={6}>
                  <Typography sx={{ fontSize: '0.7rem', color: '#22c55e', fontWeight: 600, mb: 1 }}>
                    🔥 领涨板块
                  </Typography>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                    {sectors.top_gainers.map((s) => renderSectorItem(s, true))}
                  </Box>
                </Grid>
                <Grid size={6}>
                  <Typography sx={{ fontSize: '0.7rem', color: '#ef4444', fontWeight: 600, mb: 1 }}>
                    ❄️ 领跌板块
                  </Typography>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                    {sectors.top_losers.map((s) => renderSectorItem(s, false))}
                  </Box>
                </Grid>
              </Grid>
            </Paper>
          </Grid>
        )}

        {/* 资金流向 & 市场情绪 */}
        <Grid size={{ xs: 12, md: 6 }}>
          <Grid container spacing={2} sx={{ height: '100%' }}>
            {/* 南向资金 */}
            <Grid size={{ xs: 12 }}>
              <Paper
                elevation={0}
                sx={{
                  p: 2.5,
                  borderRadius: '16px',
                  border: '1px solid #f1f5f9',
                }}
              >
                <Typography sx={{ fontSize: '0.85rem', fontWeight: 700, color: '#1e293b', mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
                  <AccountBalanceWalletIcon sx={{ fontSize: 18, color: '#f59e0b' }} /> 南向资金
                </Typography>
                {renderSouthboundFlow()}
              </Paper>
            </Grid>

            {/* 市场情绪 */}
            {sentiment && (
              <Grid size={12}>
                <Paper
                  elevation={0}
                  sx={{
                    p: 2.5,
                    borderRadius: '16px',
                    border: '1px solid #f1f5f9',
                  }}
                >
                  <Typography sx={{ fontSize: '0.85rem', fontWeight: 700, color: '#1e293b', display: 'flex', alignItems: 'center', gap: 1 }}>
                    📈 市场情绪
                  </Typography>
                  {renderSentimentBar()}
                </Paper>
              </Grid>
            )}
          </Grid>
        </Grid>
      </Grid>
    </Box>
  );
}
