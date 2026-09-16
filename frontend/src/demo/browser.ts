import { setupWorker } from "msw/browser";

import { createDemoHandlers, resetDemoState } from "./handlers";

const worker = setupWorker(...createDemoHandlers());

export async function startDemoBrowser() {
  await worker.start({
    onUnhandledRequest(request, print) {
      if (new URL(request.url).pathname.startsWith("/api/")) print.error();
    },
    serviceWorker: { url: `${import.meta.env.BASE_URL}mockServiceWorker.js` },
  });
}

export function resetDemoBrowser() {
  resetDemoState();
  window.location.hash = "#/";
  window.location.reload();
}

export function enableDemoLinks() {
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const link = target.closest("a[href]");
    if (!link || link.hasAttribute("download") || event.metaKey || event.ctrlKey || event.shiftKey) return;
    const href = link.getAttribute("href");
    if (!href?.startsWith("/") || href.startsWith("//") || href.startsWith("/api/")) return;
    event.preventDefault();
    window.location.hash = `#${href}`;
  });
}
