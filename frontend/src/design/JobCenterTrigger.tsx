import { ListChecks } from "lucide-react";

import { useActiveJobCount } from "@/app/jobs";
import { useUi } from "@/app/ui";

export function JobCenterTrigger() {
  const count = useActiveJobCount();
  const setOpen = useUi((s) => s.setJobCenterOpen);
  return (
    <button
      type="button"
      onClick={() => {
        setOpen(true);
      }}
      aria-label={count > 0 ? `任务中心，${count} 个进行中` : "任务中心"}
      className="relative flex size-9 items-center justify-center rounded-control text-ink-2 transition-colors duration-[--dur-fast] hover:bg-surface-2 hover:text-ink"
    >
      <ListChecks className="size-[18px]" strokeWidth={1.75} aria-hidden />
      {count > 0 && (
        <span className="absolute -right-0.5 -top-0.5 flex size-4 items-center justify-center rounded-full bg-primary text-[10px] font-medium text-white">
          {count}
        </span>
      )}
    </button>
  );
}
