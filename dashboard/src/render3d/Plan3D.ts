import * as THREE from 'three';
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { h, render } from 'preact';
import type { Floorplan, RoomDef, Vec2 } from '../types';
import type { CrewChip, RoomDescriptor, SceneModel } from '../scene/model';
import { bounds, doorViews, inradiusAt, wallSegments } from '../scene/geometry';
import { polygonArea } from '../floorplan/validate';
import { STATE_PATTERN } from '../scene/palette';
import { RoomLabel } from '../ui/RoomLabel';
import { contactShadowTexture, dashTexture, patternTexture, simulatedTexture } from './textures';

const WALL_H = 1.0; // dollhouse cut-away (Kiro R16.2)
const WALL_T = 0.12;
const IDLE_FLOOR = '#2A313B';
const STATUS_LED: Record<string, string> = {
  ok: '#4ADE80', // node health only; never used for a room state
  degraded: '#FFB020',
  recovering: '#FFB020',
  offline: '#111111',
  tx_dead: '#FF4D2E',
  unknown: '#5B6270',
};

// Plan coords (x, y) in metres -> world (x, height, -y).
const w = ([x, y]: Vec2, hgt = 0) => new THREE.Vector3(x, hgt, -y);

interface RoomObj {
  def: RoomDef;
  floor: THREE.Mesh<THREE.ShapeGeometry, THREE.MeshStandardMaterial>;
  rings: THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>[];
  ringR: number;
  label: CSS2DObject;
  labelEl: HTMLDivElement;
  state: string | null;
  greyed: boolean;
}

interface NodeObj {
  led: THREE.Mesh<THREE.SphereGeometry, THREE.MeshStandardMaterial>;
  bang: CSS2DObject;
}

interface LinkObj {
  tx: string;
  rx: string;
  beam: THREE.Mesh<THREE.CylinderGeometry, THREE.MeshBasicMaterial>;
  tex: THREE.Texture;
}

export interface Plan3DOptions {
  onRoomTap: (roomId: string) => void;
  onFallback: (reason: string) => void;
  reducedMotion: () => boolean;
}

