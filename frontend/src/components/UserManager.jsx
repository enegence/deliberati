import { useEffect, useState } from 'react';
import { api } from '../api';

function formatCreatedAt(value) {
  if (!value) return 'Unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export default function UserManager({ currentUser }) {
  const [users, setUsers] = useState([]);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('member');
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState('');

  const loadUsers = async () => {
    setIsLoading(true);
    setError('');
    try {
      const payload = await api.listUsers();
      setUsers(payload.users || []);
    } catch (loadError) {
      console.error('Failed to load users:', loadError);
      setError(loadError.details?.detail || 'Could not load users.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadUsers();
  }, []);

  const handleCreateUser = async (event) => {
    event.preventDefault();
    setIsSaving(true);
    setError('');
    try {
      await api.createUser(username, password, role);
      setUsername('');
      setPassword('');
      setRole('member');
      await loadUsers();
    } catch (createError) {
      console.error('Failed to create user:', createError);
      setError(createError.details?.detail || 'Could not create user.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleRoleChange = async (user, nextRole) => {
    if (nextRole === user.role) return;
    setError('');
    try {
      const payload = await api.updateUser(user.id, { role: nextRole });
      setUsers((currentUsers) => (
        currentUsers.map((entry) => (entry.id === user.id ? payload.user : entry))
      ));
    } catch (updateError) {
      console.error('Failed to update user role:', updateError);
      setError(updateError.details?.detail || 'Could not update user.');
    }
  };

  const handleDisabledChange = async (user, disabled) => {
    setError('');
    try {
      const payload = await api.updateUser(user.id, { disabled });
      setUsers((currentUsers) => (
        currentUsers.map((entry) => (entry.id === user.id ? payload.user : entry))
      ));
    } catch (updateError) {
      console.error('Failed to update user status:', updateError);
      setError(updateError.details?.detail || 'Could not update user.');
    }
  };

  return (
    <div className="user-manager">
      <form className="user-create-form" onSubmit={handleCreateUser}>
        <div className="user-create-grid">
          <label className="field-label">
            Username
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              placeholder="household-user"
            />
          </label>
          <label className="field-label">
            Password
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
              type="password"
              placeholder="Minimum 8 characters"
            />
          </label>
          <label className="field-label">
            Role
            <select value={role} onChange={(event) => setRole(event.target.value)}>
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
          </label>
        </div>
        <button className="save-bundle-button" type="submit" disabled={isSaving}>
          {isSaving ? 'Creating...' : 'Create User'}
        </button>
      </form>

      {error && <div className="bundle-error">{error}</div>}

      <div className="user-list-header">
        <span>Accounts</span>
        <button type="button" onClick={loadUsers} disabled={isLoading}>
          {isLoading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      <div className="user-list">
        {users.map((user) => {
          const isCurrentUser = user.id === currentUser?.id;
          const isDisabled = Boolean(user.disabled_at);
          return (
            <div key={user.id} className={`user-item ${isDisabled ? 'disabled' : ''}`}>
              <div className="user-item-main">
                <div className="user-name-row">
                  <span className="user-name">{user.username}</span>
                  {isCurrentUser && <span className="user-badge">You</span>}
                  {isDisabled && <span className="user-badge muted">Disabled</span>}
                </div>
                <span className="user-meta">Created {formatCreatedAt(user.created_at)}</span>
              </div>
              <div className="user-controls">
                <select
                  value={user.role}
                  onChange={(event) => handleRoleChange(user, event.target.value)}
                  aria-label={`Role for ${user.username}`}
                >
                  <option value="member">Member</option>
                  <option value="admin">Admin</option>
                </select>
                <button
                  type="button"
                  className={isDisabled ? 'secondary-button' : 'delete-bundle-button'}
                  disabled={isCurrentUser && !isDisabled}
                  onClick={() => handleDisabledChange(user, !isDisabled)}
                >
                  {isDisabled ? 'Enable' : 'Disable'}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
