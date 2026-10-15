/** Virtual-channel and QoS editor (tracker M3-06/M3-07/M3-09).
 *
 *  Declares virtual channels (depth, class, escape), maps traffic classes onto
 *  them, and sets the arbitration policy with its per-class priority or weight.
 *  Every edit is one undoable `set_vc_config` command; the canonical validator
 *  owns the rules and this editor reports its findings. Authored intent only —
 *  no router microarchitecture or timing is implied.
 */
import { type ReactElement } from 'react';
import { validateProject, type VcConfigV1, type VirtualChannelV1 } from '../../graph/project';
import {
  ARBITRATION_POLICIES, emptyVcConfig, nextVcId, removeVc, renameTrafficClass,
  setArbitrationPolicy, setArbitrationValue, setTrafficClassRow, upsertVc,
} from '../../graph/vcConfig';
import type { GraphStore } from '../../graph/store';

const POLICY_LABEL: Record<string, string> = {
  round_robin: 'Round robin',
  fixed_priority: 'Fixed priority',
  weighted_round_robin: 'Weighted round robin',
};

export function VcEditor({ store }: { store: GraphStore }): ReactElement {
  const doc = store.doc;
  const config: VcConfigV1 = doc.vcConfig ?? emptyVcConfig();
  const issues = validateProject(doc).filter((issue) => issue.path.startsWith('$.vcConfig'));

  const write = (next: VcConfigV1): void => { store.run({ type: 'set_vc_config', vcConfig: next }); };
  const addVc = (): void => write(upsertVc(config, { id: nextVcId(config), depth: 4, class: 'data', escape: false }));
  const patchVc = (id: string, patch: Partial<VirtualChannelV1>): void => {
    const found = config.virtualChannels.find((vc) => vc.id === id);
    if (found) write(upsertVc(config, { ...found, ...patch }));
  };
  const addMapping = (): void => {
    if (config.virtualChannels.length === 0) return;
    const used = new Set(config.trafficClassMap.map((row) => row.trafficClass));
    let n = 1;
    while (used.has(`tc${n}`)) n += 1;
    write(setTrafficClassRow(config, `tc${n}`, config.virtualChannels[0]!.id));
  };

  return (
    <div>
      <fieldset aria-label="Virtual channels" style={{ margin: '4px 0' }}>
        <legend>Virtual channels</legend>
        <button type="button" className="btn btn-small" onClick={addVc}>+ virtual channel</button>
        {config.virtualChannels.length === 0 && <p className="muted" style={{ fontSize: 12 }}>None declared.</p>}
        {config.virtualChannels.map((vc) => (
          <div className="row" key={vc.id} style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: 4 }}>
            <code>{vc.id}</code>
            <label>depth
              <input aria-label={`vc depth ${vc.id}`} type="number" min={1} defaultValue={vc.depth} key={`${vc.id}-d${vc.depth}`}
                onBlur={(e) => { const value = Math.max(1, Number(e.target.value) | 0); if (value !== vc.depth) patchVc(vc.id, { depth: value }); }} />
            </label>
            <label>class
              <input aria-label={`vc class ${vc.id}`} defaultValue={vc.class} key={`${vc.id}-c-${vc.class}`}
                onBlur={(e) => { const value = e.target.value.trim(); if (value && value !== vc.class) patchVc(vc.id, { class: value }); }} />
            </label>
            <label style={{ fontSize: 12 }}>
              <input type="checkbox" aria-label={`vc escape ${vc.id}`} checked={vc.escape}
                onChange={(e) => patchVc(vc.id, { escape: e.target.checked })} /> escape (deadlock-freedom)
            </label>
            <button type="button" className="btn btn-small" aria-label={`remove vc ${vc.id}`}
              onClick={() => write(removeVc(config, vc.id))}>remove</button>
          </div>
        ))}
      </fieldset>

      <fieldset aria-label="Traffic class map" style={{ margin: '4px 0' }}>
        <legend>Traffic-class map</legend>
        <button type="button" className="btn btn-small" disabled={config.virtualChannels.length === 0} onClick={addMapping}>+ mapping</button>
        {config.virtualChannels.length === 0 && <p className="muted" style={{ fontSize: 12 }}>Declare a virtual channel first.</p>}
        {config.trafficClassMap.map((row) => (
          <div className="row" key={row.trafficClass} style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: 4 }}>
            <label>class
              <input aria-label={`traffic class name ${row.trafficClass}`} defaultValue={row.trafficClass}
                key={`${row.trafficClass}-name`}
                onBlur={(e) => {
                  const value = e.target.value.trim();
                  if (value && value !== row.trafficClass) {
                    write(renameTrafficClass(config, row.trafficClass, value));
                  }
                }} />
            </label>
            <span className="muted" style={{ fontSize: 12 }}>→</span>
            <label>vc
              <select aria-label={`traffic class vc ${row.trafficClass}`} value={row.vcId}
                onChange={(e) => write(setTrafficClassRow(config, row.trafficClass, e.target.value, row.qos ?? null))}>
                {config.virtualChannels.map((vc) => <option key={vc.id} value={vc.id}>{vc.id}</option>)}
              </select>
            </label>
            <label>qos
              <input aria-label={`traffic class qos ${row.trafficClass}`} type="number" min={0} defaultValue={row.qos ?? ''}
                key={`${row.trafficClass}-q-${row.qos ?? ''}`}
                onBlur={(e) => write(setTrafficClassRow(config, row.trafficClass, row.vcId, e.target.value.trim() === '' ? null : Math.max(0, Number(e.target.value) | 0)))} />
            </label>
            <button type="button" className="btn btn-small" aria-label={`remove traffic class ${row.trafficClass}`}
              onClick={() => write(setTrafficClassRow(config, row.trafficClass, ''))}>remove</button>
          </div>
        ))}
      </fieldset>

      <fieldset aria-label="Arbitration" style={{ margin: '4px 0' }}>
        <legend>Arbitration</legend>
        <label>policy
          <select aria-label="arbitration policy" value={config.arbitration.policy}
            onChange={(e) => write(setArbitrationPolicy(config, e.target.value as VcConfigV1['arbitration']['policy']))}>
            {ARBITRATION_POLICIES.map((policy) => <option key={policy} value={policy}>{POLICY_LABEL[policy] ?? policy}</option>)}
          </select>
        </label>
        {config.arbitration.policy === 'fixed_priority' && (
          <div style={{ marginTop: 4 }}>
            {config.trafficClassMap.length === 0 && <p className="muted" style={{ fontSize: 12 }}>Map a traffic class to set its priority.</p>}
            {config.trafficClassMap.map((row) => (
              <label key={row.trafficClass} style={{ marginRight: 8 }}>
                {row.trafficClass} priority
                <input aria-label={`priority ${row.trafficClass}`} type="number" min={0}
                  defaultValue={config.arbitration.priorityByTrafficClass?.[row.trafficClass] ?? ''}
                  key={`${row.trafficClass}-p-${config.arbitration.priorityByTrafficClass?.[row.trafficClass] ?? ''}`}
                  onBlur={(e) => write(setArbitrationValue(config, 'priorityByTrafficClass', row.trafficClass,
                    e.target.value.trim() === '' ? null : Math.max(0, Number(e.target.value) | 0)))} />
              </label>
            ))}
          </div>
        )}
        {config.arbitration.policy === 'weighted_round_robin' && (
          <div style={{ marginTop: 4 }}>
            {config.trafficClassMap.length === 0 && <p className="muted" style={{ fontSize: 12 }}>Map a traffic class to set its weight.</p>}
            {config.trafficClassMap.map((row) => (
              <label key={row.trafficClass} style={{ marginRight: 8 }}>
                {row.trafficClass} weight
                <input aria-label={`weight ${row.trafficClass}`} type="number" min={1}
                  defaultValue={config.arbitration.weightByTrafficClass?.[row.trafficClass] ?? ''}
                  key={`${row.trafficClass}-w-${config.arbitration.weightByTrafficClass?.[row.trafficClass] ?? ''}`}
                  onBlur={(e) => write(setArbitrationValue(config, 'weightByTrafficClass', row.trafficClass,
                    e.target.value.trim() === '' ? null : Math.max(1, Number(e.target.value) | 0)))} />
              </label>
            ))}
          </div>
        )}
        <p className="muted" style={{ fontSize: 12 }}>
          Authored arbitration intent. No router allocator or timing is modeled here.
        </p>
      </fieldset>

      {issues.length > 0 && (
        <ul className="t-warn" role="status" aria-label="VC validation issues" data-testid="vc-issues" style={{ fontSize: 12, margin: 0, paddingLeft: 16 }}>
          {issues.map((issue, i) => <li key={`${issue.path}-${i}`}>{issue.path} — {issue.message}</li>)}
        </ul>
      )}
    </div>
  );
}
