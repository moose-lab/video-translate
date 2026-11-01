import {useState} from "react";
import RoleReferencePanel from "./RoleReferencePanel";
export default function RoleReferenceSection({projectId, csrf, sourceLanguage, refreshVersion, onChanged}: {projectId: string; csrf: string; sourceLanguage: string; refreshVersion: number; onChanged: () => void}) {
  const [open, setOpen] = useState(false), [visited, setVisited] = useState(false);
  return <section className="panel" aria-labelledby="roles-reference-title"><div className="section-head"><h2 id="roles-reference-title">角色与参考音</h2><button className="secondary" aria-expanded={open} aria-controls="roles-reference-content" onClick={() => {setVisited(true); setOpen(!open);}}>{open ? "收起角色与参考音" : "编辑角色与参考音"}</button></div><p className="muted">手动分配说话角色，从已选原片台词提取参考音，并设置角色默认或单行覆盖。</p><div id="roles-reference-content" hidden={!open}>{visited && <RoleReferencePanel projectId={projectId} csrf={csrf} sourceLanguage={sourceLanguage} refreshVersion={refreshVersion} onChanged={onChanged} />}</div></section>;
}
