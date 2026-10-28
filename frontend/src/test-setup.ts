import "@testing-library/jest-dom/vitest";

// jsdom lacks matchMedia; the theme store reads it on boot.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});

// jsdom does not implement scrollIntoView; reference cards use it when selected.
Element.prototype.scrollIntoView = () => undefined;
