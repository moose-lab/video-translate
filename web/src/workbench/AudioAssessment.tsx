import type {NaturalOutput} from "./audioTypes";
import {seconds, statusName} from "./types";
export const qcStatusName = (status: string) => ({unassessed: "尚未质检", unconfigured: "质检服务未配置", unsupported: "质检不支持此语言", unknown: "质检语言支持未知", failed: "质检失败", succeeded: "质检已完成", stale: "质检已过期", needs_review: "质检需要检查"}[status] ?? `质检${statusName(status)}`);
export function AudioAssessment({output}: {output: NaturalOutput}) {
  const comparison = output.qc.comparison;
  return <><p className="muted">实测自然时长 {seconds(output.natural_duration_ms)} 秒 · 源台词窗口 {seconds(output.slot_duration_ms)} 秒{output.natural_duration_ms > output.slot_duration_ms ? " · 自然音频超出窗口" : ""}</p>
    <p>{output.stale ? "音频已过期" : output.ready ? "此行已具备交付条件" : "此行尚待检查"} · {output.acceptance === "accepted" ? "人工已接受" : output.acceptance === "rejected" ? "人工已拒绝" : output.acceptance === "stale" ? "听审已过期" : "尚未听审"}</p>
    <p className="muted">{qcStatusName(output.qc.status)}{output.evidence_status !== "validated" ? " · 音频来源证据需要检查" : ""}{output.qc_override ? " · 人工接受包含质检风险" : ""}</p>
    {comparison && <p className="muted">识别文字{comparison.text_match ? "匹配" : "存在差异"}{typeof comparison.character_error_rate === "number" ? ` · 字符错误率 ${(comparison.character_error_rate * 100).toFixed(1)}%` : ""}{comparison.reference_carryover.length ? " · 检测到参考音文字混入" : ""}{comparison.language_status === "mismatch" ? " · 检测语言不一致" : comparison.language_status === "not_reported" ? " · 未报告检测语言" : ""}</p>}
    {Object.keys(output.qc_risks).length > 0 && <p className="error">存在质检缺口或差异。接受此版本前，请完整试听，并核对文字、语言及参考音混入风险。</p>}
  </>;
}
