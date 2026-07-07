import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// vitest runs without injected globals, so testing-library's automatic
// afterEach cleanup never registers; wire it up explicitly.
afterEach(cleanup);

// jsdom does not implement scrollIntoView; components under test call it.
if (!window.HTMLElement.prototype.scrollIntoView) {
  window.HTMLElement.prototype.scrollIntoView = () => {};
}
