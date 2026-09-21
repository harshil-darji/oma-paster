import { useEffect, useRef, useState } from "react";
import { MagnetTabs } from "@/components/obsidian/magnet-tabs";
import { api, get } from "./api";
import { Loader, Primary } from "./ui";

export const TABS = ["Models", "Appearance", "About"];

function ModelCard({ m }: { m: any }) {
  return (
    <div className="mcard">
      <h3>
        {m.role} <span className={`chip ${m.status}`}>{m.status}</span>
        {m.seconds != null && <span className="chip">{m.status === "loading" ? `${m.seconds}s…` : `${m.seconds}s to load`}</span>}
      </h3>
      <p className="note" style={{ margin: ".1rem 0" }}>{m.blurb}</p>
      <p className="note" style={{ margin: ".1rem 0" }}>model: <b style={{ color: "var(--ink)", fontWeight: 400 }}>{m.model_id}</b></p>
      {m.status === "loading" && (
        <>
          <div className="bar-ind" />
          <p className="note" style={{ margin: 0 }}>
            {m.cached === false ? "First run — downloading the weights from Hugging Face (one-time, then cached on disk)…" : "Loading from the local cache into memory…"}
          </p>
        </>
      )}
      {m.error && <p className="note" style={{ color: "var(--danger)" }}>{m.error}</p>}
      {m.note && <p className="note" style={{ color: "var(--warn)" }}>{m.note}</p>}
    </div>
  );
}

function ModelsTab({ status, refresh }: any) {
  const { settings, options, models, cuda } = status;
  const [ext, setExt] = useState(settings.extractor_model);
  const [mat, setMat] = useState(settings.matcher_model);
  const [device, setDevice] = useState(settings.device);
  const known = (kind: string, id: string) => options[kind].some((o: any) => o.id === id);
  const [extCustom, setExtCustom] = useState(!known("extractor", settings.extractor_model));
  const [matCustom, setMatCustom] = useState(!known("matcher", settings.matcher_model));
  const changed = ext !== settings.extractor_model || mat !== settings.matcher_model || device !== settings.device;
  const busy = models.some((m: any) => m.status === "loading");

  const picker = (kind: "extractor" | "matcher", value: string, set: (v: string) => void, custom: boolean, setCustom: (b: boolean) => void) => (
    <div className="setrow">
      <div>
        <label>{kind === "extractor" ? "Resume reader model" : "Question-memory model"}</label>
        <small>{options[kind].find((o: any) => o.id === value)?.note ?? "custom Hugging Face model id"}</small>
      </div>
      <div style={{ display: "grid", gap: ".4rem" }}>
        <select
          value={custom ? "__custom" : value}
          onChange={(e) => (e.target.value === "__custom" ? setCustom(true) : (setCustom(false), set(e.target.value)))}
        >
          {options[kind].map((o: any) => <option key={o.id} value={o.id}>{o.label}</option>)}
          <option value="__custom">custom…</option>
        </select>
        {custom && <input type="text" value={value} onChange={(e) => set(e.target.value)} placeholder="org/model-name" spellCheck={false} />}
      </div>
    </div>
  );

  return (
    <>
      <div className="callout">Everything runs natively on this machine ({status.settings.device.toUpperCase()}). Nothing about your resume or answers is sent to any AI service.</div>
      {models.map((m: any) => <ModelCard key={m.key} m={m} />)}
      <div className="mcard">
        <h3>Change models</h3>
        {picker("extractor", ext, setExt, extCustom, setExtCustom)}
        {picker("matcher", mat, setMat, matCustom, setMatCustom)}
        <div className="setrow">
          <div><label>Field matcher (cua-s1)</label><small>only one model exists for this today</small></div>
          <span className="note">cua-ai/cua-s1-forms</span>
        </div>
        <div className="setrow">
          <div><label>Run on</label><small>{cuda ? "NVIDIA GPU detected" : "no GPU detected — CPU only on this machine"}</small></div>
          <select value={device} onChange={(e) => setDevice(e.target.value)}>
            <option value="cpu">CPU</option>
            <option value="cuda" disabled={!cuda}>GPU (CUDA)</option>
          </select>
        </div>
        <div className="row" style={{ marginTop: ".6rem", justifyContent: "space-between" }}>
          <span className="note">Switching downloads the model on first use. If it fails, the previous one keeps working. Re-load your resume to re-read it with a new reader model.</span>
          <Primary disabled={!changed || busy} onClick={async () => { await api("/api/settings", { extractor_model: ext, matcher_model: mat, device }, "PUT"); refresh(); }}>
            save &amp; reload
          </Primary>
        </div>
      </div>
    </>
  );
}

