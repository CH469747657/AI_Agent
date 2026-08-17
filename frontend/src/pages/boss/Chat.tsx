import { useState, useRef, useEffect, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { bossApi, BossDialogResponse } from "../../api/client";

interface Message {
  role: "user" | "ai";
  text: string;
  /** AI 消息中解析出的发票号 / 报销单号 chip */
  chips?: { type: "invoice" | "reimbursement"; id: string; label: string }[];
}

const WELCOME =
  "您好，请直接问我公司报销情况，例如：\n- 本月各部门发票总额？\n- 陈辉有几张待审报销单？\n- 公司本年总报销金额？";

/** 把 AI 返回文本里的发票号/报销单号提取为可点击 chip */
function extractChips(text: string): Message["chips"] {
  const chips: NonNullable<Message["chips"]> = [];
  // 发票号：8-20 位数字（发票号常见长度），用前后非数字边界
  const invoiceRe = /(?<!\d)(\d{8,20})(?!\d)/g;
  let m: RegExpExecArray | null;
  while ((m = invoiceRe.exec(text)) !== null) {
    chips.push({
      type: "invoice",
      id: m[1],
      label: m[1],
    });
  }
  // 报销单：#123 或 报销单123 / RB-123
  const reimbRe = /(?:报销单|#|RB-)(\d{1,8})/g;
  while ((m = reimbRe.exec(text)) !== null) {
    chips.push({
      type: "reimbursement",
      id: m[1],
      label: `#${m[1]}`,
    });
  }
  // 去重（同一 ID 只保留一个）
  const seen = new Set<string>();
  return chips.filter((c) => {
    const key = `${c.type}:${c.id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function BossChat() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<Message[]>([
    { role: "ai", text: WELCOME },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, loading]);

  const send = async (e?: FormEvent) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text }]);
    setLoading(true);
    try {
      const res: BossDialogResponse = await bossApi.ask(text);
      const chips = extractChips(res.text || "");
      setMessages((prev) => [
        ...prev,
        { role: "ai", text: res.text || "(AI 未返回内容)", chips },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: "ai",
          text:
            err instanceof Error
              ? `AI 服务暂时不可用：${err.message}`
              : "AI 服务暂时不可用，请稍后重试",
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const reset = () => {
    setMessages([{ role: "ai", text: WELCOME }]);
  };

  const onChipClick = (chip: NonNullable<Message["chips"]>[number]) => {
    if (chip.type === "invoice") {
      // invoice id 通常是数字，但 chip 可能是发票号字符串——这里尝试 navigate
      navigate(`/boss/invoices/${chip.id}`);
    } else {
      navigate(`/boss/reimbursements/${chip.id}`);
    }
  };

  return (
    <div className="boss-chat">
      <div className="boss-chat__header">
        <span>老板智能问数</span>
        <button className="boss-chat__refresh" onClick={reset} title="重置对话">
          ↻
        </button>
      </div>
      <div className="boss-chat__messages" ref={scrollRef}>
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`boss-msg boss-msg--${msg.role === "user" ? "user" : "ai"}`}
          >
            {msg.text}
            {msg.chips && msg.chips.length > 0 && (
              <div style={{ marginTop: 8 }}>
                {msg.chips.map((c, j) => (
                  <span
                    key={j}
                    className="boss-chip"
                    onClick={() => onChipClick(c)}
                  >
                    {c.label} →
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="boss-msg boss-msg--ai">正在查询数据…</div>
        )}
      </div>
      <form className="boss-chat__input-bar" onSubmit={send}>
        <input
          className="boss-chat__input"
          type="text"
          placeholder="问公司报销情况…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={loading}
        />
        <button
          className="boss-chat__send"
          type="submit"
          disabled={loading || !input.trim()}
        >
          ➤
        </button>
      </form>
    </div>
  );
}
