import {useCallback, useEffect, useState} from "react";
import {api} from "../api/client";
import {projectPath, projectsApi, type Page, type Project} from "../api/projects";
import {subscribeProjectEvents} from "./projectEvents";
import type {ProviderRequirements, Run, SourceWorkflow, Timeline} from "./types";
export function useProjectData(id: string, offset: number, runOffset: number) {
  const [project, setProject] = useState<Project | null>(null), [timeline, setTimeline] = useState<Timeline | null>(null), [runs, setRuns] = useState<Page<Run>>({items: [], total: 0});
  const [providers, setProviders] = useState<ProviderRequirements | null>(null), [error, setError] = useState("");
  const [updating, setUpdating] = useState(false), [version, setVersion] = useState(0), [connection, setConnection] = useState("正在连接"), [eventSequence, setEventSequence] = useState(0);
  const [workflowId, setWorkflowId] = useState<string | null>(null), [workflow, setWorkflow] = useState<SourceWorkflow | null>(null);
  const refresh = useCallback(() => setVersion(value => value + 1), []);
  useEffect(() => subscribeProjectEvents(id, {onChange: refresh, onState: setConnection, onEvent: event => {setEventSequence(event.sequence); const workflow = event.facts?.workflow_id; if (typeof workflow === "string" && /^[A-Za-z0-9-]{1,36}$/.test(workflow)) setWorkflowId(workflow);}}), [id, refresh]);
  useEffect(() => {
    let active = true; const controller = new AbortController(), options = {signal: controller.signal};
    setUpdating(true);
    Promise.all([projectsApi.get(id, controller.signal), api<Timeline>(`${projectPath(id)}/timeline?limit=50&offset=${offset}`, options), api<Page<Run>>(`${projectPath(id)}/runs?limit=50&offset=${runOffset}`, options)])
      .then(([project, timeline, runs]) => {if (active) {setProject(project); setTimeline(timeline); setRuns(runs); setError("");}})
      .catch(error => {if (active) setError(error instanceof Error ? error.message : "项目数据加载失败");})
      .finally(() => {if (active) setUpdating(false);});
    return () => {active = false; controller.abort();};
  }, [id, offset, runOffset, version]);
  useEffect(() => {
    let active = true; const controller = new AbortController();
    api<ProviderRequirements>("/provider-settings", {signal: controller.signal}).then(value => {if (active) setProviders(value);}).catch(() => {});
    return () => {active = false; controller.abort();};
  }, [id]);
  useEffect(() => {
    if (!workflowId) return; let active = true; const controller = new AbortController();
    api<SourceWorkflow>(`${projectPath(id)}/workflow/${encodeURIComponent(workflowId)}`, {signal: controller.signal}).then(value => {if (active) setWorkflow(value);}).catch(() => {});
    return () => {active = false; controller.abort();};
  }, [id, workflowId, version]);
  return {project, timeline, runs, providers, error, updating, refresh, refreshVersion: version, connection, eventSequence, workflow, setWorkflow: (value: SourceWorkflow) => {setWorkflowId(value.id); setWorkflow(value);}};
}
