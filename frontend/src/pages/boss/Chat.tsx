import { bossApi } from "../../api/client";
import { ChatFullscreen } from "../../components/chat/ChatFullscreen";

/**
 * 老板端"智能问数"页 — 复用员工端 ChatFullscreen 主体
 *
 * ChatWidget 内部 useRoleAndUserId 会按 /boss/* 路径推导 role=boss，
 * 对话引擎后端按 BOSS 角色路由 BOSS 意图（含 3 个 BOSS 独有洞察）。
 */
export function BossChat() {
  const profile = bossApi.getProfile();

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] flex-col sm:h-[calc(100dvh-3.5rem)]">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 pt-4 text-sm text-muted-foreground sm:gap-6 sm:px-8 sm:pt-6">
        <span>
          您好，<b className="text-foreground">{profile?.name || "老板"}</b>
        </span>
        <span className="hidden h-3 w-px bg-border sm:block" />
        <span>
          可穿透查看<b className="text-foreground">全公司</b>发票与报销明细
        </span>
      </div>

      <div className="flex-1 min-h-0 px-2 pb-2 pt-2 sm:px-8 sm:pb-6 sm:pt-4">
        <ChatFullscreen />
      </div>
    </div>
  );
}
