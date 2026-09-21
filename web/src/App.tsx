import { useCallback, useEffect, useRef, useState } from "react";
import { api, get } from "./api";
import { Settings } from "./Settings";
import { Loader, Primary } from "./ui";
import { Review } from "./Review";

export function App() {
  const [status, setStatus] = useState<any>(null);
  const [theme, setTheme] = useState<any>(null);
  const [profile, setProfile] = useState<any>({ resume: null, entities: [], saved_answers: 0 });
  const [tab, setTab] = useState<string | null>(null);
  const [answersOpen, setAnswersOpen] = useState(false);

  const refreshStatus = useCallback(() => get("/api/status").then(setStatus), []);
  const refreshProfile = useCallback(() => get("/api/profile").then(setProfile), []);
  useEffect(() => {
    refreshStatus(); refreshProfile();
    const t = setInterval(refreshStatus, 1500);
    return () => clearInterval(t);
  }, [refreshStatus, refreshProfile]);
  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const next = await get("/api/theme");
        if (!stop) setTheme((cur: any) => (cur?.revision === next.revision && cur?.name === next.name ? cur : next));
      } catch { /* server still starting */ }
      if (!stop) timer = setTimeout(load, document.hidden ? 4000 : 1000);
    };
    const now = () => { clearTimeout(timer); load(); };
    document.addEventListener("visibilitychange", now);
    load();
    return () => { stop = true; clearTimeout(timer); document.removeEventListener("visibilitychange", now); };
  }, []);

  // appearance → CSS variables, straight from the theme Omarchy last applied.
  // Text and card colours are mixed from the theme's own background and
  // foreground: several themes (Solitude, White, Everforest…) ship a
  // dark_foreground or lighter_background that is nearly the page colour,
  // so using those directly makes text or cards disappear.
  const a = status?.settings?.appearance;
  useEffect(() => {
    const r = document.documentElement.style;
    const c = theme?.colors; // oma-paster always follows the active Omarchy theme
    const bg = c?.background, fg = c?.foreground;
    const map: Record<string, string | undefined> = {
      "--bg0": bg,
      "--ink": fg,
      "--accent": c?.accent,
      "--sel": c?.selection,
      "--warn": c?.yellow,
      "--danger": c?.bright_red || c?.red,
      "--ok": c?.green,
      "--info": c?.blue,
      "--link": c?.blue,
    };
    for (const [k, v] of Object.entries(map)) v ? r.setProperty(k, v) : r.removeProperty(k);
    if (bg && fg) {
      const lift = c?.mode === "light" ? "black" : "white";
      r.setProperty("--bg-deep", `color-mix(in srgb, ${bg} 88%, black)`);
      r.setProperty("--bg1", `color-mix(in srgb, ${bg} 93%, ${lift})`);
      r.setProperty("--muted", `color-mix(in srgb, ${fg} 62%, ${bg})`);
    } else {
      r.removeProperty("--bg-deep"); r.removeProperty("--bg1"); r.removeProperty("--muted");
    }
    r.setProperty("--fs", `${a?.font_size ?? 14}px`);
    a?.font === "sans" ? r.setProperty("--font", "ui-sans-serif, system-ui, sans-serif") : r.removeProperty("--font");
    r.colorScheme = c?.mode === "light" ? "light" : "dark";
  }, [a, theme]);

  const updateAppearance = (patch: any) => {
    setStatus((s: any) => ({ ...s, settings: { ...s.settings, appearance: { ...s.settings.appearance, ...patch } } }));
    api("/api/settings", { appearance: patch }, "PUT");
  };
  const clearAllData = async () => {
    if (!confirm("Erase your resume, profile details, remembered answers, and oma-paster settings? Downloaded models stay on this machine.")) return;
    await api("/api/data/clear", {});
    await Promise.all([refreshStatus(), refreshProfile()]);
    setAnswersOpen(false); setTab(null);
  }; 

  const models: any[] = status?.models ?? [];
  const loading = models.filter((m) => m.status === "loading" || m.status === "pending");
  const failed = models.filter((m) => m.status === "error");
  const settled = status && loading.length === 0;
  const ready = !!status?.ready;

  return (
    <div className="wrap">
      <header className="top">
        <h1><span className="mark" />oma-paster</h1>
        <div className="right">
          <button className="strip" onClick={() => setTab("Models")} title="Models & settings">
            <span className="segs">{models.map((m) => <span key={m.key} className={`seg ${m.status}`} title={`${m.role}: ${m.status}`} />)}</span>
            {!status ? "connecting…" : loading.length ? `loading models ${models.length - loading.length}/${models.length}` : failed.length ? "model problem" : "models ready"}
          </button>
          <button className="strip" onClick={() => setTab("Appearance")}>settings</button>
          <button className="strip" onClick={() => setAnswersOpen(true)} title="Questions and answers remembered from your applications">
            memory{profile.saved_answers ? ` · ${profile.saved_answers}` : ""}
          </button>
        </div>
      </header>
      <p className="lede">Add your resume once. Paste a job link. It fills the application in a browser window and asks you only what it can't answer.</p>

      {(!settled || failed.length > 0) && status && <Warmup models={models} openSettings={() => setTab("Models")} />}

      <ResumeCard profile={profile} setProfile={setProfile} ready={ready} />
      <JobCard profile={profile} ready={ready} refreshProfile={refreshProfile} />

      <footer className="foot">
        <span>Thoughtful applications, made local.</span>
        <span>Private by default · review every submission</span>
      </footer>

      <Settings tab={tab} setTab={setTab} status={status} refresh={refreshStatus} theme={theme} update={updateAppearance} clearAll={clearAllData} />
      <AnswersDialog open={answersOpen} close={() => setAnswersOpen(false)} onChange={refreshProfile} />
    </div>
  );
}

