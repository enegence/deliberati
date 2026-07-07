export const conversationFixture = {
  id: 'conv-1',
  title: 'Test conversation',
  created_at: '2026-07-01T00:00:00Z',
  messages: [
    { role: 'user', content: 'What is the answer?', created_at: '2026-07-01T00:00:00Z' },
    {
      role: 'assistant',
      created_at: '2026-07-01T00:01:00Z',
      stage1: [{ model: 'm/a', response: 'Response body' }],
      stage2: [{ model: 'm/a', ranking: 'FINAL RANKING:\n1. Response A', parsed_ranking: ['Response A'] }],
      stage3: { model: 'm/chair', response: 'The final verdict.' },
      metadata: { label_to_model: {}, aggregate_rankings: [] },
    },
  ],
};

export function buildBaseProps(overrides = {}) {
  return {
    conversation: conversationFixture,
    conversationSelected: true,
    conversationOverview: null,
    conversationEntities: null,
    workbookItems: [],
    requestedJumpTarget: null,
    activeSearchMatch: null,
    onSendMessage: () => {},
    onLoadTranscript: () => {},
    onClipSelectionsToWorkbook: () => {},
    onUpdateWorkbookItem: () => {},
    onDeleteWorkbookItem: () => {},
    isLoading: false,
    isOverviewLoading: false,
    overviewError: '',
    isEntitiesLoading: false,
    entitiesError: '',
    isTranscriptLoading: false,
    modelBundles: [],
    selectedBundleId: '',
    onSelectBundle: () => {},
    ...overrides,
  };
}
