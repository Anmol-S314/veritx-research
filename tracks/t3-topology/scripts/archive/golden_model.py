#!/usr/bin/env python3
"""golden_model.py — Cycle-accurate 2-VC NoC router model (5933b88 semantics).

Tests whether the admission gate is the cause of deadlock on small meshes.
Switchable gates: empty_queue | rt_alloc | capacity
"""

import math, random, sys, copy
from collections import deque

# ── Constants ──
FT_HEAD, FT_BODY, FT_TAIL, FT_SINGLE = 0, 1, 2, 3

def is_head(f): return f[2] in (FT_HEAD, FT_SINGLE)
def is_tail(f): return f[2] in (FT_TAIL, FT_SINGLE)

# Flit = (src, dst, type, esc_bit, seq)


class Router:
    """One 2-VC wormhole router (matches 5933b88 RTL semantics)."""

    def __init__(self, rid, deg, num_vcs, buf_depth, age_k, tbl_min, tbl_esc):
        self.rid = rid
        self.deg = deg          # number of network ports
        self.lp = deg           # LOCAL port index
        self.nv = num_vcs
        self.bd = buf_depth
        self.age_k = age_k
        self.tbl_min = tbl_min  # dict: dst -> port
        self.tbl_esc = tbl_esc  # dict: dst -> port

        nq = (deg + 1) * num_vcs
        self.q = [deque() for _ in range(nq)]        # flit queues
        self.q_cnt = [0] * nq
        self.blk = [0] * nq                           # cumulative age
        self.rt_alloc = [False] * nq
        self.rt_out = [0] * nq
        self.esc_mode = [False] * nq

        # credits[output_port][vc]
        self.cred = [[buf_depth] * num_vcs for _ in range(deg + 1)]
        # output stages: out_vld[port][vc], out_flt[port][vc], out_src[port][vc]
        self.ov = [[False] * num_vcs for _ in range(deg + 1)]
        self.of = [[None] * num_vcs for _ in range(deg + 1)]
        self.os = [[0] * num_vcs for _ in range(deg + 1)]
        self.rr = [0] * (deg + 1)                    # round-robin ptr
        self.esc_starve = [0] * (deg + 1)


