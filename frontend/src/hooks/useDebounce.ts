import { useState, useEffect } from "react";

/**
 * 防抖 Hook — 延迟更新值，减少高频输入时的触发次数
 *
 * @param value 需要防抖的值
 * @param delay 延迟毫秒数，默认 300ms
 * @returns 防抖后的值
 *
 * @example
 * const [search, setSearch] = useState("");
 * const debouncedSearch = useDebounce(search, 300);
 * // 用 debouncedSearch 触发 API 请求或计算
 */
export function useDebounce<T>(value: T, delay: number = 300): T {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debouncedValue;
}
