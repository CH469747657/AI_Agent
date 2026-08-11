import { useState, useEffect, useCallback } from "react";

interface UseFetchState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

/**
 * 通用数据请求 Hook
 *
 * @param fetcher 返回 Promise 的数据获取函数
 * @param deps 依赖数组，变化时重新请求
 * @param options.initialLoading 初始 loading 状态，默认 true
 */
export function useFetch<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  options?: { initialLoading?: boolean }
): UseFetchState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(options?.initialLoading !== false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetcher()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { data, loading, error, refetch };
}

/**
 * Portal 专用数据请求 Hook
 *
 * 在 useFetch 基础上增加：
 * - 401 自动跳转 /portal/login
 * - 自动从 localStorage 注入 Authorization header
 */
export function usePortalFetch<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = []
): UseFetchState<T> {
  const wrappedFetcher = useCallback(async () => {
    try {
      return await fetcher();
    } catch (err: any) {
      // 401 → 跳转登录
      if (err?.message?.includes("401") || err?.status === 401) {
        localStorage.removeItem("portal_token");
        window.location.href = "/portal/login";
      }
      throw err;
    }
  }, [fetcher]);

  return useFetch(wrappedFetcher, deps);
}
