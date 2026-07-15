#ifndef _SNAKEROUTE_HPP_
#define _SNAKEROUTE_HPP_

#include "routefunc.hpp"   // VC globals (gNumVCs, gReadReqBeginVC, ...)
#include "router.hpp"
#include "flit.hpp"
#include "outputset.hpp"

// Hamiltonian (boustrophedon "snake") broadcast route for the shared-prefix multicast
// experiment (scripts/prefix_broadcast_flitfork.py). A multicast HEAD flit (f->mcast) follows
// a snake that visits EVERY node of the mesh, so one injection + the existing eject-fork
// (multicast.patch) delivers a copy to all N-1 other nodes -- a real, deadlock-free 2-D
// broadcast. Ordinary flits (naive unicasts) fall back to dimension-order routing, so the
// naive baseline is not penalised by the snake. Registered as "snake_mesh".
void snake_mesh(const Router *r, const Flit *f, int in_channel,
                OutputSet *outputs, bool inject);

#endif
