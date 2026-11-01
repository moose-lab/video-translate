import {useState} from "react";
import type {Segment} from "./types";
import {seconds} from "./types";
import type {SourceGuard} from "./targetTypes";
import type {Speaker, ReferenceVersion} from "./referenceTypes";
import SourceRoleAssignment from "./SourceRoleAssignment";
import ReferenceExtractForm from "./ReferenceExtractForm";
import ReferenceBindingEditor from "./ReferenceBindingEditor";
export default function ReferenceSourceRow({projectId, csrf, source, row, index, roles, references, sourceLanguage, refreshVersion, onChanged}: {projectId: string; csrf: string; source: SourceGuard; row: Segment; index: number; roles: Speaker[]; references: ReferenceVersion[]; sourceLanguage: string; refreshVersion: number; onChanged: () => void}) {
  const [open, setOpen] = useState(false);
  return <li className="reference-source-row"><p className="transcript-meta">第 {index} 行 · 原片 {seconds(row.absolute_start_ms)}–{seconds(row.absolute_end_ms)} 秒</p><p dir="auto">{row.text}</p><SourceRoleAssignment projectId={projectId} csrf={csrf} source={source} row={row} index={index} roles={roles} onChanged={onChanged} /><button className="link" aria-expanded={open} onClick={() => setOpen(!open)}>第 {index} 行参考音设置</button>{open && <><ReferenceExtractForm projectId={projectId} csrf={csrf} source={source} row={row} index={index} sourceLanguage={sourceLanguage} onChanged={onChanged} />{row.revision && <ReferenceBindingEditor projectId={projectId} csrf={csrf} source={source} kind="line" subjectId={row.id} subjectRevision={row.revision} speakerId={row.speaker_id} references={references} refreshVersion={refreshVersion} onChanged={onChanged} />}</>}</li>;
}
