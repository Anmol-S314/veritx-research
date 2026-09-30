import { useState, type ReactElement } from 'react';

type Tab = 'energy' | 'rtl' | 'uvm' | 'cdc' | 'pim' | 'multicast' | 'multiplane';

const TABS: { id: Tab; label: string }[] = [
  { id: 'energy', label: 'Energy / Power' },
  { id: 'rtl', label: 'RTL' },
  { id: 'uvm', label: 'UVM / SVA' },
  { id: 'cdc', label: 'CDC' },
  { id: 'pim', label: 'PIM' },
  { id: 'multicast', label: 'Hardware Multicast' },
  { id: 'multiplane', label: 'Multiplane' },
];

const ENERGY_AUTHORITIES: { name: string; fidelity: string; units: string; inputs: string; source: string; scope: string }[] = [
  { name: 'Hops × packet proxy', fidelity: 'PROXY', units: 'hop-bits (relative)', inputs: 'BookSim sweep hops_avg', source: 'BookSim sweep output', scope: 'research Pareto input only' },
  { name: 'Timeloop / Accelergy', fidelity: 'TOOL_DERIVED', units: 'uJ (accelerator-side)', inputs: 'Timeloop stats, Accelergy ERT', source: 'Timeloop/Accelergy tools', scope: 'compute/accelerator energy — never NoC signoff' },
  { name: 'NoC energy bridge', fidelity: 'TOOL_CALIBRATED proxy (PLACEHOLDER ERT)', units: 'pJ', inputs: 'hops_avg × packet flits × 5.4 pJ/hop nominal', source: 'Accelergy 1-hop run × BookSim hops', scope: 'research estimate; ERT awaits DSENT/ORION/synthesis calibration' },
  { name: 'Analytical estimator', fidelity: 'ANALYTICAL_ESTIMATE', units: 'mm² / W (estimate, not signoff)', inputs: 'process node, published scaling refs (DAC22/CMN-600/JEDEC)', source: 'reports.py', scope: 'comparison metric only — never a Pareto objective' },
  { name: 'BookSim native Power_Module', fidelity: 'BACKEND_ACTIVITY_MODEL', units: 'W (sim_power=1 activity)', inputs: 'SwitchMonitor/BufferMonitor activity over _chan', source: 'BookSim power/', scope: 'point-to-point topologies only' },
  { name: 'LLMServingSim power model', fidelity: 'DOWNSTREAM_MODEL', units: 'W / J (serving system)', inputs: 'provisioned node configs + nvidia-smi profiles', source: 'LLMServingSim power_model.py', scope: 'serving leg only — never fabric energy' },
];