class Network:
    """Cycle-accurate mesh simulation."""

    def __init__(self, n, adj, tbl_min, tbl_esc, num_vcs=2, buf_depth=8,
                 block_k=8, gate="empty_queue", esc_yield_k=4):
        self.n = n
        self.adj = adj
        self.nv = num_vcs
        self.bd = buf_depth
        self.gate = gate
        self.eyk = esc_yield_k
        self.age_k = block_k * 8

        self.rtrs = [Router(i, len(adj[i]), num_vcs, buf_depth, self.age_k,
                            tbl_min[i], tbl_esc[i]) for i in range(n)]

        # Link buffers: link[r][port] = flit or None (network input from neighbor)
        self.link = [[None] * (len(adj[r]) + 1) for r in range(n)]

        # Tracking
        self.outstanding = {}  # (src,dst,seq) -> flits_left
        self.inj = 0
        self.ej = 0
        self.wrong_dst = 0

    def run(self, ir, seed, max_cyc, drain_cyc=50000):
        rng = random.Random(seed)
        R = self.rtrs
        nv, bd, n = self.nv, self.bd, self.n
        total = max_cyc + drain_cyc

        # Pre-generate injection schedule
        inject_queue = [[] for _ in range(n)]  # per-source pending flits
        seq = [0]

        def make_pkt(src, dst):
            nflits = rng.randint(1, 4)
            pkts = []
            for i in range(nflits):
                if i == 0: typ = FT_HEAD
                elif i == nflits - 1: typ = FT_TAIL
                else: typ = FT_BODY
                pkts.append((src, dst, typ, False, seq[0]))
                seq[0] += 1
            return pkts

        for cyc in range(total):
            # ── Inject ──
            if cyc < max_cyc:
                for s in range(n):
                    if rng.random() < ir:
                        d = rng.randrange(n)
                        while d == s:
                            d = rng.randrange(n)
                        pkt = make_pkt(s, d)
                        inject_queue[s].extend(pkt)

            # Try to inject one flit per source per cycle
            for s in range(n):
                if not inject_queue[s]:
                    continue
                flit = inject_queue[s][0]
                f_src, f_dst, f_typ, f_esc, f_seq = flit
                lp = R[s].lp
                esc_bit = f_esc
                lc = lp * nv + (1 if esc_bit else 0)

                # S3c: force ESC for body/tail in escape-mode queue
                enq = flit
                if not is_head(flit):
                    tgt = lc
                    if tgt < len(R[s].esc_mode) and R[s].esc_mode[tgt]:
                        lc = lp * nv + (nv - 1)
                        enq = (f_src, f_dst, f_typ, True, f_seq)

                cap = R[s].q_cnt[lc] < bd
                if self.gate == "empty_queue":
                    head = not is_head(enq) or R[s].q_cnt[lc] == 0
                elif self.gate == "rt_alloc":
                    head = not is_head(enq) or not R[s].rt_alloc[lc]
                else:
                    head = True

                if cap and head:
                    R[s].q[lc].append(enq)
                    R[s].q_cnt[lc] += 1
                    self.inj += 1
                    inject_queue[s].pop(0)
                    if is_head(enq):
                        nflits = sum(1 for f in inject_queue[s]
                                     if f[0] == f_src and f[1] == f_dst)
                        # count all flits of this packet
                    self.outstanding[(f_src, f_dst, f_seq)] = True

            # ── show_vc mux (escape priority with yield) ──
            svc = []
            for r in range(n):
                svc.append([0] * (R[r].lp + 1))
                for p in range(R[r].lp + 1):
                    esc_s = (R[r].ov[p][1] and
                             not (R[r].esc_starve[p] >= self.eyk and
                                  R[r].ov[p][0]))
                    svc[r][p] = 1 if esc_s else 0

            # ── cand_out (combinational) ──
            co = []
            for r in range(n):
                nq = (R[r].lp + 1) * nv
                c = [0] * nq
                for q in range(nq):
                    if R[r].q_cnt[q] > 0:
                        front = R[r].q[q][0]
                        dst = front[1]
                        if q % nv == 1:
                            c[q] = R[r].tbl_esc.get(dst, 0)
                        elif R[r].esc_mode[q]:
                            c[q] = R[r].tbl_esc.get(dst, 0)
                        elif R[r].rt_alloc[q]:
                            c[q] = R[r].rt_out[q]
                        else:
                            c[q] = R[r].tbl_min.get(dst, 0)
                co.append(c)

            # ── Grant logic ──
            esc_v = [[False] * (R[r].lp + 1) for r in range(n)]
            free_v = [[False] * (R[r].lp + 1) for r in range(n)]
            esc_pk = [[0] * (R[r].lp + 1) for r in range(n)]
            free_pk = [[0] * (R[r].lp + 1) for r in range(n)]

            for r in range(n):
                for op in range(R[r].lp):
                    # Escape: VC1 first-match
                    for ip in range(R[r].lp + 1):
                        c = ip * nv + 1
                        if (not esc_v[r][op] and not R[r].ov[op][1] and
                                R[r].q_cnt[c] > 0 and R[r].cred[op][1] > 0 and
                                co[r][c] == op and R[r].q[c][0][1] != r):
                            esc_v[r][op] = True
                            esc_pk[r][op] = ip
                    # Free: VC0 round-robin
                    for rr in range(R[r].lp + 1):
                        ip = (R[r].rr[op] + rr) % (R[r].lp + 1)
                        c = ip * nv + 0
                        if (not free_v[r][op] and not R[r].ov[op][0] and
                                R[r].q_cnt[c] > 0 and R[r].cred[op][0] > 0 and
                                co[r][c] == op and R[r].q[c][0][1] != r):
                            free_v[r][op] = True
                            free_pk[r][op] = ip

            # ── grant_deq_q ──
            gdq = [[False] * ((R[r].lp + 1) * nv) for r in range(n)]
            for r in range(n):
                for op in range(R[r].lp):
                    if esc_v[r][op]:
                        gdq[r][esc_pk[r][op] * nv + 1] = True
                    if free_v[r][op]:
                        gdq[r][free_pk[r][op] * nv + 0] = True

            # ── ej_dequeued ──
            ej_dq = [list(g) for g in gdq]
            for r in range(n):
                lp = R[r].lp
                for pass2 in range(nv - 1, -1, -1):
                    done = False
                    if not R[r].ov[lp][pass2]:
                        for p2 in range(lp + 1):
                            c2 = p2 * nv + pass2
                            if (R[r].q_cnt[c2] > 0 and
                                    R[r].q[c2][0][1] == r and
                                    not gdq[r][c2]):
                                ej_dq[r][c2] = True
                                done = True
                                break
                    if done:
                        break

            # ── Starve counters ──
            for r in range(n):
                for p in range(R[r].lp + 1):
                    if svc[r][p] == 1 and R[r].ov[p][0]:
                        R[r].esc_starve[p] = min(R[r].esc_starve[p] + 1, 15)
                    elif svc[r][p] == 0:
                        R[r].esc_starve[p] = 0

            # ── Output stage (section 1) ──
            # Use deferred updates to avoid read-write conflicts
            d_q = [deque(R[r].q[c]) for r in range(n)
                   for c in range((R[r].lp + 1) * nv)]
            d_qc = list(sum(([R[r].q_cnt[c] for c in range((R[r].lp + 1) * nv)]
                             for r in range(n)), []))
            d_ra = list(sum(([R[r].rt_alloc[c] for c in range((R[r].lp + 1) * nv)]
                             for r in range(n)), []))
            d_ro = list(sum(([R[r].rt_out[c] for c in range((R[r].lp + 1) * nv)]
                             for r in range(n)), []))
            d_em = list(sum(([R[r].esc_mode[c] for c in range((R[r].lp + 1) * nv)]
                             for r in range(n)), []))
            d_bl = list(sum(([R[r].blk[c] for c in range((R[r].lp + 1) * nv)]
                             for r in range(n)), []))
            d_cv = [[R[r].cred[op][vc] for op in range(R[r].lp + 1)
                      for vc in range(nv)] for r in range(n)]
            d_ov = [[R[r].ov[op][vc] for op in range(R[r].lp + 1)
                      for vc in range(nv)] for r in range(n)]
            d_of = [[R[r].of[op][vc] for op in range(R[r].lp + 1)
                      for vc in range(nv)] for r in range(n)]
            d_os = [[R[r].os[op][vc] for op in range(R[r].lp + 1)
                      for vc in range(nv)] for r in range(n)]
            d_rr = [list(R[r].rr) for r in range(n)]
            deq_a = [False] * sum((R[r].lp + 1) * nv for r in range(n))

            def qidx(r, c):
                off = 0
                for rr in range(r):
                    off += (R[rr].lp + 1) * nv
                return off + c

            for r in range(n):
                lp = R[r].lp
                for p3 in range(lp + 1):
                    # ── FREE stage (slot 0) ──
                    if (R[r].ov[p3][0] and svc[r][p3] == 0):
                        # Accepted
                        d_ov[r][p3 * nv + 0] = False
                        sc = R[r].os[p3][0]
                        d_cv[r][p3 * nv + sc] = R[r].cred[p3][sc] + 1
                    elif (p3 != lp and free_v[r][p3] and not R[r].ov[p3][0]):
                        fsp = free_pk[r][p3]
                        fci = fsp * nv + 0
                        flt = R[r].q[fci][0]
                        d_of[r][p3 * nv + 0] = flt
                        d_ov[r][p3 * nv + 0] = True
                        d_os[r][p3 * nv + 0] = 0
                        d_cv[r][p3 * nv + 0] = R[r].cred[p3][0] - 1
                        d_rr[r][p3] = (fsp + 1) % (lp + 1)
                        qi = qidx(r, fci)
                        if is_head(flt):
                            d_ra[qi] = True
                            d_ro[qi] = p3
                        if is_tail(flt):
                            d_ra[qi] = False
                            d_em[qi] = False
                            d_bl[qi] = 0
                        d_q[qi] = deque(list(R[r].q[fci])[1:])
                        d_qc[qi] = R[r].q_cnt[fci] - 1
                        deq_a[qi] = True

                    # ── ESCAPE stage (slot 1) ──
                    if (R[r].ov[p3][1] and svc[r][p3] == 1):
                        # Accepted
                        d_ov[r][p3 * nv + 1] = False
                        sc = R[r].os[p3][1]
                        d_cv[r][p3 * nv + sc] = R[r].cred[p3][sc] + 1
                    elif (p3 != lp and esc_v[r][p3] and not R[r].ov[p3][1]):
                        esp = esc_pk[r][p3]
                        eci = esp * nv + 1
                        flt = R[r].q[eci][0]
                        d_of[r][p3 * nv + 1] = flt
                        d_ov[r][p3 * nv + 1] = True
                        d_os[r][p3 * nv + 1] = 1
                        d_cv[r][p3 * nv + 1] = R[r].cred[p3][1] - 1
                        qi = qidx(r, eci)
                        if is_head(flt):
                            d_ra[qi] = True
                            d_ro[qi] = p3
                        if is_tail(flt):
                            d_ra[qi] = False
                            d_em[qi] = False
                            d_bl[qi] = 0
                        d_q[qi] = deque(list(R[r].q[eci])[1:])
                        d_qc[qi] = R[r].q_cnt[eci] - 1
                        deq_a[qi] = True

            # ── Ejection (section 2) ──
            for r in range(n):
                lp = R[r].lp
                ej_done = False
                for pass2 in range(nv - 1, -1, -1):
                    if ej_done:
                        break
                    if R[r].ov[lp][pass2]:
                        if svc[r][lp] == pass2:
                            pass  # will be freed by output stage
                        else:
                            continue
                    for p2 in range(lp + 1):
                        c2 = p2 * nv + pass2
                        qi = qidx(r, c2)
                        if (R[r].q_cnt[c2] > 0 and not gdq[r][c2] and
                                R[r].q[c2][0][1] == r):
                            flt = R[r].q[c2][0]
                            d_of[r][lp * nv + pass2] = flt
                            d_ov[r][lp * nv + pass2] = True
                            d_os[r][lp * nv + pass2] = pass2
                            if is_head(flt):
                                d_ra[qi] = True
                                d_ro[qi] = lp
                            if is_tail(flt):
                                d_ra[qi] = False
                                d_em[qi] = False
                                d_bl[qi] = 0
                            d_q[qi] = deque(list(R[r].q[c2])[1:])
                            d_qc[qi] = R[r].q_cnt[c2] - 1
                            deq_a[qi] = True
                            self.ej += 1
                            self.outstanding.pop((flt[0], flt[1], flt[4]), None)
                            ej_done = True
                            break

            # ── Demotion (section 3) ──
            for r in range(n):
                for p2 in range(R[r].lp + 1):
                    c2 = p2 * nv  # FREE VC only
                    qi = qidx(r, c2)
                    if d_qc[qi] > 0:
                        front = d_q[qi][0]
                        if d_bl[qi] < 255:
                            d_bl[qi] += 1
                        if d_bl[qi] >= self.age_k:
                            d_em[qi] = True
                            d_q[qi] = deque(
                                (f[0], f[1], f[2], True, f[4]) for f in d_q[qi])
                            d_bl[qi] = 0
                        elif d_em[qi]:
                            f = d_q[qi][0]
                            d_q[qi][0] = (f[0], f[1], f[2], True, f[4])

            # ── Enqueue (section 4) ──
            for r in range(n):
                lp = R[r].lp
                for p2 in range(lp + 1):
                    flt_in = self.link[r][p2]
                    if flt_in is None:
                        continue
                    esc_bit = flt_in[3]
                    lc = p2 * nv + (1 if esc_bit else 0)
                    enq = flt_in

                    # S3c
                    if not is_head(flt_in):
                        qi = qidx(r, lc)
                        if qi < len(d_em) and d_em[qi]:
                            lc = p2 * nv + (nv - 1)
                            enq = (flt_in[0], flt_in[1], flt_in[2], True, flt_in[4])

                    qi = qidx(r, lc)
                    cap = d_qc[qi] < bd
                    if self.gate == "empty_queue":
                        head = not is_head(enq) or d_qc[qi] == 0
                    elif self.gate == "rt_alloc":
                        head = not is_head(enq) or not d_ra[qi]
                    else:
                        head = True

                    if cap and head:
                        if deq_a[qi] and d_qc[qi] > 0:
                            d_q[qi][d_qc[qi] - 1] = enq
                        else:
                            d_q[qi].append(enq)
                            d_qc[qi] += 1
                    # else: blocked (stays in link buffer — lost in this model)

                    self.link[r][p2] = None

            # ── Apply deferred state ──
            for r in range(n):
                lp = R[r].lp
                nq = (lp + 1) * nv
                for c in range(nq):
                    qi = qidx(r, c)
                    R[r].q[c] = d_q[qi]
                    R[r].q_cnt[c] = d_qc[qi]
                    R[r].rt_alloc[c] = d_ra[qi]
                    R[r].rt_out[c] = d_ro[qi]
                    R[r].esc_mode[c] = d_em[qi]
                    R[r].blk[c] = d_bl[qi]
                for op in range(lp + 1):
                    for vc in range(nv):
                        idx = op * nv + vc
                        R[r].cred[op][vc] = d_cv[r][idx]
                        R[r].ov[op][vc] = d_ov[r][idx]
                        R[r].of[op][vc] = d_of[r][idx]
                        R[r].os[op][vc] = d_os[r][idx]
                    R[r].rr[op] = d_rr[r][op]

            # ── Move output flits to neighbor link buffers ──
            for r in range(n):
                lp = R[r].lp
                sn = sorted(self.adj[r])
                for p in range(lp):
                    for vc in range(nv):
                        if R[r].ov[p][vc] and R[r].of[p][vc] is not None:
                            flt = R[r].of[p][vc]
                            if p < len(sn):
                                nbr = sn[p]
                                bp = -1
                                for i, nb2 in enumerate(sorted(self.adj[nbr])):
                                    if nb2 == r:
                                        bp = i
                                        break
                                if bp >= 0 and self.link[nbr][bp] is None:
                                    self.link[nbr][bp] = flt

            # Periodic progress
            if cyc > 0 and cyc % 10000 == 0:
                pass  # silent

        return {
            "inj": self.inj,
            "ej": self.ej,
            "stuck": len(self.outstanding),
            "wrong": self.wrong_dst,
        }


