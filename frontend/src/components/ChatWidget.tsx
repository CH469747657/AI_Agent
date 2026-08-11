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
  FilePdf,
  File,
  WarningCircle,
  ArrowCounterClockwise,
  Wallet,
} from "@phosphor-icons/react";
import { dialogApi, portalApi } from "../api/client";
import type { DialogMessage, DialogRole } from "../types";
import { receiptTypes, NONSTANDARD_TYPES, ACCEPTED_TYPES, MAX_FILE_SIZE } from "../components/upload/index";

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

/** 文件图标（弹窗内预览） */
function FilePreviewIcon({ file }: { file: File }) {
  const ext = file.name.split(".").pop()?.toLowerCase() || "";
  if (ext === "pdf") {
    return (
      <div className="flex h-20 w-20 items-center justify-center rounded-xl bg-red-50">
        <FilePdf size={36} weight="fill" className="text-red-500" />
      </div>
    );
  }
  if (ext === "ofd") {
    return (
      <div className="flex h-20 w-20 items-center justify-center rounded-xl bg-orange-50">
        <File size={36} weight="fill" className="text-orange-500" />
      </div>
    );
  }
  // 图片
  return (
    <img
      src={URL.createObjectURL(file)}
      alt="预览"
      className="h-20 w-20 rounded-xl border border-slate-200 object-cover"
      onLoad={(e) => URL.revokeObjectURL((e.target as HTMLImageElement).src)}
    />
  );
}

/** 从路由推导角色与用户ID */
function useRoleAndUserId(): { role: DialogRole; userId: string; displayName: string } {
  const location = useLocation();
  const isPortal = location.pathname.startsWith("/portal");
  const isLogin = location.pathname === "/portal/login";

  return useMemo(() => {
    if (isPortal && !isLogin) {
      const emp = portalApi.getStoredEmployee();
      return {
        role: "employee" as DialogRole,
        userId: emp?.employee_no || emp?.id?.toString() || "portal_user",
        displayName: emp?.name || "员工",
      };
    }
    // 管理后台默认 admin
    return {
      role: "admin" as DialogRole,
      userId: "admin",
      displayName: "管理员",
    };
  }, [isPortal, isLogin]);
}

// ============================================================
// 可缩放 Hook
// ============================================================

/** 缩放尺寸限制 */
const MIN_WIDTH = 320;
const MIN_HEIGHT = 400;
const MAX_WIDTH = 720;
const MAX_HEIGHT = 900;

type ResizeDirection = "left" | "top" | "top-left";

