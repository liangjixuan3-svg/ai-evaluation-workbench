import type { CalibrationFilter } from "../../app/calibrationApi";

let todayEnsurePromise: Promise<unknown> | null = null;

export function ensureTodayOnce<T>(request: () => Promise<T>): Promise<T> {
  if (!todayEnsurePromise) todayEnsurePromise = request().finally(() => { todayEnsurePromise = null; });
  return todayEnsurePromise as Promise<T>;
}

export class CalibrationWorkspaceController {
  private status: CalibrationFilter = "pending";
  private selectedId = "";
  private workspaceGeneration = 0;
  private detailGeneration = 0;

  beginWorkspace(status: CalibrationFilter) { this.status = status; this.selectedId = ""; this.detailGeneration += 1; return ++this.workspaceGeneration; }
  isCurrentWorkspace(generation: number, status: CalibrationFilter) { return generation === this.workspaceGeneration && status === this.status; }
  beginDetail(reviewId: string) { this.selectedId = reviewId; return ++this.detailGeneration; }
  isCurrentDetail(generation: number, reviewId: string) { return generation === this.detailGeneration && reviewId === this.selectedId; }
  clearDetail() { this.selectedId = ""; return ++this.detailGeneration; }
  currentStatus() { return this.status; }
  selectedReviewId() { return this.selectedId; }
}
