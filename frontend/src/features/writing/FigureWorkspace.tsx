import { Download, Image as ImageIcon, Play, Sparkles, Wrench } from "lucide-react";
import mermaid from "mermaid";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/design/Button";
import { useTheme } from "@/design/theme";
import { EmptyState } from "@/design/States";
import { cn } from "@/lib/cn";
import {
  downloadHref,
  downloadText,
  FIGURE_LABEL,
  generateFigure,
  runFigure,
  type FigureKind,
  type FigureResult,
} from "./api";
import { ScriptEditor } from "./ScriptEditor";

const KINDS: FigureKind[] = ["mermaid", "graphviz", "tikz", "matplotlib"];
const LANGUAGE: Record<FigureKind, string> = {
  mermaid: "markdown",
  graphviz: "plaintext",
  tikz: "plaintext",
  matplotlib: "python",
};
const EXTENSION: Record<FigureKind, string> = { mermaid: "mmd", graphviz: "dot", tikz: "tex", matplotlib: "py" };

function messageOf(reason: unknown): string {
  return reason instanceof Error ? reason.message : "操作失败，请重试";
}

function svgDimensions(svg: string): { width: number; height: number } {
  const viewBox = /viewBox="([\d.-]+)\s+([\d.-]+)\s+([\d.]+)\s+([\d.]+)"/.exec(svg);
  if (viewBox) return { width: Number(viewBox[3]) || 800, height: Number(viewBox[4]) || 600 };
  return { width: 800, height: 600 };
}

async function svgToPng(svg: string, background: string): Promise<string> {
  const { width, height } = svgDimensions(svg);
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => {
      image.onload = () => {
        resolve();
      };
      image.onerror = () => {
        reject(new Error("SVG 转换失败"));
      };
      image.src = url;
    });
    const scale = 2;
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const context = canvas.getContext("2d");
    if (!context) throw new Error("浏览器不支持画布导出");
    context.scale(scale, scale);
    context.fillStyle = background;
    context.fillRect(0, 0, width, height);
    context.drawImage(image, 0, 0, width, height);
    return canvas.toDataURL("image/png");
  } finally {
    URL.revokeObjectURL(url);
  }
}

function surfaceColor(): string {
  if (typeof document === "undefined") return "#ffffff";
  return getComputedStyle(document.documentElement).getPropertyValue("--surface").trim() || "#ffffff";
}

