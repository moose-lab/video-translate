import {useState} from "react";
import {rateValue, purposeName, type FitDetail} from "./finishingTypes";
import {seconds, statusName} from "./types";
const issueName = (code: string) => ({FIT_CAPTURE_INVALID: "方案输入校验失败", FIT_PLAN_INVALID: "拟合方案校验失败", FIT_INPUT_CHANGED: "方案输入已变化", FIT_COMPUTATION_FAILED: "拟合计算失败", LINE_FIT_LIMIT: "有台词超出拟合上限", OUTPUT_DURATION_LIMIT: "输出时长超出限制", NATURAL_AUDIO_STALE: "自然音频已过期", LISTENING_NOT_ASSESSED: "有音频尚未听审", LISTENING_REJECTED: "有音频已被拒绝", LISTENING_STALE: "有听审已过期", QC_MANUAL_REVIEW: "语音识别存在需人工核对的差异", QC_UNASSESSED: "有音频尚未质检", QC_FAILED: "有音频质检失败", QC_ACKNOWLEDGEMENT_REQUIRED: "质检风险尚未确认"}[code] ?? "存在其他待检查项");
export default function FitPlanView({plan}: {plan: FitDetail}) {
  const [offset, setOffset] = useState(0), output = rateValue(plan.planned_output_duration_ms), pieces = plan.plan?.pieces ?? [];
  return <div className="fit-plan-view"><h3>拟合方案 · {purposeName(plan.purpose)}</h3><p role="status">{statusName(plan.status)} · {plan.current ? "输入仍为当前版本" : "输入已变化"}{plan.timeline_feasible === false ? " · 当前时间安排不可行" : ""}</p>
    {plan.plan && <p className="muted">源片段 {seconds(plan.plan.source_duration_ms)} 秒；拟合输出 {output === null ? "时长未知" : `${seconds(output)} 秒`}。{plan.dub_ready ? "正式配音听审已就绪。" : "此方案尚未达到正式配音听审条件。"}</p>}
    {plan.issues.length > 0 && <ul className="fit-issues">{plan.issues.map((code, index) => <li key={`${code}/${index}`}>{issueName(code)}</li>)}</ul>}
    {pieces.length > 0 && <details><summary>查看共享画面时间安排（{pieces.length} 段）</summary><div className="table-scroll"><table><thead><tr><th>源片段时间（秒）</th><th>输出时间（秒）</th></tr></thead><tbody>{pieces.slice(offset, offset + 100).map((piece, index) => <tr key={offset + index}><td>{seconds(piece.source_start_ms)}–{seconds(piece.source_end_ms)}</td><td>{seconds(rateValue(piece.output_start_ms)!)}–{seconds(rateValue(piece.output_end_ms)!)}</td></tr>)}</tbody></table></div>{pieces.length > 100 && <nav className="actions pagination" aria-label="拟合时间安排分页"><button className="secondary" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 100))}>上一页时间段</button><button className="secondary" disabled={offset + 100 >= pieces.length} onClick={() => setOffset(offset + 100)}>下一页时间段</button></nav>}</details>}
    <p className="muted">读取方案条目 {plan.lines.length} / {plan.total}；输出文件会沿用此方案的用途与时间安排。</p>
  </div>;
}
