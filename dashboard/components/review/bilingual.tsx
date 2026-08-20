// #280 — presentational wrapper over composeBilingual: renders a stored bilingual field with the
// correct direction + language tag for RTL safety, and a truthful, accessible placeholder when the
// value is genuinely absent (no silent blank, no invented text). Display only.
import { composeBilingual, type Lang } from "@/lib/bilingual";

export function Bilingual({
  ar,
  en,
  primary = "ar",
  fallback = "—",
  className,
  title,
  testId,
}: {
  ar: string | null | undefined;
  en: string | null | undefined;
  primary?: Lang;
  fallback?: string;                 // shown when BOTH values are absent
  className?: string;
  title?: boolean;                   // add a native title tooltip (useful for truncated cells)
  testId?: string;
}) {
  const pick = composeBilingual(ar, en, { primary });
  if (!pick.present) {
    return (
      <span data-testid={testId} data-bilingual="absent" aria-label="Not available" className={className}>
        {fallback}
      </span>
    );
  }
  return (
    <span
      data-testid={testId}
      data-bilingual={pick.lang}
      dir={pick.dir}
      lang={pick.lang}
      title={title ? pick.text : undefined}
      className={className}
    >
      {pick.text}
    </span>
  );
}
