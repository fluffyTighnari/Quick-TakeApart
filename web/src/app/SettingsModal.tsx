import { useEffect, useMemo, useState } from "react";
import { Check, Cpu, KeyRound, RefreshCw, Server, X } from "lucide-react";
import { api } from "../core/api";
import type { ApiSettings } from "../types";

const PRESET_MODELS = ["deepseek-v4.1-flash", "deepseek-flash", "deepseek-v4-pro"];

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<ApiSettings | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState(PRESET_MODELS[0]);
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [models, setModels] = useState<string[]>(PRESET_MODELS);
  const [loadingModels, setLoadingModels] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [modelError, setModelError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let alive = true;
    api.settings()
      .then((res) => {
        if (!alive) return;
        setSettings(res.settings);
        setBaseUrl(res.settings.baseUrl);
        setModel(res.settings.model || PRESET_MODELS[0]);
      })
      .catch((err) => { if (alive) setError(err instanceof Error ? err.message : String(err)); });
    return () => { alive = false; };
  }, []);

  const modelOptions = useMemo(() => {
    const out = [model, ...PRESET_MODELS, ...models].filter(Boolean);
    return [...new Set(out)];
  }, [model, models]);

  async function loadModels() {
    if (!baseUrl.trim() || loadingModels) return;
    setLoadingModels(true);
    setModelError("");
    try {
      const res = await api.listModels({
        baseUrl: baseUrl.trim(),
        apiKey: apiKey.trim() || undefined,
      });
      const next = [...new Set([...res.models, ...PRESET_MODELS])];
      setModels(next);
      // Keep the current/prefilled model even if the catalog uses an alias.
      // The user can still pick any fetched id from the datalist.
    } catch (err) {
      setModelError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingModels(false);
    }
  }

  async function save() {
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const res = await api.saveSettings({
        baseUrl: baseUrl.trim(),
        model: model.trim(),
        apiKey: apiKey.trim(),
        clearKey,
      });
      setSettings(res.settings);
      setApiKey("");
      setClearKey(false);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  const hasCredential = !!(settings?.hasKey || settings?.envKey || apiKey.trim());

  return (
    <div className="palette-backdrop" onMouseDown={(e) => {
      if (e.target === e.currentTarget) onClose();
    }}>
      <div className="palette settings-modal" style={{ padding: 18 }}>
        <div className="row" style={{ marginBottom: 12 }}>
          <div className="grow">
            <div className="eyebrow" style={{ marginBottom: 2 }}>Model API</div>
            <div className="panel-title">API 设置</div>
          </div>
          <button className="icon-btn" onClick={onClose}><X size={14} /></button>
        </div>

        <div className="settings-form">
          <div className="panel-flat panel-body">
            <div className="row wrap" style={{ gap: 6 }}>
              <span className={`chip ${hasCredential ? "teal" : "amber"}`}>
                <KeyRound size={10} />{" "}
                {settings?.hasKey
                  ? `本机 Key ${settings.keyHint}`
                  : settings?.envKey
                    ? `环境变量 Key ${settings.envKeyHint}`
                    : apiKey.trim()
                      ? "将保存新 Key"
                      : "尚未配置 Key"}
              </span>
              <span className="chip"><Server size={10} /> {settings?.settingsPath || "本地设置"}</span>
              {settings?.updatedAt ? <span className="chip muted">更新于 {settings.updatedAt.slice(0, 19).replace("T", " ")}</span> : null}
            </div>
            <p className="small muted" style={{ marginTop: 8 }}>
              保存在本机；保存后下一次请求生效。环境变量仍可作为回退。
            </p>
          </div>

          <div className="field">
            <label htmlFor="settings-base"><Server size={11} /> Base URL</label>
            <div className="settings-url-row">
              <input
                id="settings-base"
                className="input"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                onBlur={() => { if (hasCredential) void loadModels(); }}
                placeholder="https://api.deepseek.com/anthropic"
              />
              <button className="btn btn-sm" disabled={!baseUrl.trim() || loadingModels} onClick={() => void loadModels()}>
                <RefreshCw size={12} className={loadingModels ? "spin" : ""} />
                {loadingModels ? "拉取中…" : "拉取模型"}
              </button>
            </div>
            {modelError ? <div className="small" style={{ color: "var(--rust)", marginTop: 5 }}>{modelError}</div> : null}
          </div>

          <div className="field">
            <label htmlFor="settings-model"><Cpu size={11} /> 模型</label>
            <input
              id="settings-model"
              className="input"
              list="model-catalog"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="deepseek-v4.1-flash"
            />
            <datalist id="model-catalog">
              {modelOptions.map((item) => <option key={item} value={item} />)}
            </datalist>
            <div className="small muted" style={{ marginTop: 4 }}>
              默认预填 DeepSeek 4.1 Flash；填入 Base URL 后可拉取模型目录，也可以手动输入。
            </div>
          </div>

          <div className="field">
            <label htmlFor="settings-key"><KeyRound size={11} /> API Key</label>
            <input
              id="settings-key"
              className="input"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={settings?.hasKey ? `留空表示保持 ${settings.keyHint}` : "输入 API Key"}
              autoComplete="off"
            />
          </div>

          <label className="row small muted" style={{ gap: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={clearKey} onChange={(e) => setClearKey(e.target.checked)} />
            清除本机保存的 Key（环境变量仍可用）
          </label>

          {error ? <div className="notice bad">{error}</div> : null}
          {saved ? <div className="notice info"><Check size={12} /> 已保存，下一次模型请求生效。</div> : null}

          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn btn-ghost" onClick={onClose}>关闭</button>
            <button className="btn btn-primary" disabled={saving} onClick={() => void save()}>
              {saving ? "保存中…" : "保存设置"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
