import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, HashRouter } from "react-router-dom";

import { AppRouter } from "./app/router";
import { isDemoMode } from "./demo/mode";
import "./styles/theme.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Missing root element");
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
});

async function mount() {
  if (isDemoMode) {
    const { enableDemoLinks, startDemoBrowser } = await import("./demo/browser");
    await startDemoBrowser();
    enableDemoLinks();
  }
  const Router = isDemoMode ? HashRouter : BrowserRouter;
  createRoot(rootElement!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <Router><AppRouter /></Router>
      </QueryClientProvider>
    </StrictMode>,
  );
}

void mount().catch((error) => {
  rootElement.textContent = `演示站启动失败：${error instanceof Error ? error.message : String(error)}`;
});
