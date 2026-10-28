import { Check, Clipboard, Download, FileSpreadsheet, Loader2, Upload } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { Button } from "@/design/Button";
import { EmptyState, ErrorState } from "@/design/States";
import {
  CHART_LABEL,
  createChart,
  downloadHref,
  uploadDataset,
  type ChartKind,
  type ChartResult,
  type DatasetView,
} from "./api";
import { ChartCanvas } from "./ChartCanvas";

const KINDS: ChartKind[] = ["table", "line", "bar", "radar", "radar3d"];

function cell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") return String(value);
  return JSON.stringify(value);
}

function DataTable({ dataset }: { dataset: DatasetView }) {
  return (
    <div className="app-scroll min-h-0 flex-1 overflow-auto rounded-card border border-border bg-surface">
      <table className="w-full border-collapse text-left text-[var(--text-xs)]" data-testid="data-preview-table">
        <thead className="sticky top-0 bg-surface-2 text-ink-2">
          <tr>
            {dataset.columns.map((column) => (
              <th key={column.name} className="whitespace-nowrap border-b border-border px-2.5 py-2 font-medium">
                {column.name}
                <span className="ml-1 font-normal opacity-70">{column.dtype}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dataset.preview.map((row, index) => (
            <tr key={index} className="border-b border-border/60 last:border-0">
              {dataset.columns.map((column) => (
                <td key={column.name} className="max-w-[220px] truncate px-2.5 py-1.5 text-ink" title={cell(row[column.name])}>
                  {cell(row[column.name])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChartBody({
  dataset,
  result,
  type,
  x,
  y,
  active,
}: {
  dataset: DatasetView | null;
  result: ChartResult | null;
  type: ChartKind;
  x: string;
  y: string[];
  active: boolean;
}) {
  if (!dataset) {
    return (
      <EmptyState
        title="上传一份 CSV"
        description="解析后会显示列类型与前 20 行预览；选择 X/Y 列即可出图，图注的每个数字都能在统计依据中核对。"
        icon={<Upload className="size-6" aria-hidden />}
      />
    );
  }
  if (!result) {
    return (
      <EmptyState
        title="选择图表类型与数据列"
        description="左侧选择 X 与其一至六列 Y，然后生成图表。表格类型不需要绘图库。"
        icon={<FileSpreadsheet className="size-6" aria-hidden />}
      />
    );
  }
  if (type === "table") return <DataTable dataset={dataset} />;
  if (type === "radar3d") {
    return (
      <div className="app-scroll min-h-0 flex-1">
        <img src={result.imageUrl} alt="三维雷达图" data-testid="data-chart-image" className="w-full rounded-card border border-border" />
        <p className="mt-2 text-[var(--text-xs)] text-ink-2">三维雷达由服务端用同一份全量数据渲染；二维图表由 ECharts 在浏览器绘制。</p>
      </div>
    );
  }
  return (
    <div className="min-h-0 flex-1 rounded-card border border-border bg-surface p-2">
      <ChartCanvas preview={dataset.preview} x={x} y={y} type={type} active={active} />
    </div>
  );
}

export function DataWorkspace({ active }: { active: boolean }) {
  const [dataset, setDataset] = useState<DatasetView | null>(null);
  const [type, setType] = useState<ChartKind>("line");
  const [x, setX] = useState("");
  const [ys, setYs] = useState<string[]>([]);
  const [result, setResult] = useState<ChartResult | null>(null);
  const [caption, setCaption] = useState("");
  const [captionZh, setCaptionZh] = useState("");
  const [busy, setBusy] = useState<"upload" | "chart" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const yOptions = useMemo(() => dataset?.columns.filter((column) => column.name !== x) ?? [], [dataset, x]);
  const canGenerate = Boolean(dataset) && Boolean(x) && ys.length > 0 && busy === null;

  const chooseFile = async (file: File | undefined) => {
    if (!file) return;
    setBusy("upload");
    setError(null);
    setDataset(null);
    setResult(null);
    setCaption("");
    setCaptionZh("");
    setX("");
    setYs([]);
    try {
      const next = await uploadDataset(file);
      setDataset(next);
      const first = next.columns[0]?.name ?? "";
      setX(first);
      const numeric = next.columns.find((column) => column.name !== first && column.dtype !== "object")?.name;
      setYs(numeric ? [numeric] : next.columns.find((column) => column.name !== first)?.name ? [next.columns.find((column) => column.name !== first)?.name as string] : []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "上传失败");
    } finally {
      setBusy(null);
    }
  };

  const generate = async () => {
    if (!dataset || !x || ys.length === 0) return;
    setBusy("chart");
    setError(null);
    try {
      const next = await createChart(dataset.id, { type, x, y: ys });
      setResult(next);
      setCaption(next.caption);
      setCaptionZh(next.captionZh);
      setCopied(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "图表生成失败");
    } finally {
      setBusy(null);
    }
  };

  const copyCaption = async () => {
    try {
      await navigator.clipboard.writeText(caption);
      setCopied(true);
      window.setTimeout(() => {
        setCopied(false);
      }, 1500);
    } catch {
      setError("浏览器拒绝了剪贴板访问，请手动选择文本复制");
    }
  };

  const toggleY = (name: string) => {
    setYs((current) => (current.includes(name) ? current.filter((item) => item !== name) : [...current, name]));
  };

  return (
    <div className="flex min-h-0 flex-1" data-testid="writing-data">
      <aside className="flex w-[300px] shrink-0 flex-col gap-3 border-r border-border bg-surface p-4">
        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          aria-label="上传 CSV"
          data-testid="data-file"
          className="sr-only"
          onChange={(event) => {
            void chooseFile(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
        <Button
          variant="secondary"
          data-testid="data-upload"
          loading={busy === "upload"}
          onClick={() => fileRef.current?.click()}
        >
          <Upload className="size-4" aria-hidden />
          {dataset ? "换一份 CSV" : "上传 CSV"}
        </Button>
        {dataset && (
          <div className="rounded-control border border-border bg-surface-2 p-2.5" data-testid="data-meta">
            <p className="truncate text-[var(--text-sm)] font-medium text-ink" title={dataset.filename}>
              {dataset.filename}
            </p>
            <p className="mt-0.5 text-[var(--text-xs)] text-ink-2">
              {dataset.rowCount} 行 · {dataset.columns.length} 列 · 预览 {dataset.preview.length} 行
            </p>
          </div>
        )}

        <label htmlFor="data-kind" className="mt-1 text-[var(--text-sm)] font-medium text-ink">
          图表类型
        </label>
        <select
          id="data-kind"
          value={type}
          onChange={(event) => {
            setType(event.target.value as ChartKind);
          }}
          data-testid="data-chart-type"
          className="h-9 rounded-control border border-border bg-surface px-2 text-[var(--text-sm)] text-ink outline-none focus:border-primary"
        >
          {KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {CHART_LABEL[kind]}
            </option>
          ))}
        </select>

        <label htmlFor="data-x" className="text-[var(--text-sm)] font-medium text-ink">
          X 列
        </label>
        <select
          id="data-x"
          value={x}
          onChange={(event) => {
            setX(event.target.value);
            setYs((current) => current.filter((name) => name !== event.target.value));
          }}
          data-testid="data-x"
          disabled={!dataset}
          className="h-9 rounded-control border border-border bg-surface px-2 text-[var(--text-sm)] text-ink outline-none focus:border-primary disabled:opacity-50"
        >
          <option value="">选择列</option>
          {dataset?.columns.map((column) => (
            <option key={column.name} value={column.name}>
              {column.name}
            </option>
          ))}
        </select>

        <p className="text-[var(--text-sm)] font-medium text-ink">Y 列（1–6）</p>
        <div className="max-h-[180px] space-y-1 overflow-y-auto rounded-control border border-border p-2" data-testid="data-y">
          {yOptions.length === 0 && <p className="text-[var(--text-xs)] text-ink-2">先选择 X 列，再选择 Y 列。</p>}
          {yOptions.map((column) => {
            const checked = ys.includes(column.name);
            return (
              <label key={column.name} className="flex cursor-pointer items-center gap-2 text-[var(--text-xs)] text-ink">
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={!checked && ys.length >= 6}
                  onChange={() => {
                    toggleY(column.name);
                  }}
                  className="size-3.5 accent-[var(--primary)]"
                />
                <span className="truncate" title={column.name}>
                  {column.name}
                </span>
                <span className="ml-auto shrink-0 text-ink-2">{column.dtype}</span>
              </label>
            );
          })}
        </div>

        <Button variant="primary" data-testid="data-generate" disabled={!canGenerate} loading={busy === "chart"} onClick={() => { void generate(); }}>
          {busy === "chart" ? "渲染中…" : "生成图表"}
        </Button>
        {error && <p className="text-[var(--text-xs)] leading-relaxed text-danger-text">{error}</p>}
        <p className="mt-auto text-[11px] leading-relaxed text-ink-2">
          图表与图注都由真实数据计算；图注中的数字必须出现在统计依据中，否则后端会退回确定性模板。
        </p>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col bg-bg p-4" data-testid="data-canvas">
        <div className="flex min-h-0 flex-1 flex-col">
          {busy === "chart" ? (
            <div className="flex h-full items-center justify-center gap-2 text-[var(--text-sm)] text-ink-2">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              正在计算统计量并渲染图表…
            </div>
          ) : (
            <ChartBody dataset={dataset} result={result} type={type} x={x} y={ys} active={active} />
          )}
        </div>
        {dataset && result && (
          <p className="mt-2 text-[var(--text-xs)] text-ink-2">
            {type === "table"
              ? "表格显示上传文件的前 20 行；完整数据保存在服务端。"
              : "浏览器图表使用前 20 行预览；图注、统计与 PNG 使用全量数据。"}
          </p>
        )}
      </section>

      <aside className="flex w-[360px] shrink-0 flex-col border-l border-border bg-surface" data-testid="data-caption-panel">
        <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-3">
          <h2 className="text-[var(--text-sm)] font-medium text-ink">Figure Caption</h2>
          {result && <span className="text-[var(--text-xs)] text-ink-2">自动生成 · 可编辑</span>}
          <div className="ml-auto flex gap-1">
            <Button size="sm" variant="ghost" data-testid="data-copy-caption" disabled={!caption} onClick={() => { void copyCaption(); }}>
              {copied ? <Check className="size-3.5" aria-hidden /> : <Clipboard className="size-3.5" aria-hidden />}
              {copied ? "已复制" : "复制"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              data-testid="data-export-png"
              disabled={!result}
              onClick={() => {
                if (result) downloadHref("chart.png", result.imageUrl);
              }}
            >
              <Download className="size-3.5" aria-hidden />
              PNG
            </Button>
          </div>
        </header>

        <div className="app-scroll min-h-0 flex-1 space-y-3 p-3">
          {result ? (
            <>
              <textarea
                value={caption}
                onChange={(event) => {
                  setCaption(event.target.value);
                }}
                aria-label="英文 Figure Caption"
                data-testid="data-caption"
                rows={7}
                className="w-full resize-none rounded-control border border-border bg-surface-2 px-3 py-2 font-read text-[var(--text-sm)] leading-relaxed text-ink outline-none focus:border-primary"
              />
              {captionZh && <p className="rounded-control bg-surface-2 p-2 text-[var(--text-xs)] leading-relaxed text-ink-2">{captionZh}</p>}
              <details className="rounded-control border border-border p-2" data-testid="data-stats">
                <summary className="cursor-pointer text-[var(--text-xs)] font-medium text-ink">统计依据</summary>
                <pre className="app-scroll mt-2 max-h-[280px] overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-ink-2">
                  {JSON.stringify(result.stats, null, 2)}
                </pre>
              </details>
              {result.script && (
                <details className="rounded-control border border-border p-2">
                  <summary className="cursor-pointer text-[var(--text-xs)] font-medium text-ink">复现脚本</summary>
                  <pre className="app-scroll mt-2 max-h-[220px] overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-ink-2">
                    {result.script}
                  </pre>
                </details>
              )}
            </>
          ) : error ? (
            <ErrorState message="图表生成失败" detail={error} onRetry={() => { void generate(); }} />
          ) : (
            <EmptyState title="还没有 Caption" description="生成图表后会显示自动图注与统计依据。" />
          )}
        </div>
      </aside>
    </div>
  );
}
