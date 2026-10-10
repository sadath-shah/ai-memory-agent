import { ArrowUp, Bot, Brain, LoaderCircle, Wrench } from "lucide-react";
import { motion } from "framer-motion";
import {
  forwardRef, useCallback, useImperativeHandle, useLayoutEffect, useRef, useState,
  type KeyboardEvent, type ReactNode,
} from "react";
import { cn } from "@/lib/utils";
import type { Mode } from "@/types";

const MODES: Array<{ id: Mode; label: string; icon: ReactNode; hint: string }> = [
  { id: "agent", label: "Agent", icon: <Bot size={14} />, hint: "Chat, remember facts, answer from memory" },
  { id: "memory", label: "Memory", icon: <Brain size={14} />, hint: "Only look up and manage stored memories" },
  { id: "tools", label: "Tools", icon: <Wrench size={14} />, hint: "Calculator" },
];

export interface PromptBarHandle { focus: () => void }

interface Props {
  /** Resolve true when the message was handled; false keeps the draft. */
  onSend: (text: string) => Promise<boolean>;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  busy: boolean;
  placeholder?: string;
  maxHeight?: number;
}

export const AnimatedPromptBar = forwardRef<PromptBarHandle, Props>(function AnimatedPromptBar(
  { onSend, mode, onModeChange, busy, placeholder = "Message AI Memory Agent…", maxHeight = 180 }, ref,
) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const lock = useRef(false);               // synchronous guard: no duplicate submissions

  useImperativeHandle(ref, () => ({ focus: () => area.current?.focus() }), []);

  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
  }, [draft, maxHeight]);

  const working = busy || sending;
  const canSend = draft.trim().length > 0 && !working;

  const submit = useCallback(async () => {
    const text = draft.trim();
    if (!text || lock.current || busy) return;
    lock.current = true;
    setSending(true);
    let ok = false;
    try { ok = await onSend(text); } catch { ok = false; }
    if (ok) setDraft("");                    // keep the draft if sending failed
    lock.current = false;
    setSending(false);
    requestAnimationFrame(() => area.current?.focus());
  }, [draft, busy, onSend]);

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  };

  return (
    <motion.form
      className={cn("prompt", working && "prompt--busy")}
      onSubmit={(e) => { e.preventDefault(); void submit(); }}
      aria-label="Message composer"
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
    >
      <label htmlFor="msg" className="sr-only">Message</label>
      <textarea
        id="msg" ref={area} className="prompt__input" rows={1} value={draft}
        placeholder={placeholder} maxLength={4000} readOnly={working}
        aria-describedby="prompt-hint"
        onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown}
      />
      <div className="prompt__bar">
        <div className="modes" role="radiogroup" aria-label="Mode">
          {MODES.map((m) => (
            <button key={m.id} type="button" role="radio" aria-checked={mode === m.id} title={m.hint}
              className={cn("mode", mode === m.id && "mode--on")}
              onClick={() => { onModeChange(m.id); area.current?.focus(); }}>
              {m.icon}<span>{m.label}</span>
            </button>
          ))}
        </div>
        <span id="prompt-hint" className="prompt__hint">Enter to send · Shift+Enter for a new line</span>
        <motion.button id="send" type="submit" className="send" disabled={!canSend}
          aria-label={working ? "Sending message" : "Send message"} aria-busy={working}
          whileHover={canSend ? { scale: 1.06 } : undefined} whileTap={canSend ? { scale: 0.92 } : undefined}>
          {working ? <LoaderCircle size={18} className="spin" aria-hidden /> : <ArrowUp size={18} aria-hidden />}
        </motion.button>
      </div>
    </motion.form>
  );
});
