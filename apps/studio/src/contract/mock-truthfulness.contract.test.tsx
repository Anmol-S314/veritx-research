import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { useGraphStore } from '../graph/store';
import { SimPlayback } from '../pages/loom/authoring';

function MockPlaybackHarness(): React.ReactElement {
  const store = useGraphStore('ring-8', 'mock-truthfulness-contract');
  return <SimPlayback store={store} />;
}

afterEach(() => { cleanup(); localStorage.clear(); });

describe('mock trace playback provenance', () => {
  it('keeps the mock provenance and unavailable-metric disclosure through inspection', () => {
    localStorage.clear();
    render(<MockPlaybackHarness />);
    const disclosure = screen.getByText(/MOCK trace/).closest('p')!;
    expect(disclosure.textContent).toMatch(/playback geometry only/i);
    expect(disclosure.textContent).toMatch(/no per-cycle artifact/i);
    expect(disclosure.textContent).toMatch(/not shown/i);
    expect(disclosure.textContent).not.toMatch(/measured|backend-produced|simulated result/i);

    fireEvent.change(screen.getByLabelText('scrub'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('metric'), { target: { value: 'stalls' } });
    expect(screen.getByText(/MOCK trace/).closest('p')?.textContent).toMatch(/playback geometry only/i);
    expect(screen.getAllByText(/^cycle/)[0].textContent).toContain('4/24');
  });
});
