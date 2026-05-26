import { useEffect, useRef, useState } from 'react';
import BundleManager from './BundleManager';
import SearchDateRangePicker from './SearchDateRangePicker';
import { renderHighlightedText } from './SearchHighlightText';
import './Sidebar.css';

function formatSearchSource(result) {
  const metadata = result.metadata || {};
  const messageIndex = metadata.message_index;

  if (result.source_type === 'assistant_final') {
    return messageIndex ? `Final response · Message ${messageIndex}` : 'Final response';
  }
  if (result.source_type === 'user_message') {
    return messageIndex ? `User prompt · Message ${messageIndex}` : 'User prompt';
  }
  if (result.source_type === 'assistant_error') {
    return messageIndex ? `Error · Message ${messageIndex}` : 'Error';
  }
  return result.source_type || 'Match';
}

function SidebarBrandMark() {
  return (
    <div className="sidebar-brand-mark" aria-hidden="true">
      <svg viewBox="0 0 40 40" width="22" height="22">
        <circle cx="20" cy="20" r="18.5" fill="none" stroke="currentColor" strokeWidth="1" />
        <circle cx="12" cy="16" r="2.6" fill="currentColor" />
        <circle cx="28" cy="16" r="2.6" fill="currentColor" />
        <circle cx="20" cy="28" r="2.6" fill="currentColor" />
        <path d="M12 16 L28 16 L20 28 Z" fill="none" stroke="currentColor" strokeWidth="0.8" opacity="0.55" />
      </svg>
    </div>
  );
}

