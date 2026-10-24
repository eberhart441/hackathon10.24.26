import { useEffect, useState } from 'preact/hooks';
import { api } from '../api';
import { Sheet } from './Sheets';

interface Props {
  alarm: boolean;
  idle: boolean;
  onTriggered: (simulated: boolean) => void;
  onEnded: () => void;
}

// Laptop-only controls. Never rendered on the phone, and the hub rejects them from it too
// (Kiro R5).
export function LaptopBar({ alarm, idle, onTriggered, onEnded }: Props) {
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [pairing, setPairing] = useState<{ code: string; until: number } | null>(null);
  const [now, setNow] = useState(Date.now());
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!pairing) return;
    const t = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(t);
  }, [pairing]);

  const left = pairing ? Math.max(0, Math.ceil((pairing.until - now) / 1000)) : 0;

  const run = async (fn: () => Promise<void>) => {
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  return (
    <div class="laptop-bar" aria-label="Presenter controls">
      {idle ? (
        <button
          type="button"
          class="btn-alarm"
          onClick={() =>
            run(async () => {
              const r = await api.triggerAlarm();
              onTriggered(r.simulated);
            })
          }
        >
          Trigger alarm (demo)
        </button>
      ) : null}
      {alarm ? (
        <button type="button" class="btn-secondary" onClick={() => setConfirmEnd(true)}>
          End incident…
        </button>
      ) : null}
      <button
        type="button"
        class="btn-secondary"
        onClick={() =>
          run(async () => {
            const r = await api.pairingCode();
            setPairing({ code: r.code, until: Date.now() + r.expires_in * 1000 });
            setNow(Date.now());
          })
        }
      >
        Pair a phone
      </button>
      <button type="button" class="btn-secondary" onClick={() => setConfirmRevoke(true)}>
        Revoke phones…
      </button>
      {pairing && left > 0 ? (
        <div class="pair-code" role="status">
          <span class="code">{pairing.code}</span>
          <span>valid {left}s · single use</span>
        </div>
      ) : null}
      {msg ? <p class="error">{msg}</p> : null}

      {confirmEnd ? (
        <Sheet title="End incident?" onClose={() => setConfirmEnd(false)}>
          <p class="note">This returns to normal mode and deletes the incident record. Rooms not yet searched still need a sweep.</p>
          <button
            type="button"
            class="btn-danger"
            onClick={() =>
              run(async () => {
                await api.endIncident();
                setConfirmEnd(false);
                onEnded();
              })
            }
          >
            Yes, end incident
          </button>
        </Sheet>
      ) : null}
      {confirmRevoke ? (
        <Sheet title="Revoke all phones?" onClose={() => setConfirmRevoke(false)}>
          <p class="note">Every paired phone is signed out and must pair again.</p>
          <button
            type="button"
            class="btn-danger"
            onClick={() =>
              run(async () => {
                const r = await api.revokePhones();
                setConfirmRevoke(false);
                setMsg(`Phones revoked (${r.closed_sockets} disconnected).`);
              })
            }
          >
            Yes, revoke
          </button>
        </Sheet>
      ) : null}
    </div>
  );
}
