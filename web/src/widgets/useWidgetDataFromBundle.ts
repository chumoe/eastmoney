import { useState, useEffect, useCallback, useRef } from 'react';
import { useDashboardBundle } from './DashboardBundleContext';

/**
 * 带 Dashboard Bundle 缓存的 widget 数据 hook。
 *
 * 优先从 DashboardBundleContext 取数据，没有再调用 fetchFn。
 * 减少 HTTP 请求，加快 Dashboard 加载速度。
 */
export function useWidgetDataFromBundle<T>(
    bundleKey: string,
    fetchFn: () => Promise<T>,
    refreshInterval: number = 60000,
    enabled: boolean = true
) {
    const bundle = useDashboardBundle();
    const bundleData = bundle?.[bundleKey as keyof typeof bundle] as T | undefined;

    const [data, setData] = useState<T | null>(bundleData || null);
    const [loading, setLoading] = useState(!bundleData);
    const [error, setError] = useState<string | null>(null);
    const [lastUpdated, setLastUpdated] = useState<string | null>(bundle?.updated_at || null);

    const fetchFnRef = useRef(fetchFn);
    const initialized = useRef(!!bundleData);

    useEffect(() => {
        fetchFnRef.current = fetchFn;
    }, [fetchFn]);

    // 当 bundle 数据变化时更新
    useEffect(() => {
        if (bundleData !== undefined && bundleData !== null) {
            setData(bundleData);
            setLoading(false);
            setError(null);
            if (bundle?.updated_at) {
                setLastUpdated(bundle.updated_at);
            }
            initialized.current = true;
        }
    }, [bundleData, bundle?.updated_at]);

    const fetchData = useCallback(async (isAutoRefresh = false) => {
        if (!enabled) return;
        // 如果 bundle 里已经有数据了，就不用自己 fetch 了
        if (bundleData !== undefined && bundleData !== null) {
            return;
        }

        try {
            if (!initialized.current && !isAutoRefresh) {
                setLoading(true);
            }
            setError(null);
            const result = await fetchFnRef.current();
            setData(result);
            setLastUpdated(new Date().toISOString());
            initialized.current = true;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch data');
        } finally {
            setLoading(false);
        }
    }, [enabled, bundleData]);

    useEffect(() => {
        // bundle 里有数据就跳过初始 fetch
        if (bundleData !== undefined && bundleData !== null) {
            return;
        }

        fetchData(false);

        if (refreshInterval > 0 && enabled) {
            const interval = setInterval(() => fetchData(true), refreshInterval);
            return () => clearInterval(interval);
        }
    }, [fetchData, refreshInterval, enabled, bundleData]);

    return { data, loading, error, lastUpdated, refresh: () => fetchData(false) };
}
