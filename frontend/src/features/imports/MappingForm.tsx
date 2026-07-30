import type { ImportMapping } from "../../app/importApi";

const optionalFields: Array<[keyof ImportMapping, string]> = [
  ["id_path", "对话 ID"],
  ["scenario_path", "场景"],
  ["status_path", "会话状态"],
];

export function MappingForm({ value, onChange }: {
  value: ImportMapping;
  onChange: (mapping: ImportMapping) => void;
}) {
  const field = (key: keyof ImportMapping, label: string, required = false) => (
    <label className="field" key={key}>
      <span>{label}{required ? " *" : ""}</span>
      <input
        value={String(value[key] ?? "")}
        onChange={(event) => onChange({ ...value, [key]: event.target.value || null })}
        placeholder="例如 created_at"
      />
    </label>
  );

  return (
    <div className="mapping-form">
      <div className="form-grid">
        {field("record_path", "记录数组路径", true)}
        {field("occurred_at_path", "发生时间", true)}
        <label className="field">
          <span>对话结构 *</span>
          <select value={value.message_mode} onChange={(event) => onChange({
            ...value,
            message_mode: event.target.value as ImportMapping["message_mode"],
          })}>
            <option value="messages">消息数组</option>
            <option value="qa_pair">问题 + 回答</option>
          </select>
        </label>
        {optionalFields.map(([key, label]) => field(key, label))}
        {value.message_mode === "messages" ? (
          <>
            {field("messages_path", "消息数组", true)}
            {field("role_path", "角色字段", true)}
            {field("content_path", "内容字段", true)}
          </>
        ) : (
          <>
            {field("question_path", "问题字段", true)}
            {field("answer_path", "回答字段", true)}
          </>
        )}
      </div>
    </div>
  );
}
