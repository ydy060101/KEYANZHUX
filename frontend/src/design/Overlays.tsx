import { useEffect } from "react";

import { AgentDrawer } from "@/design/AgentDrawer";
import { CommandPalette } from "@/design/CommandPalette";
import { JobCenter } from "@/design/JobCenter";
import { JobCenterTrigger } from "@/design/JobCenterTrigger";
import { useUi } from "@/app/ui";

/** Right-hand slide-over used by the job centre. */
export function JobCenterPanel() {
  const open = useUi((s) => s.jobCenterOpen);
  const setOpen = useUi((s) => s.setJobCenterOpen);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [setOpen]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onMouseDown={() => {
      setOpen(false);
    }}>
      <div
        className="h-full w-[360px] border-l border-border bg-surface shadow-lg"
        role="dialog"
        aria-label="任务中心"
        onMouseDown={(event) => {
          event.stopPropagation();
        }}
      >
        <div className="flex h-[var(--topbar-height)] items-center border-b border-border px-4">
          <span className="text-[var(--text-base)] font-medium">任务中心</span>
        </div>
        <div className="h-[calc(100%-var(--topbar-height))]">
          <JobCenter />
        </div>
      </div>
    </div>
  );
}

export { AgentDrawer, CommandPalette, JobCenterTrigger };
