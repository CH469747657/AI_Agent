import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  ChatCircle,
  X,
  PaperPlaneTilt,
  Paperclip,
  ArrowsClockwise,
  Robot,
  UserCircle,
  Warning,
  WarningCircle,
  ArrowCounterClockwise,
  Calendar,
} from "@phosphor-icons/react";
import { dialogApi, portalApi, bossApi } from "../api/client";
import type { DialogMessage, DialogRole, BatchInvoiceSummary, TravelDay } from "../types";
import { ACCEPTED_TYPES, MAX_FILE_SIZE } from "../components/upload/index";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { TravelDayPicker } from "./TravelDayPicker";

/** 生成消息 ID */
function genId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/** 格式化时间 HH:MM */
function formatTime(ts: number): string {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** 文件转 base64 */
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // 去掉 data:image/xxx;base64, 前缀
      const base64 = result.split(",")[1] || result;
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

/** 文件转缩略图 data URL（用于消息内预览） */
function fileToPreview(file: File): Promise<string> {
  return new Promise((resolve) => {
    if (!file.type.startsWith("image/")) {
      resolve("");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => resolve("");
    reader.readAsDataURL(file);
  });
}

/** 从 File 对象推导后端 file_type（扩展名映射） */
function deriveFileType(file: File): string {
  const ext = file.name.split(".").pop()?.toLowerCase() || "";
  if (ext === "pdf") return "pdf";
  if (ext === "ofd") return "ofd";
  // 图片统一返回原始扩展名，后端不区分具体格式
  return ext || "jpg";
}

/** 从路由推导角色与用户ID */
function useRoleAndUserId(): { role: DialogRole; userId: string; displayName: string } {
  const location = useLocation();
  const isPortal = location.pathname.startsWith("/portal");
  const isBoss = location.pathname.startsWith("/boss");
  const isLogin = location.pathname === "/portal/login" || location.pathname === "/boss/login";

  return useMemo(() => {
    if (isPortal && !isLogin) {
      const emp = portalApi.getStoredEmployee();
      return {
        role: "employee" as DialogRole,
        userId: emp?.employee_no || emp?.id?.toString() || "portal_user",
        displayName: emp?.name || "员工",
      };
    }
    if (isBoss && !isLogin) {
      const profile = bossApi.getProfile();
      return {
        role: "boss" as DialogRole,
        userId: profile?.username || "boss",
        displayName: profile?.name || "超级管理员",
      };
    }
    // 管理后台默认 admin
    return {
      role: "admin" as DialogRole,
      userId: "admin",
      displayName: "管理员",
    };
  }, [isPortal, isBoss, isLogin]);
}

// ============================================================
// 可缩放 Hook
// ============================================================

/** 缩放尺寸限制 */
const MIN_WIDTH = 320;
const MIN_HEIGHT = 400;
const MAX_WIDTH = 720;
const MAX_HEIGHT = 900;

type ResizeDirection =
  | "left" | "right" | "top" | "bottom"
  | "top-left" | "top-right" | "bottom-left" | "bottom-right";

type InteractionType = "drag" | `resize-${ResizeDirection}` | null;

interface PanelGeo {
  x: number;  // 面板左上角 x
  y: number;  // 面板左上角 y
  width: number;
  height: number;
}

/** 可拖拽 + 可缩放窗口 hook
 *  - drag：按住 header 移动面板，边界限制在视口内
 *  - resize：8 方向缩放手柄，最小尺寸限制
 *  - 拖拽/缩放时 isInteracting=true，供视觉反馈
 */
function useDraggableResizable(defaultWidth = 400, defaultHeight = 600) {
  // 初始位置：右下角，距边距 1.5rem
  const initPos = () => ({
    x: Math.max(0, window.innerWidth - defaultWidth - 24),
    y: Math.max(0, window.innerHeight - defaultHeight - 24),
  });

  const [geo, setGeo] = useState<PanelGeo>(() => ({
    ...initPos(),
    width: defaultWidth,
    height: defaultHeight,
  }));
  const [isInteracting, setIsInteracting] = useState(false);
  const interactionRef = useRef<{
    type: Exclude<InteractionType, null>;
    startX: number;
    startY: number;
    startGeo: PanelGeo;
  } | null>(null);

  const startDrag = useCallback((e: React.PointerEvent) => {
    if (e.button !== 0) return;
    // 用 e.target 检查是否点到了按钮（重置/关闭），是则不启动拖拽
    // 注意：不能用 e.currentTarget（那是 header div 本身，closest("button") 永远 null）
    const target = e.target as HTMLElement;
    if (target.closest("button")) return;
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    interactionRef.current = {
      type: "drag",
      startX: e.clientX,
      startY: e.clientY,
      startGeo: { ...geo },
    };
    setIsInteracting(true);
  }, [geo]);

  const startResize = useCallback(
    (e: React.PointerEvent, direction: ResizeDirection) => {
      e.preventDefault();
      e.stopPropagation();
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      interactionRef.current = {
        type: `resize-${direction}` as const,
        startX: e.clientX,
        startY: e.clientY,
        startGeo: { ...geo },
      };
      setIsInteracting(true);
    },
    [geo]
  );

  useEffect(() => {
    const handleMove = (e: PointerEvent) => {
      const r = interactionRef.current;
      if (!r) return;

      const dx = e.clientX - r.startX;
      const dy = e.clientY - r.startY;
      const s = r.startGeo;

      if (r.type === "drag") {
        // 边界限制：面板不拖出视口
        const maxX = window.innerWidth - s.width - 8;
        const maxY = window.innerHeight - s.height - 8;
        setGeo({
          ...s,
          x: Math.min(Math.max(8, s.x + dx), Math.max(8, maxX)),
          y: Math.min(Math.max(8, s.y + dy), Math.max(8, maxY)),
        });
        return;
      }

      // resize：解析方向
      const dir = r.type.replace("resize-", "") as ResizeDirection;
      let { x, y, width, height } = s;

      // right / bottom：向右/下拖 → 宽/高增大
      if (dir === "right" || dir === "bottom-right" || dir === "top-right") {
        width = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, s.width + dx));
      }
      if (dir === "bottom" || dir === "bottom-right" || dir === "bottom-left") {
        height = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, s.height + dy));
      }
      // left / top：向左/上拖 → 宽/高增大，但 x/y 需随动以保持右/下边固定
      if (dir === "left" || dir === "top-left" || dir === "bottom-left") {
        const newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, s.width - dx));
        const newX = s.x + (s.width - newWidth);
        x = Math.max(8, newX);
        width = newWidth;
      }
      if (dir === "top" || dir === "top-left" || dir === "top-right") {
        const newHeight = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, s.height - dy));
        const newY = s.y + (s.height - newHeight);
        y = Math.max(8, newY);
        height = newHeight;
      }

      setGeo({ x, y, width, height });
    };

    const handleUp = () => {
      interactionRef.current = null;
      setIsInteracting(false);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
  }, []);

  return { geo, setGeo, isInteracting, startDrag, startResize };
}

