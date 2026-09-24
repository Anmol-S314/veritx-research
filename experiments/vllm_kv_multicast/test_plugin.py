#!/usr/bin/env python3
"""
Correctness Test for vLLM KV-Multicast Connector Prototype
"""

import torch
import sys
from kv_multicast_connector import VeritXKVMulticastConnector


def test_layout_transformation():
    connector = VeritXKVMulticastConnector(num_q_heads=64, num_kv_heads=8, head_dim=128)
    
    # Create dummy KV tensor: [batch=4, seq_len=512, num_kv_heads=8, head_dim=128]
    original_kv = torch.randn(4, 512, 8, 128)
    
    # Transform to head-contiguous
    contiguous_kv = connector.format_to_head_contiguous(original_kv)
    assert contiguous_kv.shape == (8, 4, 512, 128), f"Unexpected shape: {contiguous_kv.shape}"
    assert contiguous_kv.is_contiguous(), "Tensor is not contiguous in memory!"
    
    # Restore original shape
    restored_kv = connector.format_from_head_contiguous(contiguous_kv)
    assert torch.equal(original_kv, restored_kv), "Restored tensor does not match original!"
    print("✅ Test 1 Passed: Layout transformation (Contiguous <-> Original) is lossless.")


def test_multicast_byte_reduction():
    connector = VeritXKVMulticastConnector(num_q_heads=64, num_kv_heads=8, head_dim=128)
    kv_tensor = torch.randn(8, 4, 1024, 128)  # Head contiguous
    
    _, naive_bytes = connector.simulate_multicast_fetch(kv_tensor, use_multicast=False)
    _, mcast_bytes = connector.simulate_multicast_fetch(kv_tensor, use_multicast=True)
    
    ratio = naive_bytes / mcast_bytes
    assert abs(ratio - 8.0) < 1e-5, f"Expected 8x reduction, got {ratio}"
    print(f"✅ Test 2 Passed: Multicast reduces DRAM KV read volume by exactly {ratio:.1f}x (g=8).")


if __name__ == "__main__":
    print("Running vLLM KV-Multicast Connector Unit Tests...\n")
    test_layout_transformation()
    test_multicast_byte_reduction()
    print("\nAll tests passed successfully!")
