import { useState } from 'preact/hooks';
import { getMyTag, pair, setMyTag } from '../api';

// Pairing happens inside the installed app: an iOS home-screen PWA has its own storage, separate
// from Safari (Kiro R2.8). Typing is fine here; this is normal mode, never fire mode.
export function PairScreen({ onPaired }: { onPaired: () => void }) {
  const [code, setCode] = useState('');
  const [tag, setTag] = useState(() => getMyTag() ?? '');
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
      setMyTag(tag);
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
        <label class="tag-field">
          <span>Your responder tag (shows where you are on the map)</span>
          <input
            class="tag-input"
            autoCapitalize="characters"
            autoComplete="off"
            maxLength={4}
            placeholder="E1"
            aria-label="Your responder tag"
            value={tag}
            onInput={(e) => setTag((e.target as HTMLInputElement).value.replace(/[^A-Za-z0-9_-]/g, '').toUpperCase().slice(0, 4))}
          />
        </label>
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
