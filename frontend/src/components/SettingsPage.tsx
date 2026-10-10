import { Menu } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/api";
import type { AppSettings } from "@/types";

interface Props {
  reduceMotion: boolean; onReduceMotion: (v: boolean) => void;
  isMobile: boolean; onMenu: () => void;
}

export function SettingsPage({ reduceMotion, onReduceMotion, isMobile, onMenu }: Props) {
  const [info, setInfo] = useState<AppSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.settings().then(setInfo, (e: Error) => setError(e.message)); }, []);

  return (
    <main className="page" aria-label="Settings">
      <header className="topbar">
        {isMobile && <button className="icon-btn" onClick={onMenu} aria-label="Open menu" aria-controls="sidebar"><Menu size={20} /></button>}
        <h1 className="topbar__title">Settings</h1>
      </header>
      <div className="page__scroll"><div className="page__inner">
        <section className="card" aria-labelledby="s-app">
          <h2 id="s-app">Appearance</h2>
          <label className="toggle">
            <input type="checkbox" checked={reduceMotion} onChange={(e) => onReduceMotion(e.target.checked)} />
            <span><b>Reduce motion</b><span className="muted small"> Turns off entrance animations and ambient lighting. Your system setting is respected by default.</span></span>
          </label>
        </section>
        <section className="card" aria-labelledby="s-ai">
          <h2 id="s-ai">Assistant</h2>
          {error && <p className="bad" role="alert">Could not load settings: {error}</p>}
          {!info && !error && <p className="muted">Loading…</p>}
          {info && (
            <dl className="kv">
              <dt>Chat model</dt><dd>{info.chat_model}</dd>
              <dt>Embedding model</dt><dd>{info.embed_model}</dd>
              <dt>Memory user</dt><dd>{info.user_id}</dd>
            </dl>
          )}
        </section>
        <section className="card" aria-labelledby="s-priv">
          <h2 id="s-priv">Privacy</h2>
          <p className="muted">Everything runs on this computer: the Ollama model, the Qdrant memory store and your conversations.
            Usage telemetry is {info ? (info.telemetry ? "on" : "disabled") : "…"}. These values are configured on the server and are read-only here.</p>
        </section>
      </div></div>
    </main>
  );
}
