"""Independent shared-jump geometry/closure oracle for NEW reference policy."""
from dataclasses import replace
import copy
import pytest
from veritx_dse.model.gec_hybrid_route import GecHybridParams
from veritx_dse.model.topology_artifact import materialize_gec_hybrid
from veritx_dse.model.shared_resource import ResourceKind, ResourceRef
from veritx_dse.verification.gec_hybrid_escape import (
    PARTITION, TRANSITIONS, build_gec_shared_escape, load_gec_shared_escape,
    verify_gec_shared_escape)


def fixture(k=3, c=2, o=1, d=2):
    params = GecHybridParams(k, c, o, d, 2*d)
    topo = materialize_gec_hybrid(k=k, concentration=c, o=o, d=d)
    profile = build_gec_shared_escape(params, topo, partition=PARTITION, transitions=TRANSITIONS)
    return params, topo, profile


@pytest.mark.parametrize('k,c,o,d', [(3,2,1,2), (4,2,1,3), (5,1,2,2)])
def test_escape_every_context_geometry_and_concrete_isolation(k,c,o,d):
    params, topo, p = fixture(k,c,o,d)
    certificate = verify_gec_shared_escape(p, topo)
    assert certificate['verdict'] == 'PASS'
    wires = {w.shared_link_id:w for w in topo.shared_links}
    # Separate coordinate oracle: jump X to target x then Y to target y.
    for (src,dest,ingress), actions in p.contexts.items():
        target = dest // c
        if src == target:
            assert actions == ()
            continue
        escape, = (a for a in actions if a.vc_partition >= 2)
        x,y = src%k,src//k; dx,dy = target%k,target//k
        phase = 0 if x != dx else 1
        assert escape.vc_partition == 2+phase
        assert escape.next_router == (y*k+dx if phase == 0 else dy*k+x)
        assert escape.resource.kind is ResourceKind.SHARED_LINK
        wire = wires[escape.resource.resource_id]
        assert wire.src_router == src and wire.taps[escape.tap] == escape.next_router
        if ingress >= 2:
            assert actions == (escape,)
        if ingress == 1:
            assert phase == 1  # no reachable Y->X context silently dropped
    assert all((s,d,-1) in p.contexts for s in range(k*k) for d in range(k*k*c))
    assert load_gec_shared_escape(p.to_dict(), params, topo).identity() == p.identity()


@pytest.mark.parametrize('tamper', ['missing','extra','tap','kind','landing','vc','exit','hash','partition','transitions'])
def test_fail_closed_modified_context_or_concrete_resource(tamper):
    _, topo, p = fixture()
    ctx = dict(p.contexts); key=(0,16,-1); a=ctx[key][-1]
    kwargs={}
    if tamper=='missing': del ctx[key]
    elif tamper=='extra': ctx[0,16,3]=ctx[key]
    elif tamper=='tap': ctx[key]=ctx[key][:-1]+(replace(a,tap=99),)
    elif tamper=='kind': ctx[key]=ctx[key][:-1]+(replace(a,resource=ResourceRef(ResourceKind.CHANNEL,a.resource.resource_id),tap=None),)
    elif tamper=='landing': ctx[key]=ctx[key][:-1]+(replace(a,next_router=0),)
    elif tamper=='vc': ctx[key]=ctx[key][:-1]+(replace(a,vc_partition=3),)
    elif tamper=='exit': ctx[(2,16,2)] = ctx[key]
    elif tamper=='hash': kwargs['topology_hash']='foreign'
    elif tamper=='partition': kwargs['partition']=(('ADAPTIVE_X',(2,)),)+PARTITION[1:]
    else: kwargs['transitions']=TRANSITIONS+((3,0),)
    with pytest.raises(ValueError): verify_gec_shared_escape(replace(p,contexts=ctx,**kwargs),topo)


def test_renumbered_resource_ids_and_shared_taps_are_not_independent_resources():
    params, topo, _ = fixture()
    topo=replace(topo, channels=tuple(replace(c,channel_id=i) for i,c in enumerate(reversed(topo.channels))),
                 shared_links=tuple(replace(w,shared_link_id=i) for i,w in enumerate(reversed(topo.shared_links))))
    p=build_gec_shared_escape(params,topo,partition=PARTITION,transitions=TRANSITIONS)
    assert verify_gec_shared_escape(p,topo)['verdict']=='PASS'
    assert len({(a.resource,a.vc_partition) for actions in p.contexts.values() for a in actions if a.vc_partition>=2}) < sum(len(w.taps) for w in topo.shared_links)*2


@pytest.mark.parametrize('tamper',['bool','unknown','missing','tap','parent'])
def test_strict_serialized_parent_validation(tamper):
    params,topo,p=fixture(); doc=copy.deepcopy(p.to_dict())
    if tamper=='bool': doc['params']['c']=True
    elif tamper=='unknown':doc['ignored']=0
    elif tamper=='missing':doc['contexts'].pop()
    elif tamper=='tap':doc['contexts'][16][-1][-1]['tap']=99
    else:doc['topology_hash']='foreign'
    with pytest.raises(ValueError):load_gec_shared_escape(doc,params,topo)


def test_terminating_paths_do_not_replace_global_cdg_cycle_check(monkeypatch):
    import veritx_dse.verification.gec_hybrid_escape as module
    _,topo,p=fixture()
    monkeypatch.setattr(module.SharedResourceCDG,'find_cycle',lambda self: ('cycle',))
    with pytest.raises(ValueError,match='union contains cycle'):verify_gec_shared_escape(p,topo)


def test_missing_actual_wire_never_passes():
    params,topo,_=fixture()
    with pytest.raises(ValueError):build_gec_shared_escape(params,replace(topo,shared_links=topo.shared_links[:-1]),partition=PARTITION,transitions=TRANSITIONS)


@pytest.mark.parametrize('field',['partition','transitions','contexts'])
def test_boolean_integer_aliases_in_constructor_refuse(field):
    _,topo,p=fixture()
    if field=='partition':kw=dict(partition=(("ADAPTIVE_X",(False,)),)+PARTITION[1:])
    elif field=='transitions':kw=dict(transitions=((False,0),)+TRANSITIONS[1:])
    else:
        contexts=dict(p.contexts);contexts[(False,0,-1)]=contexts.pop((0,0,-1));kw=dict(contexts=contexts)
    with pytest.raises(ValueError):verify_gec_shared_escape(replace(p,**kw),topo)
