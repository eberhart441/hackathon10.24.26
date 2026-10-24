import { useState } from 'preact/hooks';
import type { ListItem } from '../scene/model';
import { StateIcon } from './icons';

interface Props {
  items: ListItem[];
  expanded: boolean;
  onToggle: () => void;
  onRoom: (roomId: string) => void;
  onSearched: (roomId: string) => Promise<void>;
}

// Flagged rooms in server ranking order (Kiro R8.2, R11.1). Bottom sheet in portrait,
// side list in landscape (CSS).
export function PriorityList({ items, expanded, onToggle, onRoom, onSearched }: Props) {
  return (
    <section class={`plist${expanded ? ' open' : ''}`} aria-label="Search priority">
      <button type="button" class="plist-handle" onClick={onToggle} aria-expanded={expanded}>
        <span class="grip" aria-hidden="true" />
        <span>Search priority · {items.filter((i) => !i.searched).length} to search</span>
      </button>
      <ol class="plist-rows">
        {items.map((i) => (
          <Row key={i.roomId} item={i} onRoom={onRoom} onSearched={onSearched} />
        ))}
      </ol>
    </section>
  );
}

export function SearchedButton({ roomId, name, searched, onSearched }: { roomId: string; name: string; searched: boolean; onSearched: (id: string) => Promise<void> }) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  if (searched) {
    return (
      <span class="searched-done" aria-label={`${name} searched`}>
        ✓ Searched
      </span>
    );
  }
  // Tap once to arm, tap again to confirm: 2 taps total (parent R13.4).
  return (
    <button
      type="button"
      class={`btn-searched${armed ? ' armed' : ''}`}
      disabled={busy}
      aria-label={armed ? `Confirm ${name} searched` : `Mark ${name} searched`}
      onClick={async (e) => {
        e.stopPropagation();
        if (!armed) {
          setArmed(true);
          window.setTimeout(() => setArmed(false), 4000);
          return;
        }
        setBusy(true);
        try {
          await onSearched(roomId);
        } finally {
          setBusy(false);
          setArmed(false);
        }
      }}
    >
      {armed ? 'Confirm' : '✓ Mark searched'}
    </button>
  );
}

function Row({ item, onRoom, onSearched }: { item: ListItem; onRoom: (id: string) => void; onSearched: (id: string) => Promise<void> }) {
  return (
    <li class={`prow st-${item.state}${item.searched ? ' searched' : ''}`}>
      <button type="button" class="prow-main" onClick={() => onRoom(item.roomId)} aria-label={`Priority ${item.rank}, ${item.name}, ${item.label}, ${item.confText}`}>
        <span class={`rank${item.isTop ? ' top' : ''}`}>{item.rank}</span>
        <span class="prow-text">
          <span class="prow-name">
            {item.name}
            {item.simulated ? <span class="chip chip-sim">SIM</span> : null}
          </span>
          <span class="prow-state">
            <StateIcon state={item.state} size={16} />
            {item.label} · {item.confText}
          </span>
          {item.detailText ? <span class="prow-detail">{item.detailText}</span> : null}
          {item.note ? <span class="prow-detail">{item.note}</span> : null}
        </span>
      </button>
      <SearchedButton roomId={item.roomId} name={item.name} searched={item.searched} onSearched={onSearched} />
    </li>
  );
}
