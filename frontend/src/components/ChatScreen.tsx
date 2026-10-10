import { AnimatePresence, motion } from "framer-motion";
import { Brain, Calculator, Menu, MessageCircleQuestion, Search, Sparkles, TriangleAlert, X } from "lucide-react";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import type { Mode, Msg } from "@/types";
import { AnimatedPromptBar, type PromptBarHandle } from "./ui/animated-prompt-bar";
import { TypingIndicator } from "./TypingIndicator";

interface Props {
  title: string;
  messages: Msg[];
  loading: boolean;
  pending: boolean;
  error: string | null;
  mode: Mode;
  isMobile: boolean;
  smoothScroll: boolean;
  onMenu: () => void;
  onModeChange: (m: Mode) => void;
  onSend: (text: string) => Promise<boolean>;
  onDismissError: () => void;
  onManageMemories: () => void;
}

export function ChatScreen(p: Props) {
  const bar = useRef<PromptBarHandle>(null);
  const end = useRef<HTMLDivElement>(null);
  const welcome = p.messages.length === 0 && !p.loading;

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: p.smoothScroll ? "smooth" : "auto", block: "end" });
  }, [p.messages, p.pending, p.smoothScroll]);

  useEffect(() => { bar.current?.focus(); }, [p.title]);

  const chips: Array<{ label: string; icon: JSX.Element; run: () => void }> = [
    { label: "Ask a question", icon: <MessageCircleQuestion size={15} />, run: () => { p.onModeChange("agent"); bar.current?.focus(); } },
    { label: "Search my memories", icon: <Search size={15} />, run: () => { p.onModeChange("memory"); bar.current?.focus(); } },
    { label: "Help me manage my memories", icon: <Brain size={15} />, run: p.onManageMemories },
    { label: "Do a calculation", icon: <Calculator size={15} />, run: () => { p.onModeChange("tools"); bar.current?.focus(); } },
  ];

  return (
    <main className={cn("chat", welcome && "chat--welcome")} aria-label="Chat">
      <header className="topbar">
        {p.isMobile && (
          <button className="icon-btn" onClick={p.onMenu} aria-label="Open menu" aria-controls="sidebar"><Menu size={20} /></button>
        )}
        <h1 className="topbar__title">{welcome ? "New chat" : p.title}</h1>
        <span className="pill"><span className="dot" />Local · private</span>
      </header>

      <div className="stage">
        {welcome ? (
          <motion.section key="welcome" className="hero" aria-label="Welcome"
            initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}>
            <div className="hero__badge"><Sparkles size={14} aria-hidden /> AI Memory Agent</div>
            <h2 className="hero__title">How can I help you today?</h2>
            <p className="hero__sub">Private and local. I remember what matters to you and answer from your own memories.</p>
          </motion.section>
        ) : (
          <div className="thread" role="log" aria-live="polite" aria-label="Conversation">
            <div className="thread__inner">
              {p.loading && <div className="muted center pad">Loading conversation…</div>}
              <AnimatePresence initial={false}>
                {p.messages.map((m, i) => (
                  <motion.article key={i} className={cn("msg", m.role === "user" ? "msg--user" : "msg--assistant")}
                    initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
                    {m.role === "assistant" && <span className="msg__avatar" aria-hidden><Sparkles size={14} /></span>}
                    <div className="msg__body"><span className="sr-only">{m.role === "user" ? "You: " : "Assistant: "}</span>{m.content}</div>
                  </motion.article>
                ))}
                {p.pending && (
                  <div className="msg msg--assistant" key="typing">
                    <span className="msg__avatar" aria-hidden><Sparkles size={14} /></span><TypingIndicator />
                  </div>
                )}
              </AnimatePresence>
              <div ref={end} className="thread__end" />
            </div>
          </div>
        )}

        <div className="dock">
          <div className="dock__inner">
            {p.error && (
              <div className="banner" role="alert">
                <TriangleAlert size={16} aria-hidden />
                <span>{p.error} <b>Your message is still in the box.</b></span>
                <button className="icon-btn" onClick={p.onDismissError} aria-label="Dismiss error"><X size={16} /></button>
              </div>
            )}
            <AnimatedPromptBar ref={bar} onSend={p.onSend} mode={p.mode} onModeChange={p.onModeChange} busy={p.pending}
              placeholder={p.mode === "memory" ? "Ask about or manage your memories…" : p.mode === "tools" ? "Try 12*(3+4)…" : "Message AI Memory Agent…"} />
            {welcome && (
              <motion.div className="chips" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.25 }}>
                {chips.map((c) => (
                  <button key={c.label} className="chip" onClick={c.run}>{c.icon}<span>{c.label}</span></button>
                ))}
              </motion.div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