// ============================================================
// 子组件
// ============================================================

/** 打字指示器 */
function TypingDots() {
  return (
    <div className="flex items-center gap-1 px-3 py-2.5">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="h-2 w-2 rounded-full bg-muted"
          animate={{ opacity: [0.3, 1, 0.3], y: [0, -3, 0] }}
          transition={{
            duration: 1,
            repeat: Infinity,
            delay: i * 0.2,
            ease: "easeInOut",
          }}
        />
      ))}
    </div>
  );
}

/** 发票摘要卡片 */
function BatchSummaryCard({
  summary,
}: {
  summary: BatchInvoiceSummary;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-background px-3 py-2 shadow-sm">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-100 text-sm font-bold text-primary-700">
        {summary.index}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-foreground">
          {summary.seller_name}
        </div>
        <div className="text-xs text-muted-foreground">
          {summary.receipt_type} · ¥{summary.total_with_tax} · {summary.issue_date}
        </div>
      </div>
    </div>
  );
}

/** 单条消息气泡 */
function MessageBubble({
  msg,
  onUndo,
}: {
  msg: DialogMessage;
  onUndo?: (invoiceId: number) => void;
}) {
  const isUser = msg.role === "user";
  const isSystem = msg.role === "system";
  const isError = !!msg.error;

  if (isSystem) {
    return (
      <div className="flex justify-center py-1">
        <span
          className={`rounded-full px-3 py-1 text-xs font-medium ${
            isError
              ? "bg-red-50 text-red-600"
              : "bg-muted text-muted-foreground"
          }`}
        >
          {isError && <Warning size={12} weight="fill" className="mr-1 inline" />}
          {msg.text}
        </span>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 24 }}
      className={`flex gap-2 ${isUser ? "flex-row-reverse" : "flex-row"}`}
    >
      {/* 头像 */}
      <div
        className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
          isUser ? "bg-primary-100" : "bg-muted"
        }`}
      >
        {isUser ? (
          <UserCircle size={16} weight="fill" className="text-primary-600" />
        ) : (
          <Robot size={16} weight="fill" className="text-muted-foreground" />
        )}
      </div>

      {/* 消息内容 */}
      <div className={`flex max-w-[88%] flex-col sm:max-w-[78%] ${isUser ? "items-end" : "items-start"}`}>
        {/* 附件预览 */}
        {msg.attachmentPreview && (
          <img
            src={msg.attachmentPreview}
            alt="附件"
            className="mb-1 max-h-32 rounded-lg border border-border object-cover"
          />
        )}
        {/* 文本气泡 */}
        <div
          className={`whitespace-pre-wrap break-words px-3 py-1.5 text-[13px] leading-relaxed sm:px-3.5 sm:py-2 sm:text-sm ${
            isUser
              ? "user-bubble"
              : isError
                ? "rounded-tl-md bg-red-50 text-red-700"
                : "ai-bubble"
          }`}
        >
          <MarkdownRenderer content={msg.text} />
        </div>
        {/* 发票摘要列表（追问用途时展示） */}
        {!isUser && msg.batchSummary && msg.batchSummary.length > 0 && (
          <div className="mt-2 space-y-2 pl-0">
            <div className="text-xs font-medium text-muted-foreground">
              请按序号描述用途：
            </div>
            <div className="space-y-1.5">
              {msg.batchSummary.map((item) => (
                <BatchSummaryCard key={item.id} summary={item} />
              ))}
            </div>
          </div>
        )}
        {/* 撤销上传按钮（仅上传成功消息显示） */}
        {!isUser && !msg.undone && msg.invoiceId && onUndo && (
          <motion.button
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.2 }}
            onClick={() => onUndo(msg.invoiceId!)}
            className="mt-1 inline-flex items-center gap-1 rounded-lg bg-background px-2.5 py-1 text-xs font-medium text-muted-foreground ring-1 ring-border transition-colors hover:bg-red-50 hover:text-red-600 hover:ring-red-200"
          >
            <ArrowCounterClockwise size={12} weight="bold" />
            撤销上传
          </motion.button>
        )}
        {/* 操作标记 + 时间 */}
        <div className={`mt-0.5 flex items-center gap-1.5 text-[10px] text-muted-foreground`}>
          {msg.actionTaken && (
            <span className="inline-flex items-center gap-0.5 rounded bg-emerald-50 px-1 py-0.5 font-medium text-emerald-600">
              已执行
            </span>
          )}
          <span>{formatTime(msg.timestamp)}</span>
        </div>
      </div>
    </motion.div>
  );
}

/** 快捷回复筹码 */
function QuickReplyChips({
  replies,
  onSelect,
}: {
  replies: string[];
  onSelect: (text: string) => void;
}) {
  if (!replies.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5 pl-9">
      {replies.map((reply, i) => (
        <motion.button
          key={`${reply}-${i}`}
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: i * 0.05 }}
          onClick={() => onSelect(reply)}
          className="rounded-full border border-primary-200 bg-primary-50 px-3 py-1 text-xs font-medium text-primary-700 transition-colors hover:bg-primary-100 active:scale-95"
        >
          {reply}
        </motion.button>
      ))}
    </div>
  );
}

// ============================================================
// 主组件
// ============================================================

/** 欢迎消息 */
function createWelcomeMessage(role: DialogRole, name: string): DialogMessage {
  const greeting =
    role === "employee"
      ? `你好${name}！我是 AI 报销助手，发送发票图片即可上传报销，输入「帮助」查看完整功能。`
      : role === "admin"
        ? `管理员你好！我可以帮你上传发票、查询报销、审批操作和数据洞察。输入「帮助」查看详情。`
        : `超级管理员好！我可以帮您查看公司报销数据洞察。输入「帮助」查看可用功能。`;
  return {
    id: "welcome",
    role: "assistant",
    text: greeting,
    timestamp: Date.now(),
    quickReplies:
      role === "employee"
        ? ["查询报销", "我的发票", "我的报销", "帮助"]
        : role === "admin"
          ? ["待审批", "公司花了多少", "有没有异常", "帮助"]
          : ["本月报销总额", "哪个部门花得多", "趋势", "帮助"],
  };
}

export function ChatWidget({ mode = "floating" }: { mode?: "floating" | "fullscreen" | "panel" }) {
  const { role, userId, displayName } = useRoleAndUserId();
  // floating 模式才用拖拽/缩放和 isOpen 状态；fullscreen/panel 始终展开
  const isFloating = mode === "floating";

  // 位置/大小持久化（localStorage）— 记忆用户上次拖拽/缩放后的状态
  const GEO_STORAGE_KEY = "chat_panel_geo";
  const loadGeo = () => {
    try {
      const saved = localStorage.getItem(GEO_STORAGE_KEY);
      if (saved) {
        const g = JSON.parse(saved);
        // 窗口尺寸变化后，确保面板不超出当前视口
        const x = Math.min(g.x, window.innerWidth - 320 - 8);
        const y = Math.min(g.y, window.innerHeight - 400 - 8);
        return { ...g, x: Math.max(8, x), y: Math.max(8, y) };
      }
    } catch {}
    return null;
  };
  const { geo, setGeo, isInteracting, startDrag, startResize } = useDraggableResizable(400, 600);
  // 首次加载从 localStorage 恢复
  useEffect(() => {
    if (!isFloating) return;
    const saved = loadGeo();
    if (saved) setGeo(saved);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isFloating]);
  // geo 变化时持久化（拖拽/缩放结束后）
  useEffect(() => {
    if (!isFloating) return;
    localStorage.setItem(GEO_STORAGE_KEY, JSON.stringify(geo));
  }, [isFloating, geo]);

  // isOpen 持久化：记忆用户是否手动隐藏
  const OPEN_STORAGE_KEY = "chat_panel_open";
  const [isOpen, setIsOpen] = useState(() => {
    if (!isFloating) return true;
    try {
      return localStorage.getItem(OPEN_STORAGE_KEY) !== "false";
    } catch {
      return false; // 默认收起，避免遮挡主内容
    }
  });
  const toggleOpen = useCallback((open: boolean) => {
    setIsOpen(open);
    try { localStorage.setItem(OPEN_STORAGE_KEY, String(open)); } catch {}
  }, []);

  // 快捷键 Cmd/Ctrl+K 切换显示
  useEffect(() => {
    if (!isFloating) return;
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        toggleOpen(!isOpen);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isFloating, isOpen, toggleOpen]);

  const [messages, setMessages] = useState<DialogMessage[]>([]);
  const [inputText, setInputText] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [filePreview, setFilePreview] = useState<string>("");
  // 批量待发送文件：用户选多文件后暂存，等输入说明并点发送时一起上传
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);

  // 出差日标记 picker 状态（仅 employee role）
  const [travelPickerOpen, setTravelPickerOpen] = useState(false);
  const [travelDays, setTravelDays] = useState<TravelDay[]>([]);
  const [currentCycleStart, setCurrentCycleStart] = useState<string | null>(null);
  const [currentCycleEnd, setCurrentCycleEnd] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 用 ref 跟踪 isTyping 状态，解决 useCallback 闭包陈旧值导致并发请求的问题
  // 当 for 循环连续调用 handleSend 时，闭包捕获的 isTyping 始终为初始 false，
  // 导致两个请求同时发出。ref 不受闭包影响，始终读取最新值。
  const isTypingRef = useRef(false);
  // uploadPendingFiles ref — handleSend 通过 ref 调用，避免 useCallback 循环依赖
  const uploadPendingFilesRef = useRef<((purpose: string) => Promise<void>) | null>(null);

  // 当前角色/用户变化时重置消息
  // 按 userId 做消息持久化 key
  const storageKey = `chat_messages_${userId}`;

  // 初始化：从 sessionStorage 恢复消息
  useEffect(() => {
    // floating 模式未展开不加载；fullscreen/panel 始终加载
    if (isFloating && !isOpen) return;
    if (messages.length > 0) return; // 已有消息不重复加载
    try {
      const saved = sessionStorage.getItem(storageKey);
      if (saved) {
        setMessages(JSON.parse(saved));
      } else {
        setMessages([createWelcomeMessage(role, displayName)]);
      }
    } catch {
      setMessages([createWelcomeMessage(role, displayName)]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isFloating, isOpen, userId]);

  // 消息变化时持久化 + 自动滚动到底部
  useEffect(() => {
    if (messages.length === 0) return;
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(messages));
    } catch {
      // sessionStorage 满了就跳过
    }
  }, [messages, storageKey]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isTyping]);

  // 自适应 textarea 高度
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`;
  }, [inputText]);

  // 员工端：加载当前周期 + 已标出差日（用于日历按钮）
  useEffect(() => {
    if (role !== "employee") return;
    portalApi
      .dashboard()
      .then((d) => {
        setCurrentCycleStart(d.cycle_start);
        setCurrentCycleEnd(d.cycle_end);
      })
      .catch(() => {});
    portalApi
      .listTravelDays()
      .then(setTravelDays)
      .catch(() => {});
  }, [role]);

  /** 员工标记出差日提交：批量增删 */
  const handleTravelDaysSubmit = async (
    selected: { date: string; note: string | null }[],
    removed: string[]
  ) => {
    const added: string[] = [];
    for (const item of selected) {
      try {
        await portalApi.createTravelDay(item.date, item.note || undefined);
        added.push(item.date);
      } catch (err) {
        console.error(`标记 ${item.date} 失败`, err);
      }
    }
    for (const date of removed) {
      try {
        await portalApi.deleteTravelDayByDate(date);
      } catch (err) {
        console.error(`删除 ${date} 失败`, err);
      }
    }
    try {
      const fresh = await portalApi.listTravelDays();
      setTravelDays(fresh);
    } catch {}
    const msgs: string[] = [];
    if (added.length > 0) {
      msgs.push(`已标记 ${added.length} 天为出差日：${added.join("、")}`);
    }
    if (removed.length > 0) {
      msgs.push(`已取消 ${removed.length} 天出差日：${removed.join("、")}`);
    }
    if (msgs.length > 0) {
      setMessages((prev) => [
        ...prev,
        {
          id: `travel-${Date.now()}`,
          role: "assistant",
          text: msgs.join("。") + "。",
          timestamp: Date.now(),
        } as DialogMessage,
      ]);
    }
  };

  /** 发送消息 */
  const handleSend = useCallback(
    async (
      text?: string,
      file?: File | null,
      opts?: {
        receiptType?: string;
        purpose?: string;
        fileType?: string;
        preview?: string;
        skipPending?: boolean;  // 内部调用时跳过批量分支，避免循环
      }
    ) => {
      const content = (text ?? inputText).trim();
      const attachFile = file ?? selectedFile;

      if (!content && !attachFile) return;
      // 用 ref 防重入，解决 useCallback 闭包陈旧值导致 for 循环并发的问题
      if (isTypingRef.current) return;
      isTypingRef.current = true;

      // 批量待发送文件：用户已选多文件 + 输入说明 + 点发送
      // 此时优先走批量上传流程，第一张带文本，后续张只发附件
      // skipPending=true 时跳过此分支（来自 uploadPendingFiles 的内部调用）
      if (!opts?.skipPending && uploadPendingFilesRef.current && pendingFiles.length > 0) {
        const purpose = content; // 用户输入的说明
        // 先把用户消息显示出来（仅第一张带文本）
        if (purpose) {
          const firstPreview = await fileToPreview(pendingFiles[0]);
          setMessages((prev) => [
            ...prev,
            {
              id: genId(),
              role: "user",
              text: purpose,
              timestamp: Date.now(),
              attachmentPreview: firstPreview || undefined,
            },
          ]);
        }
        setInputText("");
        // 释放防重入锁，让 uploadPendingFiles 内部的 handleSend 调用能正常进入
        isTypingRef.current = false;
        try {
          await uploadPendingFilesRef.current(purpose);
        } finally {
          setIsTyping(false);
        }
        return;
      }

      // 构造用户消息
      let attachmentPreview = "";
      let attachmentBase64: string | null = null;

      if (attachFile) {
        attachmentPreview = opts?.preview ?? await fileToPreview(attachFile);
        attachmentBase64 = await fileToBase64(attachFile);
      }

      const userMsg: DialogMessage = {
        id: genId(),
        role: "user",
        text: content || (attachFile ? "（发票附件）" : ""),
        timestamp: Date.now(),
        attachmentPreview: attachmentPreview || undefined,
      };

      setMessages((prev) => [...prev, userMsg]);
      setInputText("");
      setSelectedFile(null);
      setFilePreview("");
      setIsTyping(true);

      // 临时"思考"消息占位，后续流式替换为最终响应
      const thinkingId = genId();
      const thinkingMsg: DialogMessage = {
        id: thinkingId,
        role: "assistant",
        text: "正在思考…",
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, thinkingMsg]);

      try {
        await dialogApi.streamMessage(
          {
            user_id: userId,
            text: content,
            role,
            has_attachment: !!attachFile,
            attachment_base64: attachmentBase64,
            attachment_file_type: opts?.fileType ?? (attachFile ? deriveFileType(attachFile) : null),
            receipt_type: opts?.receiptType ?? null,
            user_description: opts?.purpose ?? null,
          },
          {
            onProgress: (text) => {
              // 更新思考气泡的进度文本
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === thinkingId ? { ...m, text } : m
                )
              );
            },
            onDone: (res) => {
              // 用最终响应替换思考气泡
              const followUp = res.data?.follow_up as
                | { state: string; batch_summary?: BatchInvoiceSummary[] }
                | undefined;
              const assistantMsg: DialogMessage = {
                id: genId(),
                role: "assistant",
                text: res.text || "(无响应)",
                timestamp: Date.now(),
                quickReplies: res.quick_replies || [],
                actionTaken: res.action_taken,
                error: res.error,
                invoiceId: res.data?.invoice_id as number | undefined,
                batchSummary: followUp?.batch_summary,
                followUpState: followUp?.state,
              };
              setMessages((prev) => [...prev.filter((m) => m.id !== thinkingId), assistantMsg]);
              // 执行了实际操作（上传/删除/修改发票）→ 通知其他组件刷新统计数据
              if (res.action_taken) {
                window.dispatchEvent(new CustomEvent("chat-invoices-changed"));
                // 员工端：可能标了出差日 → 刷新 travelDays 让日历组件同步显示
                if (role === "employee") {
                  portalApi
                    .listTravelDays()
                    .then(setTravelDays)
                    .catch(() => {});
                }
              }
            },
            onError: (message) => {
              const errorMsg: DialogMessage = {
                id: genId(),
                role: "system",
                text: message,
                timestamp: Date.now(),
                error: "request_failed",
              };
              setMessages((prev) => [...prev.filter((m) => m.id !== thinkingId), errorMsg]);
            },
          }
        );
      } catch (err) {
        // 兜底：streamMessage 内部应已通过 onError 处理，但若仍有异常则补救
        setMessages((prev) => {
          const filtered = prev.filter((m) => m.id !== thinkingId);
          if (filtered.length === prev.length - 1) return filtered; // 已通过 onError 处理
          const errorMsg: DialogMessage = {
            id: genId(),
            role: "system",
            text: err instanceof Error ? err.message : "请求失败，请稍后重试",
            timestamp: Date.now(),
            error: "request_failed",
          };
          return [...filtered, errorMsg];
        });
      } finally {
        setIsTyping(false);
        isTypingRef.current = false;  // 重置 ref 防重入标记
      }
    },
    [inputText, selectedFile, userId, role, pendingFiles]  // 移除 isTyping 依赖，改用 ref
  );

  /** 撤销上传 — 发送删除指令，并标记消息隐藏按钮 */
  const handleUndo = useCallback(
    (invoiceId: number) => {
      // 隐藏该消息的撤销按钮
      setMessages((prev) =>
        prev.map((m) =>
          m.invoiceId === invoiceId ? { ...m, undone: true } : m
        )
      );
      // 通过对话指令触发后端删除（从 batch 移除 + 硬删除记录+文件）
      handleSend("删除上一张");
    },
    [handleSend]
  );

  /** 文件选择 — 校验后暂存，等用户输入说明并点发送时一起上传 */
  const handleFileSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const fileList = e.target.files;
      if (!fileList || fileList.length === 0) return;

      // 多文件选择：转换为数组并逐个校验
      const files = Array.from(fileList);
      const validFiles: File[] = [];
      const errors: string[] = [];

      for (const file of files) {
        // 格式校验：MIME 或扩展名
        const ext = file.name.split(".").pop()?.toLowerCase() || "";
        const isValidMime = ACCEPTED_TYPES.includes(file.type);
        const isValidExt = ["png", "jpg", "jpeg", "gif", "bmp", "webp", "pdf", "ofd"].includes(ext);
        if (!isValidMime && !isValidExt) {
          errors.push(`${file.name}: 不支持的格式`);
          continue;
        }
        // 大小校验 20MB
        if (file.size > MAX_FILE_SIZE) {
          errors.push(`${file.name}: 超过 20MB`);
          continue;
        }
        validFiles.push(file);
      }

      // 错误提示（若有）
      if (errors.length > 0) {
        setMessages((prev) => [
          ...prev,
          {
            id: genId(),
            role: "system",
            text: `部分文件被排除：\n${errors.join("\n")}`,
            timestamp: Date.now(),
            error: "invalid_format",
          },
        ]);
      }

      if (validFiles.length === 0) {
        e.target.value = "";
        return;
      }

      // 暂存待发送文件，等用户输入说明后点发送按钮一起上传
      // 单文件场景兼容：同时设置 selectedFile + filePreview，保持原有预览行为
      setPendingFiles((prev) => [...prev, ...validFiles]);
      if (validFiles.length === 1) {
        setSelectedFile(validFiles[0]);
        setFilePreview(await fileToPreview(validFiles[0]));
      } else {
        // 多文件：清空单文件预览，用 pendingFiles 计数提示
        setSelectedFile(null);
        setFilePreview("");
      }

      // 清空 input 允许重复选同一文件
      e.target.value = "";
    },
    []
  );

  /** 批量上传暂存文件：所有张都带 purpose，文本消息已在 handleSend 中先添加 */
  const uploadPendingFiles = useCallback(
    async (purpose: string) => {
      if (pendingFiles.length === 0) return;
      const filesToUpload = pendingFiles;
      setPendingFiles([]);

      // 生成所有文件的预览（图片才有预览）
      const previews = await Promise.all(filesToUpload.map((f) => fileToPreview(f)));

      for (let i = 0; i < filesToUpload.length; i++) {
        const file = filesToUpload[i];
        const fileType = deriveFileType(file);
        const preview = previews[i] || "";
        // 第一张已在 handleSend 中显示了用户文本消息，这里 caption 留空避免重复
        const caption = "";
        // 每张都传 purpose，后端 _handle_upload_invoice 用它做批量描述解析
        // skipPending=true 跳过 handleSend 的批量分支，避免循环调用
        await handleSend(caption, file, {
          fileType,
          preview,
          purpose: purpose || undefined,
          skipPending: true,
        });
      }
    },
    [pendingFiles, handleSend]
  );

  // 注册到 ref，供 handleSend 通过 ref 调用，避免循环依赖
  useEffect(() => {
    uploadPendingFilesRef.current = uploadPendingFiles;
  }, [uploadPendingFiles]);

  /** 重置对话 */
  const handleReset = useCallback(async () => {
    try {
      await dialogApi.reset(userId, role);
    } catch {
      // 忽略重置 API 错误
    }
    sessionStorage.removeItem(storageKey);
    setMessages([createWelcomeMessage(role, displayName)]);
    setInputText("");
    setSelectedFile(null);
    setFilePreview("");
  }, [userId, storageKey, role, displayName]);

  /** 键盘快捷键：Enter 发送，Shift+Enter 换行 */
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // 最后一条 assistant 消息的快捷回复
  const lastQuickReplies = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant" && messages[i].quickReplies?.length) {
        return messages[i].quickReplies!;
      }
    }
    return [];
  }, [messages]);

  // 不在登录页显示
  const location = useLocation();
  if (location.pathname === "/portal/login") return null;

  return (
    <>
      {/* ===== 悬浮触发按钮（仅 floating 模式）===== */}
      {isFloating && (
        <AnimatePresence>
          {!isOpen && (
            <motion.button
              initial={{ scale: 0, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0, opacity: 0 }}
              transition={{ type: "spring", stiffness: 300, damping: 25 }}
              onClick={() => toggleOpen(true)}
              className="fixed bottom-6 right-6 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-primary-500 to-primary-700 text-white shadow-lg shadow-primary-600/30 transition-all hover:scale-105 hover:shadow-xl hover:shadow-primary-600/40"
              aria-label="打开智能问数（Cmd/Ctrl+K）"
              title="打开智能问数（Cmd/Ctrl+K）"
            >
              <ChatCircle size={26} weight="fill" />
              {/* 脉冲动画 */}
              <span className="absolute inset-0 -z-10 animate-ping rounded-full bg-primary-400 opacity-20" />
            </motion.button>
          )}
        </AnimatePresence>
      )}

      {/* ===== 聊天面板 ===== */}
      {/* floating: 条件渲染 + 缩放；fullscreen: flex-1 占满；panel: 右侧固定 420px */}
      {(() => {
        const panelContent = (
          <>
            {/* ---- 8 方向缩放手柄（仅 floating 模式）---- */}
            {isFloating && (
              <>
                {/* 四边 */}
                <div onPointerDown={(e) => startResize(e, "left")} className="absolute left-0 top-3 z-10 h-[calc(100%-3rem)] w-2 cursor-ew-resize rounded-r transition-colors hover:bg-primary-400/15 active:bg-primary-400/25" />
                <div onPointerDown={(e) => startResize(e, "right")} className="absolute right-0 top-3 z-10 h-[calc(100%-3rem)] w-2 cursor-ew-resize rounded-l transition-colors hover:bg-primary-400/15 active:bg-primary-400/25" />
                <div onPointerDown={(e) => startResize(e, "top")} className="absolute left-6 top-0 z-10 h-2 w-[calc(100%-4rem)] cursor-ns-resize rounded-b transition-colors hover:bg-primary-400/15 active:bg-primary-400/25" />
                <div onPointerDown={(e) => startResize(e, "bottom")} className="absolute left-6 bottom-0 z-10 h-2 w-[calc(100%-4rem)] cursor-ns-resize rounded-t transition-colors hover:bg-primary-400/15 active:bg-primary-400/25" />
                {/* 四角 */}
                <div onPointerDown={(e) => startResize(e, "top-left")} className="absolute left-0 top-0 z-20 h-4 w-4 cursor-nwse-resize rounded-tl-2xl transition-colors hover:bg-primary-400/20 active:bg-primary-400/30" />
                <div onPointerDown={(e) => startResize(e, "top-right")} className="absolute right-0 top-0 z-20 h-4 w-4 cursor-nesw-resize rounded-tr-2xl transition-colors hover:bg-primary-400/20 active:bg-primary-400/30" />
                <div onPointerDown={(e) => startResize(e, "bottom-left")} className="absolute left-0 bottom-0 z-20 h-4 w-4 cursor-nesw-resize rounded-bl-2xl transition-colors hover:bg-primary-400/20 active:bg-primary-400/30" />
                <div onPointerDown={(e) => startResize(e, "bottom-right")} className="absolute right-0 bottom-0 z-20 h-4 w-4 cursor-nwse-resize rounded-br-2xl transition-colors hover:bg-primary-400/20 active:bg-primary-400/30" />
              </>
            )}
            {/* ---- Header（流光边框包裹，floating 模式可拖拽）---- */}
            {/* 手机端铺满无 margin；桌面端 m-2 + 圆角 */}
            <div className={`flow-border ${isFloating ? "m-2" : "m-0 sm:m-2"}`}>
              <div
                onPointerDown={isFloating ? startDrag : undefined}
                className={`flex items-center justify-between bg-gradient-to-r from-primary-700 to-primary-900 px-3 py-2.5 text-white rounded-none sm:rounded-2xl sm:px-4 sm:py-3 ${isFloating ? "cursor-move select-none" : ""}`}
              >
                <div className="flex items-center gap-2.5">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/15">
                    <Robot size={18} weight="fill" />
                  </div>
                  <div className="flex flex-col">
                    <span className="flex items-center gap-1.5 font-display text-sm font-bold">
                      智能问数
                      <span className="pulse-dot" aria-label="在线" />
                    </span>
                    <span className="text-[10px] text-white/70">
                      {role === "employee" ? "员工模式" : role === "admin" ? "管理员模式" : "超级管理员模式"}
                      {" · "}
                      {displayName}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={handleReset}
                    className="flex h-7 w-7 items-center justify-center rounded-lg text-white/70 transition-colors hover:bg-white/15 hover:text-white"
                    title="重置对话"
                  >
                    <ArrowsClockwise size={16} />
                  </button>
                  {isFloating && (
                    <button
                      onClick={() => toggleOpen(false)}
                      className="flex h-7 w-7 items-center justify-center rounded-lg text-white/70 transition-colors hover:bg-white/15 hover:text-white"
                      title="收起（Cmd/Ctrl+K 恢复）"
                    >
                      <X size={18} />
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* ---- 消息列表（独立滚动，min-h-0 让 flex-1 可缩小）---- */}
            <div
              ref={messagesContainerRef}
              className="min-h-0 flex-1 space-y-2.5 overflow-y-auto bg-muted px-2.5 py-3 sm:space-y-3 sm:px-4 sm:py-4"
            >
              {messages.map((msg) => (
                <MessageBubble key={msg.id} msg={msg} onUndo={handleUndo} />
              ))}

              {/* 打字指示器 */}
              {isTyping && (
                <div className="flex gap-2">
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted">
                    <Robot size={16} weight="fill" className="text-muted-foreground" />
                  </div>
                  <div className="rounded-2xl rounded-tl-md bg-background shadow-sm ring-1 ring-border">
                    <TypingDots />
                  </div>
                </div>
              )}

              {/* 快捷回复 */}
              {!isTyping && lastQuickReplies.length > 0 && (
                <QuickReplyChips
                  replies={lastQuickReplies}
                  onSelect={(text) => handleSend(text)}
                />
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* ---- 文件预览 ---- */}
            {/* 多文件待发送：显示数量提示，输入说明后点发送一起上传 */}
            {pendingFiles.length > 1 && (
              <div className="relative z-30 flex items-center gap-2 border-t border-border bg-primary-50 px-4 py-2">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-100 text-primary-700">
                  <Paperclip size={18} weight="bold" />
                </div>
                <span className="flex-1 text-xs text-primary-800">
                  已选 <b>{pendingFiles.length}</b> 个附件待发送，输入说明后点发送一起上传（如"第一张是打车费，第二张是餐饮费"）
                </span>
                <button
                  onClick={() => { setPendingFiles([]); setSelectedFile(null); setFilePreview(""); }}
                  className="text-xs text-muted-foreground hover:text-red-500"
                >
                  取消
                </button>
              </div>
            )}
            {/* 单文件预览 */}
            {filePreview && pendingFiles.length <= 1 && (
              <div className="relative z-30 flex items-center gap-2 border-t border-border bg-muted px-4 py-2">
                <img src={filePreview} alt="待发送" className="h-12 w-12 rounded-lg border border-border object-cover" />
                <span className="flex-1 text-xs text-muted-foreground">附件已就绪，输入文字后发送，或直接发送</span>
                <button
                  onClick={() => { setSelectedFile(null); setFilePreview(""); setPendingFiles([]); }}
                  className="text-xs text-muted-foreground hover:text-red-500"
                >
                  移除
                </button>
              </div>
            )}

            {/* ---- 输入区域（scan-line 包裹，聚焦时显示扫描光条）---- */}
            <div className="scan-line relative z-30 border-t border-border bg-background px-2.5 py-2 sm:px-3 sm:py-3">
              <div className="flex items-end gap-2">
                {/* 文件上传 */}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*,.pdf,.ofd"
                  onChange={handleFileSelect}
                  multiple
                  className="sr-only"
                />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isTyping}
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
                  title="上传发票"
                >
                  <Paperclip size={20} className="pointer-events-none" />
                </button>

                {/* 标记出差日（仅员工端） */}
                {role === "employee" && (
                  <>
                    <button
                      onClick={() => setTravelPickerOpen(true)}
                      disabled={isTyping}
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-primary-50 hover:text-primary-700 disabled:opacity-40"
                      title="标记出差日"
                    >
                      <Calendar size={20} className="pointer-events-none" />
                    </button>
                    <TravelDayPicker
                      open={travelPickerOpen}
                      onClose={() => setTravelPickerOpen(false)}
                      cycleStart={currentCycleStart}
                      cycleEnd={currentCycleEnd}
                      existingTravelDays={travelDays}
                      onSubmit={handleTravelDaysSubmit}
                    />
                  </>
                )}

                {/* 文本输入 */}
                <textarea
                  ref={textareaRef}
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  onKeyDown={handleKeyDown}
                  disabled={isTyping}
                  rows={1}
                  placeholder={
                    isTyping
                      ? "助手正在回复…"
                      : pendingFiles.length > 1
                        ? `已选 ${pendingFiles.length} 个附件，输入说明后发送（如"第一张是打车费，第二张是餐费"）`
                        : "输入消息，Enter 发送，Shift+Enter 换行"
                  }
                  className="max-h-[120px] flex-1 resize-none rounded-xl border border-border bg-muted px-3 py-2 text-[13px] leading-relaxed text-foreground placeholder:text-muted-foreground focus:border-primary-400 focus:bg-background focus:outline-none focus:ring-2 focus:ring-primary-100 disabled:opacity-50 sm:px-3.5 sm:py-2.5 sm:text-sm"
                />

                {/* 发送按钮 */}
                <button
                  onClick={() => handleSend()}
                  disabled={isTyping || (!inputText.trim() && !selectedFile && pendingFiles.length === 0)}
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary-600 text-white transition-all hover:bg-primary-700 active:scale-90 disabled:cursor-not-allowed disabled:opacity-40"
                  title="发送"
                >
                  <PaperPlaneTilt size={18} weight="fill" className="pointer-events-none" />
                </button>
              </div>
            </div>
          </>
        );

        // 按模式渲染外层容器
        if (mode === "fullscreen") {
          return (
            // 手机端铺满无圆角无边框；桌面端卡片样式
            <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background rounded-none ring-0 shadow-none sm:rounded-2xl sm:shadow-card sm:ring-1 sm:ring-border">
              {panelContent}
            </div>
          );
        }
        if (mode === "panel") {
          return (
            <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background ring-1 ring-border">
              {panelContent}
            </div>
          );
        }
        // floating 模式：AnimatePresence + motion.div，位置/大小来自 geo
        return (
          <AnimatePresence>
            {isOpen && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                transition={{ type: "spring", stiffness: 300, damping: 28 }}
                style={{
                  left: geo.x,
                  top: geo.y,
                  width: geo.width,
                  height: geo.height,
                  maxWidth: "calc(100vw - 3rem)",
                  maxHeight: "calc(100dvh - 3rem)",
                  userSelect: isInteracting ? "none" : undefined,
                  // 拖拽/缩放时视觉反馈：增强阴影 + 轻微透明
                  opacity: isInteracting ? 0.92 : 1,
                }}
                className={`fixed z-50 flex flex-col overflow-hidden rounded-2xl bg-background ring-1 ring-border transition-shadow ${
                  isInteracting ? "shadow-2xl shadow-primary-900/30" : "shadow-2xl shadow-black/20"
                }`}
              >
                {panelContent}
              </motion.div>
            )}
          </AnimatePresence>
        );
      })()}

    </>
  );
}
