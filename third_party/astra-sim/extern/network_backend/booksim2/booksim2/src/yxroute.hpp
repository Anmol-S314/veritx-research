#ifndef _YXROUTE_HPP_
#define _YXROUTE_HPP_

#include "routefunc.hpp"

// YX dimension-order routing for mesh. Mirror of booksim's XY `dim_order_mesh`.
// Mixing yx_mesh and dor_mesh in one network closes the CW/CCW turn cycle that
// dimension-order routing exists to break -- that is the T2 deadlock case.
void yx_mesh(const Router *r, const Flit *f, int in_channel,
             OutputSet *outputs, bool inject);

#endif
