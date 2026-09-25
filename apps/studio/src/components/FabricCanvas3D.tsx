import { useEffect, useRef, useState, type ReactElement } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import type { DesignView } from '../types';
import { deriveFabric } from '../fabricLayout';

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return value || fallback;
}

/**
 * 3D structural fabric view (Three.js). It renders only declared intent
 * (routers, mesh links, attachments) from the DesignView — never a
 * fabricated overlay. Orbit to inspect; click a router to identify it.
 */
export default function FabricCanvas3D({
  design,
}: {
  design: DesignView;
}): ReactElement {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const layout = deriveFabric(design);
    const { routerCount, cols, rows, links, concentration, hbm, edge } = layout;
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

    const pos = (i: number): THREE.Vector3 => {
      const c = i % cols;
      const r = Math.floor(i / cols);
      return new THREE.Vector3(
        (c - (cols - 1) / 2) * SP, 0, (r - (rows - 1) / 2) * SP);
    };

    // links (one LineSegments geometry)
    const linkPositions = new Float32Array(links.length * 6);
    links.forEach(([a, b], k) => {
      const pa = pos(a);
      const pb = pos(b);
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
    const routers = new THREE.InstancedMesh(routerGeom, routerMat, routerCount);
    const dummy = new THREE.Object3D();
    const routerCoords: [number, number][] = [];
    for (let i = 0; i < routerCount; i++) {
      const p = pos(i);
      dummy.position.set(p.x, 0, p.z);
      dummy.updateMatrix();
      routers.setMatrixAt(i, dummy.matrix);
      routerCoords.push([Math.floor(i / cols), i % cols]);
    }
    routers.instanceMatrix.needsUpdate = true;
    scene.add(routers);

    // attachments (compute tiles above each router)
    const tileCount = routerCount;
    const tileGeom = track(new THREE.BoxGeometry(2.2, 1.4, 2.2));
    const tileMat = track(new THREE.MeshStandardMaterial({
      color: ok, metalness: 0.1, roughness: 0.6 }));
    const tiles = new THREE.InstancedMesh(tileGeom, tileMat, tileCount);
    for (let i = 0; i < tileCount; i++) {
      const p = pos(i);
      const attached = Math.min(concentration,
                                Math.max(0, layout.compute - i * concentration));
      dummy.position.set(p.x, 3.6, p.z);
      dummy.scale.set(1, Math.max(0.4, attached / Math.max(1, concentration)), 1);
      dummy.updateMatrix();
      tiles.setMatrixAt(i, dummy.matrix);
    }
    dummy.scale.set(1, 1, 1);
    tiles.instanceMatrix.needsUpdate = true;
    scene.add(tiles);

    // HBM blocks on the north/south edges
    if (hbm > 0) {
      const hbmGeom = track(new THREE.BoxGeometry(3.2, 2, 3.2));
      const hbmMat = track(new THREE.MeshStandardMaterial({
        color: warn, metalness: 0.2, roughness: 0.5 }));
      const hbmMesh = new THREE.InstancedMesh(hbmGeom, hbmMat, hbm);
      const zNorth = -((rows - 1) / 2) * SP - 9;
      const zSouth = ((rows - 1) / 2) * SP + 9;
      for (let i = 0; i < hbm; i++) {
        const north = i % 2 === 0;
        const slot = Math.floor(i / 2);
        const slots = Math.max(1, Math.ceil(hbm / 2));
        const x = ((slot + 0.5) / slots - 0.5) * (cols - 1) * SP;
        dummy.position.set(x, 0, north ? zNorth : zSouth);
        dummy.updateMatrix();
        hbmMesh.setMatrixAt(i, dummy.matrix);
      }
      hbmMesh.instanceMatrix.needsUpdate = true;
      scene.add(hbmMesh);
    }

    // edge (NIC/peripheral) blocks on the west edge
    if (edge > 0) {
      const edgeGeom = track(new THREE.BoxGeometry(2.4, 2, 2.4));
      const edgeMat = track(new THREE.MeshStandardMaterial({
        color: accent, metalness: 0.2, roughness: 0.6 }));
      const edgeMesh = new THREE.InstancedMesh(edgeGeom, edgeMat, edge);
      const xWest = -((cols - 1) / 2) * SP - 9;
      for (let i = 0; i < edge; i++) {
        const z = ((i + 0.5) / edge - 0.5) * (rows - 1) * SP;
        dummy.position.set(xWest, 0, z);
        dummy.updateMatrix();
        edgeMesh.setMatrixAt(i, dummy.matrix);
      }
      edgeMesh.instanceMatrix.needsUpdate = true;
      scene.add(edgeMesh);
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
        const [r, c] = routerCoords[hit.instanceId];
        setSelected(`R${r},${c}`);
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
  }, [design]);

  return (
    <div
      className="canvas-3d"
      ref={mountRef}
      role="img"
      aria-label={`3D fabric topology: ${deriveFabric(design).routerCount} routers`}
    >
      {selected && <div className="canvas-3d-badge">router {selected}</div>}
      <div className="canvas-3d-hint">drag to orbit · scroll to zoom · click a router</div>
    </div>
  );
}
