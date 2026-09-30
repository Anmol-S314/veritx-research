import type { ReactElement } from 'react';
import type { AddressDecodeGroup, FabricGroup } from '../../api';
import { fmtNum, humanize } from '../badges';
import { EmptyState } from './EmptyState';
import { useSelection } from './selection';

export default function AddressDecodeInspector({ group, fabric, onJump }: {
  group: AddressDecodeGroup;
  fabric: FabricGroup;
  onJump: (tab: string) => void;
}): ReactElement {
  const { selection, select } = useSelection();
  const rows = group.rows ?? [];

  if (!group.available || rows.length === 0) {
    return (
      <section className="card">
        <h4>Address decode</h4>
        <EmptyState title="No address ranges were declared for this design.">
          <div className="kv-grid">
            <div className="kv"><span>address transform</span>
              <span>{group.address_transform ?? 'IDENTITY'}</span></div>
            <div className="kv"><span>unmatched addresses</span>
              <span>{group.unmatched_address_policy ?? 'ERROR'}</span></div>
          </div>
        </EmptyState>
      </section>
    );
  }

  const selRow = typeof selection.id === 'string'
    && selection.kind === 'endpoint'
    ? rows.find((r) => r.name === selection.secondary
      || r.target_endpoint_id === selection.id) ?? null
    : null;
  const selRouter = selRow?.target_endpoint_id != null
    ? fabric.topology?.endpoints.find(
      (e) => e.endpoint_id === selRow.target_endpoint_id)?.router_id ?? null
    : null;

  return (
    <section className="card">
      <h4>Address decode</h4>
      <table className="tbl">
        <thead>
          <tr>
            <th>range</th><th>base</th><th>size</th>
            <th>target</th><th>endpoint</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isSel = selRow !== null && row.name === selRow.name
              && row.base === selRow.base;
            return (
              <tr key={`${row.name}-${row.base}`}
                  className={isSel ? 'row-selected' : ''}
                  style={{ cursor: 'pointer' }}
                  onClick={() => {
                    if (row.target_endpoint_id != null) {
                      select({ kind: 'endpoint',
                               id: row.target_endpoint_id,
                               secondary: row.name });
                    }
                  }}>
                <td>{row.name}</td>
                <td className="num">0x{(row.base ?? 0).toString(16)}</td>
                <td className="num">{fmtNum(row.size)}</td>
                <td>
                  {humanize(row.target_agent_kind ?? '—')}
                  {row.target_agent_instance != null
                    ? ` #${row.target_agent_instance}` : ''}
                </td>
                <td className="num">{row.target_endpoint_id}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {selRow && (
        <div className="inspector-detail">
          <h5 className="inspector-label">Range {selRow.name}</h5>
          <div className="kv-grid">
            <div className="kv"><span>target agent</span>
              <span>{humanize(selRow.target_agent_kind ?? '—')}
                {selRow.target_agent_instance != null
                  ? ` #${selRow.target_agent_instance}` : ''}</span></div>
            <div className="kv"><span>endpoint</span>
              <span className="num">{selRow.target_endpoint_id}</span></div>
            <div className="kv"><span>router</span>
              <span className="num">{selRouter ?? '—'}</span></div>
          </div>
          <div className="form-row">
            <button className="btn btn-small"
                    onClick={() => onJump('fabric')}>
              Highlight on Fabric →
            </button>
          </div>
        </div>
      )}
      <div className="kv-grid">
        <div className="kv"><span>address transform</span>
          <span>{group.address_transform ?? '—'}</span></div>
        <div className="kv"><span>unmatched policy</span>
          <span>{group.unmatched_address_policy ?? '—'}</span></div>
      </div>
    </section>
  );
}