export class Plan3D {
  private renderer: THREE.WebGLRenderer;
  private labels = new CSS2DRenderer();
  private scene = new THREE.Scene();
  private camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 200);
  private sun = new THREE.DirectionalLight('#fff6e8', 2.2);
  private group = new THREE.Group();
  private rooms = new Map<string, RoomObj>();
  private nodes = new Map<string, NodeObj>();
  private links: LinkObj[] = [];
  private chipObjs: CSS2DObject[] = [];
  private builtKey = '';
  private target = new THREE.Vector3();
  private yawStep = 0;
  private baseHalf = 5;
  private needsRender = true;
  private raf = 0;
  private lastFrame = 0;
  private frameCosts: number[] = [];
  private disposed = false;
  private plan: Floorplan | null = null;
  private floorId = '';
  private pointers = new Map<number, { x: number; y: number }>();
  private gesture: { dist: number; zoom: number; x: number; y: number; moved: boolean } | null = null;
  private ro: ResizeObserver;

  constructor(
    private host: HTMLElement,
    private opts: Plan3DOptions,
  ) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2)); // Kiro R22.2
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    host.appendChild(this.renderer.domElement);
    this.labels.domElement.className = 'plan3d-labels';
    host.appendChild(this.labels.domElement);

    this.renderer.domElement.addEventListener('webglcontextlost', (e) => {
      e.preventDefault();
      this.opts.onFallback('The 3D view lost its graphics context.');
    });

    this.scene.background = new THREE.Color('#0B0F14');
    this.scene.add(new THREE.HemisphereLight('#dfe7f2', '#1a1f27', 1.1));
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(1024, 1024);
    this.sun.shadow.bias = -0.0005;
    this.sun.shadow.radius = 4;
    this.scene.add(this.sun, this.sun.target, this.group);

    const el = this.renderer.domElement;
    el.style.touchAction = 'none';
    el.addEventListener('pointerdown', this.onPointerDown);
    el.addEventListener('pointermove', this.onPointerMove);
    el.addEventListener('pointerup', this.onPointerUp);
    el.addEventListener('pointercancel', this.onPointerUp);
    el.addEventListener('wheel', this.onWheel, { passive: false });
    document.addEventListener('visibilitychange', this.onVisibility);

    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this.resize();
    this.loop();
  }

  setData(plan: Floorplan, model: SceneModel, floorId: string) {
    this.plan = plan;
    const key = `${floorId}|${JSON.stringify(plan)}`;
    if (key !== this.builtKey) {
      this.floorId = floorId;
      this.build(plan, floorId);
      this.builtKey = key;
      this.fitTo(null);
    }
    this.update(model);
  }

  rotate() {
    this.yawStep = (this.yawStep + 1) % 4;
    this.fitTo(null);
  }

  // Frame the given rooms (fire-mode entry frames every flagged room, Kiro R13.3).
  frameRooms(roomIds: string[] | null) {
    this.fitTo(roomIds && roomIds.length ? roomIds : null, 600);
  }

  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    document.removeEventListener('visibilitychange', this.onVisibility);
    this.clearGroup();
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.labels.domElement.remove();
  }

  // ---------- build ----------

  private clearGroup() {
    for (const r of this.rooms.values()) render(null, r.labelEl);
    this.group.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.geometry) m.geometry.dispose();
      const mat = m.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
      else mat?.dispose();
    });
    this.group.clear();
    this.rooms.clear();
    this.nodes.clear();
    this.links = [];
    this.chipObjs = [];
  }

  private build(plan: Floorplan, floorId: string) {
    this.clearGroup();
    const floor = plan.floors.find((f) => f.id === floorId) ?? plan.floors[0];
    const b = bounds(floor.rooms.map((r) => r.polygon));
    const cx = (b.minX + b.maxX) / 2;
    const cy = (b.minY + b.maxY) / 2;
    const span = Math.max(b.maxX - b.minX, b.maxY - b.minY);

    // Ground slab around the building.
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(span + 8, span + 8),
      new THREE.MeshStandardMaterial({ color: '#10151C', roughness: 1 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.copy(w([cx, cy], -0.02));
    ground.receiveShadow = true;
    this.group.add(ground);
    const grid = new THREE.GridHelper(Math.ceil(span + 8), Math.ceil(span + 8), '#1D2530', '#161C24');
    grid.position.copy(w([cx, cy], -0.015));
    this.group.add(grid);

    for (const def of floor.rooms) this.buildRoom(def);
    if (floor.walls?.length) this.buildDxfWalls(floor.walls);
    else this.buildWalls(floor.rooms);
    for (const def of floor.rooms) this.buildDoorsAndFurniture(def);
    this.buildNodesAndLinks(plan, floor.rooms);

    // Shadow camera covers the floor.
    const s = this.sun.shadow.camera as THREE.OrthographicCamera;
    s.left = -span;
    s.right = span;
    s.top = span;
    s.bottom = -span;
    s.near = 0.5;
    s.far = 60;
    s.updateProjectionMatrix();
    this.sun.target.position.copy(w([cx, cy]));
    this.sun.position.copy(w([cx - 6, cy - 8], 14));
    this.needsRender = true;
  }

  private buildRoom(def: RoomDef) {
    const shape = new THREE.Shape(def.polygon.map(([x, y]) => new THREE.Vector2(x, y)));
    const geo = new THREE.ShapeGeometry(shape);
    const mat = new THREE.MeshStandardMaterial({ color: IDLE_FLOOR, map: patternTexture('idle'), roughness: 0.92, metalness: 0, transparent: true });
    const floor = new THREE.Mesh(geo, mat);
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = 0.002;
    floor.receiveShadow = true;
    floor.userData.roomId = def.id;
    this.group.add(floor);

    if (def.simulated) {
      const sim = new THREE.Mesh(
        new THREE.ShapeGeometry(shape),
        new THREE.MeshBasicMaterial({ map: simulatedTexture(), transparent: true, depthWrite: false }),
      );
      sim.rotation.x = -Math.PI / 2;
      sim.position.y = 0.006;
      sim.renderOrder = 2;
      this.group.add(sim);
    }

    const c = centroidOf(def.polygon);
    const ringR = Math.max(0.3, inradiusAt(c, def.polygon) - 0.12);
    const rings = [0, 1, 2].map(() => {
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(0.9, 1, 64),
        new THREE.MeshBasicMaterial({ color: '#FFD3C7', transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }),
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.copy(w(c, 0.012));
      ring.visible = false;
      ring.renderOrder = 3;
      this.group.add(ring);
      return ring;
    });

    const labelEl = document.createElement('div');
    labelEl.className = 'label-pin3d';
    const label = new CSS2DObject(labelEl);
    label.position.copy(w(c, WALL_H + 0.3));
    this.group.add(label);

    this.rooms.set(def.id, { def, floor, rings, ringR, label, labelEl, state: null, greyed: false });
  }

  // Walls-only DXF: extrude the wall mass itself (largest loop outside, the others as holes), so wall
  // thickness and door openings are the drawing's.
  private buildDxfWalls(loops: Vec2[][]) {
    const [outer, ...holes] = [...loops].sort((a, b) => Math.abs(polygonArea(b)) - Math.abs(polygonArea(a)));
    const v = (l: Vec2[]) => l.map(([x, y]) => new THREE.Vector2(x, y));
    const shape = new THREE.Shape(v(outer));
    shape.holes = holes.map((l) => new THREE.Path(v(l)));
    // Shape (x, y) extruded along +z; rotating -90° about x gives world (x, height, -y), as w() does.
    const geo = new THREE.ExtrudeGeometry(shape, { depth: WALL_H, bevelEnabled: false });
    geo.rotateX(-Math.PI / 2);
    const wallMesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: '#E4DED4', roughness: 0.88 }));
    wallMesh.castShadow = true;
    wallMesh.receiveShadow = true;
    const cap = new THREE.ShapeGeometry(shape);
    cap.rotateX(-Math.PI / 2);
    cap.translate(0, WALL_H + 0.004, 0);
    const capMesh = new THREE.Mesh(cap, new THREE.MeshStandardMaterial({ color: '#3B3F46', roughness: 0.6 }));
    this.group.add(wallMesh, capMesh);
  }

  private buildWalls(rooms: RoomDef[]) {
    const segs = wallSegments(rooms);
    const walls: THREE.BufferGeometry[] = [];
    const caps: THREE.BufferGeometry[] = [];
    const ao: THREE.BufferGeometry[] = [];
    for (const s of segs) {
      const dx = s.b[0] - s.a[0];
      const dy = s.b[1] - s.a[1];
      const len = Math.hypot(dx, dy);
      if (len < 0.01) continue;
      const mid: Vec2 = [(s.a[0] + s.b[0]) / 2, (s.a[1] + s.b[1]) / 2];
      const m = new THREE.Matrix4().compose(
        w(mid, WALL_H / 2),
        new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.atan2(dy, dx)),
        new THREE.Vector3(1, 1, 1),
      );
      walls.push(new THREE.BoxGeometry(len + WALL_T, WALL_H, WALL_T).applyMatrix4(m));
      const cm = m.clone().multiply(new THREE.Matrix4().makeTranslation(0, WALL_H / 2 + 0.012, 0));
      caps.push(new THREE.BoxGeometry(len + WALL_T + 0.01, 0.024, WALL_T + 0.02).applyMatrix4(cm));
      // Contact shadow strips on both sides of the wall.
      for (const side of [1, -1]) {
        const g = new THREE.PlaneGeometry(len + WALL_T, 0.35);
        g.rotateX(-Math.PI / 2);
        g.rotateY(side === 1 ? 0 : Math.PI);
        g.translate(0, 0.004, side * (WALL_T / 2 + 0.175));
        ao.push(g.applyMatrix4(new THREE.Matrix4().compose(w(mid, 0), new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.atan2(dy, dx)), new THREE.Vector3(1, 1, 1))));
      }
    }
    if (!walls.length) return;
    const wallMesh = new THREE.Mesh(mergeGeometries(walls), new THREE.MeshStandardMaterial({ color: '#E4DED4', roughness: 0.88 }));
    wallMesh.castShadow = true;
    wallMesh.receiveShadow = true;
    const capMesh = new THREE.Mesh(mergeGeometries(caps), new THREE.MeshStandardMaterial({ color: '#3B3F46', roughness: 0.6 }));
    const aoMesh = new THREE.Mesh(
      mergeGeometries(ao),
      new THREE.MeshBasicMaterial({ map: contactShadowTexture(), transparent: true, depthWrite: false }),
    );
    aoMesh.renderOrder = 1;
    this.group.add(wallMesh, capMesh, aoMesh);
  }

  private buildDoorsAndFurniture(def: RoomDef) {
    const leafMat = new THREE.MeshStandardMaterial({ color: '#8C6A4B', roughness: 0.7 });
    const arcMat = new THREE.MeshBasicMaterial({ color: '#9AA3AE', transparent: true, opacity: 0.7, side: THREE.DoubleSide });
    for (const d of doorViews(def)) {
      const along = Math.atan2(d.latch[1] - d.hinge[1], d.latch[0] - d.hinge[0]);
      const inwardAng = Math.atan2(d.inward[1], d.inward[0]);
      // Leaf opened 70° from the wall line toward the side it swings into.
      let delta = inwardAng - along;
      delta = Math.atan2(Math.sin(delta), Math.cos(delta));
      const openAng = along + Math.sign(delta) * THREE.MathUtils.degToRad(70);
      const leaf = new THREE.Mesh(new THREE.BoxGeometry(d.width, WALL_H * 0.92, 0.04), leafMat);
      leaf.geometry.translate(d.width / 2, 0, 0);
      leaf.position.copy(w(d.hinge, (WALL_H * 0.92) / 2));
      leaf.rotation.y = openAng; // plan angle a -> world rotation.y = a (because world z = -y)
      leaf.castShadow = true;
      this.group.add(leaf);

      const start = Math.min(along, along + delta);
      const arc = new THREE.Mesh(new THREE.RingGeometry(d.width - 0.02, d.width, 32, 1, start, Math.abs(delta)), arcMat);
      arc.rotation.x = -Math.PI / 2;
      arc.position.copy(w(d.hinge, 0.008));
      this.group.add(arc);
    }
    const furnMat = new THREE.MeshStandardMaterial({ color: '#5E6573', roughness: 0.8 });
    for (const f of def.furniture) {
      const hgt = f.h ?? 0.75;
      const box = new THREE.Mesh(new THREE.BoxGeometry(f.w, hgt, f.d), furnMat);
      box.position.copy(w([f.x + f.w / 2, f.y + f.d / 2], hgt / 2));
      box.castShadow = true;
      box.receiveShadow = true;
      this.group.add(box);
    }
  }

  private buildNodesAndLinks(plan: Floorplan, rooms: RoomDef[]) {
    const ids = new Set(rooms.map((r) => r.id));
    const nodes = plan.nodes.filter((n) => ids.has(n.room));
    const bodyMat = new THREE.MeshStandardMaterial({ color: '#C9CED6', roughness: 0.5 });
    for (const n of nodes) {
      const body = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.22, 0.16), bodyMat);
      body.position.copy(w(n.pos, n.h));
      body.castShadow = true;
      const led = new THREE.Mesh(
        new THREE.SphereGeometry(0.045, 16, 12),
        new THREE.MeshStandardMaterial({ color: STATUS_LED.unknown, emissive: STATUS_LED.unknown, emissiveIntensity: 1.2 }),
      );
      led.position.copy(w(n.pos, n.h + 0.16));
      const bangEl = document.createElement('div');
      bangEl.className = 'node-bang';
      bangEl.textContent = '!';
      bangEl.setAttribute('aria-label', `${n.id} fault`);
      const bang = new CSS2DObject(bangEl);
      bang.position.copy(w(n.pos, n.h + 0.45));
      bang.visible = false;
      this.group.add(body, led, bang);
      this.nodes.set(n.id, { led, bang });
    }
    const byId = new Map(nodes.map((n) => [n.id, n]));
    for (const l of plan.links) {
      const tx = byId.get(l.tx);
      const rx = byId.get(l.rx);
      if (!tx || !rx) continue;
      const a = w(tx.pos, tx.h);
      const b = w(rx.pos, rx.h);
      const len = a.distanceTo(b);
      const tex = dashTexture().clone();
      tex.needsUpdate = true;
      tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
      tex.repeat.set(1, len / 0.18);
      const beam = new THREE.Mesh(
        new THREE.CylinderGeometry(0.018, 0.018, len, 8, 1, true),
        new THREE.MeshBasicMaterial({ color: '#7CC4FF', map: tex, transparent: true, opacity: 0.9, depthWrite: false }),
      );
      beam.position.copy(a.clone().add(b).multiplyScalar(0.5));
      beam.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
      this.group.add(beam);
      this.links.push({ tx: l.tx, rx: l.rx, beam, tex });
    }
  }

  // ---------- per-message update ----------

  private update(model: SceneModel) {
    for (const r of model.rooms) {
      const obj = this.rooms.get(r.id);
      if (!obj) continue;
      this.updateRoom(obj, r);
    }
    for (const [id, n] of this.nodes) {
      const st = model.nodes[id]?.status ?? 'unknown';
      const c = STATUS_LED[st] ?? STATUS_LED.unknown;
      n.led.material.color.set(c);
      n.led.material.emissive.set(c);
      n.bang.visible = st === 'offline' || st === 'tx_dead';
    }
    for (const l of this.links) {
      const txSt = model.nodes[l.tx]?.status;
      const rxSt = model.nodes[l.rx]?.status;
      l.beam.visible = rxSt !== 'offline';
      l.beam.material.color.set(txSt === 'tx_dead' ? '#FF4D2E' : rxSt === 'degraded' ? '#FFB020' : '#7CC4FF');
      l.beam.userData.dead = txSt === 'tx_dead';
    }
    this.updateChips(model.crewChips);
    this.needsRender = true;
  }

  private updateRoom(obj: RoomObj, r: RoomDescriptor) {
    const o = r.occupancy;
    const mat = obj.floor.material;
    const pattern = o ? STATE_PATTERN[o.state] : null;
    mat.map = patternTexture(pattern && pattern !== 'solid' ? pattern : o ? 'solid' : 'idle');
    mat.color.set(o ? o.fill : IDLE_FLOOR);
    mat.opacity = o?.searched ? 0.35 : 1; // Kiro R11.3
    mat.emissive.set(o && !r.greyed ? o.fill : '#000000');
    mat.emissiveIntensity = o && !r.greyed ? 0.12 : 0;
    mat.needsUpdate = true;
    obj.state = o?.state ?? null;
    obj.greyed = r.greyed;
    render(h(RoomLabel, { room: r, onTap: this.opts.onRoomTap, compact: this.host.clientWidth < 420 }), obj.labelEl);
  }

  private updateChips(chips: CrewChip[]) {
    for (const c of this.chipObjs) {
      this.group.remove(c);
      c.element.remove();
    }
    this.chipObjs = [];
    for (const chip of chips) {
      const pts = chip.rooms.map((id) => this.rooms.get(id)).filter(Boolean) as RoomObj[];
      if (!pts.length) continue; // chips for other floors are listed by the UI instead
      const c = pts.map((p) => centroidOf(p.def.polygon));
      const mid: Vec2 = [c.reduce((s, p) => s + p[0], 0) / c.length, c.reduce((s, p) => s + p[1], 0) / c.length];
      // CSS2DRenderer owns the pin's transform, so the visual offset goes on an inner element.
      const el = document.createElement('div');
      el.className = 'crew-chip-pin';
      const inner = document.createElement('span');
      inner.className = 'crew-chip';
      inner.textContent = chip.text;
      el.appendChild(inner);
      const obj = new CSS2DObject(el);
      obj.position.copy(w(mid, 0.05)); // at floor level so it sits below the room labels
      this.group.add(obj);
      this.chipObjs.push(obj);
    }
  }

  // ---------- camera ----------

  private viewDir() {
    const yaw = THREE.MathUtils.degToRad(45 + this.yawStep * 90);
    const elev = THREE.MathUtils.degToRad(38);
    // Looking from the south-west by default (plan +y is world -z).
    return new THREE.Vector3(-Math.sin(yaw) * Math.cos(elev), Math.sin(elev), Math.cos(yaw) * Math.cos(elev));
  }

  private fitTo(roomIds: string[] | null, durationMs = 0) {
    if (!this.plan) return;
    const floor = this.plan.floors.find((f) => f.id === this.floorId) ?? this.plan.floors[0];
    const polys = (roomIds ? floor.rooms.filter((r) => roomIds.includes(r.id)) : floor.rooms).map((r) => r.polygon);
    const usable = polys.length ? polys : floor.rooms.map((r) => r.polygon);
    const b = bounds(usable);
    const center = w([(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2], WALL_H / 2);

    // Extent of the box in camera space decides the zoom.
    const dir = this.viewDir();
    const tmpCam = new THREE.OrthographicCamera();
    tmpCam.position.copy(center.clone().add(dir.clone().multiplyScalar(50)));
    tmpCam.lookAt(center);
    tmpCam.updateMatrixWorld();
    const inv = tmpCam.matrixWorldInverse;
    let maxX = 0;
    let maxY = 0;
    for (const [x, y] of [[b.minX, b.minY], [b.maxX, b.minY], [b.maxX, b.maxY], [b.minX, b.maxY]] as Vec2[]) {
      for (const hgt of [0, WALL_H + 0.6]) {
        const p = w([x, y], hgt).applyMatrix4(inv);
        maxX = Math.max(maxX, Math.abs(p.x));
        maxY = Math.max(maxY, Math.abs(p.y));
      }
    }
    const aspect = this.aspect();
    const half = Math.max(maxY, maxX / aspect) * 1.12 + 0.4;

    const from = { target: this.target.clone(), half: this.baseHalf / this.camera.zoom };
    const to = { target: center, half };
    if (!durationMs || this.opts.reducedMotion()) {
      this.applyCamera(to.target, to.half);
      return;
    }
    const t0 = performance.now();
    const step = () => {
      if (this.disposed) return;
      const k = Math.min(1, (performance.now() - t0) / durationMs);
      const e = 1 - (1 - k) ** 3;
      this.applyCamera(from.target.clone().lerp(to.target, e), from.half + (to.half - from.half) * e);
      if (k < 1) requestAnimationFrame(step);
    };
    step();
  }

  private applyCamera(target: THREE.Vector3, half: number) {
    this.target.copy(target);
    this.baseHalf = half;
    this.camera.zoom = 1;
    this.updateFrustum();
    this.camera.position.copy(target.clone().add(this.viewDir().multiplyScalar(50)));
    this.camera.lookAt(target);
    this.needsRender = true;
  }

  private aspect() {
    return Math.max(0.1, (this.host.clientWidth || 1) / (this.host.clientHeight || 1));
  }

  private updateFrustum() {
    const a = this.aspect();
    this.camera.left = -this.baseHalf * a;
    this.camera.right = this.baseHalf * a;
    this.camera.top = this.baseHalf;
    this.camera.bottom = -this.baseHalf;
    this.camera.updateProjectionMatrix();
  }

  private resize() {
    const wPx = this.host.clientWidth || 1;
    const hPx = this.host.clientHeight || 1;
    this.renderer.setSize(wPx, hPx);
    this.labels.setSize(wPx, hPx);
    this.updateFrustum();
    this.needsRender = true;
  }

  // ---------- gestures: drag pans, pinch / wheel zooms, tap selects ----------

  private onPointerDown = (e: PointerEvent) => {
    this.renderer.domElement.setPointerCapture(e.pointerId);
    this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    this.gesture = { dist: this.pinchDist(), zoom: this.camera.zoom, x: e.clientX, y: e.clientY, moved: false };
  };

  private onPointerMove = (e: PointerEvent) => {
    const prev = this.pointers.get(e.pointerId);
    if (!prev || !this.gesture) return;
    this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (Math.hypot(e.clientX - this.gesture.x, e.clientY - this.gesture.y) > 8) this.gesture.moved = true;
    if (this.pointers.size >= 2) {
      const d = this.pinchDist();
      if (this.gesture.dist > 0) this.setZoom(this.gesture.zoom * (d / this.gesture.dist));
    } else {
      const worldPerPx = (2 * this.baseHalf) / this.camera.zoom / (this.host.clientHeight || 1);
      const right = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 0);
      const up = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 1);
      const delta = right.multiplyScalar(-(e.clientX - prev.x) * worldPerPx).add(up.multiplyScalar((e.clientY - prev.y) * worldPerPx));
      this.target.add(delta);
      this.camera.position.add(delta);
      this.needsRender = true;
    }
  };

  private onPointerUp = (e: PointerEvent) => {
    const g = this.gesture;
    this.pointers.delete(e.pointerId);
    if (this.pointers.size === 0) {
      if (g && !g.moved) this.pick(e);
      this.gesture = null;
    } else {
      this.gesture = { dist: this.pinchDist(), zoom: this.camera.zoom, x: e.clientX, y: e.clientY, moved: true };
    }
  };

  private onWheel = (e: WheelEvent) => {
    e.preventDefault();
    this.setZoom(this.camera.zoom * Math.exp(-e.deltaY * 0.0015));
  };

  private pinchDist() {
    const p = [...this.pointers.values()];
    return p.length >= 2 ? Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y) : 0;
  }

  private setZoom(z: number) {
    this.camera.zoom = THREE.MathUtils.clamp(z, 0.6, 4);
    this.camera.updateProjectionMatrix();
    this.needsRender = true;
  }

  private pick(e: PointerEvent) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    const hits = ray.intersectObjects([...this.rooms.values()].map((r) => r.floor));
    const id = hits[0]?.object.userData.roomId;
    if (id) this.opts.onRoomTap(id);
  }

  // ---------- render loop: on demand, continuous only while animating ----------

  private onVisibility = () => {
    if (document.visibilityState === 'visible') {
      this.needsRender = true;
      this.loop();
    } else cancelAnimationFrame(this.raf); // Kiro R22.3
  };

  // 0 = nothing moves, 1 = only link beams move, 2 = a room effect (motion rings, glow) moves.
  private animationLevel(): 0 | 1 | 2 {
    if (this.opts.reducedMotion()) return 0;
    for (const r of this.rooms.values()) if (!r.greyed && (r.state === 'MOTION' || r.state === 'POSSIBLE')) return 2;
    return this.links.some((l) => l.beam.visible && !l.beam.userData.dead) ? 1 : 0;
  }

  private loop = () => {
    if (this.disposed || document.visibilityState === 'hidden') return;
    this.raf = requestAnimationFrame(this.loop);
    const now = performance.now();
    const level = this.animationLevel();
    if (!level && !this.needsRender) return;
    // Cap the frame rate: beams only need ~10 fps, room effects ~30 fps. Saves battery and keeps
    // the page responsive on weak GPUs. A data or camera change always renders at once.
    const minGap = level === 2 ? 33 : 100;
    if (!this.needsRender && now - this.lastFrame < minGap) return;
    this.lastFrame = now;
    const t = performance.now();
    this.animate(now, level > 0);
    this.renderer.render(this.scene, this.camera);
    this.labels.render(this.scene, this.camera);
    this.needsRender = false;
    this.watchCost(performance.now() - t);
  };

  // Always on: if drawing a frame costs more than 25 ms (median of the last 30 frames), this
  // device cannot keep the page responsive in 3D, so fall back to 2D (Kiro R16.4).
  private watchCost(ms: number) {
    this.frameCosts.push(ms);
    if (this.frameCosts.length < 30) return;
    const sorted = [...this.frameCosts].sort((a, b) => a - b);
    this.frameCosts = [];
    if (sorted[15] > 25) this.opts.onFallback('The 3D view was too slow on this device.');
  }

  private animate(now: number, on: boolean) {
    const t = now / 1000;
    for (const r of this.rooms.values()) {
      const motion = on && r.state === 'MOTION' && !r.greyed;
      r.rings.forEach((ring, i) => {
        ring.visible = motion;
        if (!motion) return;
        const k = (t / 1.8 + i / 3) % 1; // rings from the room centre only, never a person's spot
        ring.scale.setScalar(Math.max(0.01, k * r.ringR));
        ring.material.opacity = 0.55 * (1 - k);
      });
      const mat = r.floor.material;
      if (on && r.state === 'POSSIBLE' && !r.greyed) mat.emissiveIntensity = 0.1 + 0.12 * (0.5 + 0.5 * Math.sin((t * 2 * Math.PI) / 3));
    }
    for (const l of this.links) {
      if (!l.beam.visible || l.beam.userData.dead || !on) continue;
      l.tex.offset.y = -t * 1.2;
    }
  }
}

function centroidOf(poly: Vec2[]): Vec2 {
  let a = 0;
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i];
    const [x2, y2] = poly[(i + 1) % poly.length];
    const f = x1 * y2 - x2 * y1;
    a += f;
    cx += (x1 + x2) * f;
    cy += (y1 + y2) * f;
  }
  return Math.abs(a) < 1e-9 ? poly[0] : [cx / (3 * a), cy / (3 * a)];
}
