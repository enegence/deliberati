function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function getHighlightTerms(query) {
  return Array.from(
    new Set(
      (query || '')
        .trim()
        .split(/\s+/)
        .map((term) => term.trim())
        .filter((term) => term.length > 1)
        .sort((left, right) => right.length - left.length)
    )
  );
}

function buildHighlightPattern(terms) {
  return new RegExp(`(${terms.map(escapeRegExp).join('|')})`, 'ig');
}

export function renderHighlightedText(text, query, keyPrefix = 'search-highlight') {
  if (!text) {
    return null;
  }

  const terms = getHighlightTerms(query);
  if (terms.length === 0) {
    return text;
  }

  const pattern = buildHighlightPattern(terms);
  const parts = text.split(pattern);
  const loweredTerms = new Set(terms.map((term) => term.toLowerCase()));

  return parts.map((part, index) => (
    loweredTerms.has(part.toLowerCase())
      ? (
        <mark className="transcript-search-inline-mark" key={`${keyPrefix}-${index}`}>
          {part}
        </mark>
      )
      : <span key={`${keyPrefix}-${index}`}>{part}</span>
  ));
}
