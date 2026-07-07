import { useEffect, useMemo, useState } from 'react';
import { buildStageNavModel, findActiveTurnIndex } from './stageNavModel';
import './StageNavigator.css';

export default function StageNavigator({ messages, scrollContainerRef }) {
  const navModel = useMemo(() => buildStageNavModel(messages), [messages]);
  const [activeTurnIndex, setActiveTurnIndex] = useState(0);

  useEffect(() => {
    const container = scrollContainerRef?.current;
    if (!container || navModel.length === 0) {
      return undefined;
    }

    const handleScroll = () => {
      const containerTop = container.getBoundingClientRect().top;
      const anchorTops = new Map();
      navModel.forEach((turn) => {
        const firstStage = turn.stages[0];
        if (!firstStage) {
          return;
        }
        const element = document.getElementById(firstStage.anchorId);
        if (element) {
          anchorTops.set(firstStage.anchorId, element.getBoundingClientRect().top);
        }
      });
      setActiveTurnIndex(findActiveTurnIndex(navModel, anchorTops, containerTop));
    };

    handleScroll();
    container.addEventListener('scroll', handleScroll, { passive: true });
    return () => container.removeEventListener('scroll', handleScroll);
  }, [scrollContainerRef, navModel]);

  if (navModel.length === 0) {
    return null;
  }

  const clampedIndex = Math.min(activeTurnIndex, navModel.length - 1);
  const activeTurn = navModel[clampedIndex];

  const jumpToAnchor = (anchorId) => {
    document.getElementById(anchorId)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const goToTurn = (turnIndex) => {
    const turn = navModel[turnIndex];
    if (!turn || turn.stages.length === 0) {
      return;
    }
    setActiveTurnIndex(turnIndex);
    jumpToAnchor(turn.stages[0].anchorId);
  };

  return (
    <nav className="stage-navigator" aria-label="Turn and stage navigation">
      <div className="stage-navigator-turn-row">
        <button
          type="button"
          className="stage-navigator-arrow"
          onClick={() => goToTurn(clampedIndex - 1)}
          disabled={clampedIndex === 0}
          aria-label="Previous turn"
        >
          ▲
        </button>
        <span className="stage-navigator-turn-label">
          Turn {activeTurn.turnNumber}/{navModel.length}
        </span>
        <button
          type="button"
          className="stage-navigator-arrow"
          onClick={() => goToTurn(clampedIndex + 1)}
          disabled={clampedIndex >= navModel.length - 1}
          aria-label="Next turn"
        >
          ▼
        </button>
      </div>
      <div className="stage-navigator-stages">
        {activeTurn.stages.map((stage) => (
          <button
            key={stage.anchorId}
            type="button"
            className={`stage-navigator-stage stage-navigator-stage-${stage.key}`}
            onClick={() => jumpToAnchor(stage.anchorId)}
          >
            {stage.label}
          </button>
        ))}
      </div>
    </nav>
  );
}
