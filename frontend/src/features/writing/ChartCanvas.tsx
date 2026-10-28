import { BarChart, LineChart, RadarChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  RadarComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef } from "react";

import { useTheme } from "@/design/theme";
import type { ChartKind } from "./api";

echarts.use([LineChart, BarChart, RadarChart, GridComponent, LegendComponent, RadarComponent, TooltipComponent, CanvasRenderer]);

export interface ChartCanvasProps {
  preview: Record<string, unknown>[];
  x: string;
  y: string[];
  type: Exclude<ChartKind, "table" | "radar3d">;
  active: boolean;
}

function token(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function numeric(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function label(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "—";
}

function optionFor(
  preview: Record<string, unknown>[],
  x: string,
  y: string[],
  type: "line" | "bar" | "radar",
  dark: boolean,
): echarts.EChartsCoreOption {
  const categories = preview.map((row) => label(row[x]));
  const ink = token("--ink-2", dark ? "#9aa6c8" : "#475569");
  const line = token("--border", dark ? "#27315a" : "#e3e7f0");
  const palette = ["--primary", "--accent", "--warn", "--success", "--danger"].map((name) => token(name, "#4f46e5"));
  const base = { textStyle: { color: ink }, color: palette, backgroundColor: "transparent" };
  if (type === "radar") {
    const values = y.flatMap((name) => preview.map((row) => numeric(row[name]) ?? 0));
    const max = Math.max(1, ...values) * 1.1;
    const indicators = categories.slice(0, 12).map((name) => ({ name, max }));
    return {
      ...base,
      tooltip: {},
      legend: { bottom: 0, textStyle: { color: ink } },
      radar: {
        indicator: indicators,
        axisName: { color: ink },
        splitLine: { lineStyle: { color: line } },
        splitArea: { show: false },
        axisLine: { lineStyle: { color: line } },
      },
      series: [
        {
          type: "radar",
          data: y.map((name) => ({
            name,
            value: preview.slice(0, 12).map((row) => numeric(row[name]) ?? 0),
          })),
        },
      ],
    };
  }
  return {
    ...base,
    tooltip: { trigger: "axis" },
    legend: { bottom: 0, textStyle: { color: ink } },
    grid: { left: 44, right: 16, top: 20, bottom: 44 },
    xAxis: {
      type: "category",
      data: categories,
      axisLabel: { color: ink },
      axisLine: { lineStyle: { color: line } },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: ink },
      splitLine: { lineStyle: { color: line } },
    },
    series: y.map((name) => ({
      name,
      type,
      data: preview.map((row) => numeric(row[name])),
      smooth: type === "line",
      showSymbol: preview.length <= 30,
    })),
  };
}

export function ChartCanvas({ preview, x, y, type, active }: ChartCanvasProps) {
  const resolved = useTheme((state) => state.resolved);
  const host = useRef<HTMLDivElement | null>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const option = useMemo(() => optionFor(preview, x, y, type, resolved === "dark"), [preview, x, y, type, resolved]);

  useEffect(() => {
    const node = host.current;
    if (!node) return;
    const instance = echarts.init(node, undefined, { renderer: "canvas" });
    chart.current = instance;
    const resize = () => {
      if (node.clientWidth === 0 || node.clientHeight === 0) return;
      instance.resize();
    };
    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(resize);
      observer.observe(node);
    }
    window.addEventListener("resize", resize);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", resize);
      instance.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, true);
  }, [option]);

  useEffect(() => {
    if (active) window.setTimeout(() => chart.current?.resize(), 0);
  }, [active]);

  return <div ref={host} className="h-full w-full" data-testid="data-chart" role="img" aria-label="数据图表" />;
}
