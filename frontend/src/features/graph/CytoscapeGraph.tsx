import cytoscape from "cytoscape";
import { useEffect, useMemo, useRef } from "react";

import { useTheme } from "@/design/theme";
import type { GraphLayout, GraphView } from "@/features/graph/api";

interface Colors {
  primary: string;
  accent: string;
  middle: string;
  ink: string;
  border: string;
  surface: string;
}

function readColors(): Colors {
  if (typeof document === "undefined") {
    return { primary: "#4f46e5", accent: "#14b8a6", middle: "#475569", ink: "#0f172a", border: "#e3e7f0", surface: "#fff" };
  }
  const css = getComputedStyle(document.documentElement);
  const value = (name: string, fallback: string): string => css.getPropertyValue(name).trim() || fallback;
  return {
    primary: value("--primary", "#4f46e5"),
    accent: value("--accent", "#14b8a6"),
    middle: value("--ink-2", "#475569"),
    ink: value("--ink", "#0f172a"),
    border: value("--border", "#e3e7f0"),
    surface: value("--surface", "#ffffff"),
  };
}

function stylesheet(colors: Colors): cytoscape.StylesheetJsonBlock[] {
  return [
    {
      selector: "node",
      style: {
        label: "data(label)",
        "font-size": 10,
        color: colors.ink,
        "text-valign": "bottom",
        "text-halign": "center",
        "text-margin-y": 6,
        "text-wrap": "wrap",
        "text-max-width": "96px",
        "text-background-color": colors.surface,
        "text-background-opacity": 0.72,
        "text-background-padding": "2px",
        width: "data(size)",
        height: "data(size)",
        "background-color": colors.middle,
        "border-width": 1.5,
        "border-color": colors.surface,
        "overlay-opacity": 0,
      },
    },
    { selector: 'node[role = "cornerstone"]', style: { "background-color": colors.primary } },
    { selector: 'node[role = "middle"]', style: { "background-color": colors.middle } },
    { selector: 'node[role = "peripheral"]', style: { "background-color": colors.accent } },
    {
      selector: "node:selected",
      style: { "border-width": 3, "border-color": colors.primary, "border-opacity": 1 },
    },
    { selector: "node.faded", style: { opacity: 0.18 } },
    {
      selector: "edge",
      style: {
        width: 1.3,
        "line-color": colors.middle,
        "target-arrow-color": colors.middle,
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.75,
        "curve-style": "bezier",
        opacity: 0.55,
      },
    },
    { selector: "edge.faded", style: { opacity: 0.06 } },
    {
      selector: "edge.highlight",
      style: {
        width: 2,
        "line-color": colors.primary,
        "target-arrow-color": colors.primary,
        opacity: 1,
      },
    },
  ];
}

function elements(graph: GraphView): cytoscape.ElementDefinition[] {
  const nodes = graph.nodes.map((node) => ({
    data: {
      id: node.id,
      // Long titles would cover the canvas; the detail panel has the full one.
      label: node.title.length > 46 ? `${node.title.slice(0, 45)}…` : node.title,
      year: node.year,
      role: node.role,
      pagerank: node.pagerank,
      size: 24 + Math.min(1, node.pagerank * 1.5) * 44,
    },
  }));
  const edges = graph.edges.map((edge) => ({
    data: { id: `${edge.source}->${edge.target}`, source: edge.source, target: edge.target },
  }));
  return [...nodes, ...edges];
}

/** Time flows left→right; nodes of one year stack by PageRank. */
function timelineLayout(cy: cytoscape.Core): cytoscape.Layouts {
  const visible = cy.nodes(":visible");
  const positions: Record<string, { x: number; y: number }> = {};
  const years: number[] = [];
  visible.forEach((node) => {
    const year: unknown = node.data("year");
    if (typeof year === "number") years.push(year);
  });
  const min = years.length > 0 ? Math.min(...years) : 0;
  const max = years.length > 0 ? Math.max(...years) : 0;
  const width = Math.max(320, cy.width() - 180);
  const byYear = new Map<number, cytoscape.NodeSingular[]>();
  const unknown: cytoscape.NodeSingular[] = [];
  visible.forEach((node) => {
    const year: unknown = node.data("year");
    if (typeof year !== "number") {
      unknown.push(node);
      return;
    }
    const row = byYear.get(year) ?? [];
    row.push(node);
    byYear.set(year, row);
  });
  for (const [year, row] of [...byYear.entries()].sort((a, b) => a[0] - b[0])) {
    row.sort((a, b) => Number(b.data("pagerank")) - Number(a.data("pagerank")));
    const x = max === min ? width / 2 + 90 : 90 + ((year - min) / (max - min)) * width;
    row.forEach((node, index) => {
      positions[node.id()] = { x, y: 110 + index * 58 };
    });
  }
  unknown.forEach((node, index) => {
    positions[node.id()] = { x: 90 + index * 58, y: cy.height() - 70 };
  });
  return cy.layout({ name: "preset", positions, fit: true, padding: 40, animate: false });
}

