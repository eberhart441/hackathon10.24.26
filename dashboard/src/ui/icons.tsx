import type { RoomStateCode } from '../types';

// Team-drawn glyphs. No person figures (Kiro R16.5): POSSIBLE uses a "motion stopped" pause mark.
export function StateIcon({ state, size = 18 }: { state: RoomStateCode; size?: number }) {
  const common = { width: size, height: size, viewBox: '0 0 24 24', 'aria-hidden': true, fill: 'none', stroke: 'currentColor', 'stroke-width': 2.4, 'stroke-linecap': 'round' as const };
  switch (state) {
    case 'MOTION':
      return (
        <svg {...common}>
          <path d="M2 12c2.5-6 5-6 7.5 0s5 6 7.5 0 3.5-4 5-2" />
          <path d="M5 4.5a10 10 0 0 0 0 15M19 4.5a10 10 0 0 1 0 15" stroke-width="1.6" />
        </svg>
      );
    case 'POSSIBLE':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9.5" />
          <path d="M9.5 8v8M14.5 8v8" />
        </svg>
      );
    case 'UNKNOWN':
      return (
        <svg {...common}>
          <path d="M8.8 8.6a3.4 3.4 0 1 1 4.9 3.1c-1 .5-1.7 1.3-1.7 2.4v.6" />
          <circle cx="12" cy="18.6" r="0.6" fill="currentColor" />
        </svg>
      );
    case 'NO_DETECTION':
      return (
        <svg {...common}>
          <path d="M5 12h14" />
        </svg>
      );
  }
}

export function CrewIcon({ hollow, size = 22 }: { hollow: boolean; size?: number }) {
  // Upright chevron pin in the crew palette only (white + near-black).
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M12 2 20 9v13l-8-5-8 5V9z"
        fill={hollow ? 'none' : '#FFFFFF'}
        stroke={hollow ? '#FFFFFF' : '#111111'}
        stroke-width="2"
        stroke-linejoin="round"
        stroke-dasharray={hollow ? '3 2' : undefined}
      />
    </svg>
  );
}