export default function Sidebar({
  conversations,
  archivedConversations,
  starredConversationIds,
  currentConversationId,
  searchQuery,
  onSearchQueryChange,
  searchDateRange,
  onSearchDateRangeChange,
  searchResults,
  isSearchLoading,
  searchError,
  onSelectConversation,
  onSelectSearchResult,
  onNewConversation,
  onRenameConversation,
  onArchiveConversation,
  onRestoreConversation,
  onDeleteConversation,
  onToggleStarConversation,
  modelBundles,
  selectedBundleId,
  onSelectBundle,
  onSaveBundle,
  onDeleteBundle,
  onReorderBundles,
  onSetDefaultBundle,
  currentUser,
  onLogout,
}) {
  const [conversationView, setConversationView] = useState('active');
  const [openMenuConversationId, setOpenMenuConversationId] = useState(null);
  const [editingConversationId, setEditingConversationId] = useState(null);
  const [draftTitle, setDraftTitle] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [isConversationListOverflowing, setIsConversationListOverflowing] = useState(false);
  const [showConversationListScrollUpHint, setShowConversationListScrollUpHint] = useState(false);
  const [showConversationListScrollDownHint, setShowConversationListScrollDownHint] = useState(false);
  const conversationListRef = useRef(null);

  const allConversations = [...conversations, ...archivedConversations];
  const starredConversationSet = new Set(starredConversationIds);
  const starredConversations = allConversations.filter((conversation) => (
    starredConversationSet.has(conversation.id)
  ));

  const visibleConversations = (
    conversationView === 'archived'
      ? archivedConversations
      : conversationView === 'starred'
        ? starredConversations
        : conversations
  );
  const trimmedSearchQuery = searchQuery.trim();
  const showSearchResults = Boolean(trimmedSearchQuery);
  const hasActiveSearchDateRange = Boolean(searchDateRange.start || searchDateRange.end);

  const handleDelete = (event, conversation) => {
    event.stopPropagation();
    const title = conversation.title || 'New Conversation';
    if (window.confirm(`Delete "${title}" permanently?`)) {
      onDeleteConversation(conversation.id);
    }
  };

  const handleRenameStart = (event, conversation) => {
    event.stopPropagation();
    setOpenMenuConversationId(null);
    setEditingConversationId(conversation.id);
    setDraftTitle(conversation.title || 'New Conversation');
  };

  const handleRenameCancel = (event) => {
    event?.stopPropagation();
    setEditingConversationId(null);
    setDraftTitle('');
  };

  const handleRenameSubmit = async (event, conversationId) => {
    event.preventDefault();
    event.stopPropagation();

    const nextTitle = draftTitle.trim();
    if (!nextTitle) return;

    await onRenameConversation(conversationId, nextTitle);
    setEditingConversationId(null);
    setDraftTitle('');
  };

  const canManageBundles = currentUser?.role === 'admin';

  useEffect(() => {
    const node = conversationListRef.current;
    if (!node) {
      return undefined;
    }

    const updateScrollHint = () => {
      const nextOverflowing = node.scrollHeight > node.clientHeight + 1;
      const nextShowUpHint = nextOverflowing && node.scrollTop > 6;
      const nextShowDownHint = nextOverflowing && (node.scrollTop + node.clientHeight < node.scrollHeight - 6);
      setIsConversationListOverflowing(nextOverflowing);
      setShowConversationListScrollUpHint(nextShowUpHint);
      setShowConversationListScrollDownHint(nextShowDownHint);
    };

    updateScrollHint();
    node.addEventListener('scroll', updateScrollHint);
    window.addEventListener('resize', updateScrollHint);

    return () => {
      node.removeEventListener('scroll', updateScrollHint);
      window.removeEventListener('resize', updateScrollHint);
    };
  }, [
    conversationView,
    conversations,
    archivedConversations,
    starredConversationIds,
    searchResults,
    searchQuery,
    searchDateRange,
    settingsOpen,
  ]);

  const scrollConversationListDown = () => {
    if (!conversationListRef.current) {
      return;
    }

    conversationListRef.current.scrollBy({
      top: Math.max(180, conversationListRef.current.clientHeight * 0.72),
      behavior: 'smooth',
    });
  };

  const scrollConversationListUp = () => {
    if (!conversationListRef.current) {
      return;
    }

    conversationListRef.current.scrollBy({
      top: -Math.max(180, conversationListRef.current.clientHeight * 0.72),
      behavior: 'smooth',
    });
  };

  return (
    <div className="sidebar">
      {settingsOpen ? (
        <div className="sidebar-settings-inline">
          <div className="sidebar-settings-inline-header">
            <div>
              <div className="sidebar-settings-eyebrow">Settings</div>
              <h2>Council Bundles</h2>
              <p>
                {canManageBundles
                  ? 'Configure the models used for new council runs.'
                  : 'Choose the model bundle for new council runs.'}
              </p>
            </div>
            <button
              className="sidebar-settings-close"
              type="button"
              onClick={() => setSettingsOpen(false)}
            >
              Close
            </button>
          </div>
          <div className="sidebar-settings-panel-body">
            <BundleManager
              bundles={modelBundles}
              selectedBundleId={selectedBundleId}
              onSelectBundle={onSelectBundle}
              onSaveBundle={onSaveBundle}
              onDeleteBundle={onDeleteBundle}
              onReorderBundles={onReorderBundles}
              onSetDefaultBundle={onSetDefaultBundle}
              canManageBundles={canManageBundles}
            />
          </div>
        </div>
      ) : (
        <>
          <div className="sidebar-header">
            <div className="sidebar-header-main">
              <SidebarBrandMark />
              <h1>Deliberati</h1>
            </div>
            <div className="sidebar-header-bottom">
              <p className="sidebar-subtitle">
                {currentUser?.username ? `${currentUser.username} · ${currentUser.role}` : 'Council conversations'}
              </p>
              <button className="sidebar-logout" type="button" onClick={onLogout}>
                Log out
              </button>
            </div>
          </div>

          <div className="conversation-actions">
            <button className="new-conversation-btn" onClick={onNewConversation}>
              + New Conversation
            </button>
            <div className="conversation-search">
              <div className="conversation-search-input-shell">
                <input
                  className="conversation-search-input"
                  type="search"
                  value={searchQuery}
                  onChange={(event) => onSearchQueryChange(event.target.value)}
                  placeholder="Search conversations"
                  aria-label="Search conversations"
                />
                <SearchDateRangePicker
                  value={searchDateRange}
                  onChange={onSearchDateRangeChange}
                />
              </div>
              {(searchQuery || hasActiveSearchDateRange) && (
                <button
                  className="conversation-search-clear"
                  type="button"
                  onClick={() => {
                    onSearchQueryChange('');
                    onSearchDateRangeChange({ start: '', end: '' });
                  }}
                  aria-label="Clear search"
                >
                  Clear
                </button>
              )}
            </div>
            {hasActiveSearchDateRange && (
              <div className="conversation-search-date-summary">
                <span>
                  {searchDateRange.end
                    ? `Date range: ${searchDateRange.start} to ${searchDateRange.end}`
                    : `Date range: ${searchDateRange.start} onward`}
                </span>
                <button
                  className="conversation-search-filter-clear"
                  type="button"
                  onClick={() => onSearchDateRangeChange({ start: '', end: '' })}
                >
                  Reset
                </button>
              </div>
            )}
          </div>

          <div className="conversation-tabs" aria-label="Conversation view">
            <button
              className={conversationView === 'active' ? 'active' : ''}
              onClick={() => setConversationView('active')}
              type="button"
              role="tab"
              aria-selected={conversationView === 'active'}
            >
              Active
            </button>
            <button
              className={conversationView === 'starred' ? 'active' : ''}
              onClick={() => setConversationView('starred')}
              type="button"
              role="tab"
              aria-selected={conversationView === 'starred'}
            >
              Starred
            </button>
            <button
              className={conversationView === 'archived' ? 'active' : ''}
              onClick={() => setConversationView('archived')}
              type="button"
              role="tab"
              aria-selected={conversationView === 'archived'}
            >
              Archived
            </button>
          </div>
          <div className="conversation-list-panel">
            {isConversationListOverflowing && showConversationListScrollUpHint && (
              <div className="conversation-list-scroll-header">
                <button
                  type="button"
                  className="conversation-list-scroll-button"
                  onClick={scrollConversationListUp}
                  aria-label="Scroll conversation list up"
                  title="Scroll up"
                >
                  ↑
                </button>
              </div>
            )}
            <div ref={conversationListRef} className="conversation-list">
              {showSearchResults ? (
                <>
                  <div className="search-results-header">
                    <span>Search results</span>
                    <span>{isSearchLoading ? 'Searching…' : `${searchResults.length} match${searchResults.length === 1 ? '' : 'es'}`}</span>
                  </div>
                  {searchError ? (
                    <div className="search-results-empty">{searchError}</div>
                  ) : isSearchLoading && searchResults.length === 0 ? (
                    <div className="search-results-empty">Searching transcript index…</div>
                  ) : searchResults.length === 0 ? (
                    <div className="search-results-empty">
                      No matches for “{trimmedSearchQuery}”.
                      {hasActiveSearchDateRange ? ' Try widening the time range.' : ''}
                    </div>
                  ) : (
                    searchResults.map((result) => (
                      <button
                        key={`${result.conversation_id}:${result.source_type}:${result.source_ref}:${result.chunk_index}`}
                        className={`search-result-item ${
                          result.conversation_id === currentConversationId ? 'active' : ''
                        }`}
                        type="button"
                        onClick={() => {
                          setConversationView(result.archived ? 'archived' : 'active');
                          onSelectSearchResult(result);
                        }}
                      >
                        <div className="search-result-title-row">
                          <div className="search-result-title">{result.title || 'New Conversation'}</div>
                          {result.archived && (
                            <span className="search-result-badge">Archived</span>
                          )}
                        </div>
                        <div className="search-result-meta">
                          {formatSearchSource(result)}
                        </div>
                        <div className="search-result-snippet">
                          {renderHighlightedText(
                            result.snippet || result.chunk_text,
                            trimmedSearchQuery,
                            `sidebar-${result.conversation_id}-${result.chunk_index}`
                          )}
                        </div>
                      </button>
                    ))
                  )}
                </>
              ) : visibleConversations.length === 0 ? (
                <div className="no-conversations">
                  {conversationView === 'archived'
                    ? 'No archived conversations'
                    : conversationView === 'starred'
                      ? 'No starred conversations'
                      : 'No conversations yet'}
                </div>
              ) : (
                visibleConversations.map((conv) => (
                  <div
                    key={conv.id}
                    className={`conversation-item ${
                      conv.id === currentConversationId ? 'active' : ''
                    }`}
                    onClick={() => onSelectConversation(conv.id)}
                  >
                    <div className="conversation-row-top">
                      {editingConversationId === conv.id ? (
                        <form
                          className="conversation-rename-form"
                          onSubmit={(event) => handleRenameSubmit(event, conv.id)}
                          onClick={(event) => event.stopPropagation()}
                        >
                          <input
                            className="conversation-rename-input"
                            value={draftTitle}
                            onChange={(event) => setDraftTitle(event.target.value)}
                            autoFocus
                            maxLength={80}
                            onKeyDown={(event) => {
                              if (event.key === 'Escape') {
                                handleRenameCancel(event);
                              }
                            }}
                          />
                          <button type="submit">Save</button>
                          <button
                            type="button"
                            className="ghost"
                            onClick={handleRenameCancel}
                          >
                            Cancel
                          </button>
                        </form>
                      ) : (
                        <>
                          <div className="conversation-title">
                            {conv.title || 'New Conversation'}
                          </div>
                          <div className="conversation-row-actions">
                            <button
                              className={`conversation-star-trigger ${
                                starredConversationSet.has(conv.id) ? 'active' : ''
                              }`}
                              type="button"
                              aria-label={starredConversationSet.has(conv.id) ? 'Unstar conversation' : 'Star conversation'}
                              onClick={(event) => {
                                event.stopPropagation();
                                onToggleStarConversation(conv.id);
                              }}
                            >
                              <svg viewBox="0 0 24 24" aria-hidden="true">
                                <path d="M12 3.75 14.55 8.92l5.7.83-4.12 4.01.97 5.67L12 16.74l-5.1 2.69.97-5.67-4.12-4.01 5.7-.83L12 3.75Z" />
                              </svg>
                            </button>
                            <button
                              className={`conversation-menu-trigger ${
                                openMenuConversationId === conv.id ? 'active' : ''
                              }`}
                              type="button"
                              aria-label="Conversation options"
                              onClick={(event) => {
                                event.stopPropagation();
                                setOpenMenuConversationId((currentId) =>
                                  currentId === conv.id ? null : conv.id
                                );
                              }}
                            >
                              •••
                            </button>
                          </div>
                        </>
                      )}
                    </div>

                    {editingConversationId !== conv.id && (
                      <div className="conversation-meta">
                        {conv.message_count} messages
                        {conv.archived && <span className="conversation-meta-badge">Archived</span>}
                      </div>
                    )}

                    {openMenuConversationId === conv.id && editingConversationId !== conv.id && (
                      <div
                        className="conversation-menu"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <button
                          type="button"
                          onClick={(event) => handleRenameStart(event, conv)}
                        >
                          Rename
                        </button>
                        {conv.archived ? (
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              setOpenMenuConversationId(null);
                              onRestoreConversation(conv.id);
                            }}
                          >
                            Restore
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              setOpenMenuConversationId(null);
                              onArchiveConversation(conv.id);
                            }}
                          >
                            Archive
                          </button>
                        )}
                        <button
                          className="danger"
                          type="button"
                          onClick={(event) => {
                            setOpenMenuConversationId(null);
                            handleDelete(event, conv);
                          }}
                        >
                          Delete
                        </button>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}

      <div className={`sidebar-bottom-bar ${showConversationListScrollDownHint && !settingsOpen ? 'with-scroll-button' : ''}`}>
        <button
          className={`sidebar-settings-cog ${settingsOpen ? 'active' : ''}`}
          type="button"
          onClick={() => setSettingsOpen((open) => !open)}
          aria-label={settingsOpen ? 'Close settings' : 'Open settings'}
          title={settingsOpen ? 'Close settings' : 'Open settings'}
        >
          <svg viewBox="0 0 24 24" role="img" aria-hidden="true">
            <path d="M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Zm7.4 3.94a7.66 7.66 0 0 0 0-1.88l2.06-1.6-2-3.46-2.42.97a7.7 7.7 0 0 0-1.63-.94L15 3.5h-4l-.4 2.53a7.7 7.7 0 0 0-1.63.94l-2.42-.97-2 3.46 2.06 1.6a7.66 7.66 0 0 0 0 1.88l-2.06 1.6 2 3.46 2.42-.97c.5.39 1.05.71 1.63.94L11 20.5h4l.4-2.53c.58-.23 1.13-.55 1.63-.94l2.42.97 2-3.46-2.06-1.6Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <span className="sidebar-foot-meta">v0.4 · self-hosted</span>
        {!settingsOpen && showConversationListScrollDownHint && (
          <div className="conversation-list-scroll-footer">
            <button
              type="button"
              className="conversation-list-scroll-button"
              onClick={scrollConversationListDown}
              aria-label="Scroll conversation list down"
              title="Scroll down"
            >
              ↓
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