function Warmup({ models, openSettings }: any) {
  const busy = models.some((m: any) => m.status === "loading" || m.status === "pending");
  return (
    <section className="card">
      <div className="warm">
        {busy ? <Loader /> : <span />}
        <div>
          <b>{busy ? "Warming up the local models" : "A model failed to load"}</b>
          <p className="hint" style={{ margin: ".15rem 0 .5rem" }}>
            {busy ? "First run downloads them once (a few hundred MB); after that this takes seconds." : "Open settings to see why or pick another model."}
          </p>
        </div>
        <span />
        <ul>
          {models.map((m: any) => (
            <li key={m.key}>
              <b>{m.role}</b>
              <span className={m.status === "error" ? "err" : ""}>
                {m.status === "ready" ? `✓ ready · ${m.seconds}s`
                  : m.status === "error" ? m.error
                  : m.status === "pending" ? "waiting…"
                  : `${m.cached === false ? "downloading" : "loading"} · ${m.seconds}s`}
              </span>
            </li>
          ))}
        </ul>
      </div>
      {!busy && <button className="link" onClick={openSettings}>open model settings</button>}
    </section>
  );
}

/* ---------------- step 1 ---------------- */
function ResumeCard({ profile, setProfile, ready }: any) {
  const [msg, setMsg] = useState<{ text: string; kind: string }>({ text: "", kind: "" });
  const [src, setSrc] = useState("");
  const [showText, setShowText] = useState(false);
  const [text, setText] = useState("");
  const [over, setOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const saveTimer = useRef<any>();

  const done = (d: any) => {
    if (!d.ok) return setMsg({ text: d.error || "Failed", kind: "err" });
    setMsg({ text: "", kind: "" }); setSrc(""); setText(""); setShowText(false); setProfile(d);
  };
  const upload = async (file?: File) => {
    if (!file) return;
    setMsg({ text: "reading your resume…", kind: "busy" });
    done(await fetch("/api/resume/upload", { method: "PUT", headers: { "x-filename": file.name }, body: file }).then((r) => r.json()).catch(() => ({ ok: false, error: "Upload failed." })));
  };
  const edit = (i: number, value: string) => {
    const entities = profile.entities.map((e: any, j: number) => (j === i ? { ...e, value } : e));
    setProfile({ ...profile, entities });
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => api("/api/profile", { entities }, "PUT"), 500);
  };

  return (
    <section className="card">
      <h2><span className="n">1</span>Your resume</h2>
      {!profile.resume ? (
        <>
          <label className={`drop ${over ? "over" : ""}`} tabIndex={0}
            onDragOver={(e) => (e.preventDefault(), setOver(true))} onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files[0]); }}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), fileRef.current?.click())}>
            <strong>Drop your resume PDF here</strong>
            <span>or click to choose a file</span>
            <input ref={fileRef} type="file" accept="application/pdf" hidden onChange={(e) => { upload(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
          <div className="row">
            <input type="text" value={src} onChange={(e) => setSrc(e.target.value)} placeholder="…or paste a link / file path to a PDF" spellCheck={false}
              onKeyDown={(e) => e.key === "Enter" && (document.getElementById("load-src") as HTMLElement)?.click()} />
            <button id="load-src" className="btn" onClick={async () => {
              if (!src.trim()) return setMsg({ text: "Paste a link or a file path first.", kind: "err" });
              setMsg({ text: "loading…", kind: "busy" }); done(await api("/api/resume/load", { source: src }));
            }}>load</button>
          </div>
          <button className="link" style={{ display: "block", marginTop: ".6rem", fontSize: ".85rem" }} onClick={() => setShowText(!showText)}>or paste the resume text instead</button>
          {showText && (
            <div>
              <textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste your resume text here" />
              <button className="btn" onClick={async () => { setMsg({ text: "reading…", kind: "busy" }); done(await api("/api/resume/text", { text })); }}>use this text</button>
            </div>
          )}
          {!ready && <p className="hint">You can add it now — reading it starts as soon as the models finish loading.</p>}
        </>
      ) : (
        <>
          <div className="row between">
            <span className="ok">✓ <b>{profile.resume.name}</b></span>
            <span className="row">
              {profile.resume.pdf && <a className="link" href="/resume.pdf" target="_blank" rel="noopener">view</a>}
              <button className="link" onClick={async () => {
                if (!confirm("Remove this resume and its extracted profile details?")) return;
                setProfile(await api("/api/resume/reset", {})); setMsg({ text: "", kind: "" });
              }}>remove</button>
            </span>
          </div>
          <p className="hint">This is what I'll paste into forms. Fix anything that's wrong — edits save automatically.</p>
          <div className="profile">
            {profile.entities.length
              ? profile.entities.map((e: any, i: number) => (
                  <div className="f" key={e.label + i}><span>{e.label}</span><input type="text" value={e.value} onChange={(ev) => edit(i, ev.target.value)} /></div>))
              : <p className="hint">I couldn't find any details in that file. Try a different PDF, or paste the text.</p>}
          </div>
        </>
      )}
      <p className={`msg ${msg.kind}`}>{msg.text}</p>
    </section>
  );
}

