import type { HealthMessage, RecordingMessage } from '../types';

export const DISCLAIMER = 'Decision support only — does not replace a full search';

interface Props {
  paired: boolean;
  recording: RecordingMessage | null;
  health: HealthMessage | null;
  alarm: boolean;
  simulated: boolean;
  simulatedTrigger: boolean;
  onHealth: () => void;
}

// Disclaimer on every screen; recording + health once paired (Kiro R10).
export function Header({ paired, recording, health, alarm, simulated, simulatedTrigger, onHealth }: Props) {
  const faults = health ? health.nodes.filter((n) => n.status !== 'ok').length + health.tag_faults.length : 0;
  return (
    <header class={`hdr${alarm ? ' alarm' : ''}`}>
      {paired ? (
        <div class="hdr-row">
          <div class={`rec${recording?.indicator.startsWith('Recording') ? ' on' : ''}`} role="status">
            <span class="dot" aria-hidden="true" />
            {recording?.indicator ?? 'Waiting for hub…'}
          </div>
          <button type="button" class={`health-chip${faults ? ' fault' : ''}`} onClick={onHealth} aria-label={`Sensor health: ${health?.summary ?? 'unknown'}. Show details`}>
            {health?.summary ?? 'Health unknown'} <span aria-hidden="true">▾</span>
          </button>
        </div>
      ) : null}
      <p class="disclaimer">{DISCLAIMER}</p>
      {simulated || simulatedTrigger || recording?.fault ? (
        <div class="badges">
          {simulated ? <span class="badge sim">SIMULATED DATA</span> : null}
          {simulatedTrigger ? <span class="badge sim">SIMULATED TRIGGER</span> : null}
          {recording?.fault ? <span class="badge fault">{recording.fault}</span> : null}
        </div>
      ) : null}
    </header>
  );
}
