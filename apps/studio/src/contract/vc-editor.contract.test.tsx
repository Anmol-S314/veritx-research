/** Virtual-channel editor (M3-06/M3-07/M3-09): declare VCs, map traffic classes,
 *  set arbitration — one undoable command per edit, on the local graph. */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { VcEditor } from '../pages/loom/VcEditor';
import { useGraphStore } from '../graph/store';
import type { LoomProject } from '../graph/project';

const key = (scope: string): string => `loom-graph-autosave-v1:${scope}`;
const read = (scope: string): LoomProject => {
  const parsed = JSON.parse(localStorage.getItem(key(scope))!) as { graph?: LoomProject };
  return (parsed.graph ?? parsed) as LoomProject;
};

function Harness({ scope }: { scope: string }): ReactElement {
  const store = useGraphStore('mesh-8x8', scope);
  return (
    <>
      <VcEditor store={store} />
      <button type="button" onClick={() => store.undo()}>Undo vc edit</button>
    </>
  );
}

afterEach(() => { cleanup(); localStorage.clear(); });

describe('M3-06/M3-09: virtual channels', () => {
  it('adds a channel and edits depth, class and escape', () => {
    render(<Harness scope="vc-add" />);
    fireEvent.click(screen.getByRole('button', { name: '+ virtual channel' }));
    expect(read('vc-add').vcConfig?.virtualChannels).toEqual([{ id: 'vc0', depth: 4, class: 'data', escape: false }]);

    fireEvent.blur(screen.getByLabelText('vc depth vc0'), { target: { value: '12' } });
    fireEvent.blur(screen.getByLabelText('vc class vc0'), { target: { value: 'control' } });
    fireEvent.click(screen.getByLabelText('vc escape vc0'));
    expect(read('vc-add').vcConfig?.virtualChannels[0]).toEqual({ id: 'vc0', depth: 12, class: 'control', escape: true });
  });
});

describe('M3-07: traffic-class map', () => {
  it('requires a channel, then maps a class and renames it', () => {
    render(<Harness scope="vc-map" />);
    expect((screen.getByRole('button', { name: '+ mapping' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '+ virtual channel' }));
    fireEvent.click(screen.getByRole('button', { name: '+ mapping' }));
    expect(read('vc-map').vcConfig?.trafficClassMap).toEqual([{ trafficClass: 'tc1', vcId: 'vc0' }]);

    fireEvent.blur(screen.getByLabelText('traffic class name tc1'), { target: { value: 'req' } });
    expect(read('vc-map').vcConfig?.trafficClassMap[0]!.trafficClass).toBe('req');
  });

  it('removing a channel drops its mapping', () => {
    render(<Harness scope="vc-remove" />);
    fireEvent.click(screen.getByRole('button', { name: '+ virtual channel' }));
    fireEvent.click(screen.getByRole('button', { name: '+ mapping' }));
    fireEvent.click(screen.getByRole('button', { name: 'remove vc vc0' }));
    const config = read('vc-remove').vcConfig;
    expect(config?.virtualChannels).toEqual([]);
    expect(config?.trafficClassMap).toEqual([]);
  });
});

describe('M3-07: arbitration', () => {
  it('switches policy and sets a priority', () => {
    render(<Harness scope="vc-arb" />);
    fireEvent.click(screen.getByRole('button', { name: '+ virtual channel' }));
    fireEvent.click(screen.getByRole('button', { name: '+ mapping' }));
    fireEvent.change(screen.getByLabelText('arbitration policy'), { target: { value: 'fixed_priority' } });
    expect(read('vc-arb').vcConfig?.arbitration.policy).toBe('fixed_priority');

    fireEvent.blur(screen.getByLabelText('priority tc1'), { target: { value: '3' } });
    expect(read('vc-arb').vcConfig?.arbitration.priorityByTrafficClass).toEqual({ tc1: 3 });
  });

  it('is undoable per command', () => {
    render(<Harness scope="vc-undo" />);
    fireEvent.click(screen.getByRole('button', { name: '+ virtual channel' }));
    expect(read('vc-undo').vcConfig?.virtualChannels).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Undo vc edit' }));
    expect(read('vc-undo').vcConfig?.virtualChannels ?? []).toHaveLength(0);
  });
});