/* ---------------- step 2 + 3 ---------------- */
function JobCard({ profile, ready, refreshProfile }: any) {
  const [url, setUrl] = useState("");
  const [msg, setMsg] = useState<{ text: string; kind: string }>({ text: "", kind: "" });
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<any>(null);
  const reviewRef = useRef<HTMLDivElement>(null);

  const open = async () => {
    if (!profile.resume) return setMsg({ text: "Add your resume first (step 1) — that's what I fill the form from.", kind: "err" });
    if (!ready) return setMsg({ text: "The models are still loading — give it a few seconds.", kind: "err" });
    if (!url.trim()) return setMsg({ text: "Paste the link to the job application page.", kind: "err" });
    setBusy(true); setMsg({ text: "Opening the page in a browser window and filling it in…", kind: "busy" });
    const d = await api("/api/job/open", { url });
    setBusy(false);
    if (!d.ok) return setMsg({ text: d.error || "Couldn't open that page.", kind: "err" });
    setMsg({ text: "Done — look at the browser window to see it filled in.", kind: "ok" });
    setJob(d);
    setTimeout(() => reviewRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
  };

  return (
    <>
      <section className={`card ${profile.resume ? "" : "dim"}`}>
        <h2><span className="n">2</span>Job application link</h2>
        <div className="row">
          <input type="text" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://jobs.example.com/apply/123" spellCheck={false} onKeyDown={(e) => e.key === "Enter" && open()} />
          <Primary onClick={open} disabled={busy} style={{ flex: "none" }}>open &amp; fill</Primary>
        </div>
        <p className={`msg ${msg.kind}`}>{msg.text}</p>
      </section>
      {job && (
        <div ref={reviewRef}>
          <Review key={job.url + job.fields.length + Object.keys(job.suggestions).join()} job={job} setJob={setJob} setMsg={setMsg} refreshProfile={refreshProfile} />
        </div>
      )}
    </>
  );
}

const TYPE_LABEL: Record<string, string> = {
  text: "text", email: "email", tel: "phone", url: "link", number: "number",
  textarea: "long answer", radio: "choice", checkbox: "choice", select: "choice",
  combobox: "choice", date: "date", file: "file",
};

function when(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function AnswersDialog({ open, close, onChange }: any) {
  const ref = useRef<HTMLDialogElement>(null);
  const [list, setList] = useState<any[]>([]);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draftQ, setDraftQ] = useState("");
  const [draftA, setDraftA] = useState("");
  const [note, setNote] = useState("");
  const [savedKey, setSavedKey] = useState("");
  const load = () => get("/api/answers").then((d) => setList(d.answers ?? []));
  useEffect(() => {
    const d = ref.current!;
    if (open && !d.open) { setQuery(""); setEditing(null); setNote(""); load(); d.showModal(); }
    if (!open && d.open) d.close();
  }, [open]);

  const q = query.trim().toLowerCase();
  const shown = q ? list.filter((a) => `${a.q} ${a.a} ${(a.wordings || []).join(" ")}`.toLowerCase().includes(q)) : list;

  const save = async (a: any) => {
    const answer = draftA.trim();
    if (!answer) return setNote("An answer can't be empty. Delete the memory instead.");
    const r = await api(`/api/answers/${encodeURIComponent(a.key)}`, { answer, question: draftQ.trim() || a.q }, "PUT");
    if (!r.ok) return setNote(r.error || "Couldn't save that.");
    setEditing(null); setNote(""); setSavedKey(`${a.key}:${Date.now()}`); load(); onChange();
  };

  return (
    <dialog ref={ref} className="memory" onClose={close} onClick={(e) => e.target === ref.current && close()}>
      <header>
        <div>
          <h2>Memory</h2>
          <p className="hint">Questions you've answered, and the answer oma-paster will reuse. A reworded question is suggested — you still confirm it.</p>
        </div>
        <button className="link" onClick={close}>close</button>
      </header>
      <div className="mem-tools">
        <input type="text" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search questions or answers" spellCheck={false} />
        <span className="note">{shown.length}{q ? ` of ${list.length}` : ""}</span>
      </div>
      <div className="mem-list">
        {shown.length ? shown.map((a) => {
          const openRow = editing === a.key;
          const also = (a.wordings || []).filter((w: string) => w !== a.q);
          return (
            <article className={`mem ${openRow ? "open" : ""}`} key={a.key}>
              <div className="mem-q">
                <p>{a.q}</p>
                <span className="mem-meta">
                  {a.type ? <span className="tag">{TYPE_LABEL[a.type] || a.type}</span> : null}
                  <span>used {a.n || 1}×</span>
                  {when(a.updated || a.created) && <span>{a.updated ? "updated" : "saved"} {when(a.updated || a.created)}</span>}
                </span>
              </div>
              {openRow ? (
                <div className="mem-edit">
                  <label>Question<input type="text" value={draftQ} onChange={(e) => setDraftQ(e.target.value)} /></label>
                  <label>Answer<textarea rows={Math.min(8, Math.max(2, draftA.split("\n").length))} value={draftA} onChange={(e) => setDraftA(e.target.value)} /></label>
                  <div className="row">
                    <button className="btn primary" onClick={() => save(a)}>save</button>
                    <button className="btn" onClick={() => setEditing(null)}>cancel</button>
                  </div>
                </div>
              ) : (
                <>
                  <pre className="mem-a">{a.a}</pre>
                  {savedKey.startsWith(a.key + ":") && <span key={savedKey} className="saved" role="status"><i />saved</span>}
                  {also.length > 0 && <p className="also">Also matched as {also.map((w: string) => `“${w}”`).join(", ")}</p>}
                  <div className="row mem-actions">
                    <button className="link" onClick={() => { setEditing(a.key); setDraftQ(a.q); setDraftA(a.a); setNote(""); }}>edit</button>
                    <button className="link" onClick={async () => {
                      await api(`/api/answers/${encodeURIComponent(a.key)}`, undefined, "DELETE");
                      if (editing === a.key) setEditing(null);
                      load(); onChange();
                    }}>forget</button>
                  </div>
                </>
              )}
            </article>
          );
        }) : <p className="hint empty">{list.length ? "Nothing matches that search." : "Nothing remembered yet. Answers you type into an application show up here."}</p>}
      </div>
      <footer>
        <span className="note">{note}</span>
        {list.length > 0 && <button className="btn" onClick={async () => {
          if (confirm("Forget every remembered answer? Your resume stays.")) {
            await api("/api/answers/clear", {}); onChange(); close();
          }
        }}>forget all</button>}
      </footer>
    </dialog>
  );
}
