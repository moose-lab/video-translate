import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
type Credential = { configured: boolean; revision: number };
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
      check_state?: { state: string; inference_verified: boolean };
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
    endpoint: "https://api-inference.huggingface.co",
    model: "",
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
    [notice, setNotice] = useState("");
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
    } finally {
      setPending(false);
    }
  }
  async function saveService(
    s: (typeof services)[number],
    edited?: { endpoint: string; model: string },
  ) {
    if (!settings) return;
    setPending(true);
    setError("");
    try {
      const current = settings.providers[s.slot];
      const saved = await api<Settings["providers"][string]>(
        "/providers/" + s.slot,
        {
          method: "PUT",
          body: JSON.stringify({
            adapter: s.adapter,
            endpoint: edited?.endpoint ?? s.endpoint,
            space_id: "space_id" in s ? s.space_id : undefined,
            model: edited?.model ?? s.model,
            credential_ref: s.credential_ref,
            revision: current?.revision ?? 0,
            controls: {},
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
    try {
      const check = await api<{ state: string; inference_verified: boolean }>(
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
            <p role="alert" className="error">
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
                    用于需要认证的服务。令牌会加密保存，保存后不会再次显示。
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
                    save={(edited) => void saveService(s, edited)}
                    check={() => void checkService(s.slot)}
                  />
                ))}
              </div>
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
  save,
  check,
}: {
  service: (typeof services)[number];
  index: number;
  current: Settings["providers"][string] | undefined;
  pending: boolean;
  save: (edited?: { endpoint: string; model: string }) => void;
  check: () => void;
}) {
  const [endpoint, setEndpoint] = useState(
      current?.endpoint ?? service.endpoint,
    ),
    [model, setModel] = useState(current?.model ?? service.model);
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
            {current.check_state.state === "credential_required"
              ? "需要配置令牌"
              : current.check_state.state === "reachable"
                ? "服务可连接"
                : "检查未完成"}
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
        <p>服务：{service.adapter}</p>
        <label>
          {service.name}端点
          <input
            value={endpoint}
            onChange={(e) => setEndpoint(e.target.value)}
          />
        </label>
        <label>
          {service.name}模型
          <input value={model} onChange={(e) => setModel(e.target.value)} />
        </label>
        <button
          type="button"
          className="secondary"
          disabled={pending}
          onClick={() => save({ endpoint, model })}
        >
          保存{service.name}设置
        </button>
      </details>
    </section>
  );
}
