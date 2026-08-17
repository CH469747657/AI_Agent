import { ChatWidget } from "../ChatWidget";

/**
 * 管理端"智能问数"右侧固定面板壳。
 * fixed right-0 top-0，全高，宽 420px，与左侧 Sidebar 视觉对称。
 * 无悬浮按钮、无缩放手柄，常驻显示。
 */
export function ChatSidePanel() {
  return (
    <aside className="fixed right-0 top-0 z-20 flex h-[100dvh] w-[420px] flex-col border-l border-border bg-background shadow-[0_0_40px_-20px_rgba(0,0,0,0.15)]">
      <div className="flex h-full flex-col py-2 pr-2">
        <ChatWidget mode="panel" />
      </div>
    </aside>
  );
}
