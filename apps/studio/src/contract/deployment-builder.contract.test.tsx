/** Deployment builder contract (docs/design/reviews/deployment-builder.md).
 *
 *  Pins three things the UI must not drift on:
 *  - the form maps to the exact preview body;
 *  - a refusal renders its typed issues and disables creation;
 *  - an OK+COMPILED intent renders derived volumes, and creation posts the
 *    project before writing the draft, then navigates.
 *
 *  Fixtures only: no engine, no network.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api';
import type {
  DeploymentHardwareCatalogView,
  DeploymentModelCatalogView,
  DeploymentPreviewView,
  DraftView,
  ProjectView,
  ServingConfigCatalogView,
} from '../api/types';
import { StudioProvider } from '../studio';
import {
  DeploymentBuilder,
  defaultEpFor,
  deploymentBody,
  type DeploymentBuilderFormState,
} from '../pages/builder';

const QWEN = 'Qwen/Qwen3-30B-A3B-Instruct-2507';
const TRACE = 'third_party/llmservingsim/workloads/example_trace.jsonl';

const MODELS: DeploymentModelCatalogView = {
  contract_version: 1,
  models: [{
    model_name: QWEN,
    source: 'third_party/llmservingsim/configs/model/Qwen/'
      + 'Qwen3-30B-A3B-Instruct-2507.json',
    digest: 'sha256:model',
    model_family: 'mixture_of_experts',
    geometry: {
      layers: 48, hidden: 2048, heads: 32, kv_heads: 4,
      head_dim: 128, experts: 128, top_k: 8, dtype_bytes: 2,
    },
  }, {
    model_name: 'meta-llama/Llama-3.1-8B',
    source: 'third_party/llmservingsim/configs/model/meta-llama/'
      + 'Llama-3.1-8B.json',
    digest: 'sha256:dense',
    model_family: 'dense_transformer',
    geometry: {
      layers: 32, hidden: 4096, heads: 32, kv_heads: 8,
      head_dim: 128, experts: null, top_k: null, dtype_bytes: 2,
    },
  }],
};

const HARDWARE: DeploymentHardwareCatalogView = {
  contract_version: 1,
  hardware: [
    {
      hardware_id: 'B200',
      display_name: 'NVIDIA B200',
      memory_bytes: 192_000_000_000,
      memory_bandwidth_bytes_per_s: 8_000_000_000_000,
      link_bandwidth_bytes_per_s: 1_800_000_000_000,
      provenance: 'NVIDIA DGX B200 datasheet',
      timing: 'DATASHEET',
      serving_profile: false,
    },
    {
      hardware_id: 'RTXPRO6000',
      display_name: 'RTX PRO 6000',
      memory_bytes: 96_000_000_000,
      memory_bandwidth_bytes_per_s: 1_600_000_000_000,
      link_bandwidth_bytes_per_s: 450_000_000_000,
      provenance: 'tracked profiler bundle',
      timing: 'MEASURED',
      serving_profile: true,
    },
  ],
};

const SERVING: ServingConfigCatalogView = {
  contract_version: 1,
  configs: [],
  traces: [{
    contract_version: 1,
    trace_id: 'example_trace',
    display_name: 'Example trace',
    description: '10 request(s) in the trace',
    source: TRACE,
    content_digest: 'sha256:trace',
    requests: 10,
  }],
  default_config: 'configs/cluster/single_node_2gpu.json',
  default_trace: TRACE,
};

const FORM: DeploymentBuilderFormState = {
  name: 'Qwen3-30B on B200',
  modelName: QWEN,
  hardware: 'B200',
  tpSize: 2,
  epSize: 2,
  dpInstances: 1,
  maxNumSeqs: 32,
  maxNumBatchedTokens: 2048,
  trace: TRACE,
  numReqs: 10,
  meshSideLength: 2,
  linkWidthBits: 128,
  hbmControllersPerRank: 0,
};

const DERIVED = {
  prefill_chunk_tokens: 2048,
  decode_batch: 10,
  tp_prefill_bytes: 8_388_608,
  tp_decode_bytes: 40_960,
  ep_dispatch_bytes: 4_456_448,
  ep_combine_bytes: 8_388_608,
  ep_decode_bytes: 21_760,
  kv_bytes_per_token: 98_304,
};

function okPreview(): DeploymentPreviewView {
  return {
    contract_version: 1,
    status: 'OK',
    issues: [],
    report: {
      schema: 'veritx/deployment-mapping/1',
      status: 'OK',
      sources: {
        cluster: { path: 'in-memory:deployment-intent/preview', sha256: 'sha256:c' },
        model: { path: MODELS.models[0].source, sha256: 'sha256:model' },
        trace: { path: TRACE, sha256: 'sha256:trace' },
      },
      deployment: {
        model_name: QWEN,
        hardware: 'B200',
        pd_type: null,
        tp: 2,
        dp: 1,
        ep: 2,
        pp: 1,
        instances: 1,
        ranks: 2,
      },
      model: {
        layers: 48, hidden: 2048, heads: 32, kv_heads: 4,
        head_dim: 128, experts: 128, top_k: 8, dtype_bytes: 2,
        weights_bytes: null,
      },
      request: {
        num_reqs: 10, isl_mean: 12, osl_mean: 69, arrival_span_ns: 1000,
      },
      derived: DERIVED,
      assumptions: ['Effective prefill chunk is 2048 tokens and decode batch is 10 requests.'],
      issues: [],
    },
    request: { schema_version: 4, workload: { model_name: QWEN } },
    compile: { status: 'COMPILED', error: null },
  };
}

function refusedPreview(): DeploymentPreviewView {
  return {
    contract_version: 1,
    status: 'REFUSED',
    issues: [{
      code: 'MODEL_UNKNOWN',
      message: `model ${QWEN} is not in the deployment model catalog`,
      path: null,
    }],
    report: {
      schema: 'veritx/deployment-mapping/1',
      status: 'REFUSED',
      sources: {
        cluster: { path: 'in-memory:deployment-intent/preview', sha256: null },
        model: { path: QWEN, sha256: null },
        trace: { path: TRACE, sha256: null },
      },
      deployment: null,
      model: null,
      request: null,
      derived: null,
      assumptions: [],
      issues: [{
        code: 'MODEL_UNKNOWN',
        message: 'model is not in the deployment model catalog',
        path: null,
      }],
    },
    request: null,
    compile: null,
  };
}

function mockCatalogs(): void {
  vi.spyOn(api, 'health').mockResolvedValue({
    status: 'ok', api: 'ok', backends: {},
  });
  vi.spyOn(api, 'listProjects').mockResolvedValue({
    contract_version: 1, projects: [],
  });
  vi.spyOn(api, 'deploymentModels').mockResolvedValue(MODELS);
  vi.spyOn(api, 'deploymentHardware').mockResolvedValue(HARDWARE);
  vi.spyOn(api, 'servingConfigs').mockResolvedValue(SERVING);
}

function renderBuilder(): ReturnType<typeof render> {
  return render(
    <StudioProvider>
      <DeploymentBuilder />
    </StudioProvider>,
  );
}

beforeEach(mockCatalogs);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState({}, '', '/');
});

describe('defaultEpFor', () => {
  it('uses TP for MoE and 1 for dense models', () => {
    expect(defaultEpFor('mixture_of_experts', 4)).toBe(4);
    expect(defaultEpFor('dense_transformer', 4)).toBe(1);
    expect(defaultEpFor(undefined, 4)).toBe(1);
  });
});

describe('deploymentBody', () => {
  it('maps the Qwen/B200 form to the exact preview body', () => {
    expect(JSON.stringify(deploymentBody(FORM))).toBe(JSON.stringify({
      name: 'Qwen3-30B on B200',
      model_name: QWEN,
      hardware: 'B200',
      tp_size: 2,
      pp_size: 1,
      ep_size: 2,
      dp_instances: 1,
      max_num_seqs: 32,
      max_num_batched_tokens: 2048,
      trace: TRACE,
      num_reqs: 10,
      topology: { kind: 'mesh', side_length: 2, concentration: 1 },
      link_width_bits: 128,
      hbm_controllers_per_rank: 0,
    }));
  });
});

describe('DeploymentBuilder', () => {
  it('defaults EP to TP for MoE and resets to 1 for dense', async () => {
    vi.spyOn(api, 'previewDeployment').mockResolvedValue(okPreview());
    renderBuilder();

    const model = await screen.findByLabelText('Model') as HTMLSelectElement;
    const ep = screen.getByLabelText('EP size') as HTMLInputElement;
    await waitFor(() => expect(ep.value).toBe('2'));
    fireEvent.change(model, { target: { value: 'meta-llama/Llama-3.1-8B' } });
    await waitFor(() => expect(ep.value).toBe('1'));
    fireEvent.change(model, { target: { value: QWEN } });
    await waitFor(() => expect(ep.value).toBe('2'));
  });

  it('renders refusal issues and disables creation', async () => {
    vi.spyOn(api, 'previewDeployment').mockResolvedValue(refusedPreview());
    renderBuilder();

    expect(await screen.findByText('MODEL_UNKNOWN')).toBeDefined();
    expect(screen.getByText(/not in the deployment model catalog/)).toBeDefined();
    const create = screen.getByRole('button', { name: 'Create project' });
    expect((create as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Create is disabled: the deployment was refused.'))
      .toBeDefined();
    // B200 is a declared datasheet entry: no measured serving-timing claim.
    expect(screen.getByText('Datasheet · serving timing not measured'))
      .toBeDefined();
  });

  it('renders derived volumes and enables creation for a compiled intent', async () => {
    vi.spyOn(api, 'previewDeployment').mockResolvedValue(okPreview());
    renderBuilder();

    expect(await screen.findByText('4,456,448 B')).toBeDefined();
    expect(screen.getByText('40,960 B')).toBeDefined();
    expect(screen.getByText('21,760 B')).toBeDefined();
    expect(screen.getByText('98,304 B')).toBeDefined();
    // TP prefill and EP combine share one payload value.
    expect(screen.getAllByText('8,388,608 B')).toHaveLength(2);
    expect(screen.getByText('2,048 tokens')).toBeDefined();
    expect(screen.getByText('10 requests')).toBeDefined();
    expect(screen.getByText(/Effective prefill chunk is 2048 tokens/))
      .toBeDefined();
    const create = screen.getByRole('button', { name: 'Create project' });
    await waitFor(() => {
      expect((create as HTMLButtonElement).disabled).toBe(false);
    });
  });

  it('creates the project, then writes the draft, then navigates', async () => {
    const preview = okPreview();
    const previewSpy = vi.spyOn(api, 'previewDeployment')
      .mockResolvedValue(preview);
    const createSpy = vi.spyOn(api, 'createProject').mockResolvedValue({
      contract_version: 1,
      project: {
        project_id: 'p-new',
        name: 'Qwen3-30B on B200',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    } as unknown as ProjectView);
    const draftSpy = vi.spyOn(api, 'putDraft')
      .mockResolvedValue({} as unknown as DraftView);
    renderBuilder();

    const name = await screen.findByLabelText('Name');
    fireEvent.change(name, { target: { value: 'Qwen3-30B on B200' } });
    await waitFor(() => {
      expect(previewSpy).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Qwen3-30B on B200' }),
      );
    });

    const create = screen.getByRole('button', { name: 'Create project' });
    await waitFor(() => {
      expect((create as HTMLButtonElement).disabled).toBe(false);
    });
    fireEvent.click(create);

    await waitFor(() => {
      expect(window.location.pathname).toBe('/projects/p-new/workload');
    });
    expect(createSpy).toHaveBeenCalledWith('Qwen3-30B on B200');
    expect(draftSpy).toHaveBeenCalledWith('p-new', preview.request);
    expect(createSpy.mock.invocationCallOrder[0])
      .toBeLessThan(draftSpy.mock.invocationCallOrder[0]);
  });
});
