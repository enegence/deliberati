import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ChatInterface from '../ChatInterface';
import { buildBaseProps } from './fixtures.jsx';

const overviewFixture = {
  conversation_id: 'conv-1',
  title: 'Test conversation',
  message_count: 2,
  memory: null,
  memory_pending: false,
  turn_index_pending: false,
  turn_index: [
    {
      turn_number: 1,
      role: 'user',
      created_at: '2026-07-01T00:00:00Z',
      short_highlight: 'What is the answer?',
      transcript_offset: { message_index: 0 },
    },
    {
      turn_number: 2,
      role: 'assistant',
      created_at: '2026-07-01T00:01:00Z',
      short_highlight: 'The final verdict.',
      transcript_offset: { message_index: 1 },
    },
  ],
};

beforeEach(() => {
  window.localStorage.clear(); // overview must start expanded
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

describe('turn index stage links', () => {
  it('renders stage links for assistant entries only', () => {
    render(<ChatInterface {...buildBaseProps({ conversationOverview: overviewFixture })} />);
    expect(screen.getByRole('button', { name: 'Jump to turn 2 rankings' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Jump to turn 1 rankings' })).toBeNull();
  });

  it('scrolls to the stage anchor when a link is clicked', () => {
    render(<ChatInterface {...buildBaseProps({ conversationOverview: overviewFixture })} />);
    const stage2Anchor = document.getElementById('conversation-message-1-stage2');
    stage2Anchor.scrollIntoView = vi.fn();
    fireEvent.click(screen.getByRole('button', { name: 'Jump to turn 2 rankings' }));
    expect(stage2Anchor.scrollIntoView).toHaveBeenCalledTimes(1);
  });
});
