import {useEffect, useState} from "react";
import {api, ApiError} from "../api/client";
import {targetPath} from "./targetTypes";
import type {AudioPage} from "./audioTypes";
export function useTargetAudio(id: string, tag: string, offset: number, version: number, enabled: boolean) {
  const [snapshot, setSnapshot] = useState<{tag: string; page: AudioPage} | null>(null), [error, setError] = useState("");
  useEffect(() => {
    if (!enabled) return;
    let active = true; const controller = new AbortController();
    api<AudioPage>(`${targetPath(id, tag)}/synthesis?limit=50&offset=${offset}`, {signal: controller.signal}).then(page => {if (active) {setSnapshot({tag, page}); setError("");}}).catch(error => {if (active) setError(error instanceof ApiError ? error.message : "配音状态加载失败，请刷新重试。");});
    return () => {active = false; controller.abort();};
  }, [id, tag, offset, version, enabled]);
  return {audio: enabled && snapshot?.tag === tag ? snapshot.page : null, error};
}
