import {useEffect, useState} from "react";
import type {LanguageTrack} from "./targetTypes";
import {sourceGuard} from "./targetTypes";
import type {Timeline} from "./types";
import TargetContextEditor from "./TargetContextEditor";
import SubtitleImportPanel from "./SubtitleImportPanel";
export default function TargetTextTools({projectId, csrf, track, timeline, refreshVersion, onSaved, onDirty}: {projectId: string; csrf: string; track: LanguageTrack; timeline: Timeline; refreshVersion: number; onSaved: () => void; onDirty: (value: boolean) => void}) {
  const [open, setOpen] = useState(false), [visited, setVisited] = useState(false), [contextDirty, setContextDirty] = useState(false), [importDirty, setImportDirty] = useState(false), guard = sourceGuard(timeline);
  useEffect(() => {onDirty(contextDirty || importDirty);}, [contextDirty, importDirty, onDirty]);
  return <div className="target-text-tools"><button className="link" aria-expanded={open} onClick={() => {setVisited(true); setOpen(!open);}}>{open ? "收起上下文与导入" : "上下文、术语与译文导入"}</button><div hidden={!open}>{visited && <><TargetContextEditor projectId={projectId} csrf={csrf} track={track} refreshVersion={refreshVersion} onSaved={onSaved} onDirty={setContextDirty} />{guard && <SubtitleImportPanel projectId={projectId} csrf={csrf} guard={guard} tag={track.tag} roles={[]} onSaved={onSaved} onDirty={setImportDirty} />}</>}</div></div>;
}
