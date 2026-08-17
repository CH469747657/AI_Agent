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
  Key,
  ShieldCheck,
  UserCircle,
} from "@phosphor-icons/react";
import { settingsApi, adminApi } from "../api/client";
import type { LlmSettings, LlmProviderInfo, VerifySettings } from "../types";

// 服务商中文标签
const PROVIDER_LABELS: Record<string, string> = {
  qwen: "千问 (Qwen)",
  deepseek: "DeepSeek",
  openai: "OpenAI",
  anthropic: "Anthropic",
};

// 验真服务商中文标签
const VERIFY_PROVIDER_LABELS: Record<string, string> = {
  aliyun: "阿里云云市场",
  baidu: "百度智能云",
};

type TabKey = "llm" | "verify" | "password";

const TABS: { key: TabKey; label: string; icon: typeof GearSix }[] = [
  { key: "llm", label: "LLM API 参数", icon: Lightning },
  { key: "verify", label: "发票验真 API 参数", icon: ShieldCheck },
  { key: "password", label: "管理员密码修改", icon: Key },
];

export function Settings() {
  const [activeTab, setActiveTab] = useState<TabKey>("llm");

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
          系统设置
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          管理 LLM、发票验真 API 参数和管理员账户密码 — 保存后即时生效
        </p>
      </div>

      {/* Tab 切换 */}
      <div className="flex gap-1 border-b border-border">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-colors border-b-2 ${
                isActive
                  ? "border-primary-600 text-primary-600"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon size={16} weight={isActive ? "fill" : "regular"} />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Tab 内容 */}
      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.15 }}
        >
          {activeTab === "llm" && <LlmTab />}
          {activeTab === "verify" && <VerifyTab />}
          {activeTab === "password" && <PasswordTab />}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

// ============================================================
// Tab 1: LLM API 参数设置（保留原有逻辑）
// ============================================================