# ── Topologies ──
def mesh_4x4():
    n = 16; side = 4
    adj = {}
    for r in range(n):
        rr, cc = divmod(r, side)
        s = set()
        if cc > 0: s.add(r - 1)
        if cc < side - 1: s.add(r + 1)
        if rr > 0: s.add(r - side)
        if rr < side - 1: s.add(r + side)
        adj[r] = s
    return n, adj

def mesh_2x2():
    n = 4
    adj = {0: {1, 2}, 1: {0, 3}, 2: {0, 3}, 3: {1, 2}}
    return n, adj

def line_4():
    n = 4
    adj = {0: {1}, 1: {0, 2}, 2: {1, 3}, 3: {2}}
    return n, adj


# ── Route tables ──
def dim_order(n, adj):
    side = int(math.isqrt(n))
    if side * side != n:
        return bfs_table(n, adj)
    tbls = [{} for _ in range(n)]
    for src in range(n):
        sr, sc = divmod(src, side)
        sn = sorted(adj[src])
        for dst in range(n):
            if dst == src: continue
            dr, dc = divmod(dst, side)
            if sc != dc:
                nxt = sr * side + (sc + (1 if dc > sc else -1))
            else:
                nxt = (sr + (1 if dr > sr else -1)) * side + sc
            if nxt not in adj[src]:
                return bfs_table(n, adj)
            tbls[src][dst] = sn.index(nxt)
    return tbls

