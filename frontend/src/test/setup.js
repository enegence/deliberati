import '@testing-library/jest-dom/vitest';

// jsdom does not implement scrollIntoView; components under test call it.
if (!window.HTMLElement.prototype.scrollIntoView) {
  window.HTMLElement.prototype.scrollIntoView = () => {};
}
