import type {TranslationCommand} from "./targetTypes";
import {phaseName} from "./targetTypes";
import {seconds, statusName} from "./types";
export default function TranslationCommandPanel({command}: {command: TranslationCommand}) {
  return <div className="translation-command"><h3>当前翻译任务</h3><p role="status">{command.status === "incomplete" ? "需要检查后继续" : statusName(command.status)}{command.next_action === "acknowledge_uncertain_submission" ? " · 提交结果未知，请在任务区核查" : command.next_action === "translation_review" ? " · 请人工核对译文" : ""}</p>
    <ol>{command.phases.map(phase => <li key={phase.id}>{phaseName(phase.phase)} · {statusName(phase.status)}</li>)}</ol>
    {command.skipped_ids.length > 0 && <p className="muted">保留了 {command.skipped_ids.length} 行已锁定或已确认的译文。</p>}
    {command.suggestions.length > 0 && <details><summary>查看精简建议（不会自动应用）</summary>{command.suggestions.map(suggestion => <div key={`${suggestion.phase_id}/${suggestion.segment_id}`} className="shorten-suggestion"><p dir="auto">{suggestion.text}</p><p className="muted">{suggestion.stale ? "建议已过期" : suggestion.applied ? "已应用" : "未应用"}{suggestion.estimated_duration_ms ? ` · 预计 ${seconds(suggestion.estimated_duration_ms)} 秒，非实测` : " · 时长未知"}</p></div>)}<p className="muted">请按需手动修改对应行并重新确认；此处不会覆盖原译文。</p></details>}
  </div>;
}
