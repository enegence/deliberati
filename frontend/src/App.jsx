import { useState, useEffect, useDeferredValue, useRef, useCallback } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import { api } from './api';
import './App.css';

function toIsoSearchBoundary(value, boundary) {
  if (!value) {
    return '';
  }

  const candidate = new Date(
    boundary === 'end' ? `${value}T23:59:59.999` : `${value}T00:00:00`
  );
  if (Number.isNaN(candidate.getTime())) {
    return '';
  }

  return candidate.toISOString();
}

const AUTH_USE_CASES = [
  ['01', 'Career', 'The High-Stakes Career Pivot', 'Considering quitting a stable corporate job to join a risky AI startup, or start your own.'],
  ['02', 'Civic', 'De-biasing a Local Political Dispute', 'A school board or city council vote on a controversial zoning law or curriculum change.'],
  ['03', 'Medical', 'Evaluating a Bizarre Medical Symptom', 'A confusing diagnosis or strange lab result you want to understand before seeing the specialist.'],
  ['04', 'Relationship', 'Resolving an Interpersonal Deadlock', 'A long-running conflict with a partner or family member where both sides feel completely right.'],
  ['05', 'Legal', 'Reviewing a Critical Contract', 'An apartment lease, employment agreement, or freelance contract with clauses you need to understand.'],
  ['06', 'Purchase', 'Spending Real Money on a Niche Buy', '$2,000 toward a solar generator, a pro espresso machine, or a specific used car model.'],
  ['07', 'Bureaucracy', 'Navigating a Bureaucratic Nightmare', 'A denied insurance claim, an IRS notice, or a property-line dispute with local government.'],
  ['08', 'Theory', 'Sanity-Checking a Pet Theory', 'Weeks of reading and a new angle on a historical, philosophical, or economic question.'],
  ['09', 'Technical', 'Finding the Real Root Cause', 'Your HVAC thumps, or your machine throws a specific BSOD after standard troubleshooting failed.'],
  ['10', 'Ethics', 'A High-Impact Moral Choice', 'Whether to blow the whistle on a grey-area practice, or a difficult end-of-life decision.'],
  ['11', 'Research', 'Decoupling a Complex Scientific Paper', 'A breakthrough paper with real-world implications, and you need to know if the hype is real.'],
  ['12', 'Estate', 'Dividing a Family Inheritance Fairly', 'Sentimental property, family land, and modest savings across relatives with different needs.'],
  ['13', 'Workplace', 'An Ambiguous Hostile-Environment Claim', 'Subtle grey-area behavior from a manager or colleague, and unclear leverage before HR.'],
  ['14', 'Construction', 'Stress-Testing a Contractor Bid', 'A $40K kitchen remodel or foundation repair quote that may hide corner-cutting.'],
  ['15', 'Crisis PR', 'Writing a Public Apology Under Fire', 'A small organization needs a statement before tomorrow morning after a local scandal.'],
  ['16', 'Training', 'Designing an Injury-Aware Lifting Program', 'A strength program around weak points, fatigue, and old injuries.'],
  ['17', 'Garden', 'Why Is My Ecosystem Dying?', 'Backyard trees dying back and vegetables failing despite by-the-book care.'],
  ['18', 'Career', 'Ghost-Evaluating an Executive Promotion', 'A relocation, internal politics, and compensation tied to shifting company metrics.'],
  ['19', 'Finance', "Dissecting a 'Too Good to Be True' Pitch", 'A complex alternative investment pitched by someone who sounds convincing.'],
  ['20', 'Creative', "Breaking a High-Stakes Writer's Block", 'A grant proposal, software framework, or narrative climax that feels structurally stuck.'],
].map(([n, tag, title, scenario]) => ({
  n,
  tag,
  title,
  scenario,
  why: 'Independent agents debate the facts from incompatible angles; the Chairman consolidates the strongest answer without the usual single-model yes-man drift.',
}));

const SHADE_NOISE = [0.42, 0.13, 0.87, 0.55, 0.28, 0.71, 0.06, 0.94, 0.36, 0.62, 0.19, 0.78, 0.51, 0.24, 0.83, 0.46, 0.91, 0.33, 0.67, 0.09];

function darkenWarmCard(index) {
  const shade = SHADE_NOISE[index % SHADE_NOISE.length] * 0.14;
  const r = Math.round(255 * (1 - shade));
  const g = Math.round(253 * (1 - shade));
  const b = Math.round(248 * (1 - shade));
  return `rgba(${r}, ${g}, ${b}, 0.55)`;
}