def bfs_table(n, adj):
    tbls = [{} for _ in range(n)]
    for src in range(n):
        dist = [-1] * n; par = [-1] * n
        dist[src] = 0; q = deque([src])
        while q:
            u = q.popleft()
            for v in sorted(adj[u]):
                if dist[v] < 0:
                    dist[v] = dist[u] + 1; par[v] = u; q.append(v)
        sn = sorted(adj[src])
        for dst in range(n):
            if dst == src or dist[dst] < 0: continue
            cur = dst
            while par[cur] != src: cur = par[cur]
            tbls[src][dst] = sn.index(cur)
    return tbls

def escape_tree(n, adj, root=0):
    rank = [-1] * n; par = [-1] * n
    rank[root] = 0; q = deque([root])
    while q:
        u = q.popleft()
        for v in sorted(adj[u]):
            if rank[v] < 0:
                rank[v] = rank[u] + 1; par[v] = u; q.append(v)
    tbls = [{} for _ in range(n)]
    for s in range(n):
        sn = sorted(adj[s])
        pidx = {nb: i for i, nb in enumerate(sn)}
        for t in range(n):
            if t == s: continue
            x = t
            while x != -1 and x != s: x = par[x]
            if x == s or par[s] == -1:
                c = t
                while par[c] != s: c = par[c]
                tbls[s][t] = pidx.get(c, 0)
            else:
                tbls[s][t] = pidx.get(par[s], 0)
    return tbls