function forceLayout(cy: cytoscape.Core): cytoscape.Layouts {
  return cy.layout({
    name: "cose",
    animate: false,
    fit: true,
    padding: 40,
    randomize: false,
    nodeRepulsion: 9000,
    idealEdgeLength: 110,
    gravity: 60,
    numIter: 800,
  });
}

/** A three-node graph would otherwise fill the screen at 3× zoom. */
function fitAndClamp(cy: cytoscape.Core, layout: GraphLayout): void {
  (layout === "timeline" ? timelineLayout(cy) : forceLayout(cy)).run();
  if (cy.zoom() > 1.3) {
    cy.zoom(1.3);
    cy.center();
  }
}

interface Props {
  graph: GraphView;
  selectedId: string | null;
  visibleIds: Set<string>;
  layout: GraphLayout;
  onSelect: (id: string | null) => void;
  /** The page keeps the instance so it can export a PNG. */
  onCore: (core: cytoscape.Core | null) => void;
}

/**
 * The Cytoscape canvas (02 §4.5).
 *
 * Node size is PageRank and colour is the role, so the picture itself carries
 * the analysis. Hovering a node fades everything outside its closed
 * neighbourhood; clicking selects it for the detail panel. Filters hide
 * elements rather than dropping them, so re-showing one keeps its layout.
 */
export function CytoscapeGraph({ graph, selectedId, visibleIds, layout, onSelect, onCore }: Props) {
  const container = useRef<HTMLDivElement | null>(null);
  const core = useRef<cytoscape.Core | null>(null);
  const selectRef = useRef(onSelect);
  const coreRef = useRef(onCore);
  const theme = useTheme((state) => state.resolved);
  selectRef.current = onSelect;
  coreRef.current = onCore;

  const definitions = useMemo(() => elements(graph), [graph]);

  useEffect(() => {
    const node = container.current;
    if (!node) return;
    const cy = cytoscape({
      container: node,
      style: stylesheet(readColors()),
      layout: { name: "preset" },
      boxSelectionEnabled: true,
      selectionType: "single",
      minZoom: 0.15,
      maxZoom: 3,
    });
    core.current = cy;
    coreRef.current(cy);
    if (import.meta.env.DEV) {
      (node as HTMLDivElement & { __cy?: cytoscape.Core }).__cy = cy;
    }

    cy.on("tap", "node", (event) => {
      selectRef.current((event.target as cytoscape.NodeSingular).id());
    });
    cy.on("tap", (event) => {
      if (event.target === cy) selectRef.current(null);
    });
    cy.on("mouseover", "node", (event) => {
      const node = event.target as cytoscape.NodeSingular;
      const neighbourhood = node.closedNeighborhood();
      cy.elements().not(neighbourhood).addClass("faded");
      neighbourhood.edges().addClass("highlight");
    });
    cy.on("mouseout", "node", () => {
      cy.elements().removeClass("faded").removeClass("highlight");
    });

    const observer = new ResizeObserver(() => {
      cy.resize();
    });
    observer.observe(node);

    return () => {
      observer.disconnect();
      delete (node as HTMLDivElement & { __cy?: cytoscape.Core }).__cy;
      coreRef.current(null);
      core.current = null;
      cy.destroy();
    };
  }, []);

  useEffect(() => {
    const cy = core.current;
    if (!cy) return;
    cy.elements().remove();
    cy.add(definitions);
  }, [definitions]);

  // Theme changes only need a restyle; the layout and selection survive.
  useEffect(() => {
    core.current?.style(stylesheet(readColors()));
  }, [theme]);

  useEffect(() => {
    const cy = core.current;
    if (!cy) return;
    // A selection animation still running would fight the new layout for the
    // viewport, leaving nodes outside the canvas.
    cy.stop();
    cy.nodes().forEach((node) => {
      node.style("display", visibleIds.has(node.id()) ? "element" : "none");
    });
    cy.edges().forEach((edge) => {
      const visible = visibleIds.has(edge.source().id()) && visibleIds.has(edge.target().id());
      edge.style("display", visible ? "element" : "none");
    });
    fitAndClamp(cy, layout);
  }, [definitions, layout, visibleIds]);

  useEffect(() => {
    const cy = core.current;
    if (!cy) return;
    cy.nodes().unselect();
    if (!selectedId) return;
    const node = cy.getElementById(selectedId);
    if (node.nonempty()) {
      node.select();
      cy.animate({ center: { eles: node } }, { duration: 200 });
    }
  }, [selectedId, definitions]);

  return <div ref={container} data-testid="graph-canvas" className="absolute inset-0" aria-label="引用关系图" role="img" />;
}
