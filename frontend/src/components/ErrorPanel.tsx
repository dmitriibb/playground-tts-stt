import { useMemo, useState } from "react";
import { type ErrorEntry, useErrors } from "../store/errors";
import { Badge, Button, cn, Input, Select } from "./ui";

/** Bottom panel on every tab: server errors (from /ws/events) and failed requests. */
export function ErrorPanel() {
  const { entries, unread, markRead, clear } = useErrors();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [source, setSource] = useState("all");

  const shown = useMemo(() => {
    const f = filter.toLowerCase();
    return entries.filter(
      (e) =>
        (source === "all" || e.source === source) &&
        (!f || `${e.code} ${e.message} ${e.modelId} ${e.requestId}`.toLowerCase().includes(f)),
    );
  }, [entries, filter, source]);

  const toggle = () => {
    setOpen(!open);
    markRead();
  };

  return (
    <div className="fixed inset-x-0 bottom-0 z-20 border-t border-zinc-800 bg-zinc-950/95 backdrop-blur">
      <div className="flex h-9 items-center gap-3 px-4 text-sm">
        <button onClick={toggle} className="flex items-center gap-2 font-medium text-zinc-300 hover:text-white">
          <span>{open ? "▾" : "▸"}</span> Errors &amp; warnings
          <Badge tone={entries.length ? "red" : "zinc"}>{entries.length}</Badge>
          {unread > 0 && !open && <Badge tone="amber">{unread} new</Badge>}
        </button>
        {!open && entries[0] && (
          <span className="truncate text-xs text-zinc-500">
            latest: <span className="text-zinc-300">{entries[0].code ?? entries[0].level}</span> {entries[0].message}
          </span>
        )}
        {open && (
          <div className="ml-auto flex items-center gap-2">
            <Input placeholder="filter…" value={filter} onChange={(e) => setFilter(e.target.value)} className="h-7 w-48" />
            <Select value={source} onChange={(e) => setSource(e.target.value)} className="h-7">
              {["all", "client", "gateway", "stt", "tts", "engine", "common"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </Select>
            <Button size="sm" variant="outline" onClick={clear}>
              Clear
            </Button>
          </div>
        )}
      </div>
      {open && (
        <div className="max-h-72 overflow-y-auto border-t border-zinc-900 px-4 py-2">
          {shown.length === 0 && <div className="py-4 text-center text-xs text-zinc-500">No errors.</div>}
          {shown.map((e) => (
            <ErrorRow key={e.id} e={e} />
          ))}
        </div>
      )}
    </div>
  );
}

function ErrorRow({ e }: { e: ErrorEntry }) {
  const [expanded, setExpanded] = useState(false);
  const hasMore = Boolean(e.traceback || e.details);
  return (
    <div className="border-b border-zinc-900 py-1.5 text-xs">
      <div className={cn("flex items-start gap-2", hasMore && "cursor-pointer")} onClick={() => setExpanded(!expanded)}>
        <span className="w-16 shrink-0 font-mono text-zinc-500">{new Date(e.ts).toLocaleTimeString()}</span>
        <Badge tone={e.level === "error" ? "red" : "amber"}>{e.level}</Badge>
        <Badge>{e.source}</Badge>
        {e.code && <span className="font-mono text-red-300">{e.code}</span>}
        <span className="flex-1 break-words text-zinc-200">{e.message}</span>
        <span className="shrink-0 font-mono text-zinc-500">
          {e.modelId && <span className="mr-2">{e.modelId}</span>}
          {e.requestId && <span title="request / session id">#{e.requestId}</span>}
        </span>
        {hasMore && <span className="text-zinc-500">{expanded ? "▾" : "▸"}</span>}
      </div>
      {expanded && (
        <pre className="mt-1 max-h-60 overflow-auto rounded bg-zinc-900 p-2 font-mono text-[11px] text-zinc-400">
          {e.traceback ?? JSON.stringify(e.details, null, 2)}
        </pre>
      )}
    </div>
  );
}
