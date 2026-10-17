import { RowsToolbar } from "../shared/RowsToolbar";
import { defaultTtsRow, newTtsRowId, useTtsRows } from "./store";
import { TtsRow } from "./TtsRow";

export function TtsTab() {
  const { rows, add, runAll, clone } = useTtsRows();
  const last = rows.at(-1);
  return (
    <div className="space-y-3">
      <RowsToolbar
        title="TTS clients"
        count={rows.length}
        onAdd={() => add({ ...defaultTtsRow(), modelId: last?.modelId ?? "" })}
        onRunAll={runAll}
        onClone={(n) => last && clone(last.id, n, newTtsRowId)}
        hint="Each row is an independent client. “Run all” starts every row at once (all of them will play audio)."
      />
      {rows.map((r, i) => (
        <TtsRow key={r.id} cfg={r} index={i} />
      ))}
    </div>
  );
}
