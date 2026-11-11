#!/usr/bin/env python3
"""Inspect a PyTorch Chrome trace without assuming its folder name is truthful.

A forward-only candidate is not certified inference: provenance, rank coverage,
clock alignment and serving/request boundaries still need independent checking.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

BACKWARD = re.compile(
    r"autograd::engine::evaluate_function|Backward[0-9]|"
    r"aten::[^: ]+_backward|Optimizer\.step"
)


def audit(trace: dict) -> dict:
    events = trace.get("traceEvents", [])
    backward = Counter()
    cpu = []
    gpu = []
    for index, event in enumerate(events):
        name = event.get("name", "")
        if BACKWARD.search(name):
            backward[name] += 1
        if event.get("ph") != "X":
            continue
        if event.get("cat") == "cpu_op" and name.startswith("c10d::"):
            args = event.get("args", {})
            cpu.append({
                "source_event_index": index,
                "name": name,
                "timestamp_us": event.get("ts"),
                "host_duration_us": event.get("dur"),
                "input_types": args.get("Input type"),
                "input_dims": args.get("Input Dims"),
                "external_id": args.get("External id"),
            })
        if event.get("cat") == "kernel" and "nccl" in name.lower():
            args = event.get("args", {})
            gpu.append({
                "source_event_index": index,
                "name": name,
                "timestamp_us": event.get("ts"),
                "gpu_duration_us": event.get("dur"),
                "device": args.get("device"),
                "stream": args.get("stream"),
                "correlation": args.get("correlation"),
            })
    distributed = trace.get("distributedInfo") or {}
    if backward:
        status = "rejected_training_events_present"
    elif (distributed.get("backend") == "nccl"
          and distributed.get("world_size", 0) > 1 and cpu and gpu):
        status = "forward_only_candidate_requires_provenance"
    else:
        status = "insufficient_distributed_communication_evidence"
    return {
        "status": status,
        "distributed_info": distributed,
        "device_properties": trace.get("deviceProperties"),
        "base_time_nanoseconds": trace.get("baseTimeNanoseconds"),
        "event_count": len(events),
        "backward_event_count": sum(backward.values()),
        "backward_event_names": dict(backward),
        "collective_cpu_op_count": len(cpu),
        "collective_cpu_op_names": dict(Counter(e["name"] for e in cpu)),
        "nccl_gpu_kernel_count": len(gpu),
        "nccl_gpu_kernel_names": dict(Counter(e["name"] for e in gpu)),
        "collective_cpu_events": cpu,
        "nccl_gpu_events": gpu,
        "not_established": [
            "inference provenance from absence of backward events alone",
            "full participant-rank coverage or cross-rank clock alignment",
            "CPU-to-GPU or cross-rank operation matching",
            "request boundaries, TTFT, TPOT or end-to-end inference latency",
            "physical link bytes/bandwidth, packets, routes or dependencies",
            "power, energy or area",
        ],
        "timing_note": "Chrome event ts/dur are microseconds; CPU duration is not GPU completion latency. displayTimeUnit is a viewer preference, not a rescaling of ts/dur.",
    }


def self_test() -> None:
    def event(name: str, category: str = "cpu_op") -> dict:
        return {"ph": "X", "cat": category, "name": name, "ts": 10, "dur": 2}

    trace = {
        "distributedInfo": {"backend": "nccl", "world_size": 2, "rank": 0},
        "traceEvents": [event("c10d::_allgather_base_"),
                        event("ncclDevKernel_AllGather_RING_LL", "kernel")],
    }
    assert audit(trace)["status"] == "forward_only_candidate_requires_provenance"
    trace["traceEvents"].append(event("autograd::engine::evaluate_function: MmBackward0"))
    assert audit(trace)["status"] == "rejected_training_events_present"
    assert audit(trace)["backward_event_count"] == 1
    assert audit(trace)["collective_cpu_op_count"] == 1
    assert audit(trace)["nccl_gpu_kernel_count"] == 1
    assert audit({"traceEvents": []})["status"] == "insufficient_distributed_communication_evidence"
    print("PASS: training rejection, candidate classification, separate CPU/GPU counts, missing-evidence rejection")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", nargs="?", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.trace is None or args.out is None:
        parser.error("trace and --out are required unless --self-test is used")
    data = args.trace.read_bytes()
    result = audit(json.loads(data))
    result["source_path"] = str(args.trace)
    result["source_sha256"] = hashlib.sha256(data).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(result["status"], "rank=", result["distributed_info"].get("rank"),
          "cpu_collectives=", result["collective_cpu_op_count"],
          "nccl_kernels=", result["nccl_gpu_kernel_count"],
          "backward_events=", result["backward_event_count"])
    raise SystemExit(0 if result["status"].startswith("forward_only_candidate") else 2)


if __name__ == "__main__":
    main()
