"use client";
import { useEffect, useState } from "react";
import { ArrowUp } from "lucide-react";
import { RelayMark } from "@/components/logo";

const PHRASE = "Ask Relay anything, in plain words.";

// Invertix-style command bar in liquid glass. The placeholder types in letter by letter. Graphics only.
export function CommandBar() {
  const [v, setV] = useState("");
  const [focused, setFocused] = useState(false);
  const [shown, setShown] = useState("");

  useEffect(() => {
    let i = 0;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      i += 1;
      if (i > PHRASE.length) {
        timer = setTimeout(() => { i = 0; setShown(""); timer = setTimeout(tick, 350); }, 2200);
        return;
      }
      setShown(PHRASE.slice(0, i));
      timer = setTimeout(tick, 62);
    };
    timer = setTimeout(tick, 400);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div className="flex w-full items-center gap-4 rounded-[26px] glass glass-hi px-5 py-4">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-xl glass-2">
        <RelayMark className="h-4 w-4 text-white" />
      </span>
      <div className="relative flex-1">
        <input
          value={v}
          onChange={(e) => setV(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          className="w-full bg-transparent text-[15px] text-white outline-none"
        />
        {!v && !focused && (
          <div className="pointer-events-none absolute inset-0 flex items-center text-[15px] text-zinc-500">
            {shown}<span className="caret" />
          </div>
        )}
      </div>
      <button
        onClick={() => setV("")}
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white text-black transition hover:bg-zinc-200"
        aria-label="Send"
      >
        <ArrowUp size={18} strokeWidth={2.5} />
      </button>
    </div>
  );
}
