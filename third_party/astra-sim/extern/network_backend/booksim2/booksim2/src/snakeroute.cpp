#include "snakeroute.hpp"
#include "globals.hpp"

// Dimension-order (XY, low dim first) next hop -- restated because booksim's dor_next_mesh
// is static to routefunc.cpp (same reason yxroute.cpp restates its helper).
static int dor_next_mesh(int cur, int dest)
{
  if (cur == dest) return 2 * gN;   // eject
  int c = cur, d = dest;
  for (int dim = 0; dim < gN; ++dim) {
    int const cx = c % gK, dx = d % gK;
    if (cx != dx)
      return (cx < dx) ? 2 * dim : 2 * dim + 1;
    c /= gK; d /= gK;
  }
  return 2 * gN;                     // unreachable (cur==dest handled above)
}

// Successor of `cur` in the boustrophedon order on a gK x gK mesh (2-D only). Even rows run
// +x, odd rows run -x, and a row's far end steps +y into the next row -- one Hamiltonian path
// visiting every node. The path's final node is caught by the cur==dest check in snake_mesh,
// so the "+y off the top row" case never actually fires.
static int snake_next_mesh(int cur)
{
  int const k = gK;
  int const x = cur % k, y = cur / k;
  if ((y & 1) == 0)                 // even row: travel +x, then up at the right edge
    return (x < k - 1) ? 0 /*+x*/ : 2 /*+y*/;
  else                              // odd row: travel -x, then up at the left edge
    return (x > 0) ? 1 /*-x*/ : 2 /*+y*/;
}

void snake_mesh(const Router *r, const Flit *f, int in_channel,
                OutputSet *outputs, bool inject)
{
  assert(gN == 2);                  // snake broadcast is defined for a 2-D mesh
  int out_port;
  if (inject)
    out_port = -1;
  else if (r->GetID() == f->dest)
    out_port = 2 * gN;              // snake-end (or a naive unicast's dest): eject
  else if (f->mcast)
    out_port = snake_next_mesh(r->GetID());          // broadcast head follows the snake
  else
    out_port = dor_next_mesh(r->GetID(), f->dest);   // naive unicast: plain DOR, not penalised

  int vcBegin = 0, vcEnd = gNumVCs - 1;
  if (f->type == Flit::READ_REQUEST) {
    vcBegin = gReadReqBeginVC;   vcEnd = gReadReqEndVC;
  } else if (f->type == Flit::WRITE_REQUEST) {
    vcBegin = gWriteReqBeginVC;  vcEnd = gWriteReqEndVC;
  } else if (f->type == Flit::READ_REPLY) {
    vcBegin = gReadReplyBeginVC; vcEnd = gReadReplyEndVC;
  } else if (f->type == Flit::WRITE_REPLY) {
    vcBegin = gWriteReplyBeginVC; vcEnd = gWriteReplyEndVC;
  }
  assert(((f->vc >= vcBegin) && (f->vc <= vcEnd)) || (inject && (f->vc < 0)));

  outputs->Clear();
  outputs->AddRange(out_port, vcBegin, vcEnd);
}
