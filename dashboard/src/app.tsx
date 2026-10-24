// Placeholder shell. The disclaimer moves to STRINGS.disclaimer in a later task (Req 10.1).
const DISCLAIMER = "Decision support only — does not replace a full search";

export function App() {
  return (
    <main>
      <h1>RoomSense</h1>
      <p role="note">{DISCLAIMER}</p>
    </main>
  );
}