export function FigureWorkspace() {
  const resolved = useTheme((state) => state.resolved);
  const [kind, setKind] = useState<FigureKind>("mermaid");
  const [description, setDescription] = useState("");
  const [script, setScript] = useState("");
  const [result, setResult] = useState<FigureResult | null>(null);
  const [busy, setBusy] = useState<"generate" | "repair" | "run" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [svg, setSvg] = useState<string | null>(null);
  const [mermaidError, setMermaidError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const renderSeq = useRef(0);

  useEffect(() => {
    mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: resolved === "dark" ? "dark" : "default" });
  }, [resolved]);

  useEffect(() => {
    if (kind !== "mermaid" || !script.trim()) {
      setSvg(null);
      setMermaidError(null);
      return;
    }
    const seq = renderSeq.current + 1;
    renderSeq.current = seq;
    const timer = window.setTimeout(() => {
      void mermaid
        .render(`writing-figure-${seq}`, script)
        .then((output) => {
          if (renderSeq.current !== seq) return;
          setSvg(output.svg);
          setMermaidError(null);
        })
        .catch((reason: unknown) => {
          if (renderSeq.current !== seq) return;
          setSvg(null);
          setMermaidError(messageOf(reason));
        });
    }, 300);
    return () => {
      window.clearTimeout(timer);
    };
  }, [kind, script]);

  const errors = useMemo(() => {
    const list = [...(result?.errors ?? [])];
    if (mermaidError && !list.includes(mermaidError)) list.unshift(mermaidError);
    return list;
  }, [result?.errors, mermaidError]);

  const run = async (mode: "generate" | "repair" | "run", text?: string) => {
    setError(null);
    setBusy(mode);
    try {
      const next =
        mode === "run"
          ? await runFigure(kind, script)
          : await generateFigure(kind, text ?? description.trim());
      if (mode !== "run") {
        setScript(next.script);
        setDirty(false);
      } else {
        setDirty(false);
      }
      setResult(next);
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setBusy(null);
    }
  };

  const repair = async () => {
    const detail = [
      description.trim(),
      "",
      "上一次脚本渲染失败，请修复后返回完整脚本。",
      `错误：${errors.join("；")}`,
      "脚本：",
      script,
    ].join("\n");
    await run("repair", detail.slice(0, 1990));
  };

  const exportScript = () => {
    downloadText(`figure-${kind}.${EXTENSION[kind]}`, script || result?.script || "");
  };

  const exportSvg = () => {
    if (kind === "mermaid" && svg) {
      downloadText("figure-mermaid.svg", svg, "image/svg+xml;charset=utf-8");
      return;
    }
    const rendered = result?.rendered;
    if (rendered?.startsWith("data:image/svg+xml")) downloadHref("figure.svg", rendered);
  };

  const exportPng = async () => {
    const rendered = result?.rendered;
    if (rendered?.startsWith("data:image/png")) {
      downloadHref("figure.png", rendered);
      return;
    }
    if (kind === "mermaid" && svg) {
      try {
        downloadHref("figure.png", await svgToPng(svg, surfaceColor()));
      } catch (reason) {
        setError(messageOf(reason));
      }
    }
  };

  const canPng = (kind === "mermaid" && Boolean(svg)) || Boolean(result?.rendered?.startsWith("data:image/png"));
  const canSvg = kind === "mermaid" ? Boolean(svg) : Boolean(result?.rendered?.startsWith("data:image/svg+xml"));
  const previewSrc = result?.rendered?.startsWith("data:image/") ? result.rendered : null;

  return (
    <div className="flex min-h-0 flex-1" data-testid="writing-figures">
      <aside className="flex w-[280px] shrink-0 flex-col gap-3 border-r border-border bg-surface p-4">
        <label htmlFor="figure-kind" className="text-[var(--text-sm)] font-medium text-ink">
          图形类型
        </label>
        <select
          id="figure-kind"
          value={kind}
          onChange={(event) => {
            const next = event.target.value as FigureKind;
            setKind(next);
            setResult(null);
            setError(null);
            setSvg(null);
            setMermaidError(null);
          }}
          data-testid="figure-kind"
          className="h-9 rounded-control border border-border bg-surface px-2 text-[var(--text-sm)] text-ink outline-none focus:border-primary"
        >
          {KINDS.map((item) => (
            <option key={item} value={item}>
              {FIGURE_LABEL[item]}
            </option>
          ))}
        </select>

        <label htmlFor="figure-description" className="mt-1 text-[var(--text-sm)] font-medium text-ink">
          描述需求
        </label>
        <textarea
          id="figure-description"
          value={description}
          onChange={(event) => {
            setDescription(event.target.value);
          }}
          rows={7}
          maxLength={2000}
          placeholder="例如：画一个 Transformer 编码器-解码器结构图，标出注意力模块。"
          data-testid="figure-description"
          className="resize-none rounded-control border border-border bg-surface-2 px-3 py-2 text-[var(--text-base)] leading-relaxed text-ink outline-none placeholder:text-ink-2 focus:border-primary"
        />
        <Button
          variant="primary"
          data-testid="figure-generate"
          disabled={!description.trim() || busy !== null}
          loading={busy === "generate"}
          onClick={() => {
            void run("generate");
          }}
        >
          <Sparkles className="size-4" aria-hidden />
          生成并运行
        </Button>
        {error && <p className="text-[var(--text-xs)] leading-relaxed text-danger-text">{error}</p>}
        <div className="mt-auto space-y-1 text-[11px] leading-relaxed text-ink-2">
          <p>脚本在无网络的沙箱中执行（20 秒、512 MB）；Mermaid 由浏览器实时渲染。</p>
          <p>参考资料不会由模型凭空生成，图注中的数字同样需要核对。</p>
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border bg-surface px-3">
          <span className="text-[var(--text-sm)] font-medium text-ink">{FIGURE_LABEL[kind]} 脚本</span>
          {result && (
            <span className="text-[var(--text-xs)] text-ink-2">
              {result.renderer || "未渲染"}
              {result.attempts > 0 ? ` · ${result.attempts} 次尝试` : ""}
            </span>
          )}
          {dirty && <span className="text-[var(--text-xs)] text-warn-text">已修改，需重新运行</span>}
          <div className="ml-auto flex items-center gap-1.5">
            <Button
              size="sm"
              variant="secondary"
              data-testid="figure-run"
              disabled={!script.trim() || busy !== null}
              loading={busy === "run"}
              onClick={() => {
                void run("run");
              }}
            >
              <Play className="size-3.5" aria-hidden />
              运行
            </Button>
            <Button size="sm" variant="ghost" disabled={!script} onClick={exportScript}>
              <Download className="size-3.5" aria-hidden />
              脚本
            </Button>
          </div>
        </header>

        <div className="min-h-0 flex-1">
          {script ? (
            <ScriptEditor
              value={script}
              language={LANGUAGE[kind]}
              ariaLabel={`${FIGURE_LABEL[kind]} 脚本编辑器`}
              onChange={(value) => {
                setScript(value);
                setDirty(true);
              }}
            />
          ) : (
            <EmptyState
              title="还没有脚本"
              description="描述你需要的图，选择类型后生成；脚本会在这里可编辑，并在右侧实时预览。"
              icon={<ImageIcon className="size-6" aria-hidden />}
            />
          )}
        </div>
      </section>

      <aside className="flex w-[380px] shrink-0 flex-col border-l border-border bg-surface" data-testid="figure-preview">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-3">
          <h2 className="text-[var(--text-sm)] font-medium text-ink">实时预览</h2>
          <span className="text-[var(--text-xs)] text-ink-2">
            {kind === "mermaid" ? "浏览器渲染" : "沙箱渲染"}
          </span>
          <div className="ml-auto flex gap-1">
            <Button size="sm" variant="ghost" disabled={!canSvg} onClick={exportSvg} data-testid="figure-export-svg">
              SVG
            </Button>
            <Button size="sm" variant="ghost" disabled={!canPng} onClick={() => { void exportPng(); }} data-testid="figure-export-png">
              PNG
            </Button>
          </div>
        </div>

        <div className="app-scroll min-h-0 flex-1 p-3">
          {kind === "mermaid" && svg ? (
            <div
              className="overflow-x-auto rounded-card border border-border bg-white p-3"
              data-testid="figure-svg"
              // Mermaid runs with securityLevel "strict"; the SVG is generated locally.
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          ) : previewSrc ? (
            <img src={previewSrc} alt={`${FIGURE_LABEL[kind]} 渲染结果`} data-testid="figure-image" className="w-full rounded-card border border-border" />
          ) : (
            <div className="flex h-full items-center justify-center">
              <EmptyState title="暂无预览" description="生成或运行脚本后，这里会显示渲染结果。" />
            </div>
          )}

          {errors.length > 0 && (
            <div className="mt-3 rounded-card border border-danger/40 bg-danger/5 p-3" data-testid="figure-errors">
              <p className="text-[var(--text-sm)] font-medium text-danger-text">运行报错</p>
              <ul className="mt-1.5 space-y-1 text-[var(--text-xs)] leading-relaxed text-ink-2">
                {errors.map((item, index) => (
                  <li key={`${index}-${item.slice(0, 16)}`}>{item}</li>
                ))}
              </ul>
              <Button
                size="sm"
                variant="secondary"
                className="mt-2"
                data-testid="figure-repair"
                disabled={busy !== null || !description.trim()}
                loading={busy === "repair"}
                onClick={() => {
                  void repair();
                }}
              >
                <Wrench className="size-3.5" aria-hidden />
                让 Agent 修复
              </Button>
            </div>
          )}

          {result && result.notes.length > 0 && (
            <ul className={cn("mt-3 space-y-1 rounded-card border border-border p-3 text-[var(--text-xs)] text-ink-2")}>
              {result.notes.map((note, index) => (
                <li key={`${index}-${note.slice(0, 12)}`}>{note}</li>
              ))}
            </ul>
          )}
        </div>
      </aside>
    </div>
  );
}
