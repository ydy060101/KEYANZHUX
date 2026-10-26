import { useQuery } from "@tanstack/react-query";

import { api, humanMessage, toApiError } from "@/api/client";
import { useJobs } from "@/app/jobs";
import type { components } from "@/api/schema";

export type JobSnapshot = components["schemas"]["Job"];

export const jobKeys = { detail: (id: string) => ["job", id] as const };

/**
 * Follow one job to completion over SSE (T1.1).
 *
 * The stream is the fast path; a dropped connection falls back to polling the
 * job row, so progress never freezes on a flaky network (H07, H08).
 */
export function useJobStream(jobId: string | null, label = "解析 PDF") {
  const upsert = useJobs((s) => s.upsert);

  return useQuery({
    queryKey: jobKeys.detail(jobId ?? "none"),
    enabled: Boolean(jobId),
    queryFn: async () => {
      if (!jobId) throw new Error("missing job id");
      const snapshot = await watchJob(jobId, (update) => {
        upsert({
          id: update.id,
          kind: update.kind,
          label,
          status: update.status,
          progress: update.progress,
          stage: update.stage,
          ...(update.error ? { error: update.error } : {}),
        });
      });
      return snapshot;
    },
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
}

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

async function watchJob(
  jobId: string,
  onUpdate: (snapshot: JobSnapshot) => void,
): Promise<JobSnapshot> {
  const url = `/api/v1/jobs/stream?job_id=${encodeURIComponent(jobId)}`;
  try {
    const response = await fetch(url, { headers: { Accept: "text/event-stream" } });
    if (!response.ok || !response.body) throw new Error("stream unavailable");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let last: JobSnapshot | null = null;

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const parsed = parseFrame(frame);
        if (!parsed) continue;
        const snapshot = parsed.data as JobSnapshot;
        last = snapshot;
        onUpdate(snapshot);
        if (TERMINAL.has(snapshot.status)) {
          await reader.cancel().catch(() => undefined);
          return snapshot;
        }
      }
    }
    if (last) return last;
  } catch {
    // Fall through to polling: an SSE failure must not hide the job's state.
  }
  return pollJob(jobId, onUpdate);
}

function parseFrame(frame: string): { event: string; data: unknown } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

async function pollJob(
  jobId: string,
  onUpdate: (snapshot: JobSnapshot) => void,
): Promise<JobSnapshot> {
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const result = await api.GET("/jobs/{id}", { params: { path: { id: jobId } } });
    if (!result.data) {
      throw new Error(humanMessage(toApiError(result.error)));
    }
    onUpdate(result.data);
    if (TERMINAL.has(result.data.status)) return result.data;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("任务超时");
}
