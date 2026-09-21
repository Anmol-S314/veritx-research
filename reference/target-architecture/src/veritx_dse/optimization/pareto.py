def pareto_front(values,directions):
    ids=sorted(values)
    def dominates(a,b):
        no_worse=True; strict=False
        for x,y,d in zip(values[a],values[b],directions):
            if d=="MIN":
                no_worse &= x<=y; strict |= x<y
            else:
                no_worse &= x>=y; strict |= x>y
        return bool(no_worse and strict)
    return tuple(cid for cid in ids if not any(dominates(other,cid) for other in ids if other!=cid))
