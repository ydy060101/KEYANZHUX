import { create } from "zustand";

export interface Job {
  id: string;
  kind: string;
  label: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  stage: string;
  error?: string;
}

interface JobState {
  jobs: Job[];
  upsert: (job: Job) => void;
  remove: (id: string) => void;
  clearFinished: () => void;
}

export const useJobs = create<JobState>((set) => ({
  jobs: [],
  upsert: (job) =>
    set((state) => {
      const index = state.jobs.findIndex((j) => j.id === job.id);
      if (index === -1) return { jobs: [...state.jobs, job] };
      const jobs = [...state.jobs];
      jobs[index] = job;
      return { jobs };
    }),
  remove: (id) => set((state) => ({ jobs: state.jobs.filter((j) => j.id !== id) })),
  clearFinished: () =>
    set((state) => ({
      jobs: state.jobs.filter((j) => j.status === "queued" || j.status === "running"),
    })),
}));

export const useActiveJobCount = (): number =>
  useJobs((s) => s.jobs.filter((j) => j.status === "queued" || j.status === "running").length);
