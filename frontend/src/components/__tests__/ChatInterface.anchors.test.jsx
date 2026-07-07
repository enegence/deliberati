import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import ChatInterface from '../ChatInterface';
import { conversationFixture, buildBaseProps } from './fixtures.jsx';

describe('transcript stage anchors', () => {
  it('exposes ids for the message and each completed stage', () => {
    render(<ChatInterface {...buildBaseProps()} />);
    expect(document.getElementById('conversation-message-0')).not.toBeNull();
    expect(document.getElementById('conversation-message-1-stage1')).not.toBeNull();
    expect(document.getElementById('conversation-message-1-stage2')).not.toBeNull();
    expect(document.getElementById('conversation-message-1-stage3')).not.toBeNull();
  });

  it('omits stage anchors that have not completed', () => {
    const loadingConversation = {
      ...conversationFixture,
      messages: [
        conversationFixture.messages[0],
        { role: 'assistant', created_at: '2026-07-01T00:01:00Z', stage1: null, stage2: null, stage3: null, loading: { stage1: true, stage2: false, stage3: false } },
      ],
    };
    render(<ChatInterface {...buildBaseProps({ conversation: loadingConversation })} />);
    expect(document.getElementById('conversation-message-1-stage1')).toBeNull();
  });
});
