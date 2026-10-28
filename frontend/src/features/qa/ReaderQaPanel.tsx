import { useMemo } from "react";

import { QaChat } from "./QaChat";
import type { QaAnchor, QaScope } from "./api";

export interface ReaderQaPanelProps {
  docId: string;
  docTitle: string;
  onOpenAnchor: (anchor: QaAnchor) => void;
}

/** The reader's 问答 tab: the same chat, scoped to the open paper (02 §4.2). */
export function ReaderQaPanel({ docId, docTitle, onOpenAnchor }: ReaderQaPanelProps) {
  const scope = useMemo<QaScope>(() => ({ type: "doc", doc_ids: [docId] }), [docId]);
  const titles = useMemo(() => ({ [docId]: docTitle }), [docId, docTitle]);
  return (
    <QaChat
      scope={scope}
      mode="qa"
      docTitles={titles}
      onOpenAnchor={onOpenAnchor}
      compact
    />
  );
}
