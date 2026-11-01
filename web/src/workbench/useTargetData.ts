import {useEffect, useState} from "react";
import {api, ApiError} from "../api/client";
import {projectPath} from "../api/projects";
import type {Timeline} from "./types";
import type {TranslationCommand} from "./targetTypes";
import {targetPath} from "./targetTypes";
export function useTargetData(id: string, tag: string, offset: number, refreshVersion: number, commandId: string | null) {
  const [snapshot, setSnapshot] = useState<{tag: string; timeline: Timeline} | null>(null), [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [command, setCommand] = useState<TranslationCommand | null>(null), [commandError, setCommandError] = useState("");
  useEffect(() => {
    if (!tag) return;
    let active = true; const controller = new AbortController(); setLoading(true); setError("");
    const params = new URLSearchParams({target_language: tag, limit: "50", offset: String(offset)});
    api<Timeline>(`${projectPath(id)}/timeline?${params}`, {signal: controller.signal}).then(timeline => {if (active) setSnapshot({tag, timeline});}).catch(error => {if (active) setError(error instanceof ApiError ? error.message : "译文加载失败，请重试。");}).finally(() => {if (active) setLoading(false);});
    return () => {active = false; controller.abort();};
  }, [id, tag, offset, refreshVersion]);
  useEffect(() => {
    setCommand(null); setCommandError("");
    if (!commandId || !tag) return;
    let active = true; const controller = new AbortController();
    api<TranslationCommand>(`${targetPath(id, tag)}/translate/${encodeURIComponent(commandId)}`, {signal: controller.signal}).then(value => {if (active) setCommand(value);}).catch(error => {if (active) setCommandError(error instanceof ApiError ? error.message : "翻译任务详情暂时无法加载，请查看任务区。");});
    return () => {active = false; controller.abort();};
  }, [id, tag, commandId, refreshVersion]);
  return {timeline: snapshot?.tag === tag ? snapshot.timeline : null, loading, error, command, commandError};
}
