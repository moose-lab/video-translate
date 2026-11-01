import {useState} from "react";
import {api} from "../api/client";
import {projectPath} from "../api/projects";
import type {Segment} from "./types";
import type {SourceGuard} from "./targetTypes";
import type {Speaker} from "./referenceTypes";
import {useAction} from "./useAction";
type Draft = SourceGuard & {revision: number; speaker_id: string | null};
export default function SourceRoleAssignment({projectId, csrf, source, row, index, roles, onChanged}: {projectId: string; csrf: string; source: SourceGuard; row: Segment; index: number; roles: Speaker[]; onChanged: () => void}) {
  const [draft, setDraft] = useState<Draft | null>(null), {busy, error, perform} = useAction();
  const value = draft?.speaker_id ?? (draft ? "" : row.speaker_id ?? ""), active = roles.filter(role => !role.archived);
  function edit(speaker: string) {if (row.revision) setDraft(previous => ({...(previous ?? {...source, revision: row.revision!}), speaker_id: speaker || null}));}
  async function save() {if (!draft) return; const result = await perform(signal => api(`${projectPath(projectId)}/segments/${encodeURIComponent(row.id)}`, {method: "PATCH", signal, body: JSON.stringify(draft)}, csrf)); if (result) {setDraft(null); onChanged();}}
  return <div className="source-role-assignment"><label>第 {index} 行角色<select value={value} disabled={busy || !row.revision} onChange={event => edit(event.target.value)}><option value="">未分配角色</option>{value && !active.some(role => role.id === value) && <option value={value}>当前角色（其他页）</option>}{active.map(role => <option key={role.id} value={role.id}>{role.name}</option>)}</select></label><div className="actions"><button className="secondary" disabled={busy || !draft} onClick={() => void save()}>保存第 {index} 行角色</button>{draft && <button className="link" disabled={busy} onClick={() => setDraft(null)}>放弃第 {index} 行角色修改</button>}</div>{error && <p className="error" role="alert">{error}</p>}</div>;
}