def best_esc_root(n, adj):
    best, best_d = 0, n * n
    for r in range(n):
        d = [-1] * n; d[r] = 0; q = deque([r])
        while q:
            u = q.popleft()
            for v in sorted(adj[u]):
                if d[v] < 0: d[v] = d[u] + 1; q.append(v)
        md = max(d)
        if md < best_d: best_d = md; best = r
    return best


# ── Main ──
def main():
    topo_name = sys.argv[1] if len(sys.argv) > 1 else "mesh_2x2"
    gate_name = sys.argv[2] if len(sys.argv) > 2 else "all"

    if topo_name == "mesh_4x4":
        n, adj = mesh_4x4()
    elif topo_name == "mesh_2x2":
        n, adj = mesh_2x2()
    elif topo_name == "line_4":
        n, adj = line_4()
    else:
        print(f"Unknown topology: {topo_name}")
        sys.exit(1)

    tbl_min = dim_order(n, adj)
    esc_root = best_esc_root(n, adj)
    tbl_esc = escape_tree(n, adj, root=esc_root)

    gates = (["empty_queue", "rt_alloc", "capacity"] if gate_name == "all"
             else [gate_name])

    print(f"\n{'='*65}")
    print(f" Topology: {topo_name} ({n} nodes)  esc_root={esc_root}")
    print(f"{'='*65}")
    print(f"{'gate':>16s}  {'IR':>5s}  {'inj':>6s}  {'stuck':>6s}  {'status':>6s}")
    print(f"{'-'*16}  {'-'*5}  {'-'*6}  {'-'*6}  {'-'*6}")

    for gate in gates:
        for ir in [0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15]:
            worst_stuck = 0
            worst_inj = 0
            for seed in [42, 123, 456, 789, 1000]:
                net = Network(n, adj, tbl_min, tbl_esc, num_vcs=2,
                              buf_depth=8, block_k=8, gate=gate)
                r = net.run(ir, seed, max_cyc=5000, drain_cyc=5000)
                if r["stuck"] > worst_stuck:
                    worst_stuck = r["stuck"]
                    worst_inj = r["inj"]
            status = "PASS" if worst_stuck == 0 else f"FAIL"
            print(f"{gate:>16s}  {ir:5.2f}  {worst_inj:6d}  {worst_stuck:6d}  {status:>6s}")

    print()


if __name__ == "__main__":
    main()
