/** Small shadcn-style primitives, hand-written to keep the dependency list short. */
import {
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
  useEffect,
  useRef,
} from "react";

export const cn = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(" ");

type Variant = "default" | "primary" | "danger" | "ghost" | "outline";
const variants: Record<Variant, string> = {
  default: "bg-zinc-800 hover:bg-zinc-700 text-zinc-100",
  primary: "bg-sky-600 hover:bg-sky-500 text-white",
  danger: "bg-red-700 hover:bg-red-600 text-white",
  ghost: "hover:bg-zinc-800 text-zinc-300",
  outline: "border border-zinc-700 hover:bg-zinc-800 text-zinc-200",
};

export function Button({
  variant = "default",
  size = "md",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  return (
    <button
      {...props}
      className={cn(
        "inline-flex select-none items-center justify-center gap-1.5 rounded-md font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-40",
        size === "sm" ? "h-7 px-2 text-xs" : "h-8 px-3 text-sm",
        variants[variant],
        className,
      )}
    />
  );
}

type Tone = "zinc" | "green" | "amber" | "red" | "sky" | "violet";
const tones: Record<Tone, string> = {
  zinc: "bg-zinc-800 text-zinc-300 border-zinc-700",
  green: "bg-emerald-950 text-emerald-300 border-emerald-800",
  amber: "bg-amber-950 text-amber-300 border-amber-800",
  red: "bg-red-950 text-red-300 border-red-800",
  sky: "bg-sky-950 text-sky-300 border-sky-800",
  violet: "bg-violet-950 text-violet-300 border-violet-800",
};

export function Badge({
  tone = "zinc",
  children,
  title,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <span
      title={title}
      className={cn("inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] leading-none", tones[tone], className)}
    >
      {children}
    </span>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("rounded-lg border border-zinc-800 bg-zinc-900/60 p-3", className)}>{children}</div>;
}

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cn(
        "h-8 rounded-md border border-zinc-700 bg-zinc-900 px-2 text-sm text-zinc-100 disabled:opacity-50",
        className,
      )}
    />
  );
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(
        "h-8 rounded-md border border-zinc-700 bg-zinc-900 px-2 text-sm text-zinc-100 disabled:opacity-50",
        className,
      )}
    />
  );
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={cn("rounded-md border border-zinc-700 bg-zinc-900 p-2 text-sm text-zinc-100", className)}
    />
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-zinc-400" title={hint}>
      {label}
      {children}
    </label>
  );
}

/** Segmented toggle; disabled options show their reason on hover. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string; disabled?: boolean; hint?: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex flex-wrap gap-1 rounded-md bg-zinc-900 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          title={o.hint}
          disabled={o.disabled}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded px-2 py-1 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-30",
            value === o.value ? "bg-sky-700 text-white" : "text-zinc-300 hover:bg-zinc-800",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Progress({ value }: { value: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded bg-zinc-800">
      <div className="h-full bg-sky-500 transition-[width]" style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}

export function Dialog({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className="m-auto w-[min(560px,92vw)] rounded-lg border border-zinc-700 bg-zinc-900 p-0 text-zinc-200"
    >
      <div className="border-b border-zinc-800 px-4 py-3 text-sm font-semibold">{title}</div>
      <div className="p-4 text-sm">{children}</div>
    </dialog>
  );
}

export function fmtMs(ms: number | null | undefined, digits = 0): string {
  if (ms == null || Number.isNaN(ms)) return "—";
  return ms >= 10_000 ? `${(ms / 1000).toFixed(1)} s` : `${ms.toFixed(digits)} ms`;
}

export function fmtMb(mb: number | null | undefined): string {
  if (mb == null) return "—";
  return mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${Math.round(mb)} MB`;
}

export function Metric({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="flex flex-col" title={hint}>
      <span className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</span>
      <span className="font-mono text-sm text-zinc-100">{value}</span>
    </div>
  );
}
