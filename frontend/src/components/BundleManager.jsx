import { useState } from 'react';
import './BundleManager.css';

function modelTextToList(value) {
  return value
    .split('\n')
    .map((model) => model.trim())
    .filter(Boolean);
}

export default function BundleManager({
  bundles,
  selectedBundleId,
  onSelectBundle,
  onSaveBundle,
  onDeleteBundle,
  onReorderBundles,
  onSetDefaultBundle,
  canManageBundles = false,
}) {
  const [editingId, setEditingId] = useState(null);
  const [name, setName] = useState('');
  const [councilModelsText, setCouncilModelsText] = useState('');
  const [chairmanModel, setChairmanModel] = useState('');
  const [error, setError] = useState('');
  const [draggingBundleId, setDraggingBundleId] = useState(null);

  const handleEdit = (bundle) => {
    setEditingId(bundle.id);
    setName(bundle.name);
    setCouncilModelsText((bundle.council_models || []).join('\n'));
    setChairmanModel(bundle.chairman_model || '');
    setError('');
  };

  const handleNew = () => {
    setEditingId(null);
    setName('');
    setCouncilModelsText('');
    setChairmanModel('');
    setError('');
  };

  const handleSubmit = async (event) => {
    event.preventDefault();

    const councilModels = modelTextToList(councilModelsText);
    if (!name.trim() || councilModels.length === 0 || !chairmanModel.trim()) {
      setError('Name, council models, and chairman are required.');
      return;
    }

    setError('');
    await onSaveBundle({
      id: editingId,
      name: name.trim(),
      council_models: councilModels,
      chairman_model: chairmanModel.trim(),
    });

    handleNew();
  };

  const handleDelete = async () => {
    if (!editingId) return;

    setError('');
    await onDeleteBundle(editingId);
    handleNew();
  };

  const handleDrop = async (targetBundleId) => {
    if (!canManageBundles) {
      setDraggingBundleId(null);
      return;
    }

    if (!draggingBundleId || draggingBundleId === targetBundleId) {
      setDraggingBundleId(null);
      return;
    }

    const sourceIndex = bundles.findIndex((bundle) => bundle.id === draggingBundleId);
    const targetIndex = bundles.findIndex((bundle) => bundle.id === targetBundleId);
    if (sourceIndex === -1 || targetIndex === -1) {
      setDraggingBundleId(null);
      return;
    }

    const reorderedBundles = [...bundles];
    const [movedBundle] = reorderedBundles.splice(sourceIndex, 1);
    reorderedBundles.splice(targetIndex, 0, movedBundle);
    setDraggingBundleId(null);
    await onReorderBundles(reorderedBundles.map((bundle) => bundle.id));
  };

  return (
    <div className="bundle-manager">
      <div className="bundle-list-header">
        <div>
          <h3>Bundle Order</h3>
          <p>Drag bundles to change their position. Click the number badge to set the default bundle.</p>
          {!canManageBundles && <p>Bundle editing is available to admins only.</p>}
        </div>
      </div>
      <div className="bundle-list">
        {bundles.map((bundle) => (
          <div
            key={bundle.id}
            className={`bundle-item ${bundle.id === selectedBundleId ? 'selected' : ''} ${bundle.id === draggingBundleId ? 'dragging' : ''}`}
            onClick={() => {
              onSelectBundle(bundle.id);
              if (canManageBundles) {
                handleEdit(bundle);
              }
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                onSelectBundle(bundle.id);
                if (canManageBundles) {
                  handleEdit(bundle);
                }
              }
            }}
            role="button"
            tabIndex={0}
            draggable={canManageBundles}
            onDragStart={() => setDraggingBundleId(bundle.id)}
            onDragEnd={() => setDraggingBundleId(null)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              handleDrop(bundle.id);
            }}
          >
            <div className="bundle-item-topline">
              <span
                className={`bundle-order-badge ${bundle.is_default ? 'default' : ''} ${canManageBundles ? 'interactive' : ''}`}
                role={canManageBundles ? 'button' : undefined}
                tabIndex={canManageBundles ? 0 : undefined}
                onClick={(event) => {
                  if (!canManageBundles || bundle.is_default) {
                    return;
                  }
                  event.stopPropagation();
                  onSetDefaultBundle(bundle.id);
                }}
                onKeyDown={(event) => {
                  if (!canManageBundles || bundle.is_default) {
                    return;
                  }
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    event.stopPropagation();
                    onSetDefaultBundle(bundle.id);
                  }
                }}
                aria-label={bundle.is_default ? 'Default bundle' : `Set ${bundle.name} as default bundle`}
                title={bundle.is_default ? 'Default bundle' : 'Set as default bundle'}
              >
                {bundle.is_default ? '✓' : bundle.position}
              </span>
              <span className="bundle-name">{bundle.name}</span>
              <span className="bundle-drag-handle" aria-hidden="true">
                ::
              </span>
            </div>
            <span className="bundle-meta">
              {bundle.council_models.length} models
            </span>
          </div>
        ))}
      </div>

      {canManageBundles && (
        <form className="bundle-form" onSubmit={handleSubmit}>
          <div className="bundle-form-header">
            <h2>{editingId ? 'Edit Bundle' : 'New Bundle'}</h2>
            <button type="button" className="secondary-button" onClick={handleNew}>
              New
            </button>
          </div>

          <label className="field-label">
            Name
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Reasoning Council"
            />
          </label>

          <label className="field-label">
            Council models
            <textarea
              value={councilModelsText}
              onChange={(event) => setCouncilModelsText(event.target.value)}
              placeholder={'openai/gpt-5.4\ngoogle/gemini-3.1-pro-preview\nanthropic/claude-sonnet-4.6'}
              rows={6}
            />
          </label>

          <label className="field-label">
            Chairman
            <input
              value={chairmanModel}
              onChange={(event) => setChairmanModel(event.target.value)}
              placeholder="google/gemini-3.1-pro-preview"
            />
          </label>

          {error && <div className="bundle-error">{error}</div>}

          <div className="bundle-actions">
            <button type="submit" className="save-bundle-button">
              Save Bundle
            </button>
            {editingId && bundles.length > 1 && (
              <button
                type="button"
                className="delete-bundle-button"
                onClick={handleDelete}
              >
                Delete
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}
