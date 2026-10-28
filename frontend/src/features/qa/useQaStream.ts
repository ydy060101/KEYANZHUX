import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";

import { askQuestion, type QaEvent, type QaMode, type QaScope, type QaTurn } from "./api";
import { newId } from "./history";

/** Fold one SSE event into the turn it belongs to. */
function applyEvent(
  event: QaEvent,
  id: string,
  setTurns: Dispatch<SetStateAction<QaTurn[]>>,
  state: { settled: boolean },
): void {
  if (event.type === "token") {
    setTurns((prev) =>
      prev.map((item) => (item.id === id ? { ...item, answer: item.answer + event.text } : item)),
    );
    return;
  }
  if (event.type === "anchor") {
    setTurns((prev) =>
      prev.map((item) => {
        if (item.id !== id || item.citations.some((c) => c.marker === event.marker)) return item;
        return {
          ...item,
          citations: [
            ...item.citations,
            { marker: event.marker, anchor: event.anchor, quote: event.quote },
          ],
        };
      }),
    );
    return;
  }
  state.settled = true;
  if (event.type === "done") {
    const data = event.data;
    setTurns((prev) =>
      prev.map((item) =>
        item.id === id
          ? {
              ...item,
              answer: data.answer,
              citations: data.citations,
              refused: data.refused,
              flags: data.flags,
              status: "done",
              ...(data.table ? { table: data.table } : {}),
              ...(data.documents ? { documents: data.documents } : {}),
            }
          : item,
      ),
    );
    return;
  }
  setTurns((prev) =>
    prev.map((item) => (item.id === id ? { ...item, status: "error", error: event.message } : item)),
  );
}

export interface QaStreamOptions {
  scope: QaScope;
  mode: QaMode;
  blocked: boolean;
  initialTurns?: QaTurn[];
  onTurnsChange?: (turns: QaTurn[]) => void;
}

/**
 * The conversation state behind `QaChat`: ask, stream, abort, and hand each
 * completed turn to the caller's history. Kept out of the component so the
 * page file stays inside H14's line budget.
 */
export function useQaStream({
  scope,
  mode,
  blocked,
  initialTurns = [],
  onTurnsChange,
}: QaStreamOptions) {
  const [turns, setTurns] = useState<QaTurn[]>(initialTurns);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const persisted = useRef("");

  useEffect(() => {
    const last = [...turns].reverse().find((turn) => turn.status !== "streaming");
    if (!last || persisted.current === last.id) return;
    persisted.current = last.id;
    onTurnsChange?.(turns);
  }, [turns, onTurnsChange]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const ask = (raw: string) => {
    const question = raw.trim();
    if (!question || streaming || blocked) return;
    const id = newId();
    const turn: QaTurn = {
      id,
      question,
      answer: "",
      citations: [],
      refused: false,
      flags: [],
      status: "streaming",
      createdAt: new Date().toISOString(),
    };
    setTurns((prev) => [...prev, turn]);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    // An object, not a `let`: TypeScript cannot see an assignment made inside
    // the event callback and would call the after-await guard dead code.
    const state = { settled: false };
    const run = async () => {
      try {
        await askQuestion(
          { question, scope, mode },
          (event) => {
            applyEvent(event, id, setTurns, state);
          },
          controller.signal,
        );
        if (!state.settled && !controller.signal.aborted) {
          setTurns((prev) =>
            prev.map((item) =>
              item.id === id
                ? { ...item, status: "error", error: "流式连接已结束，回答可能不完整" }
                : item,
            ),
          );
        }
      } catch (error: unknown) {
        const message = controller.signal.aborted
          ? "已停止生成"
          : error instanceof Error
            ? error.message
            : "问答失败";
        setTurns((prev) =>
          prev.map((item) => (item.id === id ? { ...item, status: "error", error: message } : item)),
        );
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
          setStreaming(false);
        }
      }
    };
    void run();
  };

  const stop = () => {
    abortRef.current?.abort();
  };

  return { turns, streaming, ask, stop };
}
