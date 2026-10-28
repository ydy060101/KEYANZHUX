/** Save a data/object URL or a remote URL through a temporary anchor. */
export function downloadHref(name: string, href: string, revoke = false): void {
  const link = document.createElement("a");
  link.href = href;
  link.download = name;
  link.click();
  if (revoke) window.setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export function downloadText(name: string, body: string, mime = "text/plain;charset=utf-8"): void {
  downloadHref(name, URL.createObjectURL(new Blob([body], { type: mime })), true);
}
