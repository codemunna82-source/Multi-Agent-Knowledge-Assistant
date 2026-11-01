export function StopGeneratingButton({ onStop }: { onStop: () => void }) {
  return <button type="button" className="stop-gen" onClick={onStop} aria-label="Stop generating"><span aria-hidden="true">■</span> Stop generating</button>;
}
