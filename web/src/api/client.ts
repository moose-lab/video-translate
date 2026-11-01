const messages: Record<string, string> = {
  VALIDATION_ERROR: "输入无效，请检查各字段。", INVALID_EDIT: "片段选择或编辑无效，请检查当前数据。", REVISION_CONFLICT: "项目已更改，请刷新后核对再保存。",
  EDITOR_CONFLICT: "源数据已更改，请刷新后核对。", SUBMISSION_UNCERTAIN: "上次提交结果未知；请核查远程任务后再决定是否重试。",
  RUN_ACTIVE: "任务仍在处理中，当前不能重试。", NOT_FOUND: "项目或资源不存在，或无权访问。",
  PROVIDER_REQUIRED: "所需云端服务未配置，请前往服务配置。", INPUT_REQUIRED: "所需输入尚未就绪，请检查原片与选择范围。",
  UNSUPPORTED_MEDIA: "此文件格式不受支持，请上传 MP4、MOV、WebM、MKV 或 AVI 视频。",
  UPLOAD_TOO_LARGE: "文件超过服务器上传限制。", EMPTY_UPLOAD: "所选文件为空。",
  STORAGE_UNAVAILABLE: "文件暂时无法保存，请稍后重试。", INTERNAL_ERROR: "服务器暂时无法完成操作。",
  INVALID_CURSOR: "事件游标无效，请重新打开项目。", WORKFLOW_REQUIRED: "请通过源分析工作流启动此任务。",
  INVALID_MEDIA: "媒体无法解析，请检查文件或上传其他视频。", MEDIA_LIMIT: "媒体超出当前服务限制。",
  CONFIGURATION: "服务配置需要检查。", AUTHENTICATION: "服务认证需要检查。",
  UNSUPPORTED_LANGUAGE: "当前服务不支持所选语言，请检查服务配置。", TRANSIENT: "服务暂时不可用。",
  LEASE_EXPIRED: "任务执行已中断，请检查状态后重试。",
  TRANSLATION_PROTECTED: "所选译文均已锁定或已确认，请保留现有译文或先手动调整保护状态。",
  REFERENCE_REQUIRED: "尚未配置当前行或角色的参考音。", REFERENCE_STALE: "当前参考音已过期，请重新准备并核对。",
  REFERENCE_UNUSABLE: "当前参考音或参考文字不可用，请检查后重试。", REFERENCE_REVIEW_REQUIRED: "请先检查并确认当前参考音风险。",
  TARGET_REQUIRED: "此行尚无译文，请先填写或翻译。", TARGET_STALE: "译文与当前源文字不匹配，请重新核对译文。",
  TARGET_REVIEW_REQUIRED: "请先确认当前译文，再请求配音。", AUDIO_EVIDENCE_INVALID: "音频来源证据需要检查，暂时不能选用。",
  AUDIO_REQUIRED: "请先选择有效自然音频。", INVALID_SYNTHESIS_INPUT: "当前合成语言或声音设置不受支持。",
  FIT_AUDIO_NOT_READY: "正式配音要求每行都有可用且已接受的自然音频，请先完成听审或选择未完成试听预览。",
  FIT_TRACK_INCOMPLETE: "拟合需包含当前源字幕的全部行，请重新读取输入。", FIT_SNAPSHOT_LIMIT: "拟合输入超出大小限制，请减少目标语言。",
  DELIVERY_INPUT_CHANGED: "拟合方案或媒体已变化，请重新核对当前方案后再导出。", INVALID_AUDIO_TRACK: "请选择包含在此导出中的默认音轨。",
  CONTEXT_LIMIT: "源文字超出当前完整语境处理范围，请调整片段或使用逐行模式。",
};
export function safeCode(value: unknown): string {return typeof value === "string" && Object.hasOwn(messages, value) ? value : "REQUEST_FAILED";}
export function safeFailureMessage(value: unknown): string {return messages[safeCode(value)] ?? "操作未完成，请检查输入后重试。";}
type SafeDetail = {field: string; code: string};
export class ApiError extends Error {
  constructor(public status: number, message: string, public code = "REQUEST_FAILED", public retryable = false, public details: SafeDetail[] = []) {super(message);}
}
export async function api<T>(path: string, options: RequestInit = {}, csrf?: string): Promise<T> {
  const headers = new Headers(options.headers);
  if (typeof options.body === "string") headers.set("Content-Type", "application/json");
  if (options.body instanceof FormData) headers.delete("Content-Type");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const response = await fetch("/api" + path, {...options, headers, credentials: "same-origin"});
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("session-expired"));
    let envelope: {error?: {code?: unknown; retryable?: unknown; details?: unknown}} = {};
    try {envelope = await response.json();} catch { /* Non-JSON errors use the same bounded local message. */ }
    const code = safeCode(envelope?.error?.code);
    const details = Array.isArray(envelope?.error?.details) ? envelope.error.details.slice(0, 10).flatMap(value => {
      if (!value || typeof value !== "object" || typeof value.field !== "string" || !/^(body|query|path)(\.[A-Za-z0-9_]{1,40}){1,5}$/.test(value.field) || typeof value.code !== "string" || !/^[a-z_]{1,60}$/.test(value.code)) return [];
      return [{field: value.field, code: value.code}];
    }) : [];
    const message = response.status === 401 ? "登录已失效或账号信息有误。" : messages[code] ?? (response.status === 409 ? "设置已更改，请刷新后重试。" : "操作未完成，请检查输入后重试。");
    throw new ApiError(response.status, message, code, envelope?.error?.retryable === true, details);
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}
