import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { NodeEditor } from '../pages/loom/authoring';
import { useGraphStore } from '../graph/store';
import type { ReactElement } from 'react';

function Editor(): ReactElement {
  const store = useGraphStore('ring-8');
  return <NodeEditor store={store} />;
}

afterEach(cleanup);

describe('graph authoring keyboard access', () => {
  it('selects a canvas node with Enter and exposes its selected state', () => {
    localStorage.clear();
    render(<Editor />);
    const node = screen.getByRole('button', { name: 'n1 compute_tile' });
    expect(node.getAttribute('aria-pressed')).toBe('false');
    node.focus();
    fireEvent.keyDown(node, { key: 'Enter' });
    expect(node.getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByLabelText('node x')).toBeTruthy();
  });

  it('selects a canvas node with Space', () => {
    localStorage.clear();
    render(<Editor />);
    const node = screen.getByRole('button', { name: 'n2 compute_tile' });
    node.focus();
    fireEvent.keyDown(node, { key: ' ' });
    expect(node.getAttribute('aria-pressed')).toBe('true');
  });
});
