import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppShell } from "@/app/AppShell";
import { Button } from "@/design/Button";
import { EmptyState, ErrorState } from "@/design/States";
import { useTheme } from "@/design/theme";

describe("design system", () => {
  it("renders all four button variants without crashing", () => {
    render(
      <>
        <Button variant="primary">主</Button>
        <Button variant="secondary">次</Button>
        <Button variant="ghost">幽灵</Button>
        <Button variant="danger">危险</Button>
      </>,
    );
    expect(screen.getByRole("button", { name: "主" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "危险" })).toBeEnabled();
  });

  it("disables the button and marks it busy while loading", () => {
    render(<Button loading>提交</Button>);
    const button = screen.getByRole("button", { name: /提交/ });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it("shows empty and error states with a retry action", async () => {
    let retried = 0;
    render(
      <>
        <EmptyState title="还没有文献" description="拖拽 PDF 到这里" />
        <ErrorState message="加载失败" detail="网络中断" onRetry={() => (retried += 1)} />
      </>,
    );
    expect(screen.getByText("还没有文献")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /重试/ }));
    expect(retried).toBe(1);
  });

  it("cycles the theme and persists the choice", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppShell />
      </MemoryRouter>,
    );
    const toggle = screen.getByRole("button", { name: /切换主题/ });
    await userEvent.click(toggle);
    expect(useTheme.getState().mode).not.toBe("system");
    expect(document.documentElement.dataset["theme"]).toBe("light");
  });
});
