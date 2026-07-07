export const STAGE_LABELS = {
  prompt: 'Question',
  stage1: 'Responses',
  stage2: 'Rankings',
  stage3: 'Verdict',
};

const ASSISTANT_STAGE_KEYS = ['stage1', 'stage2', 'stage3'];

export function buildStageAnchorId(messageIndex, stageKey) {
  return stageKey === 'prompt'
    ? `conversation-message-${messageIndex}`
    : `conversation-message-${messageIndex}-${stageKey}`;
}

function buildStage(stageKey, messageIndex) {
  return {
    key: stageKey,
    label: STAGE_LABELS[stageKey],
    messageIndex,
    anchorId: buildStageAnchorId(messageIndex, stageKey),
  };
}

export function buildStageNavModel(messages) {
  const turns = [];
  let currentTurn = null;

  (messages || []).forEach((message, messageIndex) => {
    if (message.role === 'user') {
      currentTurn = {
        turnNumber: turns.length + 1,
        promptIndex: messageIndex,
        responseIndex: null,
        stages: [buildStage('prompt', messageIndex)],
      };
      turns.push(currentTurn);
      return;
    }

    if (!currentTurn || currentTurn.responseIndex !== null) {
      currentTurn = {
        turnNumber: turns.length + 1,
        promptIndex: null,
        responseIndex: null,
        stages: [],
      };
      turns.push(currentTurn);
    }

    currentTurn.responseIndex = messageIndex;
    ASSISTANT_STAGE_KEYS.forEach((stageKey) => {
      if (message[stageKey]) {
        currentTurn.stages.push(buildStage(stageKey, messageIndex));
      }
    });
  });

  return turns;
}

export function findActiveTurnIndex(navModel, anchorTops, viewportTop) {
  let activeIndex = 0;

  navModel.forEach((turn, turnIndex) => {
    const firstStage = turn.stages[0];
    if (!firstStage) {
      return;
    }

    const top = anchorTops.get(firstStage.anchorId);
    if (typeof top === 'number' && top <= viewportTop + 8) {
      activeIndex = turnIndex;
    }
  });

  return activeIndex;
}
