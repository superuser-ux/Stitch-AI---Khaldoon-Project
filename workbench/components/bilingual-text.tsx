import { presentBilingual } from "@/lib/bilingual";

// #315 — render a canonical (Arabic, English) pair in its deterministic 4-state presentation. Each
// present side is a `<bdi>` with a TRUTHFUL per-node `lang` (ar/en) + `dir="auto"` so bidi isolation and
// language are declared correctly regardless of the document chrome direction. Values are rendered RAW
// (never normalized). A missing/single side is disclosed, never fabricated. `data-bilingual-state`
// exposes the resolved state for deterministic testing.
export function BilingualText({
  ar,
  en,
  testid,
  className,
}: {
  ar?: string | null;
  en?: string | null;
  testid: string;
  className?: string;
}) {
  const p = presentBilingual(ar, en);
  return (
    <span
      data-testid={testid}
      data-bilingual-state={p.state}
      className={`flex flex-col gap-0.5 ${className ?? ""}`}
    >
      {p.ar !== null && (
        <bdi lang="ar" dir="auto" data-testid={`${testid}-ar`} className="text-sm text-(--color-fg)">
          {p.ar}
        </bdi>
      )}
      {p.en !== null && (
        <bdi lang="en" dir="auto" data-testid={`${testid}-en`} className="text-sm text-(--color-fg)">
          {p.en}
        </bdi>
      )}
      {p.disclosure !== null && (
        <span
          data-testid={`${testid}-fallback`}
          className="text-[10px] italic text-(--color-muted)"
        >
          {p.disclosure}
        </span>
      )}
    </span>
  );
}
