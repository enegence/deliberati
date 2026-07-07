import { describe, it, expect } from 'vitest';
import {
  buildStageAnchorId,
  buildStageNavModel,
  findActiveTurnIndex,
} from '../stageNavModel';

const fullAssistant = {
  role: 'assistant',
  stage1: [{ model: 'm/a', response: 'r' }],
  stage2: [{ model: 'm/a', ranking: 'FINAL RANKING:\n1. Response A' }],
  stage3: { model: 'm/chair', response: 'final' },
};

describe('buildStageAnchorId', () => {
  it('uses the message anchor for prompts and suffixed anchors for stages', () => {
    expect(buildStageAnchorId(0, 'prompt')).toBe('conversation-message-0');
    expect(buildStageAnchorId(3, 'stage2')).toBe('conversation-message-3-stage2');
  });
});

describe('buildStageNavModel', () => {
  it('pairs a user prompt with its assistant stages as one turn', () => {
    const model = buildStageNavModel([
      { role: 'user', content: 'q1' },
      fullAssistant,
    ]);
    expect(model).toHaveLength(1);
    expect(model[0].turnNumber).toBe(1);
    expect(model[0].promptIndex).toBe(0);
    expect(model[0].responseIndex).toBe(1);
    expect(model[0].stages.map((s) => s.key)).toEqual([
      'prompt', 'stage1', 'stage2', 'stage3',
    ]);
    expect(model[0].stages[2].anchorId).toBe('conversation-message-1-stage2');
  });

  it('creates one entry per question in a multi-turn conversation', () => {
    const model = buildStageNavModel([
      { role: 'user', content: 'q1' },
      fullAssistant,
      { role: 'user', content: 'q2' },
      fullAssistant,
    ]);
    expect(model).toHaveLength(2);
    expect(model[1].turnNumber).toBe(2);
    expect(model[1].promptIndex).toBe(2);
    expect(model[1].stages[1].anchorId).toBe('conversation-message-3-stage1');
  });

  it('omits stages that have not completed yet', () => {
    const model = buildStageNavModel([
      { role: 'user', content: 'q1' },
      { role: 'assistant', stage1: [{ model: 'm/a', response: 'r' }], stage2: null, stage3: null },
    ]);
    expect(model[0].stages.map((s) => s.key)).toEqual(['prompt', 'stage1']);
  });

  it('handles an in-flight turn with no assistant stages yet', () => {
    const model = buildStageNavModel([
      { role: 'user', content: 'q1' },
    ]);
    expect(model).toHaveLength(1);
    expect(model[0].stages.map((s) => s.key)).toEqual(['prompt']);
  });

  it('returns an empty model for empty or missing messages', () => {
    expect(buildStageNavModel([])).toEqual([]);
    expect(buildStageNavModel(undefined)).toEqual([]);
  });
});

describe('findActiveTurnIndex', () => {
  const navModel = buildStageNavModel([
    { role: 'user', content: 'q1' },
    fullAssistant,
    { role: 'user', content: 'q2' },
    fullAssistant,
  ]);

  it('picks the last turn whose first anchor has scrolled to/above the viewport top', () => {
    const tops = new Map([
      ['conversation-message-0', -300],
      ['conversation-message-2', -10],
    ]);
    expect(findActiveTurnIndex(navModel, tops, 0)).toBe(1);
  });

  it('stays on the first turn before any scrolling', () => {
    const tops = new Map([
      ['conversation-message-0', 40],
      ['conversation-message-2', 900],
    ]);
    expect(findActiveTurnIndex(navModel, tops, 0)).toBe(0);
  });

  it('ignores anchors with no measured position', () => {
    expect(findActiveTurnIndex(navModel, new Map(), 0)).toBe(0);
  });
});
