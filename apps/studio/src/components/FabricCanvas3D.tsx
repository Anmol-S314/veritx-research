import { useEffect, useRef, useState, type ReactElement } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { bucketOf, type FabricModel, type FabricNode } from '../fabricLayout';

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return value || fallback;
}

/**
 * 3D structural fabric view (Three.js). It renders the handed model —
 * the certified TopologyView when a revision compiled, otherwise the
 * intent preview — and never a fabricated overlay. Orbit to inspect;
 * click a router to identify it.
 */
export default function FabricCanvas3D({ model }: {
  model: FabricModel;
}): ReactElement {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const materialized = model.source === 'topology';
    const { nodes, edges, cols, rows, totals, concentration } = model;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const accent = cssVar('--accent', '#4da3c4');
    const border = cssVar('--border', '#2e3640');
    const ok = cssVar('--ok', '#4caf7d');
    const warn = cssVar('--warn', '#d9a441');

    const SP = 10;
    const scene = new THREE.Scene();
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.domElement.setAttribute('aria-hidden', 'true');
    mount.appendChild(renderer.domElement);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);
    const extent = Math.max(cols, rows) * SP;
    camera.position.set(extent * 0.85, extent * 0.95, extent * 1.15);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.autoRotate = !reduced;
    controls.autoRotateSpeed = 0.5;
    controls.target.set(0, 0, 0);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x1b2027, 1.1));
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.set(extent, extent * 1.6, extent);
    scene.add(key);

    const grid = new THREE.GridHelper(extent * 2.4, Math.max(8, cols * 2),
                                      border, border);
    grid.position.y = -3.2;
    scene.add(grid);

    const disposables: { dispose: () => void }[] = [];
    const track = <T extends { dispose: () => void }>(item: T): T => {
      disposables.push(item);
      return item;
    };

    const pos = (node: FabricNode): THREE.Vector3 => new THREE.Vector3(
      (node.col - (cols - 1) / 2) * SP, 0, (node.row - (rows - 1) / 2) * SP);
    const byId = new Map(nodes.map((n) => [n.id, n]));

    // links (one LineSegments geometry)
    const drawable = edges.filter((e) => byId.has(e.a) && byId.has(e.b));
    const linkPositions = new Float32Array(drawable.length * 6);
    drawable.forEach((edge, k) => {
      const pa = pos(byId.get(edge.a)!);
      const pb = pos(byId.get(edge.b)!);
      linkPositions.set([pa.x, pa.y, pa.z, pb.x, pb.y, pb.z], k * 6);
    });
    const linkGeom = track(new THREE.BufferGeometry());
    linkGeom.setAttribute('position',
                          new THREE.BufferAttribute(linkPositions, 3));
    const linkMat = track(new THREE.LineBasicMaterial({ color: border }));
    scene.add(new THREE.LineSegments(linkGeom, linkMat));

    // routers (instanced boxes)
    const routerGeom = track(new THREE.BoxGeometry(4, 4, 4));
    const routerMat = track(new THREE.MeshStandardMaterial({
      color: accent, metalness: 0.15, roughness: 0.55 }));
    const routers = new THREE.InstancedMesh(routerGeom, routerMat,
                                            Math.max(1, nodes.length));
    const dummy = new THREE.Object3D();
    const routerLabels: string[] = [];
    nodes.forEach((node, i) => {
      const p = pos(node);
      dummy.position.set(p.x, 0, p.z);
      dummy.updateMatrix();
      routers.setMatrixAt(i, dummy.matrix);
      routerLabels.push(`R${node.row},${node.col}`);
    });
    routers.instanceMatrix.needsUpdate = true;
    scene.add(routers);

    if (materialized) {
      // materialized agent seats, stacked on their own router
      const bucketColor: Record<string, THREE.Color | string> = {
        compute: ok, hbm: warn, nic: accent, edge: accent,
      };
      const bucketOrder = ['compute', 'hbm', 'nic', 'edge'] as const;
      const stacks: Record<string, { node: FabricNode; slot: number }[]> = {
        compute: [], hbm: [], nic: [], edge: [],
      };
      for (const node of nodes) {
        let slot = 0;
        for (const kind of bucketOrder) {
          const owned = Object.entries(node.attached)
            .filter(([k]) => bucketOf(k) === kind)
            .reduce((sum, [, count]) => sum + count, 0);
          for (let n = 0; n < owned; n++) {
            stacks[kind].push({ node, slot });
            slot += 1;
          }
        }
      }
      for (const kind of bucketOrder) {
        const entries = stacks[kind];
        if (entries.length === 0) continue;
        const geom = track(new THREE.BoxGeometry(2.2, 1.2, 2.2));
        const mat = track(new THREE.MeshStandardMaterial({
          color: bucketColor[kind], metalness: 0.1, roughness: 0.6 }));
        const mesh = new THREE.InstancedMesh(geom, mat, entries.length);
        entries.forEach(({ node, slot }, i) => {
          const p = pos(node);
          dummy.position.set(p.x, 3.4 + slot * 1.5, p.z);
          dummy.scale.set(1, 1, 1);
          dummy.updateMatrix();
          mesh.setMatrixAt(i, dummy.matrix);
        });
        mesh.instanceMatrix.needsUpdate = true;
        scene.add(mesh);
      }
    } else {
      // preview: declared compute volume above each router (position unknown)
      const tileGeom = track(new THREE.BoxGeometry(2.2, 1.4, 2.2));
      const tileMat = track(new THREE.MeshStandardMaterial({
        color: ok, metalness: 0.1, roughness: 0.6 }));
      const tiles = new THREE.InstancedMesh(tileGeom, tileMat,
                                            Math.max(1, nodes.length));
      nodes.forEach((node, i) => {
        const p = pos(node);
        const attached = Math.min(concentration,
          Math.max(0, totals.compute - i * concentration));
        dummy.position.set(p.x, 3.6, p.z);
        dummy.scale.set(1, Math.max(0.4, attached / Math.max(1, concentration)), 1);
        dummy.updateMatrix();
        tiles.setMatrixAt(i, dummy.matrix);
      });
      dummy.scale.set(1, 1, 1);
      tiles.instanceMatrix.needsUpdate = true;
      scene.add(tiles);

      // declared HBM controllers on the north/south edges (preview only)
      if (totals.hbm > 0) {
        const hbmGeom = track(new THREE.BoxGeometry(3.2, 2, 3.2));
        const hbmMat = track(new THREE.MeshStandardMaterial({
          color: warn, metalness: 0.2, roughness: 0.5 }));
        const hbmMesh = new THREE.InstancedMesh(hbmGeom, hbmMat, totals.hbm);
        const zNorth = -((rows - 1) / 2) * SP - 9;
        const zSouth = ((rows - 1) / 2) * SP + 9;
        for (let i = 0; i < totals.hbm; i++) {
          const north = i % 2 === 0;
          const slot = Math.floor(i / 2);
          const slots = Math.max(1, Math.ceil(totals.hbm / 2));
          const x = ((slot + 0.5) / slots - 0.5) * (cols - 1) * SP;
          dummy.position.set(x, 0, north ? zNorth : zSouth);
          dummy.updateMatrix();
          hbmMesh.setMatrixAt(i, dummy.matrix);
        }
        hbmMesh.instanceMatrix.needsUpdate = true;
        scene.add(hbmMesh);
      }

      // declared NIC / peripheral agents on the west edge (preview only)
      if (totals.edge > 0) {
        const edgeGeom = track(new THREE.BoxGeometry(2.4, 2, 2.4));
        const edgeMat = track(new THREE.MeshStandardMaterial({
          color: accent, metalness: 0.2, roughness: 0.6 }));
        const edgeMesh = new THREE.InstancedMesh(edgeGeom, edgeMat, totals.edge);
        const xWest = -((cols - 1) / 2) * SP - 9;
        for (let i = 0; i < totals.edge; i++) {
          const z = ((i + 0.5) / totals.edge - 0.5) * (rows - 1) * SP;
          dummy.position.set(xWest, 0, z);
          dummy.updateMatrix();
          edgeMesh.setMatrixAt(i, dummy.matrix);
        }
        edgeMesh.instanceMatrix.needsUpdate = true;
        scene.add(edgeMesh);
      }
    }

    // selection
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const onPointerDown = (event: PointerEvent): void => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObject(routers, false)[0];
      if (hit && hit.instanceId !== undefined) {
        setSelected(routerLabels[hit.instanceId] ?? null);
      } else {
        setSelected(null);
      }
    };
    renderer.domElement.addEventListener('pointerdown', onPointerDown);

    // resize
    const resize = (): void => {
      const w = mount.clientWidth || 1;
      const h = mount.clientHeight || 1;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    resize();

    renderer.setAnimationLoop(() => {
      controls.update();
      renderer.render(scene, camera);
    });

    return () => {
      renderer.setAnimationLoop(null);
      observer.disconnect();
      renderer.domElement.removeEventListener('pointerdown', onPointerDown);
      controls.dispose();
      for (const item of disposables) item.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, [model]);

  return (
    <div
      className="canvas-3d"
      ref={mountRef}
      role="img"
      aria-label={`3D fabric ${model.source === 'topology'
        ? 'topology'
        : 'preview'}: ${model.counts.routers} routers`}
    >
      {selected && <div className="canvas-3d-badge">router {selected}</div>}
      <div className="canvas-3d-hint">drag to orbit · scroll to zoom · click a router</div>
    </div>
  );
}
