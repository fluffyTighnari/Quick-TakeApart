import { useEffect, useMemo, useState } from "react";
import {
  Check, Cpu, KeyRound, Plus, RefreshCw, Server, Trash2, X,
} from "lucide-react";
import { api } from "../core/api";
import { useApp } from "../core/store";
import { useEscape } from "../ui/useEscape";
import type {
  ApiSettings, LangPack, LlmConfigView, LlmProfile, LlmProvider,
} from "../types";

type Tab = "model" | "languages";

type Draft = {
  profile_id?: string;
  provider_id: string;
  label: string;
  base_url: string;
  model: string;
  models: string[];
  think: "" | "true" | "false";
  num_ctx: string;
  note: string;
  has_key: boolean;
  key_masked: string;
  api_key: string;
  clear_key: boolean;
};

function blankDraft(provider: LlmProvider): Draft {
  return {
    provider_id: provider.provider_id,
    label: provider.label,
    base_url: provider.base_url,
    model: provider.default_model,
    models: provider.default_model ? [provider.default_model] : [],
    think: "",
    num_ctx: "",
    note: "",
    has_key: false,
    key_masked: "",
    api_key: "",
    clear_key: false,
  };
}

function draftFromProfile(profile: LlmProfile): Draft {
  return {
    profile_id: profile.profile_id,
    provider_id: profile.provider_id,
    label: profile.label,
    base_url: profile.base_url,
    model: profile.model,
    models: profile.models.length ? profile.models : [profile.model],
    think: profile.think,
    num_ctx: profile.num_ctx ? String(profile.num_ctx) : "",
    note: profile.note,
    has_key: profile.has_key,
    key_masked: profile.key_masked,
    api_key: "",
    clear_key: false,
  };
}

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const base = useApp((s) => s.base);
  const [tab, setTab] = useState<Tab>("model");
  const [providers, setProviders] = useState<LlmProvider[]>([]);
  const [profiles, setProfiles] = useState<LlmProfile[]>([]);
  const [config, setConfig] = useState<LlmConfigView | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [catalog, setCatalog] = useState<string[]>([]);
  const [catalogNote, setCatalogNote] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [settings, setSettings] = useState<ApiSettings | null>(null);
  const [languageServers, setLanguageServers] = useState<Record<string, string>>({});
  const [packs, setPacks] = useState<LangPack[]>([]);
  const [selectedPacks, setSelectedPacks] = useState<string[]>([]);

  useEscape(onClose);

  const provider = useMemo(
    () => providers.find((item) => item.provider_id === draft?.provider_id) || null,
    [providers, draft?.provider_id],
  );

  async function refresh(keepDraft = true) {
    const [providersRes, profilesRes, configRes, settingsRes] = await Promise.all([
      api.llmProviders(), api.llmProfiles(), api.llmConfig(), api.settings(),
    ]);
    setProviders(providersRes.items);
    setProfiles(profilesRes.items);
    setConfig(configRes);
    setSettings(settingsRes.settings);
    setLanguageServers(settingsRes.settings.languageServers || {});
    if (!keepDraft || !draft) {
      const active = profilesRes.items.find((item) => item.is_active);
      setDraft(active ? draftFromProfile(active) : blankDraft(providersRes.items[0]));
    }
  }

  useEffect(() => {
    let alive = true;
    refresh(false).catch((err) => {
      if (alive) setError(err instanceof Error ? err.message : String(err));
    });
    void loadPacks();
    return () => { alive = false; };
  }, []);

  async function loadPacks() {
    try {
      const res = await api.langpacks();
      setPacks(res.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const installing = packs.some((item) => item.state === "installing");

  useEffect(() => {
    if (!installing) return;
    const timer = window.setInterval(() => { void loadPacks(); }, 1200);
    return () => window.clearInterval(timer);
  }, [installing]);

  function togglePack(id: string) {
    setSelectedPacks((current) => (
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
    ));
  }

  async function downloadPacks() {
    const ids = selectedPacks.filter((id) => {
      const pack = packs.find((item) => item.id === id);
      return pack && !pack.installed && pack.state !== "installing";
    });
    if (!ids.length) return;
    setSelectedPacks([]);
    setError("");
    setMessage("");
    try {
      for (const id of ids) await api.installLangpack(id);
      setMessage(`已开始后台下载 ${ids.length} 个语言包，可以关闭这个面板`);
      await loadPacks();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function removePack(id: string) {
    const pack = packs.find((item) => item.id === id);
    if (!pack) return;
    const ok = window.confirm(`删除 ${pack.label} 语言包？对应的语言服务器会变为不可用。`);
    if (!ok) return;
    setError("");
    try {
      await api.removeLangpack(id);
      setMessage(`${pack.label} 语言包已删除`);
      await loadPacks();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function selectProvider(providerId: string) {
    const next = providers.find((item) => item.provider_id === providerId);
    if (!next) return;
    setDraft((current) => ({
      ...(current || blankDraft(next)),
      provider_id: next.provider_id,
      label: current?.label && current.profile_id ? current.label : next.label,
      base_url: next.base_url,
      model: next.default_model,
      models: next.default_model ? [next.default_model] : [],
      api_key: "",
      has_key: false,
      key_masked: "",
      clear_key: false,
    }));
    setCatalog([]);
    setCatalogNote("");
    setMessage("");
    setError("");
  }

  function startNew() {
    const first = providers[0];
    if (!first) return;
    setDraft(blankDraft(first));
    setCatalog([]);
    setCatalogNote("");
    setMessage("");
    setError("");
  }

  function editProfile(profile: LlmProfile) {
    setDraft(draftFromProfile(profile));
    setCatalog(profile.models);
    setCatalogNote("");
    setMessage("");
    setError("");
  }

  function updateDraft(patch: Partial<Draft>) {
    setDraft((current) => current ? { ...current, ...patch } : current);
  }

  function draftBody(fetchModels = false) {
    if (!draft) return null;
    const body: Record<string, unknown> = {
      provider_id: draft.provider_id,
      label: draft.label.trim(),
      base_url: draft.base_url.trim(),
      model: draft.model.trim(),
      models: draft.models,
      think: draft.think,
      num_ctx: draft.num_ctx.trim() ? Number(draft.num_ctx) : 0,
      note: draft.note.trim(),
    };
    if (draft.clear_key) body.api_key = "";
    else if (draft.api_key.trim()) body.api_key = draft.api_key.trim();
    return body;
  }

  async function save(fetchModels = false) {
    if (!draft) return;
    setBusy(fetchModels ? "正在保存并拉取清单…" : "正在保存…");
    setError("");
    setMessage("");
    try {
      const body = draftBody();
      if (!body) return;
      const saved = draft.profile_id
        ? await api.updateLlmProfile(draft.profile_id, body)
        : await api.createLlmProfile(body);
      setDraft(draftFromProfile(saved));
      await refresh(true);
      if (fetchModels) {
        const result = await api.llmModels(saved.profile_id);
        const next = [...new Set([saved.model, ...result.models])];
        setCatalog(next);
        setCatalogNote(result.note);
        setDraft((current) => current ? {
          ...current,
          models: [...new Set([...current.models, ...next])],
        } : current);
      }
      setMessage(fetchModels ? "已保存并拉取清单" : "已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function saveModels() {
    if (!draft?.profile_id) return;
    setBusy("正在保存模型勾选…");
    setError("");
    try {
      const saved = await api.updateLlmProfile(draft.profile_id, {
        model: draft.model,
        models: draft.models,
      });
      setDraft(draftFromProfile(saved));
      await refresh(true);
      setMessage("模型清单已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function activate(profile: LlmProfile) {
    setBusy("正在切换…");
    setError("");
    try {
      await api.activateLlmProfile(profile.profile_id, profile.model);
      await refresh(true);
      setMessage(`已启用 ${profile.label}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function remove(profile: LlmProfile) {
    if (!confirm(`删除配置「${profile.label}」？密钥文件也会删除。`)) return;
    setBusy("正在删除…");
    setError("");
    try {
      await api.deleteLlmProfile(profile.profile_id);
      setDraft(null);
      await refresh(false);
      setMessage("已删除");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function probe() {
    if (!draft?.profile_id) return;
    setBusy("正在探活…");
    setError("");
    try {
      const result = await api.llmProbe(draft.profile_id);
      setMessage(result.detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function saveLanguageServers() {
    setBusy("正在保存语言服务器…");
    setError("");
    try {
      const result = await api.saveSettings({ languageServers });
      setSettings(result.settings);
      setMessage("语言服务器设置已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  function toggleModel(model: string) {
    setDraft((current) => {
      if (!current) return current;
      if (model === current.model) return current;
      const has = current.models.includes(model);
      return {
        ...current,
        models: has
          ? current.models.filter((item) => item !== model)
          : [...current.models, model],
      };
    });
  }

  const activeId = config?.active?.profile_id || null;

  return (
    <div className="palette-backdrop" onMouseDown={(e) => {
      if (e.target === e.currentTarget) onClose();
    }}>
      <div className="palette settings-modal" style={{ padding: 18 }}>
        <div className="row" style={{ marginBottom: 10 }}>
          <div className="grow">
            <div className="eyebrow" style={{ marginBottom: 2 }}>Settings</div>
            <div className="panel-title">模型与语言配置</div>
          </div>
          <button className="icon-btn" onClick={onClose}><X size={14} /></button>
        </div>

        <div className="settings-tabs">
          <button className={tab === "model" ? "active" : ""} onClick={() => setTab("model")}>模型</button>
          <button className={tab === "languages" ? "active" : ""} onClick={() => setTab("languages")}>语言服务器</button>
          <span className="spacer" />
          <span className="chip teal">当前：{config?.active?.label || "环境变量"}</span>
        </div>

        {tab === "model" ? (
          <div className="settings-form">
            <div className="panel-flat panel-body">
              <div className="row" style={{ marginBottom: 7 }}>
                <div className="grow">
                  <div className="eyebrow" style={{ marginBottom: 2 }}>Profiles</div>
                  <div className="small muted">多份配置，随时切换；切换档案与模型是一次动作。</div>
                </div>
                <button className="btn btn-xs" onClick={startNew}><Plus size={11} /> 新建</button>
              </div>
              <div className="settings-profile-list">
                {profiles.map((profile) => (
                  <div className={`settings-profile${profile.profile_id === activeId ? " active" : ""}`} key={profile.profile_id}>
                    <button className="settings-profile-main" onClick={() => editProfile(profile)}>
                      <span className="grow">
                        <span className="sp-row">
                          <strong>{profile.label}</strong>
                          {profile.profile_id === activeId ? <span className="chip teal">正在用</span> : null}
                        </span>
                        <span className="small muted">{profile.provider_id} · {profile.model}</span>
                        <span className="small muted">
                          {profile.has_key ? `Key ${profile.key_masked}` : "无 Key"} · 预算 {profile.effective_num_ctx}
                        </span>
                      </span>
                    </button>
                    <div className="row" style={{ gap: 3 }}>
                      {profile.profile_id !== activeId ? (
                        <button className="btn btn-xs" disabled={!!busy} onClick={() => void activate(profile)}>启用</button>
                      ) : null}
                      <button className="icon-btn" onClick={() => void remove(profile)}><Trash2 size={12} /></button>
                    </div>
                  </div>
                ))}
                {!profiles.length ? <div className="small muted">还没有配置。选服务商、填 Key，保存第一份会自动生效。</div> : null}
              </div>
            </div>

            {draft ? (
              <div className="panel-flat panel-body">
                <div className="row" style={{ marginBottom: 8 }}>
                  <div className="grow">
                    <div className="eyebrow" style={{ marginBottom: 2 }}>{draft.profile_id || "New profile"}</div>
                    <div className="panel-title" style={{ fontSize: 16 }}>
                      {draft.profile_id ? "编辑配置" : "新建配置"}
                    </div>
                  </div>
                  {draft.profile_id ? (
                    <button className="btn btn-xs" disabled={!!busy} onClick={() => void probe()}>探活</button>
                  ) : null}
                </div>

                <div className="field">
                  <label>服务商</label>
                  <select className="select" value={draft.provider_id}
                    onChange={(e) => selectProvider(e.target.value)}>
                    {providers.map((item) => (
                      <option key={item.provider_id} value={item.provider_id}>{item.label} · {item.kind}</option>
                    ))}
                  </select>
                  {provider ? <div className="small muted" style={{ marginTop: 4 }}>{provider.key_hint}</div> : null}
                </div>

                <div className="field">
                  <label>配置名称</label>
                  <input className="input" value={draft.label}
                    onChange={(e) => updateDraft({ label: e.target.value })}
                    placeholder={provider?.label || "例如：DeepSeek 工作"} />
                </div>

                <div className="field">
                  <label><Server size={11} /> Base URL</label>
                  <input className="input" value={draft.base_url}
                    onChange={(e) => updateDraft({ base_url: e.target.value })}
                    placeholder={provider?.base_url || "https://…/v1"} />
                </div>

                {provider?.needs_key !== false ? (
                  <div className="field">
                    <label><KeyRound size={11} /> API Key</label>
                    <input className="input" type="password" value={draft.api_key}
                      onChange={(e) => updateDraft({ api_key: e.target.value })}
                      placeholder={draft.has_key ? `已设置 ${draft.key_masked} · 留空不改` : "输入 API Key"}
                      autoComplete="off" />
                    {draft.has_key ? (
                      <label className="row small muted" style={{ gap: 5 }}>
                        <input type="checkbox" checked={draft.clear_key}
                          onChange={(e) => updateDraft({ clear_key: e.target.checked })} />
                        清掉已存的密钥
                      </label>
                    ) : null}
                  </div>
                ) : null}

                <div className="field">
                  <label><Cpu size={11} /> 当前模型</label>
                  <input className="input" list="llm-model-catalog" value={draft.model}
                    onChange={(e) => {
                      const model = e.target.value;
                      updateDraft({
                        model,
                        models: [...new Set([model, ...draft.models])],
                      });
                    }}
                    placeholder={provider?.default_model || "手动输入模型名"} />
                  <datalist id="llm-model-catalog">
                    {[...new Set([...catalog, ...(provider?.known_models || []), ...draft.models])]
                      .map((model) => <option key={model} value={model} />)}
                  </datalist>
                </div>

                <div className="form-row">
                  <div className="field">
                    <label>思考</label>
                    <select className="select" value={draft.think}
                      onChange={(e) => updateDraft({ think: e.target.value as Draft["think"] })}>
                      <option value="">不发送字段</option>
                      <option value="true">开启</option>
                      <option value="false">关闭</option>
                    </select>
                  </div>
                  <div className="field">
                    <label>上下文预算</label>
                    <input className="input" type="number" min={0} value={draft.num_ctx}
                      onChange={(e) => updateDraft({ num_ctx: e.target.value })}
                      placeholder={provider?.context_window ? `模型默认 ${provider.context_window}` : "模型默认"} />
                  </div>
                </div>

                <div className="field">
                  <label>备注</label>
                  <input className="input" value={draft.note}
                    onChange={(e) => updateDraft({ note: e.target.value })} />
                </div>

                <div className="row wrap" style={{ gap: 6 }}>
                  <button className="btn btn-primary" disabled={!!busy} onClick={() => void save(true)}>
                    <RefreshCw size={12} /> 保存并拉取清单
                  </button>
                  <button className="btn" disabled={!!busy} onClick={() => void save(false)}>只保存</button>
                </div>

                {catalog.length ? (
                  <div className="settings-models">
                    <div className="rail-label" style={{ paddingLeft: 0 }}>模型清单</div>
                    {catalog.map((model) => (
                      <label className="settings-model-row" key={model}>
                        <input type="checkbox" checked={draft.models.includes(model)}
                          disabled={model === draft.model}
                          onChange={() => toggleModel(model)} />
                        <span>{model}</span>
                        {model === draft.model ? <span className="chip teal">正在用</span> : null}
                      </label>
                    ))}
                    <button className="btn btn-xs" disabled={!!busy} onClick={() => void saveModels()}>
                      保存勾选
                    </button>
                  </div>
                ) : null}
                {catalogNote ? <div className="small muted">{catalogNote}</div> : null}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="settings-form">
            <div className="panel-flat panel-body" style={{ marginBottom: 10 }}>
              <div className="eyebrow" style={{ marginBottom: 4 }}>可选语言包</div>
              <p className="small muted" style={{ marginBottom: 8 }}>
                Java 与 C/C++ 的语言服务器体积较大，默认不打进安装包。勾选后按需下载到本机，下载完重新打开项目即可重建索引。
              </p>
              {packs.map((pack) => {
                const chosen = selectedPacks.includes(pack.id);
                const running = pack.state === "installing";
                return (
                  <div className="row" key={pack.id} style={{ alignItems: "center", gap: 8, marginBottom: 6 }}>
                    <label className="settings-model-row grow" style={{ margin: 0 }}>
                      <input type="checkbox"
                        checked={pack.installed || running || chosen}
                        disabled={pack.installed || running}
                        onChange={() => togglePack(pack.id)} />
                      <span>{pack.label}</span>
                      <span className="small muted">{pack.requires}</span>
                    </label>
                    {pack.installed ? <span className="chip teal">已安装</span> : null}
                    {running ? <span className="chip amber">下载中 {pack.percent}%</span> : null}
                    {pack.state === "failed" ? <span className="chip amber">失败</span> : null}
                    {pack.installed ? (
                      <button className="btn btn-xs" onClick={() => void removePack(pack.id)}>删除</button>
                    ) : null}
                  </div>
                );
              })}
              {installing ? (
                <div className="small muted">
                  {packs.find((item) => item.state === "installing")?.message || "正在下载…"}
                </div>
              ) : null}
              {packs.filter((item) => item.state === "failed").map((item) => (
                <div className="notice bad" key={`${item.id}-fail`}>{item.label}：{item.message}</div>
              ))}
              <div className="row" style={{ justifyContent: "flex-end", marginTop: 6 }}>
                <button className="btn btn-primary"
                  disabled={!selectedPacks.length || installing}
                  onClick={() => void downloadPacks()}>
                  <Plus size={12} /> 下载勾选的语言包
                </button>
              </div>
            </div>
            <div className="panel-flat panel-body">
              <div className="eyebrow" style={{ marginBottom: 4 }}>Language servers</div>
              <p className="small muted" style={{ marginBottom: 8 }}>
                留空自动检测 PATH；已有服务器会直接复用。
              </p>
              <div className="row wrap" style={{ gap: 5, marginBottom: 8 }}>
                {(base?.languages || []).map((lang) => (
                  <span className={`chip ${lang.available ? "teal" : "amber"}`} key={lang.id}>
                    {lang.label} · {lang.files}{lang.available ? "" : " · 未检测到"}
                  </span>
                ))}
              </div>
              {[
                ["python", "Python", "node …/pyright/langserver.index.js --stdio"],
                ["typescript", "TypeScript / JavaScript", "typescript-language-server --stdio"],
                ["go", "Go", "gopls serve"],
                ["java", "Java", "语言包装好后自动填入；也可在此覆盖"],
                ["cpp", "C / C++", "clangd"],
              ].map(([id, label, placeholder]) => (
                <div className="field" key={id}>
                  <label>{label}</label>
                  <input className="input" value={languageServers[id] || ""}
                    onChange={(e) => setLanguageServers((current) => ({
                      ...current, [id]: e.target.value,
                    }))}
                    placeholder={placeholder} />
                </div>
              ))}
              <div className="row" style={{ justifyContent: "flex-end" }}>
                <button className="btn btn-primary" disabled={!!busy}
                  onClick={() => void saveLanguageServers()}>
                  <Check size={12} /> 保存语言服务器
                </button>
              </div>
            </div>
          </div>
        )}

        {error ? <div className="notice bad">{error}</div> : null}
        {message ? <div className="notice info">{message}</div> : null}
        {busy ? <div className="small muted">{busy}</div> : null}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn btn-ghost" onClick={onClose}>关闭</button>
        </div>
      </div>
    </div>
  );
}
