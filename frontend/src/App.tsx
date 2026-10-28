import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./app/AppShell";
import { LibraryPage } from "./features/library/LibraryPage";
import { ReaderEmbed } from "./features/reader/ReaderEmbed";
import { ReaderPage } from "./features/reader/ReaderPage";
import { QAPage } from "./features/qa/QAPage";
import { DiscoverPage } from "./features/discover/DiscoverPage";
import { GraphPage } from "./features/graph/GraphPage";
import { WritingPage } from "./features/writing/WritingPage";

export function App() {
  return (
    <Routes>
      {/* Outside the shell: the QA split pane embeds only the page, not a
          second navigation rail and top bar. */}
      <Route path="/embed/reader/:docId" element={<ReaderEmbed />} />
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/library" replace />} />
        <Route path="/library" element={<LibraryPage />} />
        <Route path="/reader/:docId?" element={<ReaderPage />} />
        <Route path="/qa" element={<QAPage />} />
        <Route path="/discover" element={<DiscoverPage />} />
        <Route path="/graph/:graphId?" element={<GraphPage />} />
        <Route path="/writing" element={<WritingPage />} />
        <Route path="*" element={<Navigate to="/library" replace />} />
      </Route>
    </Routes>
  );
}