/** 可缩放窗口 hook — 支持从左、上、左上三个方向缩放 */
function useResizable(defaultWidth = 400, defaultHeight = 600) {
  const [size, setSize] = useState({ width: defaultWidth, height: defaultHeight });
  const resizingRef = useRef<{
    direction: ResizeDirection;
    startX: number;
    startY: number;
    startWidth: number;
    startHeight: number;
  } | null>(null);

  const handleResizeStart = useCallback(
    (e: React.PointerEvent, direction: ResizeDirection) => {
      e.preventDefault();
      e.stopPropagation();
      const target = e.currentTarget;
      (target as HTMLElement).setPointerCapture(e.pointerId);

      resizingRef.current = {
        direction,
        startX: e.clientX,
        startY: e.clientY,
        startWidth: size.width,
        startHeight: size.height,
      };
    },
    [size.width, size.height]
  );

  useEffect(() => {
    const handleMove = (e: PointerEvent) => {
      const r = resizingRef.current;
      if (!r) return;

      const dx = e.clientX - r.startX;
      const dy = e.clientY - r.startY;

      let newWidth = r.startWidth;
      let newHeight = r.startHeight;

      if (r.direction === "left" || r.direction === "top-left") {
        // 向左拖 → dx 负 → 宽度增大
        newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, r.startWidth - dx));
      }
      if (r.direction === "top" || r.direction === "top-left") {
        // 向上拖 → dy 负 → 高度增大
        newHeight = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, r.startHeight - dy));
      }

      setSize({ width: newWidth, height: newHeight });
    };

    const handleUp = () => {
      resizingRef.current = null;
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
  }, []);

  const isResizing = resizingRef.current !== null;

  return { size, isResizing, handleResizeStart };
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
          className="h-2 w-2 rounded-full bg-slate-400"
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
              : "bg-slate-100 text-slate-500"
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
          isUser ? "bg-brand-100" : "bg-slate-100"
        }`}
      >
        {isUser ? (
          <UserCircle size={16} weight="fill" className="text-brand-600" />
        ) : (
          <Robot size={16} weight="fill" className="text-slate-500" />
        )}
      </div>

      {/* 消息内容 */}
      <div className={`flex max-w-[78%] flex-col ${isUser ? "items-end" : "items-start"}`}>
        {/* 附件预览 */}
        {msg.attachmentPreview && (
          <img
            src={msg.attachmentPreview}
            alt="附件"
            className="mb-1 max-h-32 rounded-lg border border-slate-200 object-cover"
          />
        )}
        {/* 文本气泡 */}
        <div
          className={`whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
            isUser
              ? "rounded-tr-md bg-brand-600 text-white"
              : isError
                ? "rounded-tl-md bg-red-50 text-red-700"
                : "rounded-tl-md bg-white text-slate-800 shadow-sm ring-1 ring-slate-200/60"
          }`}
        >
          {msg.text}
        </div>
        {/* 撤销上传按钮（仅上传成功消息显示） */}
        {!isUser && !msg.undone && msg.invoiceId && onUndo && (
          <motion.button
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.2 }}
            onClick={() => onUndo(msg.invoiceId!)}
            className="mt-1 inline-flex items-center gap-1 rounded-lg bg-white px-2.5 py-1 text-xs font-medium text-slate-500 ring-1 ring-slate-200 transition-colors hover:bg-red-50 hover:text-red-600 hover:ring-red-200"
          >
            <ArrowCounterClockwise size={12} weight="bold" />
            撤销上传
          </motion.button>
        )}
        {/* 操作标记 + 时间 */}
        <div className={`mt-0.5 flex items-center gap-1.5 text-[10px] text-slate-400`}>
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
          className="rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700 transition-colors hover:bg-brand-100 active:scale-95"
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
        : `老板好！我可以帮您查看公司报销数据洞察。输入「帮助」查看可用功能。`;
  return {
    id: "welcome",
    role: "assistant",
    text: greeting,
    timestamp: Date.now(),
    quickReplies:
      role === "employee"
        ? ["上传发票", "查询报销", "我花了多少", "帮助"]
        : role === "admin"
          ? ["待审批", "公司花了多少", "有没有异常", "帮助"]
          : ["本月报销总额", "哪个部门花得多", "趋势", "帮助"],
  };
}

export function ChatWidget() {
  const { role, userId, displayName } = useRoleAndUserId();
  const { size: panelSize, isResizing, handleResizeStart } = useResizable(400, 600);
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<DialogMessage[]>([]);
  const [inputText, setInputText] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [filePreview, setFilePreview] = useState<string>("");

  // 上传弹窗状态
  const [uploadModal, setUploadModal] = useState<{
    file: File;
    preview: string;
  } | null>(null);
  const [modalReceiptType, setModalReceiptType] = useState(receiptTypes[0]);
  const [modalPurpose, setModalPurpose] = useState("");

  // 无凭证报销弹窗状态
  const [noReceiptModal, setNoReceiptModal] = useState(false);
  const [noReceiptAmount, setNoReceiptAmount] = useState("");
  const [noReceiptReason, setNoReceiptReason] = useState("");

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 当前角色/用户变化时重置消息
  // 按 userId 做消息持久化 key
  const storageKey = `chat_messages_${userId}`;

  // 初始化：从 sessionStorage 恢复消息
  useEffect(() => {
    if (!isOpen) return;
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
  }, [isOpen, userId]);

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

  /** 发送消息 */
  const handleSend = useCallback(
    async (
      text?: string,
      file?: File | null,
      opts?: { receiptType?: string; purpose?: string; fileType?: string }
    ) => {
      const content = (text ?? inputText).trim();
      const attachFile = file ?? selectedFile;

      if (!content && !attachFile) return;
      if (isTyping) return;

      // 构造用户消息
      let attachmentPreview = "";
      let attachmentBase64: string | null = null;

      if (attachFile) {
        attachmentPreview = await fileToPreview(attachFile);
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

      try {
        const res = await dialogApi.sendMessage({
          user_id: userId,
          text: content,
          role,
          has_attachment: !!attachFile,
          attachment_base64: attachmentBase64,
          attachment_file_type: opts?.fileType ?? (attachFile ? deriveFileType(attachFile) : null),
          receipt_type: opts?.receiptType ?? null,
          user_description: opts?.purpose ?? null,
        });

        const assistantMsg: DialogMessage = {
          id: genId(),
          role: "assistant",
          text: res.text || "(无响应)",
          timestamp: Date.now(),
          quickReplies: res.quick_replies || [],
          actionTaken: res.action_taken,
          error: res.error,
          invoiceId: res.data?.invoice_id as number | undefined,
        };

        setMessages((prev) => [...prev, assistantMsg]);
      } catch (err) {
        const errorMsg: DialogMessage = {
          id: genId(),
          role: "system",
          text: err instanceof Error ? err.message : "请求失败，请稍后重试",
          timestamp: Date.now(),
          error: "request_failed",
        };
        setMessages((prev) => [...prev, errorMsg]);
      } finally {
        setIsTyping(false);
      }
    },
    [inputText, selectedFile, isTyping, userId, role]
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

  /** 文件选择 — 校验后弹出发票类型/用途弹窗 */
  const handleFileSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;

      // 格式校验：MIME 或扩展名
      const ext = file.name.split(".").pop()?.toLowerCase() || "";
      const isValidMime = ACCEPTED_TYPES.includes(file.type);
      const isValidExt = ["png", "jpg", "jpeg", "gif", "bmp", "webp", "pdf", "ofd"].includes(ext);
      if (!isValidMime && !isValidExt) {
        setMessages((prev) => [
          ...prev,
          {
            id: genId(),
            role: "system",
            text: "不支持的文件格式，请上传 PNG / JPG / PDF / OFD 文件",
            timestamp: Date.now(),
            error: "invalid_format",
          },
        ]);
        e.target.value = "";
        return;
      }

      // 大小校验 20MB
      if (file.size > MAX_FILE_SIZE) {
        setMessages((prev) => [
          ...prev,
          {
            id: genId(),
            role: "system",
            text: "文件过大，请选择 20MB 以内的文件",
            timestamp: Date.now(),
            error: "file_too_large",
          },
        ]);
        e.target.value = "";
        return;
      }

      // 弹出发票类型/用途选择弹窗
      const preview = await fileToPreview(file);
      setUploadModal({ file, preview });
      setModalReceiptType(receiptTypes[0]);
      setModalPurpose("");

      // 清空 input 允许重复选同一文件
      e.target.value = "";
    },
    []
  );

  /** 弹窗确认上传 */
  const handleModalConfirm = useCallback(() => {
    if (!uploadModal) return;
    const file = uploadModal.file;
    const fileType = deriveFileType(file);
    handleSend("", file, {
      receiptType: modalReceiptType,
      purpose: modalPurpose || undefined,
      fileType,
    });
    setUploadModal(null);
  }, [uploadModal, modalReceiptType, modalPurpose, handleSend]);

  /** 无凭证报销确认 */
  const handleNoReceiptConfirm = useCallback(() => {
    const amount = noReceiptAmount.trim();
    const reason = noReceiptReason.trim();
    if (!amount || !reason) return;

    // 构造用户消息（显示在对话中）
    const userMsg: DialogMessage = {
      id: genId(),
      role: "user",
      text: `无凭证报销 · 金额：¥${amount} · 原因：${reason}`,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsTyping(true);

    // 直接调用对话 API，走 emp_no_receipt 快捷通道
    dialogApi
      .sendMessage({
        user_id: userId,
        text: "无凭证报销",
        role,
        no_receipt_amount: amount,
        user_description: reason,
      })
      .then((res) => {
        const assistantMsg: DialogMessage = {
          id: genId(),
          role: "assistant",
          text: res.text || "(无响应)",
          timestamp: Date.now(),
          quickReplies: res.quick_replies || [],
          actionTaken: res.action_taken,
          error: res.error,
          invoiceId: res.data?.invoice_id as number | undefined,
        };
        setMessages((prev) => [...prev, assistantMsg]);
      })
      .catch((err) => {
        const errorMsg: DialogMessage = {
          id: genId(),
          role: "system",
          text: err instanceof Error ? err.message : "请求失败，请稍后重试",
          timestamp: Date.now(),
          error: "request_failed",
        };
        setMessages((prev) => [...prev, errorMsg]);
      })
      .finally(() => {
        setIsTyping(false);
        setNoReceiptModal(false);
        setNoReceiptAmount("");
        setNoReceiptReason("");
      });
  }, [noReceiptAmount, noReceiptReason, userId, role]);

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
      {/* ===== 悬浮触发按钮 ===== */}
      <AnimatePresence>
        {!isOpen && (
          <motion.button
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
            onClick={() => setIsOpen(true)}
            className="fixed bottom-6 right-6 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-lg shadow-brand-600/30 transition-all hover:scale-105 hover:shadow-xl hover:shadow-brand-600/40"
            aria-label="打开对话助手"
          >
            <ChatCircle size={26} weight="fill" />
            {/* 脉冲动画 */}
            <span className="absolute inset-0 -z-10 animate-ping rounded-full bg-brand-400 opacity-20" />
          </motion.button>
        )}
      </AnimatePresence>

      {/* ===== 聊天面板 ===== */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.95 }}
            transition={{ type: "spring", stiffness: 300, damping: 28 }}
            style={{
              width: panelSize.width,
              height: panelSize.height,
              maxHeight: "calc(100dvh - 3rem)",
              maxWidth: "calc(100vw - 3rem)",
              userSelect: isResizing ? "none" : undefined,
            }}
            className="fixed bottom-6 right-6 z-50 flex flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200/60"
          >
            {/* ---- Resize 手柄 ---- */}
            {/* 左边缘 */}
            <div
              onPointerDown={(e) => handleResizeStart(e, "left")}
              className="absolute left-0 top-3 z-10 h-[calc(100%-3rem)] w-2 cursor-ew-resize rounded-r transition-colors hover:bg-brand-400/15 active:bg-brand-400/25"
            />
            {/* 上边缘 — 仅覆盖 header 左侧非按钮区域 */}
            <div
              onPointerDown={(e) => handleResizeStart(e, "top")}
              className="absolute left-6 top-0 z-10 h-2 w-[calc(100%-4rem)] cursor-ns-resize rounded-b transition-colors hover:bg-brand-400/15 active:bg-brand-400/25"
            />
            {/* 左上角 */}
            <div
              onPointerDown={(e) => handleResizeStart(e, "top-left")}
              className="absolute left-0 top-0 z-20 h-4 w-4 cursor-nwse-resize rounded-tl-2xl transition-colors hover:bg-brand-400/20 active:bg-brand-400/30"
            />
            {/* ---- Header ---- */}
            <div className="flex items-center justify-between border-b border-slate-200/60 bg-gradient-to-r from-brand-600 to-brand-700 px-4 py-3 text-white">
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/20">
                  <Robot size={18} weight="fill" />
                </div>
                <div className="flex flex-col">
                  <span className="font-display text-sm font-bold">AI 报销助手</span>
                  <span className="text-[10px] text-white/70">
                    {role === "employee" ? "员工模式" : role === "admin" ? "管理员模式" : "老板模式"}
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
                <button
                  onClick={() => setIsOpen(false)}
                  className="flex h-7 w-7 items-center justify-center rounded-lg text-white/70 transition-colors hover:bg-white/15 hover:text-white"
                  title="关闭"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* ---- 消息列表 ---- */}
            <div
              ref={messagesContainerRef}
              className="flex-1 space-y-3 overflow-y-auto bg-slate-50 px-4 py-4"
            >
              {messages.map((msg) => (
                <MessageBubble key={msg.id} msg={msg} onUndo={handleUndo} />
              ))}

              {/* 打字指示器 */}
              {isTyping && (
                <div className="flex gap-2">
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-100">
                    <Robot size={16} weight="fill" className="text-slate-500" />
                  </div>
                  <div className="rounded-2xl rounded-tl-md bg-white shadow-sm ring-1 ring-slate-200/60">
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
            {filePreview && (
              <div className="relative z-30 flex items-center gap-2 border-t border-slate-200/60 bg-slate-50 px-4 py-2">
                <img src={filePreview} alt="待发送" className="h-12 w-12 rounded-lg border border-slate-200 object-cover" />
                <span className="flex-1 text-xs text-slate-500">附件已就绪，输入文字后发送，或直接发送</span>
                <button
                  onClick={() => { setSelectedFile(null); setFilePreview(""); }}
                  className="text-xs text-slate-400 hover:text-red-500"
                >
                  移除
                </button>
              </div>
            )}

            {/* ---- 输入区域 ---- */}
            <div className="relative z-30 border-t border-slate-200/60 bg-white px-3 py-3">
              <div className="flex items-end gap-2">
                {/* 文件上传 */}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*,.pdf,.ofd"
                  onChange={handleFileSelect}
                  className="sr-only"
                />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isTyping}
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:opacity-40"
                  title="上传发票"
                >
                  <Paperclip size={20} className="pointer-events-none" />
                </button>

                {/* 无凭证报销 */}
                <button
                  onClick={() => setNoReceiptModal(true)}
                  disabled={isTyping}
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-slate-400 transition-colors hover:bg-amber-50 hover:text-amber-600 disabled:opacity-40"
                  title="无凭证报销"
                >
                  <Wallet size={20} className="pointer-events-none" />
                </button>

                {/* 文本输入 */}
                <textarea
                  ref={textareaRef}
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  onKeyDown={handleKeyDown}
                  disabled={isTyping}
                  rows={1}
                  placeholder={isTyping ? "助手正在回复…" : "输入消息，Enter 发送，Shift+Enter 换行"}
                  className="max-h-[120px] flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 focus:border-brand-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-100 disabled:opacity-50"
                />

                {/* 发送按钮 */}
                <button
                  onClick={() => handleSend()}
                  disabled={isTyping || (!inputText.trim() && !selectedFile)}
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-600 text-white transition-all hover:bg-brand-700 active:scale-90 disabled:cursor-not-allowed disabled:opacity-40"
                  title="发送"
                >
                  <PaperPlaneTilt size={18} weight="fill" className="pointer-events-none" />
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ===== 上传发票弹窗 ===== */}
      <AnimatePresence>
        {uploadModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40"
            onClick={(e) => {
              if (e.target === e.currentTarget) setUploadModal(null);
            }}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              transition={{ type: "spring", stiffness: 300, damping: 28 }}
              className="w-[360px] rounded-2xl bg-white p-5 shadow-2xl ring-1 ring-slate-200/60"
              onClick={(e) => e.stopPropagation()}
            >
              {/* 标题 */}
              <div className="mb-4 flex items-center gap-2">
                <Paperclip size={18} className="text-brand-600" />
                <h3 className="text-base font-bold text-slate-800">上传发票</h3>
              </div>

              {/* 文件预览 */}
              <div className="mb-4 flex items-center gap-3 rounded-xl bg-slate-50 p-3">
                <FilePreviewIcon file={uploadModal.file} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-700">
                    {uploadModal.file.name}
                  </p>
                  <p className="text-xs text-slate-400">
                    {(uploadModal.file.size / 1024 / 1024).toFixed(1)} MB
                  </p>
                </div>
              </div>

              {/* 发票类型选择 */}
              <div className="mb-4">
                <label className="mb-2 block text-sm font-medium text-slate-700">
                  发票类型
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {receiptTypes.map((type) => {
                    const isSelected = modalReceiptType === type;
                    const isNonStandard = NONSTANDARD_TYPES.has(type);
                    return (
                      <button
                        key={type}
                        onClick={() => setModalReceiptType(type)}
                        className={`rounded-lg border px-3 py-2 text-left text-xs font-medium transition-all ${
                          isSelected
                            ? isNonStandard
                              ? "border-amber-400 bg-amber-50 text-amber-700 ring-1 ring-amber-200"
                              : "border-brand-400 bg-brand-50 text-brand-700 ring-1 ring-brand-200"
                            : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50"
                        }`}
                      >
                        {type}
                      </button>
                    );
                  })}
                </div>
                {/* 非标准类型提示 */}
                {NONSTANDARD_TYPES.has(modalReceiptType) && (
                  <div className="mt-2 flex items-start gap-1.5 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
                    <WarningCircle size={14} className="mt-0.5 shrink-0" weight="fill" />
                    <span>非标准发票类型，将使用 AI 视觉模型识别，准确率可能低于标准发票</span>
                  </div>
                )}
              </div>

              {/* 费用用途 */}
              <div className="mb-5">
                <label className="mb-2 block text-sm font-medium text-slate-700">
                  费用用途 <span className="font-normal text-slate-400">（可选）</span>
                </label>
                <textarea
                  value={modalPurpose}
                  onChange={(e) => setModalPurpose(e.target.value)}
                  rows={2}
                  placeholder="例如：出差打车、办公用品采购"
                  className="w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:border-brand-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-100"
                />
              </div>

              {/* 操作按钮 */}
              <div className="flex gap-3">
                <button
                  onClick={() => setUploadModal(null)}
                  className="flex-1 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 active:scale-[0.98]"
                >
                  取消
                </button>
                <button
                  onClick={handleModalConfirm}
                  className="flex-1 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white transition-all hover:bg-brand-700 active:scale-[0.98]"
                >
                  确认上传
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ===== 无凭证报销弹窗 ===== */}
      <AnimatePresence>
        {noReceiptModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40"
            onClick={(e) => {
              if (e.target === e.currentTarget) setNoReceiptModal(false);
            }}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              transition={{ type: "spring", stiffness: 300, damping: 28 }}
              className="w-[360px] rounded-2xl bg-white p-5 shadow-2xl ring-1 ring-slate-200/60"
              onClick={(e) => e.stopPropagation()}
            >
              {/* 标题 */}
              <div className="mb-4 flex items-center gap-2">
                <Wallet size={18} className="text-amber-500" />
                <h3 className="text-base font-bold text-slate-800">无凭证报销</h3>
              </div>

              {/* 提示 */}
              <div className="mb-4 flex items-start gap-1.5 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
                <WarningCircle size={14} className="mt-0.5 shrink-0" weight="fill" />
                <span>无凭证报销需填写金额和费用原因，提交后由人工审核</span>
              </div>

              {/* 金额输入 */}
              <div className="mb-4">
                <label className="mb-2 block text-sm font-medium text-slate-700">
                  金额 <span className="font-normal text-red-400">*必填</span>
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-slate-400">¥</span>
                  <input
                    type="text"
                    value={noReceiptAmount}
                    onChange={(e) => setNoReceiptAmount(e.target.value)}
                    placeholder="例如：120"
                    className="w-full rounded-lg border border-slate-200 bg-slate-50 py-2 pl-7 pr-3 text-sm text-slate-800 placeholder:text-slate-400 focus:border-amber-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-amber-100"
                  />
                </div>
              </div>

              {/* 费用原因 */}
              <div className="mb-5">
                <label className="mb-2 block text-sm font-medium text-slate-700">
                  费用原因 <span className="font-normal text-red-400">*必填</span>
                </label>
                <textarea
                  value={noReceiptReason}
                  onChange={(e) => setNoReceiptReason(e.target.value)}
                  rows={3}
                  placeholder="请详细描述产生费用的原因，例如：客户拜访打车费"
                  className="w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:border-amber-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-amber-100"
                />
              </div>

              {/* 操作按钮 */}
              <div className="flex gap-3">
                <button
                  onClick={() => setNoReceiptModal(false)}
                  className="flex-1 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 active:scale-[0.98]"
                >
                  取消
                </button>
                <button
                  onClick={handleNoReceiptConfirm}
                  disabled={!noReceiptAmount.trim() || !noReceiptReason.trim()}
                  className="flex-1 rounded-lg bg-amber-500 px-4 py-2.5 text-sm font-medium text-white transition-all hover:bg-amber-600 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  确认提交
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
