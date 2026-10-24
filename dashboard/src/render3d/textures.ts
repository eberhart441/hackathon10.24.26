import * as THREE from 'three';
import type { PatternId } from '../scene/palette';

// Procedural tiles (no image assets). The map multiplies the material colour, so white = full
// state colour and dark ink = the pattern. One tile covers TILE metres of floor.
export const TILE_M = 0.25;

const cache = new Map<string, THREE.CanvasTexture>();

function make(key: string, size: number, draw: (g: CanvasRenderingContext2D, s: number) => void, repeat = 1 / TILE_M) {
  const hit = cache.get(key);
  if (hit) return hit;
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const g = c.getContext('2d')!;
  draw(g, size);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(repeat, repeat);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  cache.set(key, t);
  return t;
}

export function patternTexture(p: PatternId | 'idle'): THREE.CanvasTexture {
  return make(`pat-${p}`, 128, (g, s) => {
    g.fillStyle = '#ffffff';
    g.fillRect(0, 0, s, s);
    g.fillStyle = 'rgba(0,0,0,0.42)';
    g.strokeStyle = 'rgba(0,0,0,0.42)';
    if (p === 'hatch' || p === 'crosshatch') {
      g.lineWidth = p === 'hatch' ? s * 0.26 : s * 0.16;
      // Diagonals drawn three times so the tile wraps seamlessly.
      for (const o of [-s, 0, s]) {
        g.beginPath();
        g.moveTo(o, s);
        g.lineTo(o + s, 0);
        g.stroke();
        if (p === 'crosshatch') {
          g.beginPath();
          g.moveTo(o, 0);
          g.lineTo(o + s, s);
          g.stroke();
        }
      }
    } else if (p === 'dots') {
      g.fillStyle = '#b8b8b8';
      g.fillRect(0, 0, s, s);
      g.fillStyle = '#ffffff';
      g.beginPath();
      g.arc(s / 2, s / 2, s * 0.14, 0, Math.PI * 2);
      g.fill();
    } else if (p === 'idle') {
      g.fillStyle = '#e9e9e9';
      g.fillRect(0, 0, s, s);
      g.fillStyle = 'rgba(0,0,0,0.06)';
      g.fillRect(0, 0, s, 2);
      g.fillRect(0, 0, 2, s);
    }
  });
}

// Repeating "SIMULATED" watermark for simulated rooms (Kiro R9.9).
export function simulatedTexture(): THREE.CanvasTexture {
  return make(
    'sim',
    512,
    (g, s) => {
      g.clearRect(0, 0, s, s);
      g.translate(s / 2, s / 2);
      g.rotate(-Math.PI / 7);
      g.font = `700 ${s * 0.11}px "Atkinson Hyperlegible", system-ui, sans-serif`;
      g.fillStyle = 'rgba(255,255,255,0.20)';
      g.textAlign = 'center';
      g.textBaseline = 'middle';
      for (let y = -2; y <= 2; y++) g.fillText('SIMULATED', (y % 2) * s * 0.25, y * s * 0.3);
    },
    1 / 2.2,
  );
}

// Moving dashes along a link beam; offset is animated to show packet flow.
export function dashTexture(): THREE.CanvasTexture {
  return make(
    'dash',
    64,
    (g, s) => {
      g.clearRect(0, 0, s, s);
      g.fillStyle = '#ffffff';
      g.fillRect(0, 0, s * 0.55, s);
    },
    1,
  );
}

// Soft dark gradient laid at the foot of each wall: cheap contact shadow / ambient occlusion.
export function contactShadowTexture(): THREE.CanvasTexture {
  return make(
    'ao',
    64,
    (g, s) => {
      const grad = g.createLinearGradient(0, 0, 0, s);
      grad.addColorStop(0, 'rgba(0,0,0,0.55)');
      grad.addColorStop(1, 'rgba(0,0,0,0)');
      g.fillStyle = grad;
      g.fillRect(0, 0, s, s);
    },
    1,
  );
}