export function ImplementationLabPage(): ReactElement {
  const [tab, setTab] = useState<Tab>('energy');
  return (
    <div className="page implementation-lab-page">
      <h2>Implementation Lab</h2>
      <p className="muted">
        Research features before they become certified product. Each tab
        states source, fidelity, and the exact missing bridge.
      </p>
      <div className="maturity-filter" role="tablist" aria-label="Implementation Lab tabs">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id}
            className={tab === t.id ? 'btn active' : 'btn'}
            onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'energy' && (
        <div>
          <h3>Energy &amp; Power (§37)</h3>
          <p className="muted">Six separate authorities — never merged into one number. Units and calibration ride with every value.</p>
          <table className="live-table">
            <thead><tr><th>Authority</th><th>Fidelity</th><th>Units</th><th>Canonical inputs</th><th>Source</th><th>Scope</th></tr></thead>
            <tbody>
              {ENERGY_AUTHORITIES.map((e) => (
                <tr key={e.name}>
                  <td><strong>{e.name}</strong></td>
                  <td>{e.fidelity}</td>
                  <td>{e.units}</td>
                  <td>{e.inputs}</td>
                  <td className="muted">{e.source}</td>
                  <td>{e.scope}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="card warn">
            <h4>BookSim native power unavailable for MECS</h4>
            <p>
              Multidrop <code>_md_chan</code> activity is not currently
              included in the power accounting (Power_Module walks
              <code>Network::GetChannels()/_chan</code> only). Native power
              is INVALID/INCOMPLETE for MECS until multidrop activity is
              included.
            </p>
          </div>
        </div>
      )}

      {tab === 'rtl' && (
        <div>
          <h3>RTL (§38)</h3>
          <p><span className="maturity maturity-research">RESEARCH</span> <span className="muted">RTL SIMULATION — a run is never proof.</span></p>
          <div className="card-grid">
            <div className="card"><h4>Build status</h4><p className="muted">Verilator build+run harness: validation/harness/rtl.py over tracks/t3-topology/rtl/*. No committed run log located — the committed RTL document is a read-through audit, not a run record.</p></div>
            <div className="card"><h4>Simulation status</h4><p className="muted">EXECUTABLE POTENTIAL via the harness; oracle comparison in validation/harness/compare.py. Results report as RTL_SIMULATION fidelity.</p></div>
            <div className="card"><h4>Oracle comparison</h4><p className="muted">Harness oracle comparisons run; no committed qualification result artifact located.</p></div>
            <div className="card"><h4>Source design identity</h4><p className="muted">Product integration is the missing bridge: the exact generated-RTL inputs must bind to parent design artifacts (tool/version/testbench/design/result).</p></div>
          </div>
        </div>
      )}

      {tab === 'uvm' && (
        <div>
          <h3>UVM / SVA (§39)</h3>
          <p><span className="maturity maturity-research">RESEARCH</span> <span className="muted">Generated assertions are not formal proof.</span></p>
          <table className="live-table">
            <thead><tr><th>Stage</th><th>State</th></tr></thead>
            <tbody>
              <tr><td>Generated</td><td>YES — verification/uvm_gen.py + generated tests (generator runs).</td></tr>
              <tr><td>Executed</td><td>NO — no committed simulator execution authority.</td></tr>
              <tr><td>Passed</td><td>NO — generated SVA is collateral until executed by a simulator/formal engine.</td></tr>
            </tbody>
          </table>
          <p className="muted">Missing bridge: execution/formal authority with committed pass artifacts.</p>
        </div>
      )}

      {tab === 'cdc' && (
        <div>
          <h3>CDC (§40)</h3>
          <p><span className="maturity maturity-research">RESEARCH</span></p>
          <div className="card-grid">
            <div className="card"><h4>CDC FIFO implementation</h4><p className="muted">tracks/t3-topology/rtl/cdc/cdc_fifo.sv (async FIFO, gray pointers + sync) with Verilator testbench tb_cdc.cpp. Component builds/runs via the cdc Makefile; no committed run log.</p></div>
            <div className="card"><h4>Component test status</h4><p className="muted">PARTIAL — component testbench only.</p></div>
            <div className="card warn"><h4>System-level qualification</h4><p>NOT ESTABLISHED until a real multi-clock fabric contract exists. A working CDC FIFO is not multi-clock NoC execution.</p></div>
          </div>
        </div>
      )}

      {tab === 'pim' && (
        <div>
          <h3>PIM</h3>
          <p><span className="maturity maturity-research">RESEARCH / DOWNSTREAM MODEL</span> <span className="muted">when not canonically connected.</span></p>
          <p>LLMServingSim <code>serving/core/pim_model.py</code> + <code>power_model.py</code> are real latency/power models a serving run invokes; the canonical side has PIM graph markers only, and ASTRA treats PIM markers as ZERO network traffic. A zero-traffic marker is NOT PIM simulation.</p>
          <p className="muted">Missing bridge: canonical intent → PIM execution bridge.</p>
        </div>
      )}

      {tab === 'multicast' && (
        <div>
          <h3>Hardware Multicast</h3>
          <p><span className="maturity maturity-historical">RESEARCH / HISTORICAL EXECUTABLE</span></p>
          <p>Concept: flit-fork replication at transit routers (300-line archived patch, unapplied at HEAD). Logical source replication (lowered to repeated unicasts) is the canonical form and is distinct.</p>
          <p className="muted">Historical: row-broadcast/broadcast experiments ran in history (status records c41087b1, 973ee7bd, scope-limited). Expose conceptual controls only when enabled experimentally; never reapply the patch and call it supported.</p>
        </div>
      )}

      {tab === 'multiplane' && (
        <div>
          <h3>Multiplane</h3>
          <p><span className="maturity maturity-research">RESEARCH — simultaneous plane contract not yet canonical</span></p>
          <p>Independent per-plane simulations are never presented as one simultaneous multiplane fabric. A real feature needs a first-class plane set, flow/class→plane assignment, shared endpoint/resource semantics, and one execution/verification contract.</p>
        </div>
      )}
    </div>
  );
}
