#!/usr/bin/env python3
"""Convert text traces to binary format for faster BookSim parsing.

Binary format:
  - 4 bytes: magic number (0x54524143 = "TRAC")
  - 4 bytes: count of packets
  - N × 12 bytes: packed records (cycle:uint64, src:uint16, cl:uint16, dst:uint16, size:uint16)

Usage:
  python3 trace_to_binary.py input.trace output.trace.bin
"""
import struct
import sys
from pathlib import Path

BINARY_MAGIC = 0x54524143  # "TRAC"

def convert_text_to_binary(input_path: str, output_path: str):
    """Convert text trace to binary format."""
    entries = []
    
    with open(input_path) as f:
        for line in f:
            if line.startswith('#') or line.startswith('%'):
                continue
            parts = line.split()
            if len(parts) >= 5:
                cycle, src, cl, dst, size = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
                entries.append((cycle, src, cl, dst, size))
    
    # Sort by cycle (should already be sorted, but ensure)
    entries.sort(key=lambda x: x[0])
    
    with open(output_path, 'wb') as f:
        # Write header
        f.write(struct.pack('<I', BINARY_MAGIC))
        f.write(struct.pack('<I', len(entries)))
        
        # Write all records (12 bytes each)
        for cycle, src, cl, dst, size in entries:
            f.write(struct.pack('<QHHHH', cycle, src, cl, dst, size))
    
    print(f"Converted {len(entries)} entries to binary format")
    print(f"  Input:  {input_path} ({Path(input_path).stat().st_size:,} bytes)")
    print(f"  Output: {output_path} ({Path(output_path).stat().st_size:,} bytes)")
    print(f"  Speedup: {Path(input_path).stat().st_size / Path(output_path).stat().st_size:.1f}× smaller")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} input.trace output.trace.bin")
        sys.exit(1)
    
    convert_text_to_binary(sys.argv[1], sys.argv[2])
