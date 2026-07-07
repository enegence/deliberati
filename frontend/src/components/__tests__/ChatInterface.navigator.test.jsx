import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ChatInterface from '../ChatInterface';
import { buildBaseProps } from './fixtures.jsx';

describe('ChatInterface stage navigator integration', () => {
  it('shows the navigator in conversation view when a transcript is loaded', () => {
    render(<ChatInterface {...buildBaseProps()} />);
    expect(
      screen.getByRole('navigation', { name: 'Turn and stage navigation' })
    ).toBeInTheDocument();
  });

  it('hides the navigator when no transcript is loaded', () => {
    render(<ChatInterface {...buildBaseProps({ conversation: null })} />);
    expect(
      screen.queryByRole('navigation', { name: 'Turn and stage navigation' })
    ).toBeNull();
  });

  it('hides the navigator in workbook view', async () => {
    const user = userEvent.setup();
    render(<ChatInterface {...buildBaseProps()} />);
    await user.click(screen.getByRole('tab', { name: 'Workbook' }));
    expect(
      screen.queryByRole('navigation', { name: 'Turn and stage navigation' })
    ).toBeNull();
  });
});