function AuthUseCaseCard({ useCase, index, onOpen }) {
  return (
    <article
      className="auth-uc-card"
      role="button"
      tabIndex={0}
      style={{ '--card-bg': darkenWarmCard(index) }}
      onClick={() => onOpen(useCase)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onOpen(useCase);
        }
      }}
    >
      <header className="auth-uc-head">
        <span className="auth-uc-num">{useCase.n}</span>
        <span className="auth-uc-tag">{useCase.tag}</span>
      </header>
      <h3 className="auth-uc-title">{useCase.title}</h3>
      <p className="auth-uc-scenario">{useCase.scenario}</p>
      <div className="auth-uc-divider" />
      <p className="auth-uc-why"><span>Why the Council wins.</span> {useCase.why}</p>
    </article>
  );
}

function AuthDriftSheet({ paused, onOpen }) {
  const tileKeys = ['a', 'b', 'c', 'd'];

  return (
    <div className="auth-drift-stage">
      <div
        className="auth-drift-track"
        style={{ animationPlayState: paused ? 'paused' : 'running' }}
      >
        {tileKeys.map((tileKey) => (
          <div className="auth-uc-tile" key={tileKey}>
            {AUTH_USE_CASES.map((useCase, index) => (
              <AuthUseCaseCard
                key={`${tileKey}-${useCase.n}`}
                useCase={useCase}
                index={index}
                onOpen={onOpen}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function AuthUseCasePanel({ useCase, onClose }) {
  return (
    <div className="auth-panel auth-case-panel">
      <button className="auth-case-close" type="button" onClick={onClose} aria-label="Close use case">
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <path d="M6 6 L18 18 M18 6 L6 18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </button>

      <div className="auth-case-head">
        <span className="auth-case-num">Use case · {useCase.n} / 20</span>
        <span className="auth-case-tag">{useCase.tag}</span>
      </div>

      <h2 className="auth-case-title">{useCase.title}</h2>

      <section className="auth-case-section">
        <div className="auth-case-label">The scenario</div>
        <p className="auth-case-body">{useCase.scenario}</p>
      </section>

      <section className="auth-case-section">
        <div className="auth-case-label">Why the Council wins</div>
        <p className="auth-case-body">{useCase.why}</p>
      </section>

      <div className="auth-case-cta">
        <button className="auth-submit" type="button" onClick={onClose}>
          <span>Sign in to convene</span>
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
            <path d="M5 12h14M13 6l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <button className="auth-case-back" type="button" onClick={onClose}>
          Back to sign-in
        </button>
      </div>
    </div>
  );
}

function DeliberatiMark({ className = '' }) {
  return (
    <div className={`deliberati-mark ${className}`}>
      <svg viewBox="0 0 40 40" width="34" height="34" aria-hidden="true">
        <circle cx="20" cy="20" r="18.5" fill="none" stroke="currentColor" strokeWidth="1" />
        <circle cx="12" cy="16" r="3" fill="currentColor" opacity="0.85" />
        <circle cx="28" cy="16" r="3" fill="currentColor" opacity="0.85" />
        <circle cx="20" cy="28" r="3" fill="currentColor" opacity="0.85" />
        <path d="M12 16 L28 16 L20 28 Z" fill="none" stroke="currentColor" strokeWidth="0.8" opacity="0.45" />
      </svg>
    </div>
  );
}

function AuthScreen({
  mode,
  error,
  isSubmitting,
  onSubmit,
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [activeCase, setActiveCase] = useState(null);
  const isBootstrap = mode === 'bootstrap';

  const handleSubmit = async (event) => {
    event.preventDefault();
    await onSubmit(username, password);
  };

  useEffect(() => {
    if (!activeCase) {
      return undefined;
    }

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setActiveCase(null);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeCase]);

  return (
    <div className="auth-page">
      <AuthDriftSheet
        paused={Boolean(activeCase)}
        onOpen={setActiveCase}
      />
      <div className="auth-darkness-overlay" aria-hidden="true" />
      <div className="auth-vignette" aria-hidden="true" />
      {activeCase && (
        <button
          className="auth-modal-backdrop"
          type="button"
          onClick={() => setActiveCase(null)}
          aria-label="Close use case"
        />
      )}

      <div className="auth-modal-anchor">
        {activeCase ? (
          <AuthUseCasePanel
            useCase={activeCase}
            onClose={() => setActiveCase(null)}
          />
        ) : (
        <form className="auth-panel" onSubmit={handleSubmit}>
          <div className="auth-brand-block">
            <DeliberatiMark />
            <div className="auth-brand-text">
              <h1>Deliberati</h1>
              <div>A self-hosted council of LLMs</div>
            </div>
          </div>

          <div className="auth-modal-divider" />

          <p className="auth-lede">
            {isBootstrap
              ? 'Create the first admin account to convene the council.'
              : 'Sign in to convene the council. Prompts become structured debates; debates become persistent, exportable insight.'}
          </p>

          <label className="auth-field">
            <span>Username</span>
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              spellCheck="false"
            />
          </label>
          <label className="auth-field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={isBootstrap ? 'new-password' : 'current-password'}
            />
          </label>
          {error && <div className="auth-error">{error}</div>}
          <button className={`auth-submit ${isSubmitting ? 'is-busy' : ''}`} type="submit" disabled={isSubmitting}>
            <span>{isSubmitting ? 'Convening...' : isBootstrap ? 'Create admin' : 'Sign in'}</span>
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
              <path d="M5 12h14M13 6l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>

          <div className="auth-panel-foot">
            <span className="auth-foot-dot" />
            <span>Self-hosted. Built on Karpathy's original.</span>
          </div>
        </form>
        )}
      </div>

      <footer className="auth-page-foot">
        <span>Deliberati</span>
        <span>v0.4 · self-hosted</span>
        <span>Council workspace</span>
      </footer>
    </div>
  );
}

function readLocalJson(key, fallback) {
  if (typeof window === 'undefined') {
    return fallback;
  }

  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function buildStarredStorageKey(userId) {
  return `llm-council-starred:${userId}`;
}

function buildWorkbookStorageKey(userId) {
  return `llm-council-workbooks:${userId}`;
}

function buildBundleSelectionStorageKey(userId) {
  return `llm-council-selected-bundle:${userId}`;
}

function readLocalString(key, fallback = '') {
  if (typeof window === 'undefined') {
    return fallback;
  }

  const raw = window.localStorage.getItem(key);
  return raw ?? fallback;
}

function createWorkbookItem(selection) {
  const itemId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  return {
    id: itemId,
    source_id: selection.sourceId,
    label: selection.label,
    text: selection.text,
    created_at: new Date().toISOString(),
  };
}

function App() {
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    if (typeof window === 'undefined') {
      return 280;
    }

    const storedWidth = Number(window.localStorage.getItem('llm-council-sidebar-width'));
    return Number.isFinite(storedWidth) && storedWidth >= 220 && storedWidth <= 460
      ? storedWidth
      : 280;
  });
  const [conversations, setConversations] = useState([]);
  const [archivedConversations, setArchivedConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [currentConversationOverview, setCurrentConversationOverview] = useState(null);
  const [currentConversationEntities, setCurrentConversationEntities] = useState(null);
  const [modelBundles, setModelBundles] = useState([]);
  const [selectedBundleId, setSelectedBundleId] = useState('');
  const [requestedJumpTarget, setRequestedJumpTarget] = useState(null);
  const [activeSearchMatch, setActiveSearchMatch] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchDateRange, setSearchDateRange] = useState({
    start: '',
    end: '',
  });
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const [searchResults, setSearchResults] = useState([]);
  const [isSearchLoading, setIsSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isOverviewLoading, setIsOverviewLoading] = useState(false);
  const [overviewError, setOverviewError] = useState('');
  const [isEntitiesLoading, setIsEntitiesLoading] = useState(false);
  const [entitiesError, setEntitiesError] = useState('');
  const [isTranscriptLoading, setIsTranscriptLoading] = useState(false);
  const [isSidebarResizing, setIsSidebarResizing] = useState(false);
  const [starredConversationIds, setStarredConversationIds] = useState([]);
  const [workbookEntriesByConversation, setWorkbookEntriesByConversation] = useState({});
  const [authState, setAuthState] = useState({
    loading: true,
    configured: false,
    bootstrapRequired: false,
    user: null,
    error: '',
  });
  const [isAuthSubmitting, setIsAuthSubmitting] = useState(false);
  const authUserId = authState.user?.id;
  const currentConversationIdRef = useRef(currentConversationId);

  useEffect(() => {
    currentConversationIdRef.current = currentConversationId;
  }, [currentConversationId]);

  const loadConversations = useCallback(async () => {
    try {
      const [convs, archivedConvs] = await Promise.all([
        api.listConversations(),
        api.listConversations({ archived: true }),
      ]);
      setConversations(convs);
      setArchivedConversations(archivedConvs);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  }, []);

  const loadModelBundles = useCallback(async () => {
    try {
      const bundles = await api.listModelBundles();
      const storedBundleId = authUserId
        ? readLocalString(buildBundleSelectionStorageKey(authUserId), '')
        : '';
      const defaultBundleId = bundles.find((bundle) => bundle.is_default)?.id || bundles[0]?.id || '';
      setModelBundles(bundles);
      setSelectedBundleId((currentId) => {
        if (bundles.some((bundle) => bundle.id === currentId)) {
          return currentId;
        }
        if (storedBundleId && bundles.some((bundle) => bundle.id === storedBundleId)) {
          return storedBundleId;
        }
        return defaultBundleId;
      });
      return bundles;
    } catch (error) {
      console.error('Failed to load model bundles:', error);
      return [];
    }
  }, [authUserId]);

  async function refreshAuthStatus() {
    try {
      const status = await api.getAuthStatus();
      setAuthState({
        loading: false,
        configured: status.configured,
        bootstrapRequired: status.bootstrap_required,
        user: status.user,
        error: '',
      });
      return status;
    } catch (error) {
      console.error('Failed to load auth status:', error);
      setAuthState((current) => ({
        ...current,
        loading: false,
        error: 'Auth status is unavailable.',
      }));
      return null;
    }
  }

  useEffect(() => {
    refreshAuthStatus();
  }, []);

  useEffect(() => {
    if (!authUserId) {
      setStarredConversationIds([]);
      setWorkbookEntriesByConversation({});
      return;
    }

    setStarredConversationIds(readLocalJson(buildStarredStorageKey(authUserId), []));
    setWorkbookEntriesByConversation(readLocalJson(buildWorkbookStorageKey(authUserId), {}));
  }, [authUserId]);

  useEffect(() => {
    if (!authUserId) {
      return;
    }

    window.localStorage.setItem(
      buildStarredStorageKey(authUserId),
      JSON.stringify(starredConversationIds)
    );
  }, [authUserId, starredConversationIds]);

  useEffect(() => {
    if (!authUserId) {
      return;
    }

    window.localStorage.setItem(
      buildWorkbookStorageKey(authUserId),
      JSON.stringify(workbookEntriesByConversation)
    );
  }, [authUserId, workbookEntriesByConversation]);

  useEffect(() => {
    if (!authUserId) {
      setConversations([]);
      setArchivedConversations([]);
      setCurrentConversationId(null);
      setCurrentConversation(null);
      setCurrentConversationOverview(null);
      setCurrentConversationEntities(null);
      setModelBundles([]);
      setSelectedBundleId('');
      return;
    }

    loadConversations();
    loadModelBundles();
  }, [authUserId, loadConversations, loadModelBundles]);

  useEffect(() => {
    if (!authUserId || !selectedBundleId) {
      return;
    }

    window.localStorage.setItem(
      buildBundleSelectionStorageKey(authUserId),
      selectedBundleId
    );
  }, [authUserId, selectedBundleId]);

  useEffect(() => {
    if (!isSidebarResizing) {
      return undefined;
    }

    const handleMouseMove = (event) => {
      const nextWidth = Math.min(460, Math.max(220, event.clientX));
      setSidebarWidth(nextWidth);
    };

    const handleMouseUp = () => {
      setIsSidebarResizing(false);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isSidebarResizing]);

  useEffect(() => {
    window.localStorage.setItem('llm-council-sidebar-width', String(sidebarWidth));
  }, [sidebarWidth]);

  useEffect(() => {
    if (!searchQuery.trim()) {
      setRequestedJumpTarget(null);
      setActiveSearchMatch(null);
    }
  }, [searchQuery]);

  useEffect(() => {
    let cancelled = false;
    const query = deferredSearchQuery.trim();

    if (!query) {
      setSearchResults([]);
      setSearchError('');
      setIsSearchLoading(false);
      return () => {
        cancelled = true;
      };
    }

    setIsSearchLoading(true);
    setSearchError('');

    const timeoutId = window.setTimeout(async () => {
      try {
        const payload = await api.searchConversations(query, 12, {
          startAt: toIsoSearchBoundary(searchDateRange.start, 'start'),
          endAt: toIsoSearchBoundary(searchDateRange.end, 'end'),
        });
        if (!cancelled) {
          setSearchResults(payload.results || []);
          setIsSearchLoading(false);
        }
      } catch (error) {
        if (!cancelled) {
          console.error('Failed to search conversations:', error);
          setSearchResults([]);
          setSearchError('Search failed.');
          setIsSearchLoading(false);
        }
      }
    }, 180);

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [deferredSearchQuery, searchDateRange, conversations, archivedConversations]);

  // Load conversation details when selected
  useEffect(() => {
    let cancelled = false;

    if (!currentConversationId) {
      setCurrentConversation(null);
      setCurrentConversationOverview(null);
      setCurrentConversationEntities(null);
      setOverviewError('');
      setEntitiesError('');
      setIsOverviewLoading(false);
      setIsEntitiesLoading(false);
      setIsTranscriptLoading(false);
      return () => {
        cancelled = true;
      };
    }

    setCurrentConversation(null);
    setCurrentConversationOverview(null);
    setCurrentConversationEntities(null);
    setOverviewError('');
    setEntitiesError('');
    setIsOverviewLoading(true);
    setIsEntitiesLoading(true);
    setIsTranscriptLoading(false);

    api.getConversationOverview(currentConversationId)
      .then(async (overview) => {
        if (cancelled) return;

        setCurrentConversationOverview(overview);
        setIsOverviewLoading(false);

        if (!overview.default_transcript_collapsed) {
          setIsTranscriptLoading(true);
          try {
            const conversation = await api.getConversation(currentConversationId);
            if (!cancelled) {
              setCurrentConversation(conversation);
            }
          } catch (error) {
            if (!cancelled) {
              console.error('Failed to load conversation:', error);
            }
          } finally {
            if (!cancelled) {
              setIsTranscriptLoading(false);
            }
          }
        }
      })
      .catch((error) => {
        if (cancelled) return;
        console.error('Failed to load conversation overview:', error);
        setOverviewError('Failed to load conversation overview.');
        setIsOverviewLoading(false);
        setIsTranscriptLoading(true);

        api.getConversation(currentConversationId)
          .then((conversation) => {
            if (!cancelled) {
              setCurrentConversation(conversation);
            }
          })
          .catch((conversationError) => {
            if (!cancelled) {
              console.error('Failed to load conversation:', conversationError);
            }
          })
          .finally(() => {
            if (!cancelled) {
              setIsTranscriptLoading(false);
            }
          });
      });

    api.getConversationEntities(currentConversationId)
      .then((payload) => {
        if (cancelled) return;
        setCurrentConversationEntities(payload);
        setIsEntitiesLoading(false);
      })
      .catch((error) => {
        if (cancelled) return;
        console.error('Failed to load conversation entities:', error);
        setEntitiesError('Failed to load conversation entities.');
        setIsEntitiesLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [currentConversationId]);

  useEffect(() => {
    if (
      !currentConversationId ||
      !currentConversationOverview ||
      (!currentConversationOverview.memory_pending && !currentConversationOverview.turn_index_pending)
    ) {
      return undefined;
    }

    const timeoutId = window.setTimeout(async () => {
      try {
        const overview = await api.getConversationOverview(currentConversationId);
        setCurrentConversationOverview(overview);
      } catch (error) {
        console.error('Failed to refresh conversation overview:', error);
      }
    }, 3000);

    return () => window.clearTimeout(timeoutId);
  }, [currentConversationId, currentConversationOverview]);

  useEffect(() => {
    if (!currentConversationId || !currentConversationEntities?.pending) {
      return undefined;
    }

    const timeoutId = window.setTimeout(async () => {
      try {
        const payload = await api.getConversationEntities(currentConversationId);
        setCurrentConversationEntities(payload);
      } catch (error) {
        console.error('Failed to refresh conversation entities:', error);
      }
    }, 3000);

    return () => window.clearTimeout(timeoutId);
  }, [currentConversationId, currentConversationEntities]);

  const loadCurrentConversationTranscript = async () => {
    if (!currentConversationId) return null;

    setIsTranscriptLoading(true);
    try {
      const conversation = await api.getConversation(currentConversationId);
      setCurrentConversation(conversation);
      return conversation;
    } catch (error) {
      console.error('Failed to load conversation:', error);
      return null;
    } finally {
      setIsTranscriptLoading(false);
    }
  };

  const refreshConversationPanels = async (conversationId) => {
    if (!conversationId) {
      return;
    }

    try {
      const [overview, entities] = await Promise.all([
        api.getConversationOverview(conversationId),
        api.getConversationEntities(conversationId),
      ]);

      if (currentConversationIdRef.current !== conversationId) {
        return;
      }

      setCurrentConversationOverview(overview);
      setCurrentConversationEntities(entities);
      setOverviewError('');
      setEntitiesError('');
    } catch (error) {
      console.error('Failed to refresh derived conversation panels:', error);
    }
  };

  const handleSaveBundle = async (bundle) => {
    let savedBundle = null;
    if (bundle.id) {
      savedBundle = await api.updateModelBundle(bundle.id, {
        name: bundle.name,
        council_models: bundle.council_models,
        chairman_model: bundle.chairman_model,
      });
    } else {
      savedBundle = await api.createModelBundle({
        name: bundle.name,
        council_models: bundle.council_models,
        chairman_model: bundle.chairman_model,
      });
    }

    await loadModelBundles();
    if (savedBundle?.id) {
      setSelectedBundleId(savedBundle.id);
    }
  };

  const handleDeleteBundle = async (bundleId) => {
    await api.deleteModelBundle(bundleId);
    await loadModelBundles();
  };

  const handleReorderBundles = async (bundleIds) => {
    await api.reorderModelBundles(bundleIds);
    await loadModelBundles();
  };

  const handleSetDefaultBundle = async (bundleId) => {
    await api.setDefaultModelBundle(bundleId);
    await loadModelBundles();
  };

  const handleNewConversation = async () => {
    try {
      const newConv = await api.createConversation();
      setConversations([
        {
          id: newConv.id,
          created_at: newConv.created_at,
          title: newConv.title,
          message_count: 0,
          archived: false,
          archived_at: null,
        },
        ...conversations,
      ]);
      setCurrentConversationId(newConv.id);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setRequestedJumpTarget(null);
    setActiveSearchMatch(null);
    setCurrentConversationId(id);
  };

  const handleSelectSearchResult = (result) => {
    const messageIndexOneBased = result?.metadata?.message_index;
    const nextJumpTarget = Number.isInteger(messageIndexOneBased) && messageIndexOneBased > 0
      ? {
          conversationId: result.conversation_id,
          messageIndex: messageIndexOneBased - 1,
          requestId: `${result.conversation_id}:${result.source_type}:${result.source_ref}:${result.chunk_index}:${Date.now()}`,
        }
      : null;

    setActiveSearchMatch({
      conversationId: result.conversation_id,
      messageIndex: Number.isInteger(messageIndexOneBased) && messageIndexOneBased > 0
        ? messageIndexOneBased - 1
        : null,
      sourceType: result.source_type || null,
      query: searchQuery.trim(),
    });
    setRequestedJumpTarget(nextJumpTarget);
    setCurrentConversationId(result.conversation_id);
  };

  const handleRenameConversation = async (conversationId, title) => {
    try {
      const updatedConversation = await api.renameConversation(conversationId, title);
      await loadConversations();
      if (conversationId === currentConversationId) {
        if (currentConversation) {
          setCurrentConversation(updatedConversation);
        }
        setCurrentConversationOverview((currentOverview) => (
          currentOverview
            ? { ...currentOverview, title: updatedConversation.title }
            : currentOverview
        ));
      }
    } catch (error) {
      console.error('Failed to rename conversation:', error);
    }
  };

  const clearCurrentConversationIfNeeded = (conversationId) => {
    if (conversationId === currentConversationId) {
      setCurrentConversationId(null);
      setCurrentConversation(null);
      setCurrentConversationOverview(null);
      setCurrentConversationEntities(null);
      setOverviewError('');
      setEntitiesError('');
      setIsOverviewLoading(false);
      setIsEntitiesLoading(false);
      setIsTranscriptLoading(false);
    }
  };

  const handleArchiveConversation = async (conversationId) => {
    try {
      await api.archiveConversation(conversationId);
      clearCurrentConversationIfNeeded(conversationId);
      await loadConversations();
    } catch (error) {
      console.error('Failed to archive conversation:', error);
    }
  };

  const handleRestoreConversation = async (conversationId) => {
    try {
      await api.restoreConversation(conversationId);
      await loadConversations();
    } catch (error) {
      console.error('Failed to restore conversation:', error);
    }
  };

  const handleDeleteConversation = async (conversationId) => {
    try {
      await api.deleteConversation(conversationId);
      clearCurrentConversationIfNeeded(conversationId);
      setStarredConversationIds((currentIds) => currentIds.filter((id) => id !== conversationId));
      setWorkbookEntriesByConversation((currentEntries) => {
        if (!(conversationId in currentEntries)) {
          return currentEntries;
        }

        const nextEntries = { ...currentEntries };
        delete nextEntries[conversationId];
        return nextEntries;
      });
      await loadConversations();
    } catch (error) {
      console.error('Failed to delete conversation:', error);
    }
  };

  const handleToggleStarConversation = (conversationId) => {
    setStarredConversationIds((currentIds) => (
      currentIds.includes(conversationId)
        ? currentIds.filter((id) => id !== conversationId)
        : [...currentIds, conversationId]
    ));
  };

  const handleClipSelectionsToWorkbook = (conversationId, selections) => {
    if (!conversationId || selections.length === 0) {
      return;
    }

    setWorkbookEntriesByConversation((currentEntries) => ({
      ...currentEntries,
      [conversationId]: [
        ...(currentEntries[conversationId] || []),
        ...selections.map(createWorkbookItem),
      ],
    }));
  };

  const handleUpdateWorkbookItem = (conversationId, itemId, text) => {
    setWorkbookEntriesByConversation((currentEntries) => ({
      ...currentEntries,
      [conversationId]: (currentEntries[conversationId] || []).map((item) => (
        item.id === itemId ? { ...item, text } : item
      )),
    }));
  };

  const handleDeleteWorkbookItem = (conversationId, itemId) => {
    setWorkbookEntriesByConversation((currentEntries) => ({
      ...currentEntries,
      [conversationId]: (currentEntries[conversationId] || []).filter((item) => item.id !== itemId),
    }));
  };

  const handleSendMessage = async (content, bundleId) => {
    if (!currentConversationId) return;

    const conversationIdForSend = currentConversationId;
    const selectedBundle = modelBundles.find((bundle) => bundle.id === bundleId);
    setIsLoading(true);
    let addedOptimisticMessages = false;
    try {
      let conversationForSend = currentConversation;
      if (!conversationForSend) {
        conversationForSend = await loadCurrentConversationTranscript();
      }

      if (!conversationForSend) {
        throw new Error('Failed to load conversation transcript');
      }

      // Optimistically add user message to UI
      const userMessage = {
        role: 'user',
        content,
        created_at: new Date().toISOString(),
        bundle: selectedBundle
          ? { id: selectedBundle.id, name: selectedBundle.name }
          : null,
      };
      setCurrentConversation((prev) => ({
        ...(prev ?? conversationForSend),
        messages: [...(prev ?? conversationForSend).messages, userMessage],
      }));

      // Create a partial assistant message that will be updated progressively
      const assistantMessage = {
        role: 'assistant',
        created_at: new Date().toISOString(),
        stage1: null,
        stage2: null,
        stage3: null,
        metadata: null,
        error: null,
        loading: {
          stage1: false,
          stage2: false,
          stage3: false,
        },
        bundle: selectedBundle
          ? {
              id: selectedBundle.id,
              name: selectedBundle.name,
              chairman_model: selectedBundle.chairman_model,
              council_models: selectedBundle.council_models,
            }
          : null,
      };

      // Add the partial assistant message
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, assistantMessage],
      }));
      addedOptimisticMessages = true;

      setCurrentConversationOverview((currentOverview) => (
        currentOverview
          ? { ...currentOverview, message_count: currentOverview.message_count + 2 }
          : currentOverview
      ));

      // Send message with streaming
      await api.sendMessageStream(conversationIdForSend, content, bundleId, (eventType, event) => {
        switch (eventType) {
          case 'stage1_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage1 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage1_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage1 = event.data;
              lastMsg.loading.stage1 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage2_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage2 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage2_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage2 = event.data;
              lastMsg.metadata = event.metadata;
              lastMsg.loading.stage2 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage3_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage3 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage3_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage3 = event.data;
              if (event.metadata) {
                lastMsg.metadata = event.metadata;
              }
              lastMsg.loading.stage3 = false;
              return { ...prev, messages };
            });
            if (event.metadata?.usage?.summary) {
              setCurrentConversationOverview((currentOverview) => (
                currentOverview
                  ? {
                      ...currentOverview,
                      usage_summary: event.metadata.usage.summary,
                    }
                  : currentOverview
              ));
            }
            break;

          case 'title_complete':
            if (event.data?.title) {
              setCurrentConversation((prev) => (
                prev
                  ? {
                      ...prev,
                      title: event.data.title,
                      messages: prev.messages.map((message, index, messages) => (
                        index === messages.length - 1
                          ? {
                              ...message,
                              metadata: event.data.usage_summary
                                ? {
                                    ...(message.metadata || {}),
                                    usage: event.data.usage_summary,
                                  }
                                : message.metadata,
                            }
                          : message
                      )),
                    }
                  : prev
              ));
              setCurrentConversationOverview((currentOverview) => (
                currentOverview
                  ? {
                      ...currentOverview,
                      title: event.data.title,
                      usage_summary: event.data.usage_summary?.summary || currentOverview.usage_summary,
                    }
                  : currentOverview
              ));
            }
            loadConversations();
            break;

          case 'complete':
            // Stream complete, reload conversations list
            loadConversations();
            setIsLoading(false);
            break;

          case 'error':
            console.error('Stream error:', event.message);
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              if (lastMsg?.loading) {
                lastMsg.loading = {
                  stage1: false,
                  stage2: false,
                  stage3: false,
                };
              }
              if (lastMsg) {
                lastMsg.error = {
                  message: event.message || 'The council run failed.',
                  details: event.details || null,
                };
              }
              return { ...prev, messages };
            });
            setIsLoading(false);
            break;

          default:
            console.log('Unknown event type:', eventType);
        }
      });
      await refreshConversationPanels(conversationIdForSend);
    } catch (error) {
      console.error('Failed to send message:', error);
      // Remove optimistic messages on error
      if (addedOptimisticMessages) {
        setCurrentConversation((prev) => (
          prev
            ? {
                ...prev,
                messages: prev.messages.slice(0, -2),
              }
            : prev
        ));
        setCurrentConversationOverview((currentOverview) => (
          currentOverview
            ? {
                ...currentOverview,
                message_count: Math.max(0, currentOverview.message_count - 2),
              }
            : currentOverview
        ));
      }
      setIsLoading(false);
    }
  };

  const handleAuthSubmit = async (username, password) => {
    setIsAuthSubmitting(true);
    setAuthState((current) => ({ ...current, error: '' }));

    try {
      const payload = authState.bootstrapRequired
        ? await api.bootstrapAdmin(username, password)
        : await api.login(username, password);

      setAuthState((current) => ({
        ...current,
        loading: false,
        bootstrapRequired: false,
        user: payload.user,
        error: '',
      }));
    } catch (error) {
      console.error('Auth failed:', error);
      setAuthState((current) => ({
        ...current,
        error: error.details?.detail || 'Authentication failed.',
      }));
    } finally {
      setIsAuthSubmitting(false);
    }
  };

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch (error) {
      console.error('Logout failed:', error);
    } finally {
      await refreshAuthStatus();
    }
  };

  if (authState.loading) {
    return (
      <div className="auth-page">
        <div className="auth-panel auth-panel-static">
          <h1>LLM Council</h1>
          <p>Checking session...</p>
        </div>
      </div>
    );
  }

  if (!authState.configured) {
    return (
      <div className="auth-page">
        <div className="auth-panel auth-panel-static">
          <h1>LLM Council</h1>
          <p>Postgres is required for local accounts. Set DATABASE_URL and restart the app.</p>
        </div>
      </div>
    );
  }

  if (!authState.user) {
    return (
      <AuthScreen
        mode={authState.bootstrapRequired ? 'bootstrap' : 'login'}
        error={authState.error}
        isSubmitting={isAuthSubmitting}
        onSubmit={handleAuthSubmit}
      />
    );
  }

  return (
    <div className="app">
      <div className="app-chrome">
        <span className="app-chrome-dot app-chrome-dot-red" />
        <span className="app-chrome-dot app-chrome-dot-yellow" />
        <span className="app-chrome-dot app-chrome-dot-green" />
        <span className="app-chrome-label">deliberati.app/conversation</span>
      </div>
      <div className="app-grid">
        <div
          className={`sidebar-shell ${isSidebarResizing ? 'resizing' : ''}`}
          style={{
            width: `${sidebarWidth}px`,
            flexBasis: `${sidebarWidth}px`,
          }}
        >
          <Sidebar
            conversations={conversations}
            archivedConversations={archivedConversations}
            starredConversationIds={starredConversationIds}
            currentConversationId={currentConversationId}
            searchQuery={searchQuery}
            onSearchQueryChange={setSearchQuery}
            searchDateRange={searchDateRange}
            onSearchDateRangeChange={setSearchDateRange}
            searchResults={searchResults}
            isSearchLoading={isSearchLoading}
            searchError={searchError}
            onSelectConversation={handleSelectConversation}
            onSelectSearchResult={handleSelectSearchResult}
            onNewConversation={handleNewConversation}
            onRenameConversation={handleRenameConversation}
            onArchiveConversation={handleArchiveConversation}
            onRestoreConversation={handleRestoreConversation}
            onDeleteConversation={handleDeleteConversation}
            onToggleStarConversation={handleToggleStarConversation}
            modelBundles={modelBundles}
            selectedBundleId={selectedBundleId}
            onSelectBundle={setSelectedBundleId}
            onSaveBundle={handleSaveBundle}
            onDeleteBundle={handleDeleteBundle}
            onReorderBundles={handleReorderBundles}
            onSetDefaultBundle={handleSetDefaultBundle}
            currentUser={authState.user}
            onLogout={handleLogout}
          />
          <div
            className="sidebar-resizer"
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize council sidebar"
            onMouseDown={(event) => {
              event.preventDefault();
              setIsSidebarResizing(true);
            }}
          />
        </div>
        <ChatInterface
          key={currentConversationId || 'no-conversation'}
          conversation={currentConversation}
          conversationSelected={Boolean(currentConversationId)}
          conversationOverview={currentConversationOverview}
          conversationEntities={currentConversationEntities}
          workbookItems={workbookEntriesByConversation[currentConversationId] || []}
          requestedJumpTarget={requestedJumpTarget}
          activeSearchMatch={activeSearchMatch}
          onSendMessage={handleSendMessage}
          onLoadTranscript={loadCurrentConversationTranscript}
          onClipSelectionsToWorkbook={handleClipSelectionsToWorkbook}
          onUpdateWorkbookItem={handleUpdateWorkbookItem}
          onDeleteWorkbookItem={handleDeleteWorkbookItem}
          isLoading={isLoading}
          isOverviewLoading={isOverviewLoading}
          overviewError={overviewError}
          isEntitiesLoading={isEntitiesLoading}
          entitiesError={entitiesError}
          isTranscriptLoading={isTranscriptLoading}
          modelBundles={modelBundles}
          selectedBundleId={selectedBundleId}
          onSelectBundle={setSelectedBundleId}
        />
      </div>
    </div>
  );
}

export default App;
