import { useEffect, useState, useCallback } from "react";
import { portalApi } from "../../api/client";
import type { PortalDashboard } from "../../types";
import { Spinner } from "@phosphor-icons/react";
import { ChatFullscreen } from "../../components/chat/ChatFullscreen";

export function PortalHome() {
  const [dashboard, setDashboard] = useState<PortalDashboard | null>(null);
  const [loading, setLoading] = useState(true);

  const loadDashboard = useCallback(() => {
    return portalApi.dashboard()
      .then(setDashboard)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  // 监听对话操作（上传/删除/修改发票）→ 刷新本周期统计
  useEffect(() => {
    const handler = () => { loadDashboard(); };
    window.addEventListener("chat-invoices-changed", handler);
    return () => window.removeEventListener("chat-invoices-changed", handler);
  }, [loadDashboard]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner size={24} className="animate-spin text-primary-600" />
      </div>
    );
  }

  const employee = portalApi.getStoredEmployee();
  const dashboardData = dashboard ?? {
    invoice_count: 0,
    invoice_total: 0,
    cycle_key: "",
    cycle_start: "",
    cycle_end: "",
  } as PortalDashboard;

  // 周期显示：2026-07-21 ~ 2026-08-20 → "7.21–8.20"
  const fmtCycle = (iso: string) => {
    if (!iso) return "";
    const d = new Date(iso);
    return `${d.getMonth() + 1}.${d.getDate()}`;
  };
  const cycleLabel = dashboardData.cycle_start
    ? `${fmtCycle(dashboardData.cycle_start)}–${fmtCycle(dashboardData.cycle_end)}`
    : "";

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] flex-col sm:h-[calc(100dvh-3.5rem)]">
      {/* 顶部迷你摘要条 — 本周期发票统计（手机端可换行） */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 pt-4 text-sm text-muted-foreground sm:gap-6 sm:px-8 sm:pt-6">
        <span>
          你好，<b className="text-foreground">{employee?.name}</b>
        </span>
        <span className="hidden h-3 w-px bg-border sm:block" />
        {cycleLabel && (
          <span>
            本期 <b className="font-mono text-foreground">{cycleLabel}</b>
          </span>
        )}
        <span>
          发票 <b className="font-mono text-foreground">{dashboardData.invoice_count}</b>
        </span>
        <span>
          金额{" "}
          <b className="font-mono text-foreground">
            ¥{dashboardData.invoice_total.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
          </b>
        </span>
      </div>

      {/* 智能问数全屏主体 — min-h-0 让内部 overflow 生效，手机端 px-2 铺满 */}
      <div className="flex-1 min-h-0 px-2 pb-2 pt-2 sm:px-8 sm:pb-6 sm:pt-4">
        <ChatFullscreen />
      </div>
    </div>
  );
}
