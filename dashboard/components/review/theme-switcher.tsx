"use client";
import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";

// lunaris is the single design system; the only theme axis is light/dark (dark default).
export function ThemeSwitcher() {
  const [dark, setDark] = useState(true);
  useEffect(() => { setDark((localStorage.getItem("tanaghom-theme") || "dark") !== "light"); }, []);

  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try { localStorage.setItem("tanaghom-theme", next ? "dark" : "light"); } catch { /* ignore */ }
  };

  return (
    <Button data-testid="theme-trigger" variant="outline" size="sm" onClick={toggle} aria-label="Toggle theme">
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </Button>
  );
}
