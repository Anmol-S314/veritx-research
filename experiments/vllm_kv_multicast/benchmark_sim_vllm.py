#!/usr/bin/env python3
"""
Benchmark Simulation for vLLM KV-Multicast & Contiguous Layout Plugin

Models tokens/sec across:
1. Base vLLM: Naive GQA 8x reads + Interleaved Layout (EFF_INTERLEAVED = 0.66)
2. Contiguous Layout Only: Naive GQA 8x reads + Contiguous Layout (EFF_CONTIGUOUS = 0.91)
3. Multicast + Contiguous: 1x Multicast read + Contiguous Layout (EFF_CONTIGUOUS = 0.91)
"""

from kv_multicast_connector import VeritXKVMulticastConnector


def run_vllm_benchmark():
    # Llama-3-70B GQA configuration (64 Query Heads, 8 KV Heads -> g = 8)
    connector = VeritXKVMulticastConnector(num_q_heads=64, num_kv_heads=8, head_dim=128)
    
    # 8x Accelerator Node: 4608 GB/s total DRAM BW
    peak_dram_bw_gbs = 4608.0
    weight_bytes_bfp8 = 70.6e9 * 1.0  # 70.6 GB weights at BFP8 precision
    
    context_lengths = [8192, 32768, 131072]
    batch_sizes = [1, 4, 11]  # Batch 11 fills max 192GB capacity at 32K context
    
    print("===============================================================================================")
    print("  vLLM ROOFLINE SIMULATION: Llama-3-70B (g=8 GQA, 4608 GB/s DRAM BW)")
    print("===============================================================================================")
    print(f"{'Context':>8} | {'Batch':>5} | {'Base (Interleaved)':>18} | {'Contiguous Only':>16} | {'Mcast + Contiguous':>18} | {'Total Speedup':>13}")
    print("-----------------------------------------------------------------------------------------------")
    
    for seq_len in context_lengths:
        for batch in batch_sizes:
            # 1. Base vLLM: Interleaved layout + Naive 8x reads
            base_tok_s = connector.estimate_dram_throughput(
                batch_size=batch, seq_len=seq_len, peak_bw_gbs=peak_dram_bw_gbs,
                weight_bytes=weight_bytes_bfp8, use_multicast=False, use_contiguous_layout=False
            )
            # 2. Contiguous Only: Contiguous layout + Naive 8x reads
            contig_only_tok_s = connector.estimate_dram_throughput(
                batch_size=batch, seq_len=seq_len, peak_bw_gbs=peak_dram_bw_gbs,
                weight_bytes=weight_bytes_bfp8, use_multicast=False, use_contiguous_layout=True
            )
            # 3. Multicast + Contiguous: Contiguous layout + 1x Multicast read
            mcast_tok_s = connector.estimate_dram_throughput(
                batch_size=batch, seq_len=seq_len, peak_bw_gbs=peak_dram_bw_gbs,
                weight_bytes=weight_bytes_bfp8, use_multicast=True, use_contiguous_layout=True
            )
            
            total_speedup = mcast_tok_s / base_tok_s if base_tok_s > 0 else 1.0
            
            print(f"{seq_len:>8} | {batch:>5} | {base_tok_s:>15.1f} t/s | {contig_only_tok_s:>13.1f} t/s | {mcast_tok_s:>15.1f} t/s | {total_speedup:>12.2f}x")
    
    print("-----------------------------------------------------------------------------------------------")
    print("Summary:")
    print("• Base vLLM models both interleaved layout efficiency (EFF_INTERLEAVED=0.66) and naive 8x reads.")
    print(f"• Multicast eliminates the 8x redundant KV reads, with theoretical ceiling = g (8.0x for Llama-3-70B as B->inf).")
    print("===============================================================================================")


if __name__ == "__main__":
    run_vllm_benchmark()
