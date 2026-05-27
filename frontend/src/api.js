/**
 * API client for the LLM Council backend.
 */

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.DEV ? 'http://localhost:8002' : '');

function getCookie(name) {
  const prefix = `${name}=`;
  return document.cookie
    .split(';')
    .map((cookie) => cookie.trim())
    .find((cookie) => cookie.startsWith(prefix))
    ?.slice(prefix.length) || '';
}

function isUnsafeMethod(method = 'GET') {
  return ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method.toUpperCase());
}

function buildHeaders(options = {}) {
  const headers = {
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers || {}),
  };
  const method = options.method || 'GET';
  const csrfToken = getCookie('llm_council_csrf');
  if (csrfToken && isUnsafeMethod(method)) {
    headers['X-CSRF-Token'] = csrfToken;
  }
  return headers;
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    ...options,
    headers: buildHeaders(options),
  });

  if (!response.ok) {
    const error = new Error(`Request failed: ${response.status}`);
    error.status = response.status;
    try {
      error.details = await response.json();
    } catch {
      error.details = null;
    }
    throw error;
  }

  return response.json();
}

export const api = {
  /**
   * Get auth/bootstrap status.
   */
  async getAuthStatus() {
    return request('/api/auth/status');
  },

  /**
   * Create the first admin user.
   */
  async bootstrapAdmin(username, password) {
    return request('/api/auth/bootstrap', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
  },

  /**
   * Log in with local credentials.
   */
  async login(username, password) {
    return request('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
  },

  /**
   * Log out the current session.
   */
  async logout() {
    return request('/api/auth/logout', {
      method: 'POST',
    });
  },

  /**
   * Create a local user. Admin-only.
   */
  async createUser(username, password, role = 'member') {
    return request('/api/users', {
      method: 'POST',
      body: JSON.stringify({ username, password, role }),
    });
  },

  /**
   * List local users. Admin-only.
   */
  async listUsers() {
    return request('/api/users');
  },

  /**
   * Update a local user. Admin-only.
   */
  async updateUser(userId, updates) {
    return request(`/api/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify(updates),
    });
  },

  /**
   * List all conversations.
   */
  async listConversations({ archived = false } = {}) {
    return request(`/api/conversations?archived=${archived}`);
  },

  /**
   * List all model bundles.
   */
  async listModelBundles() {
    return request('/api/model-bundles');
  },

  /**
   * Create a model bundle.
   */
  async createModelBundle(bundle) {
    return request('/api/model-bundles', {
      method: 'POST',
      body: JSON.stringify(bundle),
    });
  },

  /**
   * Update a model bundle.
   */
  async updateModelBundle(bundleId, bundle) {
    return request(`/api/model-bundles/${bundleId}`, {
      method: 'PUT',
      body: JSON.stringify(bundle),
    });
  },

  /**
   * Reorder model bundles.
   */
  async reorderModelBundles(bundleIds) {
    return request('/api/model-bundles/reorder', {
      method: 'POST',
      body: JSON.stringify({ bundle_ids: bundleIds }),
    });
  },

  /**
   * Set the default model bundle.
   */
  async setDefaultModelBundle(bundleId) {
    return request(`/api/model-bundles/${bundleId}/default`, {
      method: 'POST',
    });
  },

  /**
   * Delete a model bundle.
   */
  async deleteModelBundle(bundleId) {
    return request(`/api/model-bundles/${bundleId}`, {
      method: 'DELETE',
    });
  },

  /**
   * Create a new conversation.
   */
  async createConversation() {
    return request('/api/conversations', {
      method: 'POST',
      body: JSON.stringify({}),
    });
  },

  /**
   * Get a specific conversation.
   */
  async getConversation(conversationId) {
    return request(`/api/conversations/${conversationId}`);
  },

  /**
   * Get compact overview data for a conversation.
   */
  async getConversationOverview(conversationId) {
    return request(`/api/conversations/${conversationId}/overview`);
  },

  /**
   * Get extracted entities and themes for a conversation.
   */
  async getConversationEntities(conversationId) {
    return request(`/api/conversations/${conversationId}/entities`);
  },

  /**
   * Search conversations and indexed transcript chunks.
   */
  async searchConversations(query, limit = 12, filters = {}) {
    const params = new URLSearchParams({
      q: query,
      limit: String(limit),
    });
    if (filters.startAt) {
      params.set('start_at', filters.startAt);
    }
    if (filters.endAt) {
      params.set('end_at', filters.endAt);
    }
    return request(`/api/search?${params.toString()}`);
  },

  /**
   * Rename a conversation.
   */
  async renameConversation(conversationId, title) {
    return request(`/api/conversations/${conversationId}`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    });
  },

  /**
   * Archive a conversation.
   */
  async archiveConversation(conversationId) {
    return request(`/api/conversations/${conversationId}/archive`, { method: 'POST' });
  },

  /**
   * Restore an archived conversation.
   */
  async restoreConversation(conversationId) {
    return request(`/api/conversations/${conversationId}/restore`, { method: 'POST' });
  },

  /**
   * Permanently delete a conversation.
   */
  async deleteConversation(conversationId) {
    return request(`/api/conversations/${conversationId}`, { method: 'DELETE' });
  },

  /**
   * Send a message in a conversation.
   */
  async sendMessage(conversationId, content, bundleId) {
    return request(`/api/conversations/${conversationId}/message`, {
      method: 'POST',
      body: JSON.stringify({ content, bundle_id: bundleId }),
    });
  },

  /**
   * Send a message and receive streaming updates.
   * @param {string} conversationId - The conversation ID
   * @param {string} content - The message content
   * @param {function} onEvent - Callback function for each event: (eventType, data) => void
   * @returns {Promise<void>}
   */
  async sendMessageStream(conversationId, content, bundleId, onEvent) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message/stream`,
      {
        method: 'POST',
        credentials: 'include',
        headers: buildHeaders({
          method: 'POST',
          body: true,
        }),
        body: JSON.stringify({ content, bundle_id: bundleId }),
      }
    );

    if (!response.ok) {
      throw new Error('Failed to send message');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const processEventBlock = (block) => {
      const data = block
        .split('\n')
        .filter((line) => line.startsWith('data: '))
        .map((line) => line.slice(6))
        .join('\n');

      if (!data) return;

      try {
        const event = JSON.parse(data);
        onEvent(event.type, event);
      } catch (e) {
        console.error('Failed to parse SSE event:', e, data);
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        break;
      }

      buffer += decoder.decode(value, { stream: true });

      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() ?? '';

      for (const block of blocks) {
        processEventBlock(block);
      }
    }

    if (buffer.trim()) {
      processEventBlock(buffer);
    }
  },
};
