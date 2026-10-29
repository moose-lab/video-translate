import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
export type Identity = {
  csrf_token: string;
  user: { name: string };
  workspace: { name: string };
};
export default function AuthPage({
  onAuth,
}: {
  onAuth: (user: Identity) => void;
}) {
  const [register, setRegister] = useState(false),
    [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [name, setName] = useState(""),
    [error, setError] = useState(""),
    [invalid, setInvalid] = useState(false),
    [pending, setPending] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError("");
    setInvalid(false);
    try {
      const result = await api<Identity>(
        `/auth/${register ? "register" : "login"}`,
        {
          method: "POST",
          body: JSON.stringify(
            register ? { name, email, password } : { email, password },
          ),
        },
      );
      setPassword("");
      onAuth(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作未完成");
      setInvalid(e instanceof ApiError && [400, 401, 422].includes(e.status));
    } finally {
      setPending(false);
    }
  }
  return (
    <main className="auth">
      <div className="auth-intro">
        <span className="brand">◼ VIDEO TRANSLATE</span>
        <h1>
          让声音，
          <br />
          跨越语言。
        </h1>
        <p>在一个工作空间里，管理视频翻译与配音服务。</p>
      </div>
      <section className="auth-box">
        <p className="eyebrow">WELCOME</p>
        <h2>{register ? "创建工作空间" : "欢迎回来"}</h2>
        <p className="muted">
          {register
            ? "注册后即可配置你的云端服务。"
            : "登录以继续配置你的工作空间。"}
        </p>
        <form onSubmit={submit}>
          {register && (
            <label>
              名称
              <input
                required
                aria-invalid={invalid || undefined}
                aria-describedby={error ? "auth-error" : undefined}
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="name"
              />
            </label>
          )}
          <label>
            邮箱
            <input
              aria-invalid={invalid || undefined}
              aria-describedby={error ? "auth-error" : undefined}
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />
          </label>
          <label>
            密码
            <input
              aria-invalid={invalid || undefined}
              aria-describedby={error ? "auth-error" : undefined}
              type="password"
              required
              minLength={10}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={register ? "new-password" : "current-password"}
            />
          </label>
          {error && (
            <p id="auth-error" role="alert" className="error">
              {error}
            </p>
          )}
          <button disabled={pending}>
            {pending ? "处理中…" : register ? "创建账号" : "登录"}
          </button>
        </form>
        <button
          className="link"
          onClick={() => {
            setRegister(!register);
            setError("");
          }}
        >
          {register ? "已有账号？登录" : "还没有账号？创建账号"}
        </button>
      </section>
    </main>
  );
}
