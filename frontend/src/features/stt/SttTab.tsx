import { RowsToolbar } from "../shared/RowsToolbar";
import { defaultSttRow, newRowId, useSttRows } from "./store";
import { SttRow } from "./SttRow";

export function SttTab() {
  const { rows, add, runAll, clone } = useSttRows();
  const last = rows.at(-1);
  return (
    <div className="space-y-3">
      <RowsToolbar
        title="STT clients"
        count={rows.length}
        onAdd={() => add({ ...defaultSttRow(), modelId: last?.modelId ?? "" })}
        onRunAll={runAll}
        onClone={(n) => last && clone(last.id, n, newRowId)}
        hint="Each row is an independent client with its own connection. “Run all” starts every non-mic row at once."
      />
      {rows.map((r, i) => (
        <SttRow key={r.id} cfg={r} index={i} />
      ))}
    </div>
  );
}
