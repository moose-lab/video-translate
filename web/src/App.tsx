import { useEffect, useState } from "react";
import { api } from "./api/client";
import AuthPage, { type Identity } from "./auth/AuthPage";
import ServiceSetup from "./settings/ServiceSetup";
export default function App() {
  const [identity, setIdentity] = useState<Identity | null>(null),
    [loading, setLoading] = useState(true);
  useEffect(() => {
    void api<Identity>("/auth/me")
      .then(setIdentity)
      .catch(() => setIdentity(null))
      .finally(() => setLoading(false));
    const expired = () => setIdentity(null);
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  async function logout() {
    if (!identity) return;
    try {
      await api("/auth/logout", { method: "POST" }, identity.csrf_token);
    } finally {
      setIdentity(null);
    }
  }
  if (loading) return <main className="loading">正在加载工作空间…</main>;
  return identity ? (
    <ServiceSetup csrf={identity.csrf_token} logout={() => void logout()} />
  ) : (
    <AuthPage onAuth={setIdentity} />
  );
}
