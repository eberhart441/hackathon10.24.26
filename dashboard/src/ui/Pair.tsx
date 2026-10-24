import { useState } from 'preact/hooks';
import { pair } from '../api';

// Pairing happens inside the installed app: an iOS home-screen PWA has its own storage, separate
// from Safari (Kiro R2.8). Typing is fine here; this is normal mode, never fire mode.
export function PairScreen({ onPaired }: { onPaired: () => void }) {
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: Event) => {
    e.preventDefault();
    if (!/^\d{6}$/.test(code)) {
      setError('Enter the 6-digit code shown on the laptop.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await pair(code);
      onPaired();
    } catch (err) {
      setError((err as Error).message);
      setCode('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <main class="center-screen">
      <form class="pair" onSubmit={submit}>
        <h1>Pair this phone</h1>
        <p>On the laptop dashboard, tap “Pair a phone”, then enter the 6-digit code.</p>
        <input
          class="code-input"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="\d{6}"
          maxLength={6}
          aria-label="Pairing code"
          value={code}
          onInput={(e) => setCode((e.target as HTMLInputElement).value.replace(/\D/g, '').slice(0, 6))}
        />
        <button class="btn-primary" type="submit" disabled={busy || code.length !== 6}>
          {busy ? 'Pairing…' : 'Pair'}
        </button>
        {error ? (
          <p class="error" role="alert">
            {error}
          </p>
        ) : null}
      </form>
    </main>
  );
}
