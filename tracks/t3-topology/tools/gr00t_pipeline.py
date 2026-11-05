#!/usr/bin/env python3
"""Bounded GR00T dataset ledger and explicitly synthetic sensor/trajectory projection."""
from __future__ import annotations
import argparse, hashlib, json, math, subprocess, sys
from pathlib import Path

REVISION = 'ea7ac0b68f87da62f1e726771bba0fe74300802f'
REPO = 'nvidia/PhysicalAI-Robotics-GR00T-X-Embodiment-Sim'
SUBSET = 'unitree_g1.LMPnPAppleToPlateDC'
HASHES = {'parquet_sha256':'dbbcb8ac2831fb62f16425b3c7dfe7b57169a6a24960a8a743bbef903bd6fd32', 'mp4_sha256':'e3287f43ec3a8ea8b1f75453c2c559c75909cdd9128b0a147bb7fc936fc84e4d'}

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def read_ledger(path):
    rows=[json.loads(x) for x in Path(path).read_text().splitlines()]
    if len(rows)!=684 or rows[0].get('record_type')!='metadata': raise ValueError('ledger must contain metadata + exactly 683 frames')
    m=rows[0]
    if m.get('source',{}).get('revision')!=REVISION or m.get('source',{}).get('repo')!=REPO or m.get('inputs')!=HASHES: raise ValueError('ledger provenance/hash mismatch')
    frames=rows[1:]; last=-1
    for i,r in enumerate(frames,1):
        t=r.get('timestamp_s'); pts=r.get('video_pts_s')
        if r.get('frame_index')!=i or not isinstance(t,(int,float)) or not math.isfinite(t) or t<=last or not isinstance(pts,(int,float)) or abs(t-pts)>.001: raise ValueError(f'invalid frame/timestamp {i}')
        if r.get('state')!={'dtype':'float64','elements':43,'raw_value_bytes':344} or r.get('action')!={'dtype':'float64','elements':43,'raw_value_bytes':344}: raise ValueError(f'invalid vector summary {i}')
        if type(r.get('h264_demux_packet_bytes')) is not int or r['h264_demux_packet_bytes']<=0: raise ValueError(f'invalid packet size {i}')
        last=t
    return rows

def project(ledger, trace, manifest):
    rows=read_ledger(ledger); frame=rows[1]
    # Authored physical-observation projection: camera 0 -> endpoint 0, state 1 -> endpoint 1, action demo 2 -> endpoint 2.
    # Packetization is an explicit 256-byte flit assumption; no vector values are projected.
    packets=[(0,1, math.ceil(15638/256)),(1,2,math.ceil(344/256))]
    Path(trace).write_text(''.join(f'0 {s} 0 {d} {n}\n' for s,d,n in packets))
    Path(manifest).write_text(json.dumps({'label':'sensor/trajectory projection; NOT model execution traffic','ledger_sha256':sha(ledger),'mapping':{'camera_h264':'0->1','state summary':'1->2','action demonstration':'1->2 (not predicted inference)'},'time_mapping':'single observation at cycle 0; native timestamps intentionally not replayed','packetization':'ceil(bytes/256), assumed 256-byte flit','trace_sha256':sha(trace),'packets':2},sort_keys=True,indent=2)+'\n')

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='cmd',required=True)
    v=sub.add_parser('verify'); v.add_argument('--ledger',required=True)
    f=sub.add_parser('fetch'); f.add_argument('--cache-dir',required=True); f.add_argument('--output-dir',required=True)
    q=sub.add_parser('project'); q.add_argument('--ledger',required=True); q.add_argument('--trace',required=True); q.add_argument('--manifest',required=True)
    d=sub.add_parser('timeloop-doctor')
    args=p.parse_args(argv)
    try:
        if args.cmd=='verify': read_ledger(args.ledger); print('verified 683-frame pinned ledger')
        elif args.cmd=='fetch':
            try: from huggingface_hub import hf_hub_download
            except ImportError as e: raise RuntimeError('optional huggingface_hub dependency missing') from e
            out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
            for name,key in [('episode_000000.parquet','parquet_sha256'),('episode_000000.mp4','mp4_sha256')]:
                path=hf_hub_download(repo_id=REPO,repo_type='dataset',revision=REVISION,filename=f'{SUBSET}/{name}',cache_dir=args.cache_dir)
                if sha(path)!=HASHES[key]: raise ValueError(f'{name} SHA256 mismatch')
                (out/name).write_bytes(Path(path).read_bytes())
        elif args.cmd=='project': project(args.ledger,args.trace,args.manifest)
        else:
            import shutil
            missing=[x for x in ('scons','g++') if not shutil.which(x)]
            if missing: raise RuntimeError('Timeloop unavailable: missing '+', '.join(missing))
            if not (Path('third_party/timeloop/src/pat').exists()): raise RuntimeError('Timeloop PAT dependency unavailable')
            raise RuntimeError('Timeloop sources present; binary absent. Build/run only from disposable copy; GEMM smoke is not GR00T reconstruction.')
    except Exception as e:
        print(f'gr00t_pipeline: {e}',file=sys.stderr); return 2
    return 0
if __name__=='__main__': raise SystemExit(main())
