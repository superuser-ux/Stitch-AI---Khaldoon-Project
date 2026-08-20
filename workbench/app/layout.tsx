import type { Metadata } from "next";
// #340 — FullCalendar v7's package-provided CSS, loaded through Next's supported global boundary
// (external stylesheets may be imported anywhere under `app/`). `skeleton.css` is the STRUCTURAL
// layer: without it every `.fc-*` node falls back to block flow and the calendar collapses into a
// vertical text stream — semantically correct, visually unusable. The Classic theme adds the skin
// (borders, buttons, event chips, focus outlines) and its palette supplies the `--fc-classic-*`
// variables. Nothing here is copied or re-implemented; these are the package's own exports.
//
// ORDER IS LOAD-BEARING: the palette declares `--fc-classic-*` on `:root`, and globals.css rebinds
// those same variables on `:root` to the V2 tokens. Equal specificity means SOURCE ORDER decides, so
// the package CSS must come FIRST and globals.css LAST. Appending these below `./globals.css` would
// let the package palette win and silently kill the token bridge — with no error to notice.
import "@fullcalendar/react/skeleton.css";
import "@fullcalendar/react/themes/classic/theme.css";
import "@fullcalendar/react/themes/classic/palette.css";
import "./globals.css";
import { Suspense } from "react";
import { WorkbenchShell } from "@/components/workbench-shell";
import { ShellNavProvider } from "@/components/shell-nav";
import { IamProvider } from "@/components/iam-boundary";
import {
  APPEARANCE_KEY, SCHEDULE_STYLE_KEY, THEME_ATTR, SCHEDULE_STYLE_ATTR, DEFAULT_SCHEDULE_STYLE,
} from "@/lib/presentation-prefs";

export const metadata: Metadata = {
  title: "Tanaghom Workbench (V2)",
  description:
    "V2 workbench — a transition-lane frontend over the same Tanaghom API authority (#293 Stage 0).",
};

// #335/#380 — the pre-paint presentation initializer. A BOUNDED V2 presentation-only script: it reads
// only the two allowlisted local preference values, reflects them onto <html> BEFORE first paint (so
// there is no incorrect-theme flash), tolerates storage being unavailable/denied/malformed, performs NO
// network or domain action, and adds NOTHING that would require weakening CSP (V2 declares no CSP; this
// inline script makes no external request). DETERMINISTIC LIGHT (#380): the ONLY explicit theme is
// `dark`; anything else — `light`, a stale `system`, absent, or malformed — leaves no attribute, so the
// Light base :root renders and the OS preference never participates. The string is built from the same
// frozen constants the React controls use, so the two can never drift.
const PREPAINT_INIT = `(function(){try{var d=document.documentElement;var a=null,s=null;` +
  `try{a=localStorage.getItem(${JSON.stringify(APPEARANCE_KEY)});}catch(e){}` +
  `try{s=localStorage.getItem(${JSON.stringify(SCHEDULE_STYLE_KEY)});}catch(e){}` +
  `if(a==="dark"){d.setAttribute(${JSON.stringify(THEME_ATTR)},"dark");}` +
  `else{d.removeAttribute(${JSON.stringify(THEME_ATTR)});}` +
  `d.setAttribute(${JSON.stringify(SCHEDULE_STYLE_ATTR)},(s==="editorial"||s==="operational")?s:${JSON.stringify(DEFAULT_SCHEDULE_STYLE)});` +
  `}catch(e){}})();`;

// `dir` starts as ltr and is switched on <html> by the client direction toggle. Keeping direction,
// appearance (data-theme), and schedule style (data-schedule-style) as three INDEPENDENT attributes on
// <html> is what keeps them orthogonal and lets CSS logical properties resolve for the whole tree.
//
// #331 — the ONE coherent shell wraps every route here. The default schedule style is stamped on the
// SSR html so the operational baseline holds even without JS; the pre-paint script then reconciles the
// stored preference before paint. suppressHydrationWarning covers the script's pre-hydration edits.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr" data-schedule-style={DEFAULT_SCHEDULE_STYLE} suppressHydrationWarning>
      <body>
        <script dangerouslySetInnerHTML={{ __html: PREPAINT_INIT }} />
        {/* #382 — the ONE shared navigation authority wraps the shell AND the route children so both
            consume the same resolved stage/gate/lens (ruling 2). ShellNavProvider reads the live URL
            via useSearchParams, so it sits under a Suspense boundary per Next 15's requirement; the
            fallback is null because the shell chrome is client-hydrated anyway (fetches, toggles). */}
        <Suspense fallback={null}>
          <IamProvider>
            <ShellNavProvider>
              <WorkbenchShell>{children}</WorkbenchShell>
            </ShellNavProvider>
          </IamProvider>
        </Suspense>
      </body>
    </html>
  );
}
