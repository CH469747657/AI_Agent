import { useState, useMemo, useEffect } from "react";
import { X, Calendar, Check } from "@phosphor-icons/react";
import type { TravelDay } from "../types";

interface TravelDayPickerProps {
  open: boolean;
  onClose: () => void;
  cycleStart: string | null;
  cycleEnd: string | null;
  existingTravelDays: TravelDay[];
  onSubmit: (
    selected: { date: string; note: string | null }[],
    removed: string[]
  ) => Promise<void>;
}

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];

function iso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function parseISO(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function TravelDayPicker({
  open,
  onClose,
  cycleStart,
  cycleEnd,
  existingTravelDays,
  onSubmit,
}: TravelDayPickerProps) {
  const [viewYear, setViewYear] = useState<number>(new Date().getFullYear());
  const [viewMonth, setViewMonth] = useState<number>(new Date().getMonth());
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const existingDates = useMemo(
    () => new Set(existingTravelDays.map((td) => td.travel_date)),
    [existingTravelDays]
  );

  useEffect(() => {
    if (open && cycleStart) {
      const d = parseISO(cycleStart);
      setViewYear(d.getFullYear());
      setViewMonth(d.getMonth());
      setSelected(new Set());
      setRemoved(new Set());
      setNote("");
      setError(null);
    }
  }, [open, cycleStart]);

  if (!open) return null;

  const cycleStartD = cycleStart ? parseISO(cycleStart) : null;
  const cycleEndD = cycleEnd ? parseISO(cycleEnd) : null;

  const isClickable = (d: Date): boolean => {
    if (!cycleStartD || !cycleEndD) return false;
    return d >= cycleStartD && d <= cycleEndD;
  };

  const isExisting = (d: Date): boolean => existingDates.has(iso(d));
  const isSelected = (d: Date): boolean => selected.has(iso(d));
  const isRemoved = (d: Date): boolean => removed.has(iso(d));

  const toggleDate = (d: Date) => {
    if (!isClickable(d)) return;
    const key = iso(d);
    if (isExisting(d)) {
      setRemoved((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        return next;
      });
    } else {
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        return next;
      });
    }
  };

  const firstDay = new Date(viewYear, viewMonth, 1);
  const lastDay = new Date(viewYear, viewMonth + 1, 0);
  const startWeekday = (firstDay.getDay() + 6) % 7;
  const daysInMonth = lastDay.getDate();
  const cells: (Date | null)[] = [];
  for (let i = 0; i < startWeekday; i++) cells.push(null);
  for (let i = 1; i <= daysInMonth; i++) {
    cells.push(new Date(viewYear, viewMonth, i));
  }

  const prevMonth = () => {
    setViewMonth((m) => {
      if (m === 0) {
        setViewYear((y) => y - 1);
        return 11;
      }
      return m - 1;
    });
  };
  const nextMonth = () => {
    setViewMonth((m) => {
      if (m === 11) {
        setViewYear((y) => y + 1);
        return 0;
      }
      return m + 1;
    });
  };

  const clearSelection = () => {
    setSelected(new Set());
    setRemoved(new Set());
  };

  const selectedList = Array.from(selected).sort();
  const removedList = Array.from(removed).sort();

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(
        selectedList.map((date) => ({ date, note: note.trim() || null })),
        removedList
      );
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-md flex-col overflow-y-auto rounded-t-2xl bg-background p-4 shadow-xl sm:max-h-[85vh] sm:rounded-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Calendar size={18} className="text-primary-700" />
            <h3 className="font-display text-sm font-bold text-foreground">
              标记出差日
            </h3>
          </div>
          <button
            onClick={onClose}
            className="text-muted-foreground transition-colors hover:text-foreground"
          >
            <X size={18} />
          </button>
        </div>

        <div className="mb-2 flex items-center justify-between">
          <button
            onClick={prevMonth}
            className="rounded-md px-2 py-1 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            ‹
          </button>
          <span className="text-sm font-medium text-foreground">
            {viewYear} 年 {viewMonth + 1} 月
          </span>
          <button
            onClick={nextMonth}
            className="rounded-md px-2 py-1 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            ›
          </button>
        </div>

        <div className="mb-1 grid grid-cols-7 gap-1 text-center text-[11px] text-muted-foreground">
          {WEEKDAYS.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </div>

        <div className="grid grid-cols-7 gap-1">
          {cells.map((d, i) => {
            if (!d) return <div key={`empty-${i}`} />;
            const clickable = isClickable(d);
            const existing = isExisting(d);
            const sel = isSelected(d);
            const rm = isRemoved(d);
            return (
              <button
                key={iso(d)}
                onClick={() => toggleDate(d)}
                disabled={!clickable}
                className={`aspect-square rounded-md text-xs font-medium transition-colors ${
                  !clickable
                    ? "cursor-not-allowed text-muted-foreground/40"
                    : rm
                      ? "bg-error-50 text-error-600 line-through"
                      : sel
                        ? "bg-primary-700 text-white"
                        : existing
                          ? "bg-primary-50 text-primary-700"
                          : "text-foreground hover:bg-muted"
                }`}
              >
                {d.getDate()}
              </button>
            );
          })}
        </div>

        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="备注（可选，如北京出差）"
          className="mt-3 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-100"
        />

        {selectedList.length > 0 && (
          <div className="mt-2 text-xs text-muted-foreground">
            已选 {selectedList.length} 天：{selectedList.join("、")}
          </div>
        )}
        {removedList.length > 0 && (
          <div className="mt-1 text-xs text-error-600">
            取消 {removedList.length} 天：{removedList.join("、")}
          </div>
        )}
        {error && (
          <div className="mt-2 text-xs text-error-600">提交失败：{error}</div>
        )}

        <div className="mt-4 flex items-center justify-between gap-2">
          <button
            onClick={clearSelection}
            disabled={selected.size === 0 && removed.size === 0}
            className="rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
          >
            清空选择
          </button>
          <button
            onClick={handleSubmit}
            disabled={
              submitting || (selected.size === 0 && removed.size === 0)
            }
            className="flex items-center gap-1 rounded-md bg-primary-700 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-primary-800 disabled:opacity-40"
          >
            <Check size={14} />
            {submitting ? "提交中…" : "完成"}
          </button>
        </div>
      </div>
    </div>
  );
}