function AppearanceTab({ settings, theme, update }: any) {
  const a = settings.appearance;
  const c = theme?.colors ?? {};
  const palette = ["background", "darker_background", "lighter_background", "selection", "muted", "foreground", "accent", "red", "orange", "yellow", "green", "cyan", "blue", "magenta", "brown"];
  return (
    <>
      <div className="setrow">
        <div>
          <label>Omarchy theme</label>
          <small>Always follows <code>omarchy theme set</code> — currently <b>{theme?.name ?? "…"}</b></small>
        </div>
      </div>
      <div className="swatches" title="Active Omarchy palette">
        {palette.map((k) => c[k] && <i key={k} style={{ background: c[k] }} title={`${k} ${c[k]}`} />)}
      </div>
      <div className="setrow">
        <div><label>Text size</label><small>{a.font_size}px</small></div>
        <input type="range" min={12} max={18} value={a.font_size} onChange={(e) => update({ font_size: +e.target.value })} />
      </div>
      <div className="setrow">
        <div><label>Font</label><small>Omarchy's monospace, or the system sans-serif</small></div>
        <select value={a.font} onChange={(e) => update({ font: e.target.value })}>
          <option value="mono">JetBrainsMono Nerd (Omarchy)</option>
          <option value="sans">System sans-serif</option>
        </select>
      </div>
    </>
  );
}

function AboutTab({ clearAll }: { clearAll: () => void }) {
  const [s, setS] = useState<any>(null);
  useEffect(() => { get("/api/about").then(setS); }, []);
  const rows: [string, string][] = s ? [
    ["oma-paster", s.app_version], ["Runs on", `${s.device.toUpperCase()} · ${s.platform}`], ["Python / PyTorch", `${s.python} / ${s.torch}`],
    ["Browser automation", `Playwright ${s.playwright} → ${s.browser}`], ["Omarchy theme", s.theme], ["Your data", s.data_dir],
  ] : [];
  return (
    <>
      <p>Fill job applications from your resume, in a real browser window — locally.</p>
      <dl className="kv">{rows.flatMap(([k, v]) => [<dt key={k}>{k}</dt>, <dd key={k + "v"}>{v}</dd>])}</dl>
      <h3 style={{ marginTop: "1.2rem" }}>What leaves this machine</h3>
      <p className="note">Only three things touch the network: the one-time download of model weights from Hugging Face, the job page you open, and the application you choose to submit. Your resume, saved answers and settings stay in the data folder above (files readable only by you). No telemetry.</p>
      <a className="github-link" href="https://github.com/harshil-darji/oma-paster" target="_blank" rel="noreferrer">
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 0a8 8 0 0 0-2.53 15.59c.4.07.55-.17.55-.38v-1.49c-2.23.49-2.7-.95-2.7-.95-.36-.93-.89-1.18-.89-1.18-.73-.5.06-.49.06-.49.8.06 1.23.83 1.23.83.72 1.22 1.87.87 2.33.67.07-.51.28-.87.51-1.07-1.78-.2-3.65-.88-3.65-3.96 0-.88.32-1.6.83-2.16-.08-.2-.36-1.02.08-2.13 0 0 .68-.22 2.2.82a7.7 7.7 0 0 1 4.01 0c1.53-1.04 2.2-.82 2.2-.82.44 1.11.16 1.93.08 2.13.52.56.83 1.28.83 2.16 0 3.09-1.88 3.75-3.66 3.95.29.25.54.73.54 1.48v2.2c0 .21.14.45.55.38A8 8 0 0 0 8 0Z" /></svg>
        <span>View the source on GitHub</span>
      </a>
      <div className="data-danger">
        <div><label>Local application data</label><small>Erase your resume, extracted profile details, remembered answers, and settings. Downloaded model files are kept.</small></div>
        <button className="link danger-link" onClick={clearAll}>erase all data</button>
      </div>
    </>
  );
}

export function Settings({ tab, setTab, status, refresh, theme, update, clearAll }: any) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current!;
    if (tab && !d.open) d.showModal();
    if (!tab && d.open) d.close();
  }, [tab]);
  return (
    <dialog ref={ref} className="settings" onClose={() => setTab(null)} onClick={(e) => e.target === ref.current && setTab(null)}>
      <header>
        <h2>Settings</h2>
        <button className="link" onClick={() => setTab(null)}>close</button>
      </header>
      <div className="tabs">
        <MagnetTabs slug="settings" options={TABS} activeTab={tab ?? "Models"} onSelect={setTab} />
      </div>
      <div className="body">
        {!status ? <Loader /> : tab === "Models" ? <ModelsTab key={JSON.stringify(status.settings)} status={status} refresh={refresh} />
          : tab === "Appearance" ? <AppearanceTab settings={status.settings} theme={theme} update={update} />
          : tab === "About" ? <AboutTab clearAll={clearAll} /> : null}
      </div>
    </dialog>
  );
}
