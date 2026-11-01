import {useEffect, useRef, useState} from "react";
import {ApiError} from "../api/client";
export function useAction() {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null), mounted = useRef(true);
  useEffect(() => {mounted.current = true; return () => {mounted.current = false; controller.current?.abort();};}, []);
  async function perform<T>(operation: (signal: AbortSignal) => Promise<T>): Promise<T | undefined> {
    if (controller.current) return;
    const request = new AbortController(); controller.current = request; setBusy(true); setError("");
    try {const result = await operation(request.signal); return mounted.current && !request.signal.aborted ? result : undefined;}
    catch (error) {if (mounted.current) setError(error instanceof ApiError ? `${error.message}${error.code !== "REQUEST_FAILED" ? ` (${error.code})` : ""}` : "网络请求未完成，请检查连接后重试。");}
    finally {controller.current = null; if (mounted.current) setBusy(false);}
  }
  return {busy, error, perform};
}
