import type { TaskItem } from "../../app/api";

const statusLabels: Record<string, string> = {
  open: "待处理",
  in_progress: "进行中",
  awaiting_retest: "待复测",
  not_recovered: "未恢复",
};

export function TaskCard({ item, index }: { item: TaskItem; index: number }) {
  return (
    <article className={`task-card priority-${item.priority.toLowerCase()}`} style={{ "--delay": `${index * 70}ms` } as React.CSSProperties}>
      <div className="task-rank">{String(index + 1).padStart(2, "0")}</div>
      <div className="task-body">
        <div className="task-meta">
          <span className="priority-tag">{item.priority}</span>
          <span>{statusLabels[item.status] ?? item.status}</span>
          <span>影响 {item.impact_count} 条</span>
        </div>
        <h3>{item.title}</h3>
        <p>{item.description}</p>
      </div>
      <a className="action-button" href={item.next_action.path}>
        {item.next_action.label}<span aria-hidden="true">↗</span>
      </a>
    </article>
  );
}
