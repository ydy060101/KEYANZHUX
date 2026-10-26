import { create } from "zustand";

interface UiState {
  commandOpen: boolean;
  agentOpen: boolean;
  jobCenterOpen: boolean;
  setCommandOpen: (open: boolean) => void;
  setAgentOpen: (open: boolean) => void;
  setJobCenterOpen: (open: boolean) => void;
  toggleAgent: () => void;
}

export const useUi = create<UiState>((set) => ({
  commandOpen: false,
  agentOpen: false,
  jobCenterOpen: false,
  setCommandOpen: (open) => set({ commandOpen: open }),
  setAgentOpen: (open) => set({ agentOpen: open }),
  setJobCenterOpen: (open) => set({ jobCenterOpen: open }),
  toggleAgent: () => set((s) => ({ agentOpen: !s.agentOpen })),
}));
