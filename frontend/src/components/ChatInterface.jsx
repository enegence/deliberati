import { useEffect, useRef, useState } from 'react';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import HighlightedMarkdown from './HighlightedMarkdown';
import { renderHighlightedText } from './SearchHighlightText';
import './ChatInterface.css';

const EMPTY_ARRAY = [];
const EMPTY_USAGE_SUMMARY = {
  request_count: 0,
  prompt_tokens: 0,
  completion_tokens: 0,
  total_tokens: 0,
  reasoning_tokens: 0,
  cached_tokens: 0,
  cache_write_tokens: 0,
  audio_tokens: 0,
  cost: null,
  upstream_inference_cost: null,
  cost_request_count: 0,
  cost_missing_request_count: 0,
  currency: 'usd',
  providers: EMPTY_ARRAY,
  assistant_turns_with_usage: 0,
};

function stripOverviewFormatting(text) {
  if (!text) {
    return '';
  }

  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line
      .replace(/^#{1,6}\s+/, '')
      .replace(/^>\s+/, '')
      .replace(/^[-*+]\s+/, '')
      .replace(/^\d+(?:\.\d+){0,4}[.):-]?\s+/, '')
      .replace(/[`*_~]+/g, '')
      .trim())
    .filter(Boolean)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function buildOverviewSections(memory) {
  if (!memory) {
    return [];
  }

  const summaryJson = memory.summary_json || {};
  const currentGoal = stripOverviewFormatting(
    summaryJson.current_goal || summaryJson.latest_user_request || summaryJson.user_objective || ''
  );
  const objective = stripOverviewFormatting(summaryJson.user_objective || '');
  const backgroundContext = (summaryJson.background_context_notes || [])
    .map(stripOverviewFormatting)
    .filter(Boolean);
  const constraints = (summaryJson.stable_constraints || summaryJson.persistent_constraints || [])
    .map(stripOverviewFormatting)
    .filter(Boolean);
  const decisions = (summaryJson.recent_decisions || summaryJson.recent_council_conclusions || [])
    .map(stripOverviewFormatting)
    .filter(Boolean);
  const openThreads = (summaryJson.open_threads || summaryJson.recent_user_requests || [])
    .map(stripOverviewFormatting)
    .filter((item) => item && item !== currentGoal);
  const activeBundle = stripOverviewFormatting(summaryJson.active_bundle?.name || '');

  const sections = [];
  if (currentGoal) {
    sections.push({ title: 'Current goal', kind: 'text', content: currentGoal });
  }
  if (objective && objective !== currentGoal) {
    sections.push({ title: 'Original objective', kind: 'text', content: objective });
  }
  if (backgroundContext.length > 0) {
    sections.push({ title: 'Background context', kind: 'list', items: backgroundContext });
  }
  if (constraints.length > 0) {
    sections.push({ title: 'Stable constraints', kind: 'list', items: constraints });
  }
  if (decisions.length > 0) {
    sections.push({ title: 'Recent decisions', kind: 'list', items: decisions });
  }
  if (openThreads.length > 0) {
    sections.push({ title: 'Open threads', kind: 'list', items: openThreads });
  }
  if (activeBundle) {
    sections.push({ title: 'Active bundle', kind: 'text', content: activeBundle });
  }

  if (sections.length === 0 && memory.summary_text) {
    const fallbackText = stripOverviewFormatting(memory.summary_text);
    if (fallbackText) {
      sections.push({ title: 'Conversation memory', kind: 'text', content: fallbackText });
    }
  }

  return sections;
}

function buildEntitySections(entityPayload) {
  const entries = entityPayload?.entities || [];
  if (entries.length === 0) {
    return [];
  }

  const themes = entries
    .filter((entry) => entry.link_type === 'theme')
    .map((entry) => entry.canonical_name);
  const namedEntities = entries
    .filter((entry) => entry.link_type === 'mentioned')
    .map((entry) => entry.canonical_name);
  const bundles = entries
    .filter((entry) => entry.link_type === 'uses_bundle')
    .map((entry) => entry.canonical_name);
  const models = entries
    .filter((entry) => entry.link_type === 'mentions_model')
    .map((entry) => entry.canonical_name);

  const sections = [];
  if (themes.length > 0) {
    sections.push({ title: 'Themes', items: themes });
  }
  if (namedEntities.length > 0) {
    sections.push({ title: 'Entities', items: namedEntities });
  }
  if (bundles.length > 0) {
    sections.push({ title: 'Bundles', items: bundles });
  }
  if (models.length > 0) {
    sections.push({ title: 'Models', items: models });
  }

  return sections;
}

function formatTurnTimestamp(value) {
  if (!value) {
    return '';
  }

  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) {
    return '';
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(timestamp);
}

function toFiniteNumber(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }

  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function summarizeConversationUsage(conversation) {
  if (!conversation?.messages?.length) {
    return EMPTY_USAGE_SUMMARY;
  }

  const providers = new Set();
  const summary = {
    ...EMPTY_USAGE_SUMMARY,
  };

  conversation.messages.forEach((message) => {
    const usageSummary = message?.metadata?.usage?.summary;
    if (!usageSummary) {
      return;
    }

    summary.assistant_turns_with_usage += 1;
    summary.request_count += toFiniteNumber(usageSummary.request_count) || 0;
    summary.prompt_tokens += toFiniteNumber(usageSummary.prompt_tokens) || 0;
    summary.completion_tokens += toFiniteNumber(usageSummary.completion_tokens) || 0;
    summary.total_tokens += toFiniteNumber(usageSummary.total_tokens) || 0;
    summary.reasoning_tokens += toFiniteNumber(usageSummary.reasoning_tokens) || 0;
    summary.cached_tokens += toFiniteNumber(usageSummary.cached_tokens) || 0;
    summary.cache_write_tokens += toFiniteNumber(usageSummary.cache_write_tokens) || 0;
    summary.audio_tokens += toFiniteNumber(usageSummary.audio_tokens) || 0;
    summary.cost_request_count += toFiniteNumber(usageSummary.cost_request_count) || 0;
    summary.cost_missing_request_count += toFiniteNumber(usageSummary.cost_missing_request_count) || 0;

    const cost = toFiniteNumber(usageSummary.cost);
    if (cost !== null) {
      summary.cost = (summary.cost ?? 0) + cost;
    }

    const upstreamCost = toFiniteNumber(usageSummary.upstream_inference_cost);
    if (upstreamCost !== null) {
      summary.upstream_inference_cost = (summary.upstream_inference_cost ?? 0) + upstreamCost;
    }

    (usageSummary.providers || []).forEach((provider) => {
      if (provider) {
        providers.add(provider);
      }
    });
  });

  return {
    ...summary,
    cost: summary.cost === null ? null : Number(summary.cost.toFixed(8)),
    upstream_inference_cost: summary.upstream_inference_cost === null
      ? null
      : Number(summary.upstream_inference_cost.toFixed(8)),
    providers: Array.from(providers).sort(),
  };
}

function formatUsageNumber(value) {
  const numeric = toFiniteNumber(value);
  if (numeric === null) {
    return '0';
  }

  return new Intl.NumberFormat().format(Math.round(numeric));
}

function formatUsageCurrency(value, currency = 'usd') {
  const numeric = toFiniteNumber(value);
  if (numeric === null) {
    return null;
  }

  if (String(currency).toLowerCase() === 'usd') {
    let fractionDigits = 2;
    if (Math.abs(numeric) < 0.01) {
      fractionDigits = 4;
    }
    if (Math.abs(numeric) < 0.0001) {
      fractionDigits = 6;
    }

    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(numeric);
  }

  return `${numeric.toFixed(4)} ${currency.toUpperCase()}`;
}

function ConversationUsageMeter({ summary }) {
  if (!summary) {
    return null;
  }

  const hasUsage = (summary.request_count ?? 0) > 0;
  const formattedCost = formatUsageCurrency(summary.cost, summary.currency);
  const formattedUpstreamCost = formatUsageCurrency(
    summary.upstream_inference_cost,
    summary.currency
  );

  return (
    <div className="conversation-usage-meter">
      <div className={`conversation-usage-stat conversation-usage-stat-primary ${hasUsage ? '' : 'muted'}`}>
        <span className="conversation-usage-label">Cost</span>
        <strong>{formattedCost || 'Unavailable'}</strong>
      </div>
      <div className={`conversation-usage-stat ${hasUsage ? '' : 'muted'}`}>
        <span className="conversation-usage-label">Tokens</span>
        <strong>{hasUsage ? formatUsageNumber(summary.total_tokens) : 'Unavailable'}</strong>
      </div>
      <div className={`conversation-usage-stat ${hasUsage ? '' : 'muted'}`}>
        <span className="conversation-usage-label">Requests</span>
        <strong>{hasUsage ? formatUsageNumber(summary.request_count) : 'Unavailable'}</strong>
      </div>
      {!hasUsage && (
        <div className="conversation-usage-note">
          Usage appears on new council runs. Older conversations do not have persisted cost data.
        </div>
      )}
      {hasUsage && formattedUpstreamCost && (
        <div className="conversation-usage-note">
          Upstream: {formattedUpstreamCost}
        </div>
      )}
      {hasUsage && summary.cost_missing_request_count > 0 && (
        <div className="conversation-usage-note">
          Cost missing for {formatUsageNumber(summary.cost_missing_request_count)} request{summary.cost_missing_request_count === 1 ? '' : 's'}
        </div>
      )}
    </div>
  );
}

function UsageIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M16 4h-3a2 2 0 0 0-2-2H9a2 2 0 0 0-2 2H4v16h12V4Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M9 4h2"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function buildStage1SelectionText(stage1) {
  return stage1
    .map((response, index) => (
      `Model ${index + 1}: ${response.model}\n\n${response.response}`
    ))
    .join('\n\n---\n\n');
}

function buildStage2SelectionText(stage2, metadata) {
  const rankingSections = stage2.map((ranking, index) => {
    const parsed = (ranking.parsed_ranking || []).length > 0
      ? `\n\nExtracted ranking:\n${ranking.parsed_ranking.map((label, parsedIndex) => `${parsedIndex + 1}. ${label}`).join('\n')}`
      : '';
    return `Ranking ${index + 1}: ${ranking.model}\n\n${ranking.ranking}${parsed}`;
  });

  const aggregate = (metadata?.aggregate_rankings || []).length > 0
    ? `\n\nAggregate rankings:\n${metadata.aggregate_rankings.map((entry, index) => (
        `${index + 1}. ${entry.model} (avg ${entry.average_rank.toFixed(2)}, ${entry.rankings_count} votes)`
      )).join('\n')}`
    : '';

  return `${rankingSections.join('\n\n---\n\n')}${aggregate}`;
}

function buildStage3SelectionText(stage3) {
  return `Chairman: ${stage3.model}\n\n${stage3.response}`;
}

function buildErrorSelectionText(error) {
  const attemptedModels = error.details?.attempted_models || error.attempted_models || [];
  return attemptedModels.length > 0
    ? `${error.message}\n\nAttempted: ${attemptedModels.join(', ')}`
    : error.message;
}

function getMessageClipSegments(message, messageIndex) {
  const turnNumber = messageIndex + 1;

  if (message.role === 'user') {
    return [{
      id: `segment:${messageIndex}:prompt`,
      sourceId: `conversation:${messageIndex}:prompt`,
      label: `Turn ${turnNumber} · Prompt`,
      text: message.content,
      messageIndex,
      order: 0,
    }];
  }

  const segments = [];

  if (message.stage1) {
    segments.push({
      id: `segment:${messageIndex}:stage1`,
      sourceId: `conversation:${messageIndex}:stage1`,
      label: `Turn ${turnNumber} · Stage 1`,
      text: buildStage1SelectionText(message.stage1),
      messageIndex,
      order: 1,
    });
  }

  if (message.stage2) {
    segments.push({
      id: `segment:${messageIndex}:stage2`,
      sourceId: `conversation:${messageIndex}:stage2`,
      label: `Turn ${turnNumber} · Stage 2`,
      text: buildStage2SelectionText(message.stage2, message.metadata),
      messageIndex,
      order: 2,
    });
  }

  if (message.stage3) {
    segments.push({
      id: `segment:${messageIndex}:stage3`,
      sourceId: `conversation:${messageIndex}:stage3`,
      label: `Turn ${turnNumber} · Final answer`,
      text: buildStage3SelectionText(message.stage3),
      messageIndex,
      order: 3,
    });
  }

  if (message.error?.message) {
    segments.push({
      id: `segment:${messageIndex}:error`,
      sourceId: `conversation:${messageIndex}:error`,
      label: `Turn ${turnNumber} · Error`,
      text: buildErrorSelectionText(message.error),
      messageIndex,
      order: 4,
    });
  }

  return segments;
}

function buildConversationExportMarkdown(conversation, overview) {
  const lines = [
    `# ${overview?.title || conversation?.title || 'Conversation'}`,
    '',
    `Exported: ${new Date().toLocaleString()}`,
  ];

  if (overview?.message_count || conversation?.messages?.length) {
    lines.push(`Messages: ${overview?.message_count || conversation.messages.length}`);
  }

  lines.push('');

  (conversation?.messages || []).forEach((message, index) => {
    lines.push(`## Turn ${index + 1} · ${message.role === 'user' ? 'User' : 'LLM Council'}`);
    if (formatTurnTimestamp(message.created_at)) {
      lines.push(`Time: ${formatTurnTimestamp(message.created_at)}`);
    }
    if (message.bundle?.name || message.metadata?.bundle?.name) {
      lines.push(`Bundle: ${message.bundle?.name || message.metadata?.bundle?.name}`);
    }
    lines.push('');

    if (message.role === 'user') {
      lines.push(message.content || '');
      lines.push('');
      return;
    }

    if (message.stage1) {
      lines.push('### Stage 1');
      lines.push('');
      lines.push(buildStage1SelectionText(message.stage1));
      lines.push('');
    }

    if (message.stage2) {
      lines.push('### Stage 2');
      lines.push('');
      lines.push(buildStage2SelectionText(message.stage2, message.metadata));
      lines.push('');
    }

    if (message.stage3) {
      lines.push('### Stage 3');
      lines.push('');
      lines.push(buildStage3SelectionText(message.stage3));
      lines.push('');
    }

    if (message.error?.message) {
      lines.push('### Error');
      lines.push('');
      lines.push(buildErrorSelectionText(message.error));
      lines.push('');
    }
  });

  return lines.join('\n');
}

function buildWorkbookExportMarkdown(title, items) {
  const lines = [
    `# ${title} Workbook`,
    '',
    `Exported: ${new Date().toLocaleString()}`,
    '',
  ];

  items.forEach((item, index) => {
    lines.push(`## ${index + 1}. ${item.label}`);
    lines.push('');
    lines.push(item.text || '');
    lines.push('');
  });

  return lines.join('\n');
}

function downloadTextFile(filename, contents) {
  const blob = new Blob([contents], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export default function ChatInterface({
  conversation,
  conversationSelected,
  conversationOverview,
  conversationEntities,
  workbookItems,
  requestedJumpTarget,
  activeSearchMatch,
  onSendMessage,
  onLoadTranscript,
  onClipSelectionsToWorkbook,
  onUpdateWorkbookItem,
  onDeleteWorkbookItem,
  isLoading,
  isOverviewLoading,
  overviewError,
  isEntitiesLoading,
  entitiesError,
  isTranscriptLoading,
  modelBundles,
  selectedBundleId,
  onSelectBundle,
}) {
  const [input, setInput] = useState('');
  const [viewMode, setViewMode] = useState('conversation');
  const [selectedClipIds, setSelectedClipIds] = useState({});
  const [isOverviewCollapsed, setIsOverviewCollapsed] = useState(() => {
    if (typeof window === 'undefined') {
      return false;
    }

    return window.localStorage.getItem('llm-council-overview-collapsed') === 'true';
  });
  const [overviewWidth, setOverviewWidth] = useState(() => {
    if (typeof window === 'undefined') {
      return 320;
    }

    const storedWidth = Number(window.localStorage.getItem('llm-council-overview-width'));
    return Number.isFinite(storedWidth) && storedWidth >= 260 && storedWidth <= 520
      ? storedWidth
      : 320;
  });
  const [isOverviewResizing, setIsOverviewResizing] = useState(false);
  const [highlightedMessageIndex, setHighlightedMessageIndex] = useState(null);
  const [isOverviewOverflowing, setIsOverviewOverflowing] = useState(false);
  const [showOverviewScrollUpHint, setShowOverviewScrollUpHint] = useState(false);
  const [showOverviewScrollDownHint, setShowOverviewScrollDownHint] = useState(false);
  const [isUsageOpen, setIsUsageOpen] = useState(false);
  const messagesEndRef = useRef(null);
  const pendingJumpIndexRef = useRef(null);
  const handledJumpRequestRef = useRef(null);
  const overviewPanelRef = useRef(null);
  const overviewScrollRef = useRef(null);
  const transcriptScrollRef = useRef(null);
  const selectionAnchorRef = useRef(null);
  const usagePopoverRef = useRef(null);

  const messageCount = conversationOverview?.message_count ?? conversation?.messages.length ?? 0;
  const turnIndex = conversationOverview?.turn_index ?? EMPTY_ARRAY;
  const summaryPending = Boolean(conversationOverview?.memory_pending);
  const turnIndexPending = Boolean(conversationOverview?.turn_index_pending);
  const overviewSections = buildOverviewSections(conversationOverview?.memory);
  const entitySections = buildEntitySections(conversationEntities);
  const currentConversationKey = conversation?.id || conversationOverview?.conversation_id || null;
  const liveUsageSummary = conversation ? summarizeConversationUsage(conversation) : null;
  const usageSummary = (
    liveUsageSummary && (
      liveUsageSummary.request_count > 0
      || liveUsageSummary.assistant_turns_with_usage > 0
      || !conversationOverview?.usage_summary
    )
  )
    ? liveUsageSummary
    : (conversationOverview?.usage_summary || EMPTY_USAGE_SUMMARY);
  const activeTranscriptSearch = (
    activeSearchMatch && activeSearchMatch.conversationId === currentConversationKey
  )
    ? activeSearchMatch
    : null;
  const selectedBundle = modelBundles.find((bundle) => bundle.id === selectedBundleId) || null;
  const selectedClipCount = Object.keys(selectedClipIds).length;

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const scrollToMessage = (messageIndex) => {
    const element = document.getElementById(`conversation-message-${messageIndex}`);
    element?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const scrollOverviewDown = () => {
    if (!overviewScrollRef.current) {
      return;
    }

    overviewScrollRef.current.scrollBy({
      top: Math.max(180, overviewScrollRef.current.clientHeight * 0.7),
      behavior: 'smooth',
    });
  };

  const scrollOverviewUp = () => {
    if (!overviewScrollRef.current) {
      return;
    }

    overviewScrollRef.current.scrollBy({
      top: -Math.max(180, overviewScrollRef.current.clientHeight * 0.7),
      behavior: 'smooth',
    });
  };

  const getTurnSelectionId = (messageIndex) => `turn:${messageIndex}`;
  const getIsTurnSelected = (messageIndex) => Boolean(selectedClipIds[getTurnSelectionId(messageIndex)]);
  const getIsSegmentSelected = (segmentId) => Boolean(selectedClipIds[segmentId]);

  const buildSelectableOrder = () => {
    if (conversation?.messages?.length) {
      const selectableIds = [];
      conversation.messages.forEach((message, messageIndex) => {
        selectableIds.push(getTurnSelectionId(messageIndex));
        getMessageClipSegments(message, messageIndex).forEach((segment) => {
          selectableIds.push(segment.id);
        });
      });
      return selectableIds;
    }

    return turnIndex
      .map((entry) => entry.transcript_offset?.message_index)
      .filter((messageIndex) => typeof messageIndex === 'number')
      .map((messageIndex) => getTurnSelectionId(messageIndex));
  };

  const shouldIgnoreSelectionClick = (event) => {
    if (event.defaultPrevented) {
      return true;
    }

    const selectedText = window.getSelection?.();
    if (selectedText && selectedText.type === 'Range' && selectedText.toString().trim()) {
      return true;
    }

    const interactiveAncestor = event.target.closest(
      'button, a, input, textarea, select, option, summary, [contenteditable="true"], [data-selection-ignore="true"]'
    );

    return Boolean(interactiveAncestor && interactiveAncestor !== event.currentTarget);
  };

  const applySelectionFromEvent = (targetId, event) => {
    const orderedIds = buildSelectableOrder();
    const isMetaSelection = event.metaKey || event.ctrlKey;
    const isShiftSelection = event.shiftKey;

    setSelectedClipIds((currentSelections) => {
      if (
        isShiftSelection &&
        selectionAnchorRef.current &&
        orderedIds.includes(selectionAnchorRef.current) &&
        orderedIds.includes(targetId)
      ) {
        const startIndex = orderedIds.indexOf(selectionAnchorRef.current);
        const endIndex = orderedIds.indexOf(targetId);
        const [rangeStart, rangeEnd] = startIndex < endIndex
          ? [startIndex, endIndex]
          : [endIndex, startIndex];
        const nextSelections = {};
        orderedIds.slice(rangeStart, rangeEnd + 1).forEach((id) => {
          nextSelections[id] = true;
        });
        return nextSelections;
      }

      if (isMetaSelection) {
        const nextSelections = { ...currentSelections };
        if (nextSelections[targetId]) {
          delete nextSelections[targetId];
        } else {
          nextSelections[targetId] = true;
        }
        return nextSelections;
      }

      return { [targetId]: true };
    });

    selectionAnchorRef.current = targetId;
    return !(isMetaSelection || isShiftSelection);
  };

  const handleSelectableClick = (targetId, event) => {
    if (shouldIgnoreSelectionClick(event)) {
      return false;
    }

    return applySelectionFromEvent(targetId, event);
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversation]);

  useEffect(() => {
    if (pendingJumpIndexRef.current === null || !conversation) {
      return;
    }

    scrollToMessage(pendingJumpIndexRef.current);
    pendingJumpIndexRef.current = null;
  }, [conversation]);

  useEffect(() => {
    if (
      !requestedJumpTarget ||
      handledJumpRequestRef.current === requestedJumpTarget.requestId ||
      typeof requestedJumpTarget.messageIndex !== 'number'
    ) {
      return;
    }

    handledJumpRequestRef.current = requestedJumpTarget.requestId;
    pendingJumpIndexRef.current = requestedJumpTarget.messageIndex;
    window.setTimeout(() => {
      setHighlightedMessageIndex(requestedJumpTarget.messageIndex);
    }, 0);

    if (!conversation) {
      onLoadTranscript();
      return;
    }

    scrollToMessage(requestedJumpTarget.messageIndex);
    pendingJumpIndexRef.current = null;
  }, [conversation, onLoadTranscript, requestedJumpTarget]);

  useEffect(() => {
    if (highlightedMessageIndex === null) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      setHighlightedMessageIndex((currentIndex) => (
        currentIndex === highlightedMessageIndex ? null : currentIndex
      ));
    }, 2600);

    return () => window.clearTimeout(timeoutId);
  }, [highlightedMessageIndex]);

  useEffect(() => {
    if (!isUsageOpen) {
      return undefined;
    }

    const handlePointerDown = (event) => {
      if (usagePopoverRef.current?.contains(event.target)) {
        return;
      }
      setIsUsageOpen(false);
    };

    window.addEventListener('pointerdown', handlePointerDown);
    return () => window.removeEventListener('pointerdown', handlePointerDown);
  }, [isUsageOpen]);

  useEffect(() => {
    if (!isOverviewResizing) {
      return undefined;
    }

    const handleMouseMove = (event) => {
      const workspace = overviewPanelRef.current?.closest('.conversation-workspace');
      if (!workspace) {
        return;
      }

      const bounds = workspace.getBoundingClientRect();
      const nextWidth = Math.min(520, Math.max(260, event.clientX - bounds.left));
      setOverviewWidth(nextWidth);
    };

    const handleMouseUp = () => {
      setIsOverviewResizing(false);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isOverviewResizing]);

  useEffect(() => {
    window.localStorage.setItem('llm-council-overview-width', String(overviewWidth));
  }, [overviewWidth]);

  useEffect(() => {
    window.localStorage.setItem('llm-council-overview-collapsed', String(isOverviewCollapsed));
  }, [isOverviewCollapsed]);

  useEffect(() => {
    const node = overviewScrollRef.current;
    if (!node) {
      return undefined;
    }

    const updateScrollHint = () => {
      const nextOverflowing = node.scrollHeight > node.clientHeight + 1;
      const nextShowUpHint = nextOverflowing && node.scrollTop > 6;
      const nextShowDownHint = nextOverflowing && (node.scrollTop + node.clientHeight < node.scrollHeight - 6);
      setIsOverviewOverflowing(nextOverflowing);
      setShowOverviewScrollUpHint(nextShowUpHint);
      setShowOverviewScrollDownHint(nextShowDownHint);
    };

    updateScrollHint();
    node.addEventListener('scroll', updateScrollHint);
    window.addEventListener('resize', updateScrollHint);

    return () => {
      node.removeEventListener('scroll', updateScrollHint);
      window.removeEventListener('resize', updateScrollHint);
    };
  }, [
    isOverviewCollapsed,
    overviewWidth,
    turnIndex,
    overviewSections,
    entitySections,
    isOverviewLoading,
    overviewError,
    isEntitiesLoading,
    entitiesError,
  ]);

  const handleSubmit = (event) => {
    event.preventDefault();
    if (input.trim() && !isLoading && selectedBundleId) {
      onSendMessage(input, selectedBundleId);
      setInput('');
    }
  };

  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSubmit(event);
    }
  };

  const handleJumpToTurn = async (entry) => {
    const messageIndex = entry.transcript_offset?.message_index;
    if (typeof messageIndex !== 'number') {
      return;
    }

    if (!conversation) {
      pendingJumpIndexRef.current = messageIndex;
      await onLoadTranscript();
      return;
    }

    scrollToMessage(messageIndex);
  };

  const handleTurnJumpSelection = async (entry, event) => {
    const messageIndex = entry.transcript_offset?.message_index;
    if (typeof messageIndex !== 'number') {
      return;
    }

    const shouldScroll = applySelectionFromEvent(getTurnSelectionId(messageIndex), event);
    if (!shouldScroll) {
      return;
    }

    await handleJumpToTurn(entry);
  };

  const getMessageSearchHighlight = (messageIndex) => {
    if (!activeTranscriptSearch || activeTranscriptSearch.messageIndex !== messageIndex) {
      return {
        query: '',
        sourceType: null,
      };
    }

    return {
      query: activeTranscriptSearch.query,
      sourceType: activeTranscriptSearch.sourceType,
    };
  };

  const collectSelectedClipItems = async () => {
    if (selectedClipCount === 0 || !currentConversationKey) {
      return [];
    }

    let sourceConversation = conversation;
    if (!sourceConversation) {
      sourceConversation = await onLoadTranscript();
    }

    if (!sourceConversation) {
      return [];
    }

    const selectedEntries = [];
    const selectedEntryMap = new Map();

    sourceConversation.messages.forEach((message, messageIndex) => {
      const segments = getMessageClipSegments(message, messageIndex);

      if (selectedClipIds[getTurnSelectionId(messageIndex)]) {
        segments.forEach((segment) => {
          selectedEntryMap.set(segment.id, segment);
        });
      }

      segments.forEach((segment) => {
        if (selectedClipIds[segment.id]) {
          selectedEntryMap.set(segment.id, segment);
        }
      });
    });

    selectedEntryMap.forEach((value) => selectedEntries.push(value));

    return selectedEntries
      .sort((left, right) => (
        left.messageIndex === right.messageIndex
          ? left.order - right.order
          : left.messageIndex - right.messageIndex
      ))
      .map(({ sourceId, label, text }) => ({ sourceId, label, text }));
  };

  const handleClipToWorkbook = async () => {
    const selections = await collectSelectedClipItems();
    if (selections.length === 0 || !currentConversationKey) {
      return;
    }

    onClipSelectionsToWorkbook(currentConversationKey, selections);
    setSelectedClipIds({});
    selectionAnchorRef.current = null;
    setIsOverviewCollapsed(true);
    setViewMode('workbook');
  };

  const handleChangeViewMode = (nextViewMode) => {
    if (nextViewMode === 'workbook') {
      setIsOverviewCollapsed(true);
    }
    setViewMode(nextViewMode);
  };

  const handleExportConversation = async () => {
    let sourceConversation = conversation;
    if (!sourceConversation) {
      sourceConversation = await onLoadTranscript();
    }
    if (!sourceConversation) {
      return;
    }

    const filenameBase = (conversationOverview?.title || sourceConversation.title || 'conversation')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'conversation';

    downloadTextFile(
      `${filenameBase}.md`,
      buildConversationExportMarkdown(sourceConversation, conversationOverview)
    );
  };

  const handleExportWorkbook = () => {
    const filenameBase = (conversationOverview?.title || conversation?.title || 'conversation-workbook')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'conversation-workbook';

    downloadTextFile(
      `${filenameBase}-workbook.md`,
      buildWorkbookExportMarkdown(conversationOverview?.title || conversation?.title || 'Conversation', workbookItems)
    );
  };

  const renderTranscript = () => {
    if (conversation) {
      if (conversation.messages.length === 0) {
        return (
          <div className="empty-state empty-state-inline">
            <h2>Start a conversation</h2>
            <p>Ask a question to consult the LLM Council</p>
          </div>
        );
      }

      return conversation.messages.map((message, index) => {
        const searchHighlight = getMessageSearchHighlight(index);
        const highlightQuery = searchHighlight.query;
        const highlightSourceType = searchHighlight.sourceType;
        const turnSelectionId = getTurnSelectionId(index);
        const isTurnSelected = getIsTurnSelected(index);

        return (
          <div
            key={index}
            id={`conversation-message-${index}`}
            className={`message-group ${
              highlightedMessageIndex === index ? 'message-group-search-match' : ''
            }`}
          >
            <div
              className={`message-group-row ${isTurnSelected ? 'message-group-row-selected' : ''}`}
              onClick={(event) => {
                handleSelectableClick(turnSelectionId, event);
              }}
            >
              {message.role === 'user' ? (
                <div className="user-message">
                  <div className="message-header">
                    <div className="message-header-main">
                      <div className="message-label">You</div>
                      {formatTurnTimestamp(message.created_at) && (
                        <div className="message-timestamp">{formatTurnTimestamp(message.created_at)}</div>
                      )}
                    </div>
                  </div>
                  {message.bundle?.name && (
                    <div className="message-bundle">Bundle: {message.bundle.name}</div>
                  )}
                  <div
                    className={`message-content selectable-card ${getIsSegmentSelected(`segment:${index}:prompt`) ? 'selected' : ''}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      handleSelectableClick(`segment:${index}:prompt`, event);
                    }}
                  >
                    <div className="markdown-content">
                      <HighlightedMarkdown
                        highlightQuery={highlightSourceType === 'user_message' ? highlightQuery : ''}
                      >
                        {message.content}
                      </HighlightedMarkdown>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="assistant-message">
                  <div className="message-header">
                    <div className="message-header-main">
                      <div className="message-label">LLM Council</div>
                      {formatTurnTimestamp(message.created_at) && (
                        <div className="message-timestamp">{formatTurnTimestamp(message.created_at)}</div>
                      )}
                    </div>
                  </div>
                  {(message.bundle?.name || message.metadata?.bundle?.name) && (
                    <div className="message-bundle">
                      Bundle: {message.bundle?.name || message.metadata?.bundle?.name}
                    </div>
                  )}

                  {message.loading?.stage1 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 1: Collecting individual responses...</span>
                    </div>
                  )}
                  {message.stage1 && (
                    <div
                      className={`stage-selectable-card selectable-card ${getIsSegmentSelected(`segment:${index}:stage1`) ? 'selected' : ''}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        handleSelectableClick(`segment:${index}:stage1`, event);
                      }}
                    >
                      <Stage1 responses={message.stage1} />
                    </div>
                  )}

                  {message.loading?.stage2 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 2: Peer rankings...</span>
                    </div>
                  )}
                  {message.stage2 && (
                    <div
                      className={`stage-selectable-card selectable-card ${getIsSegmentSelected(`segment:${index}:stage2`) ? 'selected' : ''}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        handleSelectableClick(`segment:${index}:stage2`, event);
                      }}
                    >
                      <Stage2
                        rankings={message.stage2}
                        labelToModel={message.metadata?.label_to_model}
                        aggregateRankings={message.metadata?.aggregate_rankings}
                      />
                    </div>
                  )}

                  {message.loading?.stage3 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 3: Final synthesis...</span>
                    </div>
                  )}
                  {message.stage3 && (
                    <div
                      className={`stage-selectable-card selectable-card ${getIsSegmentSelected(`segment:${index}:stage3`) ? 'selected' : ''}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        handleSelectableClick(`segment:${index}:stage3`, event);
                      }}
                    >
                      <Stage3
                        finalResponse={message.stage3}
                        highlightQuery={highlightSourceType === 'assistant_final' ? highlightQuery : ''}
                      />
                    </div>
                  )}

                  {message.error && (
                    <div
                      className={`message-error selectable-card ${getIsSegmentSelected(`segment:${index}:error`) ? 'selected' : ''}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        handleSelectableClick(`segment:${index}:error`, event);
                      }}
                    >
                      <strong>Council run stopped</strong>
                      <p>
                        {renderHighlightedText(
                          message.error.message,
                          highlightSourceType === 'assistant_error' ? highlightQuery : '',
                          `error-${index}`
                        )}
                      </p>
                      {(message.error.details?.attempted_models || message.error.attempted_models) && (
                        <div className="message-error-meta">
                          Attempted: {(message.error.details?.attempted_models || message.error.attempted_models).join(', ')}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        );
      });
    }

    if (isTranscriptLoading) {
      return (
        <div className="transcript-status">
          <div className="spinner"></div>
          <span>Loading transcript...</span>
        </div>
      );
    }

    if (isOverviewLoading) {
      return (
        <div className="transcript-status">
          <div className="spinner"></div>
          <span>Loading conversation overview...</span>
        </div>
      );
    }

    return (
      <div className="transcript-collapsed">
        <h2>Transcript hidden by default</h2>
        <p>
          This conversation is long enough that the app loads the compact overview first.
          Open the full transcript only when you need the detailed Stage 1/2/3 history.
        </p>
        <button
          type="button"
          className="load-transcript-button"
          onClick={onLoadTranscript}
        >
          Load full transcript
        </button>
      </div>
    );
  };

  const renderWorkbook = () => {
    if (workbookItems.length === 0) {
      return (
        <div className="workbook-empty">
          <h2>Workbook is empty</h2>
          <p>Select prompts, stages, or whole turns in the conversation view, then clip them here.</p>
        </div>
      );
    }

    return (
      <div className="workbook-list">
        {workbookItems.map((item, index) => (
          <article key={item.id} className="workbook-item">
            <div className="workbook-item-header">
              <div className="workbook-item-number">{String(index + 1).padStart(2, '0')}</div>
              <div className="workbook-item-heading">
                <div className="workbook-item-label">{item.label}</div>
                <div className="workbook-item-index">Clip {index + 1}</div>
              </div>
              <button
                type="button"
                className="workbook-item-remove"
                onClick={() => onDeleteWorkbookItem(currentConversationKey, item.id)}
              >
                Remove
              </button>
            </div>
            <textarea
              className="workbook-item-editor"
              value={item.text}
              onChange={(event) => onUpdateWorkbookItem(currentConversationKey, item.id, event.target.value)}
              rows={8}
            />
          </article>
        ))}
      </div>
    );
  };

  if (!conversationSelected) {
    return (
      <div className="chat-interface">
        <div className="empty-state">
          <h2>Welcome to LLM Council</h2>
          <p>Create a new conversation to get started</p>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-interface">
      <div className="messages-container">
        <div className="conversation-workspace">
          <aside
            ref={overviewPanelRef}
            className={`conversation-overview-panel ${isOverviewCollapsed ? 'collapsed' : ''} ${isOverviewResizing ? 'resizing' : ''}`}
            style={
              isOverviewCollapsed
                ? undefined
                : {
                    width: `${overviewWidth}px`,
                    flexBasis: `${overviewWidth}px`,
                    minWidth: `${overviewWidth}px`,
                    maxWidth: `${overviewWidth}px`,
                  }
            }
          >
            {isOverviewCollapsed && (
              <button
                type="button"
                className="overview-toggle-button"
                onClick={() => setIsOverviewCollapsed((collapsed) => !collapsed)}
                aria-label="Expand conversation overview"
                title="Expand overview"
              >
                ›
              </button>
            )}

            <div ref={overviewScrollRef} className="conversation-overview-scroll">
              <div className="overview-header">
                <div className="overview-header-top">
                  <div className="overview-eyebrow">Conversation overview</div>
                </div>
                <div className="overview-header-main">
                  <h2 title={conversationOverview?.title || conversation?.title || 'Conversation'}>
                    {conversationOverview?.title || conversation?.title || 'Conversation'}
                  </h2>
                </div>
                <div className="overview-header-bottom">
                  <div className="overview-meta">{messageCount} messages</div>
                </div>
                {!isOverviewCollapsed && (
                  <button
                    type="button"
                    className="overview-toggle-button overview-toggle-button-expanded"
                    onClick={() => setIsOverviewCollapsed(true)}
                    aria-label="Collapse conversation overview"
                    title="Collapse overview"
                  >
                    ‹
                  </button>
                )}
              </div>

              {isOverviewCollapsed ? (
                <div className="overview-collapsed-turn-strip">
                  {turnIndex.map((entry) => {
                    const messageIndex = entry.transcript_offset?.message_index;
                    const isSelected = typeof messageIndex === 'number' && getIsTurnSelected(messageIndex);
                    return (
                      <div key={`${entry.turn_number}-${entry.role}`} className="overview-turn-chip-shell">
                        <button
                          className={`overview-turn-chip overview-turn-chip-${entry.role} ${isSelected ? 'selected' : ''}`}
                          type="button"
                          title={`${entry.role} turn ${entry.turn_number}`}
                          onClick={(event) => handleTurnJumpSelection(entry, event)}
                        >
                          {isSelected ? '✓' : entry.turn_number}
                        </button>
                      </div>
                    );
                  })}
                </div>
              ) : (isOverviewLoading ? (
                <div className="overview-status">Loading overview...</div>
              ) : overviewError ? (
                <div className="overview-status overview-status-error">{overviewError}</div>
              ) : (
                <>
                  <section className="overview-section">
                    <div className="overview-section-title">Rolling summary</div>
                    {overviewSections.length > 0 ? (
                      <div className="overview-summary">
                        {overviewSections.map((section) => (
                          <div key={section.title} className="overview-summary-section">
                            <div className="overview-summary-section-title">{section.title}</div>
                            {section.kind === 'list' ? (
                              <ul className="overview-summary-list">
                                {section.items.map((item) => (
                                  <li key={item}>{item}</li>
                                ))}
                              </ul>
                            ) : (
                              <p className="overview-summary-text">{section.content}</p>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : summaryPending ? (
                      <div className="overview-status">
                        Rolling summary backfill has been queued. It will appear after the worker processes this conversation.
                      </div>
                    ) : (
                      <div className="overview-empty">
                        No rolling summary yet. The worker will populate this after a completed run.
                      </div>
                    )}
                  </section>

                  <section className="overview-section">
                    <div className="overview-section-title">Turn index</div>
                    {turnIndex.length === 0 ? (
                      turnIndexPending ? (
                        <div className="overview-status">
                          Turn index backfill has been queued. It will appear after the worker processes this conversation.
                        </div>
                      ) : (
                        <div className="overview-empty">No indexed turns yet.</div>
                      )
                    ) : (
                      <div className="overview-turn-list">
                        {turnIndex.map((entry) => {
                          const messageIndex = entry.transcript_offset?.message_index;
                          const isSelected = typeof messageIndex === 'number' && getIsTurnSelected(messageIndex);
                          return (
                            <button
                              key={`${entry.turn_number}-${entry.role}`}
                              className={`overview-turn ${isSelected ? 'selected' : ''}`}
                              type="button"
                              onClick={(event) => handleTurnJumpSelection(entry, event)}
                            >
                              <div className="overview-turn-meta">
                                <span className={`overview-turn-role overview-turn-role-${entry.role}`}>
                                  {entry.role}
                                </span>
                                <span>Turn {entry.turn_number}</span>
                                {formatTurnTimestamp(entry.created_at) && (
                                  <span className="overview-turn-timestamp">
                                    {formatTurnTimestamp(entry.created_at)}
                                  </span>
                                )}
                              </div>
                              <div className="overview-turn-highlight">{entry.short_highlight}</div>
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </section>

                  <section className="overview-section">
                    <div className="overview-section-title">Themes and entities</div>
                    {entitiesError ? (
                      <div className="overview-status overview-status-error">{entitiesError}</div>
                    ) : isEntitiesLoading ? (
                      <div className="overview-status">Loading extracted themes and entities...</div>
                    ) : entitySections.length === 0 ? (
                      conversationEntities?.pending ? (
                        <div className="overview-status">
                          Entity extraction has been queued. It will appear after the worker processes this conversation.
                        </div>
                      ) : (
                        <div className="overview-empty">
                          No extracted themes or entities yet.
                        </div>
                      )
                    ) : (
                      <div className="overview-entity-sections">
                        {entitySections.map((section) => (
                          <div key={section.title} className="overview-entity-section">
                            <div className="overview-summary-section-title">{section.title}</div>
                            <div className="overview-entity-chip-list">
                              {section.items.map((item) => (
                                <span key={`${section.title}-${item}`} className="overview-entity-chip">
                                  {item}
                                </span>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </section>
                </>
              ))}
            </div>

            {isOverviewOverflowing && showOverviewScrollUpHint && (
              <div className="overview-scroll-header">
                <button
                  type="button"
                  className="overview-scroll-button"
                  onClick={scrollOverviewUp}
                  aria-label="Scroll conversation overview up"
                  title="Scroll up"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M7 14.5 12 9.5l5 5" />
                  </svg>
                </button>
              </div>
            )}

            {isOverviewOverflowing && showOverviewScrollDownHint && (
              <div className="overview-scroll-footer">
                <button
                  type="button"
                  className="overview-scroll-button"
                  onClick={scrollOverviewDown}
                  aria-label="Scroll conversation overview down"
                  title="Scroll down"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="m7 9.5 5 5 5-5" />
                  </svg>
                </button>
              </div>
            )}

            {!isOverviewCollapsed && (
              <div
                className="overview-resizer"
                role="separator"
                aria-orientation="vertical"
                aria-label="Resize conversation overview"
                onMouseDown={(event) => {
                  event.preventDefault();
                  setIsOverviewResizing(true);
                }}
              />
            )}
          </aside>

          <section className="conversation-transcript-panel">
            <header className="conversation-panel-header">
              <div className="conversation-panel-header-top">
                <div className="conversation-panel-eyebrow">
                  {viewMode === 'conversation' ? 'Conversation view' : 'Workbook view'}
                </div>
              </div>

              <div className="conversation-panel-header-main">
                <h2 title={conversationOverview?.title || conversation?.title || 'Conversation'}>
                  {conversationOverview?.title || conversation?.title || 'Conversation'}
                </h2>
                <div className="conversation-panel-main-actions">
                  <div className="conversation-view-switcher" role="tablist" aria-label="Conversation view mode">
                    <button
                      type="button"
                      className={viewMode === 'conversation' ? 'active' : ''}
                      onClick={() => handleChangeViewMode('conversation')}
                      role="tab"
                      aria-selected={viewMode === 'conversation'}
                    >
                      Conversation
                    </button>
                    <button
                      type="button"
                      className={viewMode === 'workbook' ? 'active' : ''}
                      onClick={() => handleChangeViewMode('workbook')}
                      role="tab"
                      aria-selected={viewMode === 'workbook'}
                    >
                      Workbook
                    </button>
                  </div>
                  <div className="conversation-header-utility" ref={usagePopoverRef}>
                    <button
                      type="button"
                      className={`panel-icon-button ${isUsageOpen ? 'active' : ''}`}
                      onClick={() => setIsUsageOpen((open) => !open)}
                      aria-label="Show usage and cost"
                      title="Usage and cost"
                    >
                      <UsageIcon />
                    </button>
                    {isUsageOpen && (
                      <div className="usage-popover" role="dialog" aria-label="Conversation usage and cost">
                        <ConversationUsageMeter summary={usageSummary} />
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className="conversation-panel-header-bottom">
                <div className="conversation-panel-subtitle">
                  <span>{messageCount} messages</span>
                  {selectedBundle?.name && (
                    <>
                      <span className="conversation-meta-separator">·</span>
                      <span className="conversation-bundle-meta">
                        Bundle {selectedBundle.position}. {selectedBundle.name}
                      </span>
                    </>
                  )}
                  {workbookItems.length > 0 && (
                    <>
                      <span className="conversation-meta-separator">·</span>
                      <span>{workbookItems.length} workbook clips</span>
                    </>
                  )}
                </div>
                <div className="conversation-panel-actions">
                  <button
                    type="button"
                    className="panel-inline-button"
                    onClick={handleClipToWorkbook}
                    disabled={selectedClipCount === 0}
                    title="Clip to workbook"
                  >
                    Clip{selectedClipCount > 0 ? ` (${selectedClipCount})` : ''}
                  </button>
                  <button
                    type="button"
                    className="panel-inline-button"
                    onClick={viewMode === 'workbook' ? handleExportWorkbook : handleExportConversation}
                    disabled={viewMode === 'workbook' && workbookItems.length === 0}
                    title={viewMode === 'workbook' ? 'Export workbook' : 'Export conversation'}
                  >
                    Export
                  </button>
                </div>
              </div>
            </header>

            <div ref={transcriptScrollRef} className="conversation-panel-body">
              <div className="conversation-panel-scroll">
                {viewMode === 'conversation' ? renderTranscript() : renderWorkbook()}

                {viewMode === 'conversation' && isLoading && (
                  <div className="loading-indicator">
                    <div className="spinner"></div>
                    <span>Consulting the council...</span>
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>
            </div>
          </section>
        </div>
      </div>

      <form className="input-form" onSubmit={handleSubmit}>
        <div className="composer-layout">
          <textarea
            className="message-input"
            placeholder={
              messageCount === 0
                ? 'Ask your question... (Shift+Enter for new line, Enter to send)'
                : 'Ask a follow-up... (Shift+Enter for new line, Enter to send)'
            }
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading || modelBundles.length === 0}
            rows={3}
          />
          <div className="composer-sidecar">
            <div className="bundle-select-shell">
              <span className="bundle-inline-dot" aria-hidden="true" />
              <select
                id="bundle-select"
                className="bundle-select"
                value={selectedBundleId}
                onChange={(event) => onSelectBundle(event.target.value)}
                disabled={isLoading || modelBundles.length === 0}
                aria-label="Select model bundle"
              >
                {modelBundles.map((bundle) => (
                  <option key={bundle.id} value={bundle.id}>
                    {bundle.position}. {bundle.name}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              className="send-button"
              disabled={!input.trim() || isLoading || !selectedBundleId}
            >
              Send
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