function LlmTab() {
  const [saved, setSaved] = useState<LlmSettings | null>(null);
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

  const handleProviderChange = (provider: string) => {
    const info = providers?.[provider];
    setForm((prev) => ({
      ...prev,
      llm_provider: provider,
      llm_model: info?.models?.[0] || prev.llm_model,
      llm_text_model: "",
      llm_base_url:
        prev.llm_base_url && info
          ? prev.llm_base_url === info.base_url
            ? ""
            : prev.llm_base_url
          : "",
    }));
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg(null);
    setError(null);
    try {
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

      if (Object.keys(payload).length === 0) {
        setSaveMsg("配置未变化，无需保存");
        setSaving(false);
        return;
      }

      const result = await settingsApi.updateLlmSettings(payload);
      setSaved(result);
      setForm(result);
      setSaveMsg("保存成功，配置已热更新到运行时");
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
      const payload: Partial<LlmSettings> = {
        llm_provider: form.llm_provider,
        llm_model: form.llm_model,
        llm_text_model: form.llm_text_model || undefined,
        llm_base_url: form.llm_base_url || undefined,
      };
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

  const currentModels = providers?.[form.llm_provider]?.models || [];
  const visionPrefixes =
    providers?.[form.llm_provider]?.vision_prefixes || [];
  const isVisionModel = (m: string) =>
    visionPrefixes.some((p) => m.startsWith(p));

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size={24} className="animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="flex items-center gap-2 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">
          <Warning size={18} />
          {error}
          <button
            onClick={() => setError(null)}
            className="ml-auto text-rose-400 hover:text-rose-600"
          >
            &times;
          </button>
        </div>
      )}

      <div className="rounded-2xl border border-border bg-background p-6">
        <div className="flex items-center gap-2 mb-6">
          <Lightning size={20} weight="fill" className="text-primary-600" />
          <h2 className="font-display text-lg font-bold text-foreground">
            大模型服务配置
          </h2>
        </div>

        <div className="space-y-5 max-w-2xl">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">
              服务商
            </label>
            <select
              value={form.llm_provider}
              onChange={(e) => handleProviderChange(e.target.value)}
              className="w-full rounded-lg border border-border bg-muted px-3 py-2.5 text-sm focus:border-primary-400 focus:bg-background"
            >
              {Object.entries(PROVIDER_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">
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
                className="flex-1 rounded-lg border border-border bg-muted px-3 py-2.5 text-sm font-mono focus:border-primary-400 focus:bg-background"
              />
              <button
                onClick={() => setShowKey(!showKey)}
                className="flex items-center gap-1 rounded-lg border border-border bg-muted px-3 py-2 text-sm text-muted-foreground hover:bg-muted"
                title={showKey ? "隐藏" : "显示"}
              >
                {showKey ? <EyeSlash size={16} /> : <Eye size={16} />}
              </button>
            </div>
            <p className="text-xs text-muted-foreground">
              API Key 仅存储在服务端数据库中，不会暴露给前端
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">
              视觉模型
              <span className="ml-1 text-xs text-muted-foreground">
                (用于发票 OCR 识别)
              </span>
            </label>
            {currentModels.length > 0 ? (
              <select
                value={form.llm_model}
                onChange={(e) =>
                  setForm({ ...form, llm_model: e.target.value })
                }
                className="w-full rounded-lg border border-border bg-muted px-3 py-2.5 text-sm focus:border-primary-400 focus:bg-background"
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
                className="w-full rounded-lg border border-border bg-muted px-3 py-2.5 text-sm focus:border-primary-400 focus:bg-background"
              />
            )}
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">
              文本模型
              <span className="ml-1 text-xs text-muted-foreground">
                (用于意图识别、项目提取)
              </span>
            </label>
            {currentModels.length > 0 ? (
              <select
                value={form.llm_text_model}
                onChange={(e) =>
                  setForm({ ...form, llm_text_model: e.target.value })
                }
                className="w-full rounded-lg border border-border bg-muted px-3 py-2.5 text-sm focus:border-primary-400 focus:bg-background"
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
                className="w-full rounded-lg border border-border bg-muted px-3 py-2.5 text-sm focus:border-primary-400 focus:bg-background"
              />
            )}
            <p className="text-xs text-muted-foreground">
              留空时服务端会从视觉模型名自动推导：qwen3-vl-plus → qwen-plus
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">
              自定义 Base URL
              <span className="ml-1 text-xs text-muted-foreground">(可选)</span>
            </label>
            <input
              value={form.llm_base_url}
              onChange={(e) =>
                setForm({ ...form, llm_base_url: e.target.value })
              }
              placeholder={`留空使用默认值（${
                providers?.[form.llm_provider]?.base_url || "..."
              }）`}
              className="w-full rounded-lg border border-border bg-muted px-3 py-2.5 text-sm font-mono focus:border-primary-400 focus:bg-background"
            />
            <p className="text-xs text-muted-foreground">
              仅在使用代理或自定义 API 端点时填写
            </p>
          </div>
        </div>

        <div className="mt-6 flex items-center gap-3 border-t border-border pt-5">
          <button
            onClick={handleTest}
            disabled={testing}
            className="flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
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
            className="flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:opacity-50"
          >
            {saving ? (
              <Spinner size={16} className="animate-spin" />
            ) : (
              <FloppyDisk size={16} />
            )}
            {saving ? "保存中..." : "保存配置"}
          </button>

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
    </div>
  );
}

// ============================================================
// Tab 2: 发票验真 API 参数设置
// ============================================================

function VerifyTab() {
  const [saved, setSaved] = useState<VerifySettings | null>(null);
  const [form, setForm] = useState<VerifySettings>({
    verify_provider: "aliyun",
    verify_api_key: "",
    verify_secret_key: "",
    aliyun_verify_appcode: "",
    aliyun_verify_appsecret: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  const isDirty =
    saved !== null &&
    (form.verify_provider !== saved.verify_provider ||
      form.verify_api_key !== saved.verify_api_key ||
      form.verify_secret_key !== saved.verify_secret_key ||
      form.aliyun_verify_appcode !== saved.aliyun_verify_appcode ||
      form.aliyun_verify_appsecret !== saved.aliyun_verify_appsecret);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const settings = await settingsApi.getVerifySettings();
      setSaved(settings);
      setForm(settings);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载配置失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg(null);
    setError(null);
    try {
      const payload: Partial<VerifySettings> = {};
      if (form.verify_provider !== saved?.verify_provider)
        payload.verify_provider = form.verify_provider;
      if (form.verify_api_key !== saved?.verify_api_key)
        payload.verify_api_key = form.verify_api_key;
      if (form.verify_secret_key !== saved?.verify_secret_key)
        payload.verify_secret_key = form.verify_secret_key;
      if (form.aliyun_verify_appcode !== saved?.aliyun_verify_appcode)
        payload.aliyun_verify_appcode = form.aliyun_verify_appcode;
      if (form.aliyun_verify_appsecret !== saved?.aliyun_verify_appsecret)
        payload.aliyun_verify_appsecret = form.aliyun_verify_appsecret;

      if (Object.keys(payload).length === 0) {
        setSaveMsg("配置未变化，无需保存");
        setSaving(false);
        return;
      }

      const result = await settingsApi.updateVerifySettings(payload);
      setSaved(result);
      setForm(result);
      setSaveMsg("保存成功，配置已热更新到运行时");
      setTimeout(() => setSaveMsg(null), 5000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const toggleKey = (field: string) => {
    setShowKeys((prev) => ({ ...prev, [field]: !prev[field] }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size={24} className="animate-spin text-muted-foreground" />
      </div>
    );
  }

  const isAliyun = form.verify_provider === "aliyun";

  return (
    <div className="space-y-6">
      {error && (
        <div className="flex items-center gap-2 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">
          <Warning size={18} />
          {error}
          <button
            onClick={() => setError(null)}
            className="ml-auto text-rose-400 hover:text-rose-600"
          >
            &times;
          </button>
        </div>
      )}

      <div className="rounded-2xl border border-border bg-background p-6">
        <div className="flex items-center gap-2 mb-6">
          <ShieldCheck size={20} weight="fill" className="text-primary-600" />
          <h2 className="font-display text-lg font-bold text-foreground">
            发票验真服务配置
          </h2>
        </div>

        <div className="space-y-5 max-w-2xl">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">
              验真服务商
            </label>
            <select
              value={form.verify_provider}
              onChange={(e) =>
                setForm({ ...form, verify_provider: e.target.value })
              }
              className="w-full rounded-lg border border-border bg-muted px-3 py-2.5 text-sm focus:border-primary-400 focus:bg-background"
            >
              {Object.entries(VERIFY_PROVIDER_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">
              切换服务商后，对应字段会被使用，其他字段保留但不生效
            </p>
          </div>

          {/* 百度智能云字段 */}
          <div className={isAliyun ? "opacity-40 pointer-events-none" : ""}>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              百度智能云
            </div>
            <div className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-foreground">
                  API Key (AK)
                </label>
                <div className="flex gap-2">
                  <input
                    type={showKeys.baidu_ak ? "text" : "password"}
                    value={form.verify_api_key}
                    onChange={(e) =>
                      setForm({ ...form, verify_api_key: e.target.value })
                    }
                    placeholder="百度智能云 API Key"
                    className="flex-1 rounded-lg border border-border bg-muted px-3 py-2.5 text-sm font-mono focus:border-primary-400 focus:bg-background"
                  />
                  <button
                    onClick={() => toggleKey("baidu_ak")}
                    className="flex items-center gap-1 rounded-lg border border-border bg-muted px-3 py-2 text-sm text-muted-foreground hover:bg-muted"
                  >
                    {showKeys.baidu_ak ? <EyeSlash size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium text-foreground">
                  Secret Key (SK)
                </label>
                <div className="flex gap-2">
                  <input
                    type={showKeys.baidu_sk ? "text" : "password"}
                    value={form.verify_secret_key}
                    onChange={(e) =>
                      setForm({ ...form, verify_secret_key: e.target.value })
                    }
                    placeholder="百度智能云 Secret Key"
                    className="flex-1 rounded-lg border border-border bg-muted px-3 py-2.5 text-sm font-mono focus:border-primary-400 focus:bg-background"
                  />
                  <button
                    onClick={() => toggleKey("baidu_sk")}
                    className="flex items-center gap-1 rounded-lg border border-border bg-muted px-3 py-2 text-sm text-muted-foreground hover:bg-muted"
                  >
                    {showKeys.baidu_sk ? <EyeSlash size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* 阿里云字段 */}
          <div className={!isAliyun ? "opacity-40 pointer-events-none" : ""}>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              阿里云云市场
            </div>
            <div className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-foreground">
                  AppCode
                </label>
                <div className="flex gap-2">
                  <input
                    type={showKeys.appcode ? "text" : "password"}
                    value={form.aliyun_verify_appcode}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        aliyun_verify_appcode: e.target.value,
                      })
                    }
                    placeholder="阿里云云市场 AppCode"
                    className="flex-1 rounded-lg border border-border bg-muted px-3 py-2.5 text-sm font-mono focus:border-primary-400 focus:bg-background"
                  />
                  <button
                    onClick={() => toggleKey("appcode")}
                    className="flex items-center gap-1 rounded-lg border border-border bg-muted px-3 py-2 text-sm text-muted-foreground hover:bg-muted"
                  >
                    {showKeys.appcode ? <EyeSlash size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium text-foreground">
                  AppSecret
                </label>
                <div className="flex gap-2">
                  <input
                    type={showKeys.appsecret ? "text" : "password"}
                    value={form.aliyun_verify_appsecret}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        aliyun_verify_appsecret: e.target.value,
                      })
                    }
                    placeholder="阿里云云市场 AppSecret"
                    className="flex-1 rounded-lg border border-border bg-muted px-3 py-2.5 text-sm font-mono focus:border-primary-400 focus:bg-background"
                  />
                  <button
                    onClick={() => toggleKey("appsecret")}
                    className="flex items-center gap-1 rounded-lg border border-border bg-muted px-3 py-2 text-sm text-muted-foreground hover:bg-muted"
                  >
                    {showKeys.appsecret ? <EyeSlash size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-6 flex items-center gap-3 border-t border-border pt-5">
          <button
            onClick={handleSave}
            disabled={saving || !isDirty}
            className="flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:opacity-50"
          >
            {saving ? (
              <Spinner size={16} className="animate-spin" />
            ) : (
              <FloppyDisk size={16} />
            )}
            {saving ? "保存中..." : "保存配置"}
          </button>

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
      </div>

      <div className="rounded-2xl border border-border bg-background p-6">
        <h3 className="font-display text-sm font-bold text-foreground mb-3">
          配置说明
        </h3>
        <ul className="space-y-2 text-sm text-muted-foreground">
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-primary-400" />
            验真配置保存后立即热更新，下次发票验真调用即使用新参数
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-primary-400" />
            阿里云云市场用 AppCode/AppSecret 鉴权；百度智能云用 AK/SK 鉴权
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
            敏感字段返回掩码版（如 `xxxx...xxxx`），未修改的字段保持原值不变
          </li>
        </ul>
      </div>
    </div>
  );
}

// ============================================================
// Tab 3: 管理员密码修改
// ============================================================

function PasswordTab() {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPasswords, setShowPasswords] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const admin = adminApi.getStoredAdmin();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccessMsg(null);

    if (!oldPassword || !newPassword || !confirmPassword) {
      setError("请填写完整字段");
      return;
    }
    if (newPassword.length < 6) {
      setError("新密码至少 6 位");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("两次输入的新密码不一致");
      return;
    }
    if (oldPassword === newPassword) {
      setError("新密码不能与当前密码相同");
      return;
    }

    setSaving(true);
    try {
      await adminApi.changePassword(oldPassword, newPassword);
      setSuccessMsg("密码修改成功，下次登录请使用新密码");
      setOldPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "修改失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      {error && (
        <div className="flex items-center gap-2 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">
          <Warning size={18} />
          {error}
        </div>
      )}
      {successMsg && (
        <div className="flex items-center gap-2 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-700">
          <CheckCircle size={18} weight="fill" />
          {successMsg}
        </div>
      )}

      <div className="rounded-2xl border border-border bg-background p-6 max-w-xl">
        <div className="flex items-center gap-2 mb-6">
          <UserCircle size={20} weight="fill" className="text-primary-600" />
          <h2 className="font-display text-lg font-bold text-foreground">
            管理员账户信息
          </h2>
        </div>

        <div className="mb-6 rounded-lg bg-muted p-3 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">当前账户：</span>
            <span className="font-mono font-semibold text-foreground">
              {admin?.username || "admin"}
            </span>
            <span className="ml-2 rounded bg-primary-100 px-2 py-0.5 text-xs text-primary-700">
              {admin?.role || "admin"}
            </span>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">
              当前密码
            </label>
            <input
              type={showPasswords ? "text" : "password"}
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              placeholder="请输入当前密码"
              className="w-full rounded-lg border border-border bg-muted px-3 py-2.5 text-sm focus:border-primary-400 focus:bg-background"
              required
              autoFocus
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">
              新密码
              <span className="ml-1 text-xs text-muted-foreground">
                (至少 6 位)
              </span>
            </label>
            <input
              type={showPasswords ? "text" : "password"}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="请输入新密码"
              className="w-full rounded-lg border border-border bg-muted px-3 py-2.5 text-sm focus:border-primary-400 focus:bg-background"
              required
              minLength={6}
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">
              确认新密码
            </label>
            <input
              type={showPasswords ? "text" : "password"}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="请再次输入新密码"
              className="w-full rounded-lg border border-border bg-muted px-3 py-2.5 text-sm focus:border-primary-400 focus:bg-background"
              required
              minLength={6}
            />
          </div>

          <div className="flex items-center gap-3 border-t border-border pt-5">
            <button
              type="submit"
              disabled={saving}
              className="flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:opacity-50"
            >
              {saving ? (
                <Spinner size={16} className="animate-spin" />
              ) : (
                <Key size={16} />
              )}
              {saving ? "保存中..." : "保存新密码"}
            </button>
            <button
              type="button"
              onClick={() => setShowPasswords(!showPasswords)}
              className="flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm text-muted-foreground hover:bg-muted"
            >
              {showPasswords ? <EyeSlash size={16} /> : <Eye size={16} />}
              {showPasswords ? "隐藏密码" : "显示密码"}
            </button>
          </div>
        </form>
      </div>

      <div className="rounded-2xl border border-border bg-background p-6 max-w-xl">
        <h3 className="font-display text-sm font-bold text-foreground mb-3">
          安全提示
        </h3>
        <ul className="space-y-2 text-sm text-muted-foreground">
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
            新密码以 bcrypt 哈希形式存储在数据库中，不可逆向解密
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
            修改成功后当前登录态仍有效，但下次登录需使用新密码
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
            忘记密码时，可在服务端 .env 重置 ADMIN_PASSWORD_HASH 后重启服务
          </li>
        </ul>
      </div>
    </div>
  );
}
