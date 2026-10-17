import { useState } from "react";
import { Button, Input } from "../../components/ui";

export function RowsToolbar({
  title,
  count,
  hint,
  onAdd,
  onRunAll,
  onClone,
}: {
  title: string;
  count: number;
  hint: string;
  onAdd: () => void;
  onRunAll: () => void;
  onClone: (n: number) => void;
}) {
  const [n, setN] = useState(4);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <h2 className="mr-2 text-sm font-semibold uppercase tracking-wide text-zinc-400">
        {title} <span className="text-zinc-600">({count})</span>
      </h2>
      <Button variant="primary" onClick={onRunAll} title="Start all rows at the same moment">
        ▶ Run all rows
      </Button>
      <Button onClick={onAdd}>+ Add row</Button>
      <span className="ml-2 flex items-center gap-1 text-xs text-zinc-400">
        Clone last row ×
        <Input type="number" min={1} max={64} value={n} onChange={(e) => setN(+e.target.value)} className="h-7 w-14" />
        <Button size="sm" variant="outline" onClick={() => onClone(n)} disabled={!count}>
          Clone
        </Button>
      </span>
      <span className="text-xs text-zinc-500">{hint}</span>
    </div>
  );
}
