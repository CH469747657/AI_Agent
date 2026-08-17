import { ChatWidget } from "../ChatWidget";

/**
 * 员工端"智能问数"全屏主体壳。
 * 占满父容器剩余高度，无悬浮按钮、无缩放手柄。
 * 流光边框 + 脉冲指示点由 ChatWidget 内部 header 实现。
 * min-h-0 让 flex 子项可缩小，内部消息区 overflow-y-auto 才能独立滚动。
 */
export function ChatFullscreen() {
  return (
    <div className="flex h-full min-h-0 w-full flex-col px-0 sm:px-2">
      <ChatWidget mode="fullscreen" />
    </div>
  );
}
