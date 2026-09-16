import { useQuery } from "@tanstack/react-query";

import { demoWorkbench, getWorkbench, type WorkbenchSummary } from "../../app/api";
import { isDemoMode } from "../../demo/mode";
import { TaskCard } from "./TaskCard";

const countLabels = {
  new_alerts: ["新告警", "需要先判断影响"],
  pending_attributions: ["待确认归因", "AI 已准备原因建议"],
  pending_qa: ["QA 待审核", "可发布给知识库"],
  pending_retests: ["待复测", "确认改进是否生效"],
} as const;

function WorkbenchView({ data, demo }: { data: WorkbenchSummary; demo: boolean }) {
  const passRate = `${(data.pass_rate * 100).toFixed(1)}%`;
  return (
    <div className="workbench-page">
      <section className="hero">
        <div>
          <span className="eyebrow">THURSDAY · QUALITY BRIEFING</span>
          <h1>先处理最影响<br /><em>用户体验</em>的三件事</h1>
          <p>系统已完成抽样、评测和聚类。你只需要确认原因、审核改法、验证效果。</p>
        </div>
        <div className="score-stamp">
          <span>今日通过率</span>
          <strong>{passRate}</strong>
          <small className={data.pass_rate_delta < 0 ? "negative" : "positive"}>
            {isDemoMode ? "仅含 2 条示例对话" : <>{data.pass_rate_delta > 0 ? "+" : ""}{(data.pass_rate_delta * 100).toFixed(1)}% 较昨日</>}
          </small>
        </div>
      </section>

      {demo && <div className="demo-note"><span>演示数据</span> {isDemoMode ? "本页为虚构案例，不连接线上服务。" : "接入线上对话后，此处自动切换为实时任务。"}</div>}

      <section className="count-strip" aria-label="待办概览">
        {Object.entries(data.counts).map(([key, value]) => {
          const [label, hint] = countLabels[key as keyof typeof countLabels];
          return <div key={key}><strong>{String(value).padStart(2, "0")}</strong><span>{label}<small>{hint}</small></span></div>;
        })}
      </section>

      <section className="priority-section">
        <div className="section-heading">
          <div><span className="eyebrow">ACTION QUEUE</span><h2>优先处理</h2></div>
          <p>按优先级、影响量和等待时长排序</p>
        </div>
        <div className="task-list">
          {data.priority_items.map((item, index) => <TaskCard key={item.id} item={item} index={index} />)}
        </div>
      </section>

      <section className="support-grid">
        <div className="loop-card">
          <div className="section-heading compact"><div><span className="eyebrow">CLOSED LOOP</span><h2>本周改进闭环</h2></div></div>
          {isDemoMode ? <div className="loop-flow">
            <div className="done"><strong>01</strong><span>确认原因</span></div>
            <i />
            <div className="done"><strong>02</strong><span>审核 QA</span></div>
            <i />
            <div className="active"><strong>03</strong><span>登记发布</span></div>
            <i />
            <div><strong>04</strong><span>模拟复测</span></div>
          </div> : <div className="loop-flow">
            <div className="done"><strong>1,846</strong><span>自动评测</span></div>
            <i />
            <div className="done"><strong>36</strong><span>问题归因</span></div>
            <i />
            <div className="active"><strong>8</strong><span>QA 发布</span></div>
            <i />
            <div><strong>5</strong><span>确认恢复</span></div>
          </div>}
          <p className="loop-insight"><span>↑</span> {isDemoMode ? "这是可操作的示例流程，不代表真实业务效果或线上统计。" : "已验证改进覆盖 412 条日均对话，预计减少 23% 人工转接。"}</p>
        </div>
        <div className="activity-card">
          <div className="section-heading compact"><div><span className="eyebrow">AUDIT TRAIL</span><h2>最近动态</h2></div></div>
          <ol>
            {data.recent_activity.map((activity) => (
              <li key={activity.id}><span /><div><strong>{activity.action}</strong><small>{new Date(activity.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })} · {activity.actor}</small></div></li>
            ))}
          </ol>
        </div>
      </section>
    </div>
  );
}

export function WorkbenchPage() {
  const query = useQuery({ queryKey: ["workbench"], queryFn: getWorkbench });
  if (query.isPending) return <div className="page-state"><span className="loader" />正在整理今日优先任务…</div>;
  if (query.isError) return <WorkbenchView data={demoWorkbench} demo />;
  return <WorkbenchView data={query.data} demo={isDemoMode || query.data === demoWorkbench} />;
}
