import { motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

interface StatCardProps {
  label: string;
  value: number;
  prefix?: string;
  suffix?: string;
  icon: React.ReactNode;
  iconBg: string;
  delay: number;
}

export function StatCard({
  label,
  value,
  prefix = "",
  suffix = "",
  icon,
  iconBg,
  delay,
}: StatCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 120, damping: 20, delay }}
      className="rounded-xl border border-border bg-background p-4"
    >
      <div className="flex items-center justify-between">
        <div
          className={`flex h-9 w-9 items-center justify-center rounded-lg ${iconBg}`}
        >
          {icon}
        </div>
      </div>
      <div className="mt-3">
        <CountUp value={value} prefix={prefix} suffix={suffix} />
        <p className="mt-1 text-sm text-muted-foreground">{label}</p>
      </div>
    </motion.div>
  );
}

function CountUp({
  value,
  prefix,
  suffix,
}: {
  value: number;
  prefix: string;
  suffix: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    const start = performance.now();
    const duration = 800;
    let raf: number;

    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(value * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);

  const isFloat = !Number.isInteger(value);

  return (
    <span
      ref={ref}
      className="font-display font-mono text-xl font-bold tracking-tight text-foreground"
    >
      {prefix}
      {isFloat
        ? display.toLocaleString("zh-CN", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          })
        : Math.round(display).toLocaleString("zh-CN")}
      {suffix}
    </span>
  );
}
