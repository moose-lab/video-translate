import { useEffect, useState } from "react";
import { api } from "./api/client";
import AuthPage, { type Identity } from "./auth/AuthPage";
import ServiceSetup from "./settings/ServiceSetup";
import Workbench from "./workbench/Workbench";
export default function App() {
  const [identity, setIdentity] = useState<Identity | null>(null),
    [loading, setLoading] = useState(true),
    [services, setServices] = useState(window.location.hash === "#/services");
  useEffect(() => {
    let active = true;
    void api<Identity>("/auth/me")
      .then(value => { if (active) setIdentity(value); })
      .catch(() => { if (active) setIdentity(null); })
      .finally(() => setLoading(false));
    const expired = () => { active = false; setLoading(false); setIdentity(null); window.history.replaceState(null, "", "#/projects"); };
    const navigate = () => setServices(window.location.hash === "#/services");
    window.addEventListener("hashchange", navigate);
    window.addEventListener("session-expired", expired);
    return () => { active = false; window.removeEventListener("session-expired", expired); window.removeEventListener("hashchange", navigate); };
  }, []);
  async function logout() {
    if (!identity) return;
    const csrf = identity.csrf_token;
    setIdentity(null);
    window.history.replaceState(null, "", "#/projects");
    setServices(false);
    try { await api("/auth/logout", { method: "POST" }, csrf); }
    catch { /* Local state and project subscriptions have already been cleared. */ }
  }
  if (loading) return <main className="loading">正在加载工作空间…</main>;
  return identity ? (
    services ? <ServiceSetup csrf={identity.csrf_token} logout={() => void logout()} /> : <>
      <header className="app-header"><a className="brand" href="#/projects">◼ VIDEO TRANSLATE</a><nav aria-label="工作空间导航"><a href="#/projects" aria-current="page">项目</a><a href="#/services">服务配置</a><button className="link" onClick={() => void logout()}>退出登录</button></nav></header>
      <Workbench csrf={identity.csrf_token} />
    </>
  ) : (
    <AuthPage onAuth={setIdentity} />
  );
}
