import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import LanguagePicker from "./LanguagePicker";
type Credential = { configured: boolean; revision: number };
type CheckState = {
  state: string;
  inference_verified: boolean;
  reachable?: boolean | null;
  credentials_valid?: boolean | null;
  limits?: { max_duration_seconds?: number };
  capabilities?: { coverage?: string };
  checked_at?: string;
};
type Settings = {
  credentials: Record<string, Credential>;
  providers: Record<
    string,
    {
      revision: number;
      adapter?: string;
      model?: string;
      endpoint?: string;
      space_id?: string;
      credential_ref?: string | null;
      controls?: Record<string, unknown>;
      check_state?: CheckState;
    }
  >;
};
const services = [
  {
    slot: "separation",
    name: "背景分离",
    desc: "将人声与背景声音分开",
    adapter: "demucs",
    space_id: "kajise/Demucs_v4-FT_2s",
    endpoint: "https://kajise-demucs-v4-ft-2s.hf.space",
    model: "htdemucs_ft",
    credential_ref: null,
  },
  {
    slot: "transcription",
    name: "识别与角色",
    desc: "识别说话内容和角色",
    adapter: "nvidia_stream",
    space_id: "nvidia/nemotron-diarization",
    endpoint: "https://nvidia-nemotron-diarization.hf.space",
    model: "nemotron-diarization",
    credential_ref: null,
  },
  {
    slot: "translation",
    name: "翻译",
    desc: "翻译分段内容",
    adapter: "hf_router",
    endpoint: "https://router.huggingface.co/v1",
    model: "",
    credential_ref: "huggingface",
  },
  {
    slot: "synthesis",
    name: "声音克隆",
    desc: "根据参考音频生成配音",
    adapter: "omnivoice",
    space_id: "k2-fsa/OmniVoice",
    endpoint: "https://k2-fsa-omnivoice.hf.space",
    model: "OmniVoice",
    credential_ref: "huggingface",
  },
  {
    slot: "verification",
    name: "配音复核",
    desc: "检查配音与文本",
    adapter: "hf_router",
    endpoint: "https://router.huggingface.co/v1",
    model: "openai/whisper-large-v3",
    credential_ref: "huggingface",
  },
] as const;
export default function ServiceSetup({
  csrf,
  logout,
}: {
  csrf: string;
  logout: () => void;
}) {
  const [settings, setSettings] = useState<Settings | null>(null),
    [token, setToken] = useState(""),
    [pending, setPending] = useState(false),
    [error, setError] = useState(""),
    [errorTarget, setErrorTarget] = useState(""),
    [invalid, setInvalid] = useState(false),
    [notice, setNotice] = useState(""),
    [showLanguages, setShowLanguages] = useState(false),
    [sourceLanguage, setSourceLanguage] = useState("auto"),
    [targetLanguage, setTargetLanguage] = useState("");
  async function load() {
    try {
      setSettings(await api<Settings>("/provider-settings", {}, csrf));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  }
  useEffect(() => {
    void load();
  }, []);
  async function saveToken(e: FormEvent, clear = false) {
    e.preventDefault();
    if (!settings) return;
    setPending(true);
    setError("");
    setErrorTarget("");
    setInvalid(false);
    try {
      const credential = await api<Credential>(
        "/credentials/huggingface",
        {
          method: "PUT",
          body: JSON.stringify({
            revision: settings.credentials.huggingface.revision,
            ...(clear ? { clear: true } : { token }),
          }),
        },
        csrf,
      );
      setToken("");
      setSettings({
        ...settings,
        credentials: { ...settings.credentials, huggingface: credential },
      });
      setNotice(clear ? "令牌已清除。" : "令牌已安全保存。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
      setErrorTarget("credential");
      setInvalid(e instanceof ApiError && [400, 422].includes(e.status));
    } finally {
      setPending(false);
    }
  }
  async function saveService(
    s: (typeof services)[number],
    edited?: {
      endpoint: string;
      model: string;
      adapter?: string;
      space_id?: string;
      credential_ref?: string | null;
    },
  ) {
    if (!settings) return;
    setPending(true);
    setError("");
    setErrorTarget("");
    setInvalid(false);
    try {
      const current = settings.providers[s.slot];
      const saved = await api<Settings["providers"][string]>(
        "/providers/" + s.slot,
        {
          method: "PUT",
          body: JSON.stringify({
            adapter: edited?.adapter ?? s.adapter,
            endpoint: edited?.endpoint ?? s.endpoint,
            space_id:
              edited?.space_id ?? ("space_id" in s ? s.space_id : undefined),
            model: edited?.model ?? s.model,
            credential_ref:
              edited && "credential_ref" in edited
                ? edited.credential_ref
                : edited?.adapter === "openai_compatible"
                  ? "translation"
                  : s.credential_ref,
            revision: current?.revision ?? 0,
            controls: edited ? (current?.controls ?? {}) : {},
          }),
        },
        csrf,
      );
      setSettings({
        ...settings,
        providers: { ...settings.providers, [s.slot]: saved },
      });
      setNotice(s.name + "设置已保存。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
      setErrorTarget(s.slot);
      setInvalid(e instanceof ApiError && [400, 422].includes(e.status));
    } finally {
      setPending(false);
    }
  }
  async function checkService(slot: string) {
    if (!settings) return;
    const current = settings.providers[slot];
    if (!current?.revision) return;
    setPending(true);
    setError("");
    setErrorTarget("");
    setInvalid(false);
    try {
      const check = await api<CheckState>(
        "/providers/" + slot + "/check",
        {
          method: "POST",
          body: JSON.stringify({ revision: current.revision }),
        },
        csrf,
      );
      setSettings({
        ...settings,
        providers: {
          ...settings.providers,
          [slot]: { ...current, check_state: check },
        },
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "检查失败");
      setErrorTarget(slot);
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <header>
        <span className="brand">◼ VIDEO TRANSLATE</span>
        <button className="link" onClick={logout}>
          退出登录
        </button>
      </header>
      <main className="workspace">
        <aside>
          <span className="eyebrow">WORKSPACE</span>
          <strong>工作空间</strong>
          <div className="nav-active">服务配置</div>
        </aside>
        <div className="content">
          <div className="page-head">
            <div>
              <span className="eyebrow">SETUP / 01</span>
              <h1>配置云端服务</h1>
              <p className="muted">连接服务，为后续翻译与配音做好准备。</p>
            </div>
            <span className="pill">配置阶段</span>
          </div>
          {error && (
            <p id="setup-error" role="alert" className="error">
              {error}
            </p>
          )}
          {notice && (
            <p role="status" className="notice">
              {notice}
            </p>
          )}
          {!settings ? (
            <p>正在加载设置…</p>
          ) : (
            <>
              <section className="credential">
                <div>
                  <span className="eyebrow">SHARED CREDENTIAL</span>
                  <h2>Hugging Face 令牌</h2>
                  <p className="muted">
                    用于需要认证的服务。令牌会加密保存，保存后不会再次显示。{" "}
                    <a
                      href="https://huggingface.co/settings/tokens"
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      管理 Hugging Face 令牌
                    </a>
                  </p>
                  <span className="status">
                    {settings.credentials.huggingface.configured
                      ? "已配置"
                      : "尚未配置"}
                  </span>
                </div>
                <form onSubmit={(e) => void saveToken(e)}>
                  <label>
                    Hugging Face 访问令牌
                    <input
                      aria-invalid={
                        (errorTarget === "credential" && invalid) || undefined
                      }
                      aria-describedby={
                        errorTarget === "credential" ? "setup-error" : undefined
                      }
                      type="password"
                      autoComplete="off"
                      value={token}
                      onChange={(e) => setToken(e.target.value)}
                    />
                  </label>
                  <div className="actions">
                    <button disabled={pending || !token.trim()}>
                      保存令牌
                    </button>
                    {settings.credentials.huggingface.configured && (
                      <button
                        type="button"
                        className="secondary"
                        disabled={pending}
                        onClick={(e) => void saveToken(e, true)}
                      >
                        清除令牌
                      </button>
                    )}
                  </div>
                </form>
              </section>
              <CustomCredential
                csrf={csrf}
                current={settings.credentials.translation}
                onSaved={(credential) =>
                  setSettings((previous) =>
                    previous
                      ? {
                          ...previous,
                          credentials: {
                            ...previous.credentials,
                            translation: credential,
                          },
                        }
                      : previous,
                  )
                }
              />
              <div className="section-head">
                <div>
                  <span className="eyebrow">SERVICE CONNECTIONS</span>
                  <h2>服务连接</h2>
                </div>
                <p>配置不会启动推理</p>
              </div>
              <div className="services">
                {services.map((s, i) => (
                  <ServiceCard
                    key={s.slot}
                    service={s}
                    index={i}
                    current={settings.providers[s.slot]}
                    pending={pending}
                    fieldError={errorTarget === s.slot}
                    invalid={invalid}
                    save={(edited) => void saveService(s, edited)}
                    check={() => void checkService(s.slot)}
                  />
                ))}
              </div>
              <details
                className="catalog"
                onToggle={(event) => setShowLanguages(event.currentTarget.open)}
              >
                <summary>浏览语言目录</summary>
                <p>合成语言目录与各服务覆盖范围分别计算，真实流程尚未验证。</p>
                {showLanguages && (
                  <>
                    <h3>源语言</h3>
                    <LanguagePicker
                      target={false}
                      value={sourceLanguage}
                      onChange={setSourceLanguage}
                    />
                    <h3>目标语言</h3>
                    <LanguagePicker
                      target
                      value={targetLanguage}
                      onChange={setTargetLanguage}
                    />
                  </>
                )}
              </details>
              <p className="footnote">
                语言目录表示合成模型的声明范围，并不代表所有语言均已通过完整流程验证。
              </p>
            </>
          )}
        </div>
      </main>
    </>
  );
}

function ServiceCard({
  service,
  index,
  current,
  pending,
  fieldError,
  invalid,
  save,
  check,
}: {
  service: (typeof services)[number];
  index: number;
  current: Settings["providers"][string] | undefined;
  pending: boolean;
  fieldError: boolean;
  invalid: boolean;
  save: (edited?: {
    endpoint: string;
    model: string;
    adapter?: string;
    space_id?: string;
    credential_ref?: string | null;
  }) => void;
  check: () => void;
}) {
  const [endpoint, setEndpoint] = useState(
      current?.endpoint ?? service.endpoint,
    ),
    [model, setModel] = useState(current?.model ?? service.model),
    [adapter, setAdapter] = useState(current?.adapter ?? service.adapter),
    [spaceId, setSpaceId] = useState(
      current?.space_id ?? ("space_id" in service ? service.space_id : ""),
    ),
    [credentialRef, setCredentialRef] = useState(
      current?.credential_ref === null
        ? ""
        : (current?.credential_ref ?? service.credential_ref ?? ""),
    );
  return (
    <section className="service">
      <span className="number">0{index + 1}</span>
      <div className="service-info">
        <h3>{service.name}</h3>
        <p>{service.desc}</p>
        <small>
          {current?.revision ? "设置已保存" : "尚未保存设置"} · 实际推理未验证
        </small>
        {current?.check_state && (
          <p role="status">
            {(
              {
                credential_required: "需要配置令牌",
                configuration_required: "需要配置端点或模型",
                reachable: "服务可连接",
                auth: "账号验证失败",
                quota: "服务额度不足或受限",
                network: "网络检查失败",
                configuration: "服务配置无效",
                check_failed: "服务检查未完成",
              } as Record<string, string>
            )[current.check_state.state] ?? "检查未完成"}
          </p>
        )}
        {current?.check_state?.credentials_valid === true && (
          <p>账号验证通过；实际推理权限未验证。</p>
        )}
        {current?.check_state?.credentials_valid === false && (
          <p>账号验证失败，请检查令牌。</p>
        )}
        {current?.check_state?.limits?.max_duration_seconds && (
          <p>
            文件时长上限：{current.check_state.limits.max_duration_seconds} 秒
          </p>
        )}
      </div>
      <div className="actions">
        <button className="secondary" disabled={pending} onClick={() => save()}>
          保存默认设置
        </button>
        <button
          className="secondary"
          disabled={pending || !current?.revision}
          onClick={check}
        >
          检查{service.name}
        </button>
      </div>
      <details>
        <summary>查看连接信息</summary>
        {service.slot === "translation" ? (
          <label>
            翻译服务类型
            <select
              aria-invalid={(fieldError && invalid) || undefined}
              aria-describedby={fieldError ? "setup-error" : undefined}
              value={adapter}
              onChange={(e) => {
                setAdapter(e.target.value);
                setCredentialRef(
                  e.target.value === "openai_compatible"
                    ? "translation"
                    : "huggingface",
                );
              }}
            >
              <option value="hf_router">Hugging Face Router</option>
              <option value="openai_compatible">自定义 OpenAI 兼容服务</option>
            </select>
          </label>
        ) : (
          <p>服务：{service.adapter}</p>
        )}
        {"space_id" in service && (
          <p>
            <a
              href={
                "https://huggingface.co/spaces/" +
                encodeURIComponent(service.space_id.split("/")[0]) +
                "/" +
                encodeURIComponent(service.space_id.split("/")[1])
              }
              target="_blank"
              rel="noreferrer noopener"
            >
              查看服务来源
            </a>
          </p>
        )}
        {service.slot === "synthesis" && spaceId === "k2-fsa/OmniVoice" && (
          <div>
            <p>预训练模型许可：CC-BY-NC（非商业用途）。</p>
            <p>上游代码许可：Apache-2.0。</p>
            <p>
              <a
                href="https://huggingface.co/k2-fsa/OmniVoice#license"
                target="_blank"
                rel="noreferrer noopener"
              >
                查看模型许可
              </a>
            </p>
          </div>
        )}
        {"space_id" in service && (
          <label>
            {service.name} Space ID
            <input
              aria-invalid={(fieldError && invalid) || undefined}
              aria-describedby={fieldError ? "setup-error" : undefined}
              readOnly={service.slot === "transcription"}
              value={spaceId}
              onChange={(e) => setSpaceId(e.target.value)}
            />
          </label>
        )}
        {service.slot === "translation" && adapter === "openai_compatible" && (
          <label>
            翻译服务凭据
            <select
              aria-invalid={(fieldError && invalid) || undefined}
              aria-describedby={fieldError ? "setup-error" : undefined}
              value={credentialRef || "none"}
              onChange={(e) =>
                setCredentialRef(
                  e.target.value === "none" ? "" : e.target.value,
                )
              }
            >
              <option value="translation">自定义翻译令牌</option>
              <option value="none">无需令牌</option>
            </select>
          </label>
        )}
        {service.slot === "synthesis" && (
          <label>
            声音克隆凭据
            <select
              aria-invalid={(fieldError && invalid) || undefined}
              aria-describedby={fieldError ? "setup-error" : undefined}
              value={credentialRef}
              onChange={(e) => setCredentialRef(e.target.value)}
            >
              <option value="huggingface">Hugging Face 令牌</option>
              <option value="">公开演示，无令牌</option>
            </select>
          </label>
        )}
        <label>
          {service.name}端点
          <input
            aria-invalid={(fieldError && invalid) || undefined}
            aria-describedby={fieldError ? "setup-error" : undefined}
            readOnly={service.slot === "transcription"}
            value={endpoint}
            onChange={(e) => setEndpoint(e.target.value)}
          />
        </label>
        <label>
          {service.name}模型
          <input
            readOnly={["separation", "transcription", "synthesis"].includes(
              service.slot,
            )}
            aria-invalid={(fieldError && invalid) || undefined}
            aria-describedby={fieldError ? "setup-error" : undefined}
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="secondary"
          disabled={pending}
          onClick={() =>
            save({
              endpoint,
              model,
              adapter,
              space_id: "space_id" in service ? spaceId : undefined,
              ...(service.slot === "synthesis" ||
              (service.slot === "translation" &&
                adapter === "openai_compatible")
                ? { credential_ref: credentialRef || null }
                : {}),
            })
          }
        >
          保存{service.name}设置
        </button>
      </details>
    </section>
  );
}

function CustomCredential({
  csrf,
  current,
  onSaved,
}: {
  csrf: string;
  current: Credential;
  onSaved: (value: Credential) => void;
}) {
  const [token, setToken] = useState(""),
    [pending, setPending] = useState(false),
    [error, setError] = useState(""),
    [invalid, setInvalid] = useState(false);
  async function save(e: FormEvent, clear = false) {
    e.preventDefault();
    setPending(true);
    setError("");
    setInvalid(false);
    try {
      const result = await api<Credential>(
        "/credentials/translation",
        {
          method: "PUT",
          body: JSON.stringify({
            revision: current.revision,
            ...(clear ? { clear: true } : { token }),
          }),
        },
        csrf,
      );
      setToken("");
      onSaved(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
      setInvalid(e instanceof ApiError && [400, 422].includes(e.status));
    } finally {
      setPending(false);
    }
  }
  return (
    <details className="custom-credential">
      <summary>自定义翻译服务凭据</summary>
      <p>仅用于管理员允许的自定义 OpenAI 兼容服务。</p>
      <p>{current.configured ? "已配置" : "尚未配置"}</p>
      <form onSubmit={(e) => void save(e)}>
        <label>
          自定义翻译访问令牌
          <input
            aria-invalid={invalid || undefined}
            aria-describedby={
              error ? "translation-credential-error" : undefined
            }
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </label>
        <div className="actions">
          <button disabled={pending || !token.trim()}>保存自定义令牌</button>
          {current.configured && (
            <button
              type="button"
              className="secondary"
              disabled={pending}
              onClick={(e) => void save(e, true)}
            >
              清除自定义令牌
            </button>
          )}
        </div>
      </form>
      {error && (
        <p id="translation-credential-error" role="alert" className="error">
          {error}
        </p>
      )}
    </details>
  );
}
