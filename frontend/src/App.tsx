import { MotionConfig } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api";
import { ChatScreen } from "@/components/ChatScreen";
import { MemoryManagement } from "@/components/MemoryManagement";
import { SettingsPage } from "@/components/SettingsPage";
import { Sidebar } from "@/components/Sidebar";
import { useMediaQuery } from "@/hooks/use-media-query";
import { usePersistedState } from "@/hooks/use-persisted-state";
import { cn } from "@/lib/utils";
import type { ConversationSummary, Mode, Msg, View } from "@/types";

const NEW_CHAT = "new";

export default function App() {
  const isMobile = useMediaQuery("(max-width: 820px)");
  const [collapsed, setCollapsed] = usePersistedState("mma.sidebarCollapsed", false);
  const [reduceMotion, setReduceMotion] = usePersistedState("mma.reduceMotion", false);
  const [savedActive, setSavedActive] = usePersistedState<string | null>("mma.activeConversation", null);

  const [view, setView] = useState<View>("chat");
  const [drawer, setDrawer] = useState(false);
  const [mode, setMode] = useState<Mode>("agent");

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [convLoading, setConvLoading] = useState(true);
  const [convError, setConvError] = useState<string | null>(null);

  const [activeId, setActiveId] = useState<string | null>(null);   // null = a brand-new, unsent chat
  const [messages, setMessages] = useState<Msg[]>([]);
  const [loadingChat, setLoadingChat] = useState(false);
  const [pending, setPending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const menuButtonFocus = useRef<HTMLElement | null>(null);

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await api.conversations());
      setConvError(null);
    } catch (e) { setConvError((e as Error).message); }
    setConvLoading(false);
  }, []);

  const openConversation = useCallback(async (id: string) => {
    setLoadingChat(true); setSendError(null);
    try {
      const history = await api.history(id);
      setMessages(history); setActiveId(id); setSavedActive(id);
    } catch (e) {
      // gone or unreadable: fall back to a fresh chat instead of a broken screen
      setMessages([]); setActiveId(null); setSavedActive(null);
      if ((e as { status?: number }).status !== 404) setSendError((e as Error).message);
    }
    setLoadingChat(false);
  }, [setSavedActive]);

  // First load: conversation list + restore the chat that was open before the reload.
  useEffect(() => {
    void refreshConversations();
    if (savedActive) void openConversation(savedActive);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeDrawer(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  useEffect(() => { if (!isMobile) setDrawer(false); }, [isMobile]);

  function openDrawer() { menuButtonFocus.current = document.activeElement as HTMLElement; setDrawer(true); }
  function closeDrawer() { setDrawer(false); menuButtonFocus.current?.focus?.(); }

  const afterNavigate = () => { if (isMobile) setDrawer(false); };

  function newChat() {
    if (inFlight.current) return;
    setView("chat"); setActiveId(null); setSavedActive(null); setMessages([]); setSendError(null);
    afterNavigate();
  }
  function selectConversation(id: string) {
    if (inFlight.current) return;
    setView("chat"); afterNavigate();
    if (id !== activeId) void openConversation(id);
  }
  function navigate(next: View) { setView(next); afterNavigate(); }

  /** Real request to the existing backend. Resolves true only when it was handled. */
  const send = useCallback(async (text: string): Promise<boolean> => {
    if (inFlight.current) return false;
    inFlight.current = true;
    setPending(true); setSendError(null);
    setMessages((m) => [...m, { role: "user", content: text }]);
    const rollback = () => setMessages((m) => (m.length && m[m.length - 1].role === "user" ? m.slice(0, -1) : m));
    try {
      const r = await api.chat(text, activeId ?? NEW_CHAT, mode);
      if (r.action === "ERROR") {            // e.g. Ollama unavailable: nothing was answered
        rollback(); setSendError(r.reply); return false;
      }
      setMessages((m) => [...m, { role: "assistant", content: r.reply }]);
      if (r.conversation_id) { setActiveId(r.conversation_id); setSavedActive(r.conversation_id); }
      void refreshConversations();
      return true;
    } catch (e) {
      rollback(); setSendError((e as Error).message); return false;
    } finally {
      inFlight.current = false; setPending(false);
    }
  }, [activeId, mode, refreshConversations, setSavedActive]);

  const title = conversations.find((c) => c.id === activeId)?.title ?? "Conversation";
  const sidebarProps = {
    collapsed, mobile: isMobile, open: drawer, view, conversations, conversationsError: convError,
    conversationsLoading: convLoading, activeId, locked: pending,
    onNewChat: newChat, onOpenConversation: selectConversation, onNavigate: navigate,
    onToggleCollapse: () => setCollapsed(!collapsed), onClose: closeDrawer,
    onRetry: () => { setConvLoading(true); void refreshConversations(); },
  };

  return (
    <MotionConfig reducedMotion={reduceMotion ? "always" : "user"}>
      <div className={cn("app", reduceMotion && "reduce-motion")}>
        <Sidebar {...sidebarProps} />
        <div className="content">
          {view === "chat" && (
            <ChatScreen title={title} messages={messages} loading={loadingChat} pending={pending} error={sendError}
              mode={mode} isMobile={isMobile} smoothScroll={!reduceMotion} onMenu={openDrawer} onModeChange={setMode}
              onSend={send} onDismissError={() => setSendError(null)} onManageMemories={() => navigate("memories")} />
          )}
          {view === "memories" && <MemoryManagement isMobile={isMobile} onMenu={openDrawer} />}
          {view === "settings" && (
            <SettingsPage reduceMotion={reduceMotion} onReduceMotion={setReduceMotion} isMobile={isMobile} onMenu={openDrawer} />
          )}
        </div>
      </div>
    </MotionConfig>
  );
}
