import { useEffect, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  GearSix,
  Lightning,
  Eye,
  EyeSlash,
  CheckCircle,
  Warning,
  Spinner,
  FloppyDisk,
  PlugsConnected,
} from "@phosphor-icons/react";
import { settingsApi } from "../api/client";
import type { LlmSettings, LlmProviderInfo } from "../types";

// 服务商中文标签
const PROVIDER_LABELS: Record<string, string> = {
  qwen: "千问 (Qwen)",
  deepseek: "DeepSeek",
  openai: "OpenAI",
  anthropic: "Anthropic",
};

export function Settings() {
  // 当前配置（从服务端加载）
  const [saved, setSaved] = useState<LlmSettings | null>(null);
  // 编辑中的表单值
  const [form, setForm] = useState<LlmSettings>({
    llm_provider: "qwen",
    llm_api_key: "",
    llm_model: "qwen3-vl-plus",
    llm_text_model: "",
    llm_base_url: "",
  });
  const [providers, setProviders] = useState<
    Record<string, LlmProviderInfo> | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);
  const [showKey, setShowKey] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  // 标记表单是否被修改（与 saved 比较）
  const isDirty =
    saved !== null &&
    (form.llm_provider !== saved.llm_provider ||
      form.llm_api_key !== saved.llm_api_key ||
      form.llm_model !== saved.llm_model ||
      form.llm_text_model !== saved.llm_text_model ||
      form.llm_base_url !== saved.llm_base_url);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [settings, provs] = await Promise.all([
        settingsApi.getLlmSettings(),
        settingsApi.getProviders(),
      ]);
      setSaved(settings);
      setForm(settings);
      setProviders(provs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载配置失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // 切换服务商时，自动填充该服务商的推荐模型和 base URL
  const handleProviderChange = (provider: string) => {
    const info = providers?.[provider];
    setForm((prev) => ({
      ...prev,
      llm_provider: provider,
      // 自动选第一个模型
      llm_model: info?.models?.[0] || prev.llm_model,
      // 文本模型留空（服务端自动推导）
      llm_text_model: "",
      // 如果用户没自定义过 base_url，则清空让服务端用默认值
      llm_base_url: prev.llm_base_url && info
        ? (prev.llm_base_url === info.base_url ? "" : prev.llm_base_url)
        : "",
    }));
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg(null);
    setError(null);
    try {
      // 构造更新 payload：只传有变化的字段
      const payload: Partial<LlmSettings> = {};
      if (form.llm_provider !== saved?.llm_provider)
        payload.llm_provider = form.llm_provider;
      if (form.llm_api_key !== saved?.llm_api_key)
        payload.llm_api_key = form.llm_api_key;
      if (form.llm_model !== saved?.llm_model)
        payload.llm_model = form.llm_model;
      if (form.llm_text_model !== saved?.llm_text_model)
        payload.llm_text_model = form.llm_text_model;
      if (form.llm_base_url !== saved?.llm_base_url)
        payload.llm_base_url = form.llm_base_url;

      // 如果没有变化，不调用 API
      if (Object.keys(payload).length === 0) {
        setSaveMsg("配置未变化，无需保存");
        setSaving(false);
        return;
      }

      const result = await settingsApi.updateLlmSettings(payload);
      setSaved(result);
      setForm(result);
      setSaveMsg("保存成功，配置已热更新到运行时");
      // 3 秒后自动清除成功消息
      setTimeout(() => setSaveMsg(null), 5000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      // 用当前表单值测试（如果是掩码 key，则不传 key 让服务端用已保存的）
      const payload: Partial<LlmSettings> = {
        llm_provider: form.llm_provider,
        llm_model: form.llm_model,
        llm_text_model: form.llm_text_model || undefined,
        llm_base_url: form.llm_base_url || undefined,
      };
      // 只有用户修改了 key（不是掩码格式）才传
      if (
        form.llm_api_key &&
        !form.llm_api_key.includes("...") &&
        form.llm_api_key !== saved?.llm_api_key
      ) {
        payload.llm_api_key = form.llm_api_key;
      }
      const result = await settingsApi.testLlmConnection(payload);
      setTestResult(result);
    } catch (e) {
      setTestResult({
        success: false,
        message: e instanceof Error ? e.message : "测试失败",
      });
    } finally {
      setTesting(false);
    }
  };

  // 当前服务商的模型列表
  const currentModels = providers?.[form.llm_provider]?.models || [];
  // 区分视觉模型和文本模型
  const visionPrefixes =
    providers?.[form.llm_provider]?.vision_prefixes || [];
  const isVisionModel = (m: string) =>
    visionPrefixes.some((p) => m.startsWith(p));

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size={24} className="animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight text-slate-900">
          LLM 模型设置
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          配置对话引擎使用的 LLM 服务商、API Key 和模型参数 — 保存后即时生效，无需重启服务
        </p>
      </div>

      {/* Error banner */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="flex items-center gap-2 rounded-xl bg-rose-50 p-4 text-sm text-rose-700"
          >
            <Warning size={18} />
            {error}
            <button onClick={() => setError(null)} className="ml-auto text-rose-400 hover:text-rose-600">
              &times;
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main card */}
      <div className="rounded-2xl border border-slate-200/60 bg-white p-6">
        <div className="flex items-center gap-2 mb-6">
          <GearSix size={20} weight="fill" className="text-brand-600" />
          <h2 className="font-display text-lg font-bold text-slate-900">
            大模型服务配置
          </h2>
        </div>

        <div className="space-y-5 max-w-2xl">
          {/* 服务商 */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-slate-700">
              服务商
            </label>
            <select
              value={form.llm_provider}
              onChange={(e) => handleProviderChange(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm focus:border-brand-400 focus:bg-white"
            >
              {Object.entries(PROVIDER_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>

          {/* API Key */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-slate-700">
              API Key
            </label>
            <div className="flex gap-2">
              <input
                type={showKey ? "text" : "password"}
                value={form.llm_api_key}
                onChange={(e) =>
                  setForm({ ...form, llm_api_key: e.target.value })
                }
                placeholder="sk-..."
                className="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm font-mono focus:border-brand-400 focus:bg-white"
              />
              <button
                onClick={() => setShowKey(!showKey)}
                className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500 hover:bg-slate-100"
                title={showKey ? "隐藏" : "显示"}
              >
                {showKey ? <EyeSlash size={16} /> : <Eye size={16} />}
              </button>
            </div>
            <p className="text-xs text-slate-400">
              API Key 仅存储在服务端数据库中，不会暴露给前端
            </p>
          </div>

          {/* 视觉模型 */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-slate-700">
              视觉模型
              <span className="ml-1 text-xs text-slate-400">
                (用于发票 OCR 识别)
              </span>
            </label>
            {currentModels.length > 0 ? (
              <select
                value={form.llm_model}
                onChange={(e) =>
                  setForm({ ...form, llm_model: e.target.value })
                }
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm focus:border-brand-400 focus:bg-white"
              >
                {currentModels.filter(isVisionModel).map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
                {currentModels.filter((m) => !isVisionModel(m)).length > 0 && (
                  <optgroup label="纯文本模型（不推荐用于OCR）">
                    {currentModels
                      .filter((m) => !isVisionModel(m))
                      .map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                  </optgroup>
                )}
              </select>
            ) : (
              <input
                value={form.llm_model}
                onChange={(e) =>
                  setForm({ ...form, llm_model: e.target.value })
                }
                placeholder="如 qwen3-vl-plus"
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm focus:border-brand-400 focus:bg-white"
              />
            )}
          </div>

          {/* 文本模型 */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-slate-700">
              文本模型
              <span className="ml-1 text-xs text-slate-400">
                (用于意图识别、项目提取)
              </span>
            </label>
            {currentModels.length > 0 ? (
              <select
                value={form.llm_text_model}
                onChange={(e) =>
                  setForm({ ...form, llm_text_model: e.target.value })
                }
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm focus:border-brand-400 focus:bg-white"
              >
                <option value="">自动推导（推荐）</option>
                {currentModels
                  .filter((m) => !isVisionModel(m))
                  .map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                {currentModels.filter((m) => isVisionModel(m)).length > 0 && (
                  <optgroup label="视觉模型（可用但较慢）">
                    {currentModels
                      .filter((m) => isVisionModel(m))
                      .map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                  </optgroup>
                )}
              </select>
            ) : (
              <input
                value={form.llm_text_model}
                onChange={(e) =>
                  setForm({ ...form, llm_text_model: e.target.value })
                }
                placeholder="留空则自动推导（如 qwen-plus）"
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm focus:border-brand-400 focus:bg-white"
              />
            )}
            <p className="text-xs text-slate-400">
              留空时服务端会从视觉模型名自动推导：qwen3-vl-plus → qwen-plus
            </p>
          </div>

          {/* 自定义 Base URL */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-slate-700">
              自定义 Base URL
              <span className="ml-1 text-xs text-slate-400">(可选)</span>
            </label>
            <input
              value={form.llm_base_url}
              onChange={(e) =>
                setForm({ ...form, llm_base_url: e.target.value })
              }
              placeholder={`留空使用默认值（${
                providers?.[form.llm_provider]?.base_url || "..."
              }）`}
              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm font-mono focus:border-brand-400 focus:bg-white"
            />
            <p className="text-xs text-slate-400">
              仅在使用代理或自定义 API 端点时填写
            </p>
          </div>
        </div>

        {/* Actions */}
        <div className="mt-6 flex items-center gap-3 border-t border-slate-100 pt-5">
          <button
            onClick={handleTest}
            disabled={testing}
            className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-50"
          >
            {testing ? (
              <Spinner size={16} className="animate-spin" />
            ) : (
              <PlugsConnected size={16} />
            )}
            {testing ? "测试中..." : "测试连通性"}
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !isDirty}
            className="flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-700 disabled:opacity-50"
          >
            {saving ? (
              <Spinner size={16} className="animate-spin" />
            ) : (
              <FloppyDisk size={16} />
            )}
            {saving ? "保存中..." : "保存配置"}
          </button>

          {/* Success / info message */}
          <AnimatePresence>
            {saveMsg && (
              <motion.span
                initial={{ opacity: 0, x: -4 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
                className="flex items-center gap-1 text-sm text-emerald-600"
              >
                <CheckCircle size={16} weight="fill" />
                {saveMsg}
              </motion.span>
            )}
          </AnimatePresence>
        </div>

        {/* Test result */}
        <AnimatePresence>
          {testResult && (
            <motion.div
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              className={`mt-4 flex items-start gap-2 rounded-xl p-4 text-sm ${
                testResult.success
                  ? "bg-emerald-50 text-emerald-800"
                  : "bg-rose-50 text-rose-800"
              }`}
            >
              {testResult.success ? (
                <Lightning size={18} weight="fill" className="mt-0.5 shrink-0" />
              ) : (
                <Warning size={18} weight="fill" className="mt-0.5 shrink-0" />
              )}
              <div>
                <div className="font-medium">{testResult.message}</div>
              </div>
              <button
                onClick={() => setTestResult(null)}
                className="ml-auto text-current opacity-50 hover:opacity-100"
              >
                &times;
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Tips */}
      <div className="rounded-2xl border border-slate-200/60 bg-white p-6">
        <h3 className="font-display text-sm font-bold text-slate-700 mb-3">
          配置说明
        </h3>
        <ul className="space-y-2 text-sm text-slate-500">
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-400" />
            保存配置后会立即热更新到运行时，对话引擎会自动使用新的 LLM 客户端
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-400" />
            文本模型留空时，服务端会从视觉模型名自动推导文本模型
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-400" />
            切换服务商时，模型下拉会自动填充该服务商的推荐模型
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
            API Key 仅存储在服务端数据库中，前端显示的是掩码版本
          </li>
        </ul>
      </div>
    </div>
  );
}
