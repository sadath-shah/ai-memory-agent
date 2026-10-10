import { Brain, History, MessageSquarePlus, PanelLeftClose, PanelLeftOpen, Settings, Sparkles, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatWhen } from "@/lib/format";
import type { ConversationSummary, View } from "@/types";

interface Props {
  collapsed: boolean;
  mobile: boolean;
  open: boolean;                       // mobile drawer
  view: View;
  conversations: ConversationSummary[];
  conversationsError: string | null;
  conversationsLoading: boolean;
  activeId: string | null;
  locked: boolean;                     // a request is in flight: don't switch chats
  onNewChat: () => void;
  onOpenConversation: (id: string) => void;
  onNavigate: (view: View) => void;
  onToggleCollapse: () => void;
  onClose: () => void;
  onRetry: () => void;
}

export function Sidebar(p: Props) {
  const compact = p.collapsed && !p.mobile;
  const hidden = p.mobile && !p.open;
  // `inert` isn't in React 18's types: pass it as a plain attribute.
  const inertProps = (hidden ? { inert: "" } : {}) as Record<string, string>;
  return (
    <>
      {p.mobile && p.open && <div className="backdrop" onClick={p.onClose} aria-hidden />}
      <aside id="sidebar" className={cn("sidebar", compact && "sidebar--compact", p.mobile && "sidebar--drawer", p.mobile && p.open && "sidebar--open")}
        aria-label="Sidebar" {...inertProps}>
        <div className="sidebar__head">
          <div className="brand" title="AI Memory Agent">
            <span className="brand__logo"><Sparkles size={16} aria-hidden /></span>
            {!compact && <span className="brand__name">AI Memory Agent</span>}
          </div>
          {p.mobile ? (
            <button className="icon-btn" onClick={p.onClose} aria-label="Close menu"><X size={18} /></button>
          ) : (
            <button className="icon-btn" onClick={p.onToggleCollapse} aria-expanded={!p.collapsed} aria-controls="sidebar"
              aria-label={p.collapsed ? "Expand sidebar" : "Collapse sidebar"} title={p.collapsed ? "Expand sidebar" : "Collapse sidebar"}>
              {p.collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            </button>
          )}
        </div>

        <button className="new-chat" onClick={p.onNewChat} disabled={p.locked} aria-label="New chat" title="New chat">
          <MessageSquarePlus size={18} aria-hidden />{!compact && <span>New chat</span>}
        </button>

        <nav className="sidebar__history" aria-label="Conversations">
          {compact ? (
            <button className="nav-item" onClick={p.onToggleCollapse} aria-label="Show conversations" title="Conversations">
              <History size={18} aria-hidden />
            </button>
          ) : (
            <>
              <div className="section-label">Conversations</div>
              {p.conversationsLoading && <div className="muted small pad">Loading…</div>}
              {p.conversationsError && (
                <div className="small pad bad">Couldn't load conversations.{" "}
                  <button className="link" onClick={p.onRetry}>Retry</button></div>
              )}
              {!p.conversationsLoading && !p.conversationsError && p.conversations.length === 0 && (
                <div className="muted small pad">No conversations yet. Start one below.</div>
              )}
              <ul className="convs">
                {p.conversations.map((c) => (
                  <li key={c.id}>
                    <button className={cn("conv", p.view === "chat" && c.id === p.activeId && "conv--active")}
                      aria-current={p.view === "chat" && c.id === p.activeId ? "page" : undefined}
                      disabled={p.locked} onClick={() => p.onOpenConversation(c.id)} title={c.title}>
                      <span className="conv__title">{c.title}</span>
                      <span className="conv__when">{formatWhen(c.updated_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </nav>

        <nav className="sidebar__foot" aria-label="Pages">
          <button className={cn("nav-item", p.view === "memories" && "nav-item--on")} onClick={() => p.onNavigate("memories")}
            aria-current={p.view === "memories" ? "page" : undefined} aria-label="Memory Management" title="Memory Management">
            <Brain size={18} aria-hidden />{!compact && <span>Memory Management</span>}
          </button>
          <button className={cn("nav-item", p.view === "settings" && "nav-item--on")} onClick={() => p.onNavigate("settings")}
            aria-current={p.view === "settings" ? "page" : undefined} aria-label="Settings" title="Settings">
            <Settings size={18} aria-hidden />{!compact && <span>Settings</span>}
          </button>
        </nav>
      </aside>
    </>
  );
}
