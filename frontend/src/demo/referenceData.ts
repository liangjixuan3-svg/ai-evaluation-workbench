import type { CalibrationReviewDetail } from "../app/calibrationApi";
import type { ConfirmedImport } from "../app/importApi";
import type { EvaluationPromptVersion } from "../app/evaluationPromptApi";
import type { PublishedQualityStandardVersion, QualityStandard, StandardRules } from "../app/qualityStandardApi";
import { DEMO_TIME } from "./demoData";

export const standardRules: StandardRules = {
  threshold: 75,
  weights: { correctness: 0.3, completeness: 0.25, relevance: 0.2, service_experience: 0.1, compliance: 0.15 },
  anchors: [
    { level: "excellent", description: "100：事实准确完整，主动说明下一步" },
    { level: "good", description: "80：核心结论正确，仅有次要遗漏" },
    { level: "acceptable", description: "60：部分解决问题，缺少关键步骤" },
    { level: "poor", description: "40：明显遗漏或理解偏差" },
    { level: "unacceptable", description: "0：结论错误或严重违规" },
  ],
  common_rules: [
    { id: "G-01", title: "隐私保护", requirement: "不得在回答中完整复述用户敏感信息。", dimension: "compliance", effect: { kind: "veto", dimension_cap: null }, source_quote: "不得在回答中完整复述手机号、身份证号、银行卡号", source_locator: "第 3 章 G-01", confidence: 1, confirmed: true },
    { id: "G-04", title: "直接回应", requirement: "先回答当前问题，再说明核查和后续步骤。", dimension: "relevance", effect: { kind: "normal", dimension_cap: null }, source_quote: "回答首段应先回应用户当前问题", source_locator: "第 3 章 G-04", confidence: 1, confirmed: true },
  ],
  scenarios: [
    { name: "退款进度查询", rules: [{ id: "R-02", title: "说明到账时效", requirement: "说明退款原路退回及适用到账时效；示例时效仅用于演示。", dimension: "completeness", effect: { kind: "normal", dimension_cap: null }, source_quote: "退款成功后，应说明款项通常原路退回", source_locator: "第 4 章 R-02", confidence: 1, confirmed: true }] },
    { name: "物流异常催单", rules: [{ id: "L-06", title: "给出下一步与时效", requirement: "告知用户后续处理人、预计反馈和升级方式。", dimension: "completeness", effect: { kind: "dimension_cap", dimension_cap: 60 }, source_quote: "必须告诉用户接下来由谁处理、预计何时反馈", source_locator: "第 5 章 L-06", confidence: 1, confirmed: true }] },
  ],
};

export const standardVersion: PublishedQualityStandardVersion = {
  standard_id: "demo-standard", standard_name: "客服质量标准示例", version_id: "demo-standard-v1", version_number: 1,
  source_filename: "公司客服质量标准示例.docx", published_at: DEMO_TIME, rules: standardRules,
};

export const standard: QualityStandard = {
  id: "demo-standard", name: standardVersion.standard_name, status: "published", updated_at: DEMO_TIME,
  draft: null,
  versions: [{ id: standardVersion.version_id, version_number: 1, source_filename: standardVersion.source_filename, rules: standardRules, published_at: DEMO_TIME }],
  parse_jobs: [],
};

export const initialPrompt: EvaluationPromptVersion = {
  id: "demo-prompt-v1", name: "客服质量评测", version: "v1", active: true,
  content: "按已发布公司质量标准逐维度评分。先检查一票否决，再输出总分、具体理由、原文证据和置信度。不得推测对话中没有的订单或物流状态。",
  published_at: DEMO_TIME, created_at: DEMO_TIME,
};

export const confirmedImport: ConfirmedImport = {
  id: "demo-import-1", filename: "客服对话示例.json", source_id: "demo-source", available_count: 2, confirmed_at: DEMO_TIME,
};

export const calibrationDetail: CalibrationReviewDetail = {
  id: "calibration-result-1", review_id: "calibration-1", evaluation_result_id: "result-logistics",
  selection_reason: "low_confidence", status: "pending", agreed: null, corrected_passed: null,
  disagreement_dimension: null, review_basis: null, reviewed_by: null, reviewed_at: null, include_in_regression: false,
  batch: { id: "demo-batch", batch_date: "2026-07-30", target_count: 1, status: "open" },
  data_source: { name: "客服演示样本", kind: "demo" },
  conversation: { id: "DEMO-L001", external_id: "DEMO-L001", scenario: "物流异常催单", status: "closed", messages: [{ role: "user", content: "物流三天没更新，帮我催一下。" }, { role: "assistant", content: "请耐心等待。" }] },
  evaluation: { total_score: 38, dimension_scores: { correctness: 65, completeness: 20, relevance: 45, service_experience: 45, compliance: 85 }, passed: false, confidence: "low", reason: "没有提供核查、催办和反馈时效。", evidence: ["请耐心等待。"], severe_factual_error: false, severe_compliance_error: false },
  locked_rule: {
    quality_standard: { id: "demo-standard-v1", version_number: 1, rules: standardRules as unknown as Record<string, unknown> },
    prompt: { id: initialPrompt.id, name: initialPrompt.name, version: initialPrompt.version, content: initialPrompt.content },
    model: { provider: "演示数据", model: "预生成评测结果", parameters: {} },
  },
};
