import ReactMarkdown from 'react-markdown';

const SKIP_HIGHLIGHT_TAGS = new Set(['code', 'pre', 'script', 'style']);

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

function buildHighlightedNodes(value, pattern) {
  if (!value) {
    return [];
  }

  pattern.lastIndex = 0;
  const nodes = [];
  let lastIndex = 0;
  let match = pattern.exec(value);

  while (match) {
    if (match.index > lastIndex) {
      nodes.push({
        type: 'text',
        value: value.slice(lastIndex, match.index),
      });
    }

    nodes.push({
      type: 'element',
      tagName: 'mark',
      properties: {
        className: ['transcript-search-inline-mark'],
      },
      children: [
        {
          type: 'text',
          value: match[0],
        },
      ],
    });

    lastIndex = match.index + match[0].length;
    match = pattern.exec(value);
  }

  if (lastIndex < value.length) {
    nodes.push({
      type: 'text',
      value: value.slice(lastIndex),
    });
  }

  return nodes;
}

function highlightTree(node, pattern) {
  if (!node?.children || !Array.isArray(node.children)) {
    return;
  }

  if (node.type === 'element' && SKIP_HIGHLIGHT_TAGS.has(node.tagName)) {
    return;
  }

  node.children = node.children.flatMap((child) => {
    if (child.type === 'text') {
      return buildHighlightedNodes(child.value, pattern);
    }

    highlightTree(child, pattern);
    return [child];
  });
}

function rehypeHighlightMatches({ query = '' } = {}) {
  const terms = getHighlightTerms(query);

  return (tree) => {
    if (terms.length === 0) {
      return;
    }

    highlightTree(tree, buildHighlightPattern(terms));
  };
}

export default function HighlightedMarkdown({ children, highlightQuery = '' }) {
  const trimmedQuery = (highlightQuery || '').trim();

  return (
    <ReactMarkdown
      rehypePlugins={
        trimmedQuery
          ? [[rehypeHighlightMatches, { query: trimmedQuery }]]
          : undefined
      }
    >
      {children || ''}
    </ReactMarkdown>
  );
}
