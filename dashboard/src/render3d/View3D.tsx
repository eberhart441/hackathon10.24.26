import { useEffect, useRef } from 'preact/hooks';
import type { Floorplan } from '../types';
import type { SceneModel } from '../scene/model';
import { Plan3D } from './Plan3D';

interface Props {
  plan: Floorplan;
  model: SceneModel;
  floorId: string;
  onRoomTap: (roomId: string) => void;
  onFallback: (reason: string) => void;
  frameRequest: { seq: number; rooms: string[] | null };
  rotateSeq: number;
  reducedMotion: boolean;
}

// Probed once: every getContext call creates a WebGL context, and browsers cap how many live.
let webgl: boolean | null = null;
export function webglAvailable(): boolean {
  if (webgl !== null) return webgl;
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl2') || c.getContext('webgl');
    webgl = !!gl;
    (gl as WebGLRenderingContext | null)?.getExtension('WEBGL_lose_context')?.loseContext();
  } catch {
    webgl = false;
  }
  return webgl;
}

export function View3D(p: Props) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<Plan3D | null>(null);
  const latest = useRef(p);
  latest.current = p;

  useEffect(() => {
    let v: Plan3D;
    try {
      v = new Plan3D(host.current!, {
        onRoomTap: (id) => latest.current.onRoomTap(id),
        onFallback: (why) => latest.current.onFallback(why),
        reducedMotion: () => latest.current.reducedMotion,
      });
    } catch {
      p.onFallback('This device cannot show the 3D view.');
      return;
    }
    view.current = v;
    return () => {
      v.dispose();
      view.current = null;
    };
  }, []);

  useEffect(() => {
    view.current?.setData(p.plan, p.model, p.floorId);
  }, [p.plan, p.model, p.floorId]);

  useEffect(() => {
    if (p.frameRequest.seq) view.current?.frameRooms(p.frameRequest.rooms);
  }, [p.frameRequest.seq]);

  useEffect(() => {
    if (p.rotateSeq) view.current?.rotate();
  }, [p.rotateSeq]);

  return <div class="plan3d" ref={host} />;
}
