import { motion } from "framer-motion";
import { Brain, Menu, Pencil, RefreshCw, Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { cn } from "@/lib/utils";
import { formatWhen } from "@/lib/format";
import type { Memory } from "@/types";
import { ConfirmDialog } from "./ConfirmDialog";

type Flash = { kind: "good" | "bad"; text: string } | null;

export function MemoryManagement({ onMenu, isMobile }: { onMenu: () => void; isMobile: boolean }) {
  const [items, setItems] = useState<Memory[]>([]);
  const [count, setCount] = useState<number | null>(null);    // straight from the backend response
  const [userId, setUserId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [flash, setFlash] = useState<Flash>(null);
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [toDelete, setToDelete] = useState<Memory | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const r = await api.memories();
      setItems(r.memories); setCount(r.count); setUserId(r.user_id); setError(null);
    } catch (e) {
      setItems([]); setCount(null); setError((e as Error).message);
    }
    setLoading(false);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return q ? items.filter((m) => m.memory.toLowerCase().includes(q)) : items;
  }, [items, filter]);

  async function saveEdit() {
    if (!editing) return;
    const text = editing.text.trim();
    if (!text) { setFlash({ kind: "bad", text: "The memory text can't be empty." }); return; }
    if (text === items.find((m) => m.id === editing.id)?.memory) { setEditing(null); return; }
    setSaving(true);
    try {
      const r = await api.updateMemory(editing.id, text);      // UI changes only after the backend confirms
      setEditing(null); setFlash({ kind: "good", text: r.message }); await load(true);
    } catch (e) { setFlash({ kind: "bad", text: `Update failed: ${(e as Error).message}` }); }
    setSaving(false);
  }

  async function confirmDelete() {
    if (!toDelete) return;
    setDeleting(true);
    try {
      const r = await api.deleteMemory(toDelete.id);
      setToDelete(null); setFlash({ kind: "good", text: r.message }); await load(true);
    } catch (e) { setToDelete(null); setFlash({ kind: "bad", text: `Delete failed: ${(e as Error).message}` }); }
    setDeleting(false);
  }

  return (
    <main className="page" aria-label="Memory Management">
      <header className="topbar">
        {isMobile && <button className="icon-btn" onClick={onMenu} aria-label="Open menu" aria-controls="sidebar"><Menu size={20} /></button>}
        <h1 className="topbar__title">Memory Management</h1>
        <span className="badge" aria-label="Number of memories" data-testid="count">{count ?? "–"}</span>
        <button className="btn" onClick={() => { setFlash(null); void load(); }} disabled={loading} aria-label="Refresh memories">
          <RefreshCw size={15} className={cn(loading && "spin")} aria-hidden /> Refresh
        </button>
      </header>
      <div className="page__scroll">
        <div className="page__inner">
          <p className="muted">Long-term memories stored locally for <b>{userId || "…"}</b>. Changes here apply to everything the assistant knows.</p>
          <label className="search"><Search size={16} aria-hidden /><span className="sr-only">Filter memories</span>
            <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search memories…" autoComplete="off" />
          </label>
          <div className={cn("flash", flash?.kind)} role="status" aria-live="polite">
            {flash?.text ?? (filter && count !== null ? `${shown.length} of ${count} match “${filter.trim()}”` : "")}
          </div>

          {loading && <ul className="mem-list" aria-busy>{[0, 1, 2, 3].map((i) => <li key={i} className="skeleton" />)}</ul>}
          {!loading && error && (
            <div className="state bad" role="alert">Could not load memories: {error}
              <div><button className="btn" onClick={() => void load()}>Retry</button></div></div>
          )}
          {!loading && !error && items.length === 0 && (
            <div className="state"><Brain size={22} aria-hidden /><p>No memories yet.</p>
              <p className="muted">Tell the assistant something about yourself in a chat and it will show up here.</p></div>
          )}
          {!loading && !error && items.length > 0 && shown.length === 0 && <div className="state">No memories match your search.</div>}

          {!loading && !error && shown.length > 0 && (
            <ul className="mem-list">
              {shown.map((m) => (
                <motion.li key={m.id} className="mem" layout="position" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
                  {editing?.id === m.id ? (
                    <>
                      <textarea className="mem__edit" value={editing.text} aria-label="Edit memory text" autoFocus
                        onChange={(e) => setEditing({ id: m.id, text: e.target.value })}
                        onKeyDown={(e) => { if (e.key === "Escape") setEditing(null); }} />
                      <div className="row">
                        <button className="btn btn--primary" onClick={() => void saveEdit()} disabled={saving}>Save</button>
                        <button className="btn" onClick={() => setEditing(null)} disabled={saving}>Cancel</button>
                      </div>
                    </>
                  ) : (
                    <>
                      <p className="mem__text">{m.memory}</p>
                      <div className="mem__meta">
                        <span className="muted small">{m.updated_at ? "Updated" : "Added"} {formatWhen(m.updated_at || m.created_at)}</span>
                        <span className="row">
                          <button className="btn" onClick={() => { setFlash(null); setEditing({ id: m.id, text: m.memory }); }} aria-label={`Update memory: ${m.memory}`}>
                            <Pencil size={14} aria-hidden /> Update</button>
                          <button className="btn btn--danger" onClick={() => setToDelete(m)} aria-label={`Delete memory: ${m.memory}`}>
                            <Trash2 size={14} aria-hidden /> Delete</button>
                        </span>
                      </div>
                    </>
                  )}
                </motion.li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <ConfirmDialog open={toDelete !== null} title="Delete this memory?" body={toDelete?.memory ?? ""} confirmLabel="Delete"
        busy={deleting} onConfirm={() => void confirmDelete()} onCancel={() => { setToDelete(null); setFlash({ kind: "good", text: "Deletion cancelled. Nothing was deleted." }); }} />
    </main>
  );
}
