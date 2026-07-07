import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useRef } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import StageNavigator from '../StageNavigator';

const fullAssistant = {
  role: 'assistant',
  stage1: [{ model: 'm/a', response: 'r' }],
  stage2: [{ model: 'm/a', ranking: 'FINAL RANKING:\n1. Response A' }],
  stage3: { model: 'm/chair', response: 'final' },
};

const twoTurnMessages = [
  { role: 'user', content: 'q1' },
  fullAssistant,
  { role: 'user', content: 'q2' },
  fullAssistant,
];

function Harness({ messages }) {
  const scrollRef = useRef(null);
  return (
    <div>
      <div ref={scrollRef} data-testid="scroll-container">
        {messages.map((message, index) => (
          <div key={index}>
            <div id={`conversation-message-${index}`} />
            {message.role === 'assistant' && (
              <>
                <div id={`conversation-message-${index}-stage1`} />
                <div id={`conversation-message-${index}-stage2`} />
                <div id={`conversation-message-${index}-stage3`} />
              </>
            )}
          </div>
        ))}
      </div>
      <StageNavigator messages={messages} scrollContainerRef={scrollRef} />
    </div>
  );
}

beforeEach(() => {
  // Fresh stub each test so per-element spies below don't leak between tests.
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

describe('StageNavigator', () => {
  it('renders nothing when there are no messages', () => {
    render(<Harness messages={[]} />);
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  it('shows stage buttons for the active turn', () => {
    render(<Harness messages={[twoTurnMessages[0], twoTurnMessages[1]]} />);
    expect(screen.getByRole('navigation', { name: 'Turn and stage navigation' })).toBeInTheDocument();
    expect(screen.getByText('Turn 1/1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Question' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Responses' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rankings' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Verdict' })).toBeInTheDocument();
  });

  it('scrolls to the matching stage anchor on click', () => {
    render(<Harness messages={[twoTurnMessages[0], twoTurnMessages[1]]} />);
    const stage2Anchor = document.getElementById('conversation-message-1-stage2');
    stage2Anchor.scrollIntoView = vi.fn();
    fireEvent.click(screen.getByRole('button', { name: 'Rankings' }));
    expect(stage2Anchor.scrollIntoView).toHaveBeenCalledTimes(1);
  });

  it('starts on the last turn in jsdom and moves back with the previous arrow', () => {
    // jsdom reports every rect at top 0, so the mount-time measurement marks
    // the LAST turn active (all anchors read as "at or above" the viewport top).
    render(<Harness messages={twoTurnMessages} />);
    expect(screen.getByText('Turn 2/2')).toBeInTheDocument();

    const turn1Prompt = document.getElementById('conversation-message-0');
    turn1Prompt.scrollIntoView = vi.fn();
    fireEvent.click(screen.getByRole('button', { name: 'Previous turn' }));
    expect(screen.getByText('Turn 1/2')).toBeInTheDocument();
    expect(turn1Prompt.scrollIntoView).toHaveBeenCalledTimes(1);
  });

  it('tracks the active turn from scroll position', () => {
    render(<Harness messages={twoTurnMessages} />);
    expect(screen.getByText('Turn 2/2')).toBeInTheDocument(); // jsdom mount state, see above

    const container = screen.getByTestId('scroll-container');
    container.getBoundingClientRect = () => ({ top: 0 });
    // Both prompts sit BELOW the viewport top -> turn 1 becomes active again.
    document.getElementById('conversation-message-0').getBoundingClientRect = () => ({ top: 40 });
    document.getElementById('conversation-message-2').getBoundingClientRect = () => ({ top: 900 });

    fireEvent.scroll(container);
    expect(screen.getByText('Turn 1/2')).toBeInTheDocument();
  });
});
