#include "yxroute.hpp"
#include "globals.hpp"

// Next hop, high dimension first (Y before X). booksim's own dor_next_mesh has
// this as its `descending` branch, but that helper is static to routefunc.cpp,
// so we restate the 10 lines rather than patch a declaration into the header.
static int yx_next_mesh(int cur, int dest)
{
  if (cur == dest) {
    return 2 * gN; // eject
  }

  int dim_left;
  for (dim_left = (gN - 1); dim_left > 0; --dim_left) {
    if ((cur * gK / gNodes) != (dest * gK / gNodes)) { break; }
    cur = (cur * gK) % gNodes;
    dest = (dest * gK) % gNodes;
  }
  cur = (cur * gK) / gNodes;
  dest = (dest * gK) / gNodes;

  return (cur < dest) ? 2 * dim_left : 2 * dim_left + 1;
}

void yx_mesh(const Router *r, const Flit *f, int in_channel,
             OutputSet *outputs, bool inject)
{
  int out_port = inject ? -1 : yx_next_mesh(r->GetID(), f->dest);

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
