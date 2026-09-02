import os
import sys
from time import time
from .request import *
from .logger import get_logger
from .run_paths import input_path

logger = get_logger("GraphGenerator")

# In-process Chakra converter (avoids subprocess overhead)
_llm_converter_cls = None

def _get_llm_converter():
    """Lazy-load LLMConverter to avoid import at module load time."""
    global _llm_converter_cls
    if _llm_converter_cls is None:
        # Add chakra to sys.path if not already there
        chakra_root = os.path.join(os.getcwd(), "extern/graph_frontend/chakra")
        if chakra_root not in sys.path:
            sys.path.insert(0, chakra_root)
        from chakra.src.converter.llm_converter import LLMConverter
        _llm_converter_cls = LLMConverter
    return _llm_converter_cls

def generate_graph(batch, hardware, num_npus, node_id=0, instance_id=0, npu_offset=0, enable_local_offloading=False, event=False, workload_name=None, inputs_root=None, cleanup_trace=True, use_in_process=True):

    cwd = os.getcwd()
    chakra = os.path.join(cwd, "extern/graph_frontend/chakra")
    if inputs_root is None:
        inputs_root = os.path.join(cwd, "inputs")

    if event:
        file_name = 'event_handler'
    else:
        file_name = f'{hardware}/{batch.model}/instance{instance_id}_batch{batch.batch_id}'

    # For DP groups, all instances write .et files to a shared workload folder
    output_name = workload_name if workload_name else file_name

    trace_path = input_path(inputs_root, "trace", f"{file_name}.txt")
    output_path = input_path(inputs_root, "workload", output_name, "llm")
    workload_dir = os.path.dirname(output_path)
    os.makedirs(workload_dir, exist_ok=True)

    if use_in_process:
        # In-process: call converter directly (saves ~30ms per call)
        try:
            LLMConverter = _get_llm_converter()
            converter = LLMConverter(trace_path, output_path, num_npus, npu_offset, enable_local_offloading)
            converter.convert()
        except Exception as e:
            # Fallback to subprocess if in-process fails
            logger.warning("In-process converter failed, falling back to subprocess: %s", e)
            import subprocess
            cmd = [
                sys.executable, '-m', 'chakra.src.converter.converter', 'LLM',
                '--input', trace_path,
                '--output', output_path,
                '--num-npus', str(num_npus),
                '--npu-offset', str(npu_offset),
            ]
            if enable_local_offloading:
                cmd.append('--local-offloading')
            subprocess.run(cmd, cwd=chakra, text=True, check=True)
    else:
        # Subprocess fallback
        import subprocess
        cmd = [
            sys.executable, '-m', 'chakra.src.converter.converter', 'LLM',
            '--input', trace_path,
            '--output', output_path,
            '--num-npus', str(num_npus),
            '--npu-offset', str(npu_offset),
        ]
        if enable_local_offloading:
            cmd.append('--local-offloading')
        subprocess.run(cmd, cwd=chakra, text=True, check=True)

    if cleanup_trace:
        try:
            os.remove(trace_path)
        except FileNotFoundError:
            pass
    return
