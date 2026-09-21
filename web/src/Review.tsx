import { useEffect, useMemo, useRef, useState } from "react";
import { api, get } from "./api";
import { Primary } from "./ui";

type Mark = "typing" | "done" | "fail";

function Saved() {
  return <span className="saved" role="status"><i />saved</span>;
}

function Control({ f, value, set, final }: any) {
  const name = f.id;
  switch (f.type) {
    case "select":
      return <select name={name} value={value} onChange={(e) => { set(e.target.value); final(e.target.value); }}><option value="" />{f.options.map((o: string) => <option key={o}>{o}</option>)}</select>;
    case "textarea":
      return <textarea rows={4} value={value} onChange={(e) => set(e.target.value)} onBlur={() => final()} />;
    case "radio":
      return <div className="opts">{f.options.map((o: any) => (
        <label className="opt" key={o.id}><input type="radio" name={name} checked={value.toLowerCase() === o.label.toLowerCase()} onChange={() => { set(o.label); final(o.label); }} /> {o.label}</label>))}</div>;
    case "checkbox": {
      const toggle = (label: string, on: boolean) => {
        const next = f.single ? (on ? "yes" : "") : [...new Set((value ? value.split("; ") : []).filter((v: string) => v !== label).concat(on ? [label] : []))].join("; ");
        set(next); final(next);
      };
      return <div className="opts">{f.options.map((o: any) => (
        <label className="opt" key={o.id}><input type="checkbox" checked={f.single ? /^(yes|true)$/i.test(value) : value.split("; ").includes(o.label)} onChange={(e) => toggle(o.label, e.target.checked)} /> {o.label}</label>))}</div>;
    }
    case "file":
      return <input type="text" value={value} onChange={(e) => set(e.target.value)} onBlur={() => final()} placeholder="full path to a file" />;
    default:
      return <input type="text" value={value} onChange={(e) => set(e.target.value)} onBlur={() => final()} placeholder={f.placeholder || ""} />;
  }
}

export function Review({ job, setJob, setMsg, refreshProfile }: any) {
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(job.fields.map((f: any) => [f.id, job.suggestions[f.id]?.value ?? ""])));
  const [marks, setMarks] = useState<Record<string, Mark>>({});
  const [saved, setSaved] = useState<Record<string, number>>({});
  const [captcha, setCaptcha] = useState<any>(job.captcha);
  const [shot, setShot] = useState<string | null>(null);
  const [summary, setSummary] = useState("");
  const chain = useRef<Record<string, Promise<any>>>({});
  const timers = useRef<Record<string, any>>({});
  const latest = useRef(values); latest.current = values;

  const groups = useMemo(() => {
    const g: Record<string, any[]> = { need: [], check: [], filled: [], optional: [] };
    for (const f of job.fields) {
      const s = job.suggestions[f.id];
      (s?.source === "similar" ? g.check : s && !job.errors[f.id] ? g.filled : f.required ? g.need : g.optional).push(f);
    }
    return g;
  }, [job]);

  const left = (fs: any[]) => fs.filter((f) => marks[f.id] !== "done").length;
  const needLeft = left(groups.need), checkLeft = left(groups.check);

  const waiting = captcha && (captcha.challenge || (captcha.present && !captcha.solved));
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(async () => { const s = await get("/api/job/status"); if (s.captcha) setCaptcha(s.captcha); }, 2000);
    return () => clearInterval(t);
  }, [waiting]);

  // push one value into the live page (serialised per field so a slow request can't clobber a newer keystroke)
  const push = (id: string, value: string, isFinal: boolean) => {
    if (!value) return;
    clearTimeout(timers.current[id]);
    setMarks((m) => (isFinal ? m : { ...m, [id]: "typing" }));
    const run = (chain.current[id] ?? Promise.resolve()).then(() => api("/api/job/field", { id, value: latest.current[id] || value, remember: isFinal }));
    chain.current[id] = run.catch(() => {});
    run.then((r: any) => {
      if (r.captcha) setCaptcha(r.captcha);
      setMarks((m) => ({ ...m, [id]: r.ok ? (isFinal ? "done" : "typing") : "fail" }));
      if (r.remembered) setSaved((s) => ({ ...s, [id]: (s[id] ?? 0) + 1 }));
    });
  };
  const setValue = (id: string, v: string, live: boolean) => {
    setValues((s) => ({ ...s, [id]: v }));
    if (live) { clearTimeout(timers.current[id]); timers.current[id] = setTimeout(() => push(id, v, false), 350); }
  };

  const row = (f: any, cls: string) => {
    const s = job.suggestions[f.id];
    const mark = marks[f.id];
    const tag = mark === "done" ? ["sent", "sent ✓"] : mark === "typing" ? ["sent", "typing → browser"] : mark === "fail" ? ["need", "couldn't fill"]
      : cls === "need" ? ["need", "needs you"] : cls === "check" ? ["similar", "similar · confirm"] : cls === "filled" ? [s.source, s.source] : ["", "optional"];
    const open = mark !== "done" && (cls === "need" || cls === "check" || mark === "fail");
    const title = f.type === "checkbox" && f.single ? "" : f.label || "(unlabelled question)";
    return (
      <div key={f.id} className={`q ${open && cls !== "filled" ? cls : ""}`}>
        <label>{title}{f.required ? " *" : ""}<span className={`tag ${tag[0]}`}>{tag[1]}</span>{saved[f.id] ? <Saved key={saved[f.id]} /> : null}</label>
        {cls === "check" && mark !== "done" && (
          <div className="from">You answered <b>“{s.from}”</b> before. Same thing? <button className="link" onClick={() => push(f.id, values[f.id], true)}>use this answer</button></div>)}
        <Control f={f} value={values[f.id] ?? ""} set={(v: string) => setValue(f.id, v, ["text", "email", "tel", "url", "number", "textarea", "combobox", "date"].includes(f.type))} final={(v?: string) => push(f.id, v ?? values[f.id], true)} />
      </div>
    );
  };

  const rescan = async () => { setSummary("rescanning…"); const d = await api("/api/job/rescan", {}); setMarks({}); setJob(d); };
  const submit = async () => {
    const n = needLeft + checkLeft;
    if (!confirm(n ? `${n} question(s) are still unanswered or unconfirmed. Submit anyway?` : "Submit this application now?")) return;
    setMsg({ text: "submitting…", kind: "busy" });
    const r = await api("/api/job/submit", {});
    if (r.captcha) { setCaptcha({ present: true, solved: false }); return setMsg({ text: r.message, kind: "err" }); }
    if (r.next_step) { setMarks({}); setJob(r); return setMsg({ text: "Next step loaded — review it and submit again.", kind: "ok" }); }
    if (!r.ok) return setMsg({ text: r.message || r.error || "Submit failed.", kind: "err" });
    if (r.screenshot) setShot(r.screenshot);
    setMsg(r.success ? { text: "Submitted — the site is showing a confirmation. 🎉", kind: "ok" }
      : r.invalid?.length ? { text: "The site rejected some fields — check the browser window.", kind: "err" }
      : { text: "Clicked submit — check the browser window or the screenshot below to confirm.", kind: "" });
    refreshProfile();
  };

  const parts = [];
  if (needLeft) parts.push(<span key="n" style={{ color: "var(--warn)" }}>{needLeft} required question{needLeft > 1 ? "s" : ""} need{needLeft > 1 ? "" : "s"} your answer</span>);
  if (checkLeft) parts.push(<span key="c" style={{ color: "var(--accent)" }}>{checkLeft} suggested from past answers — confirm {checkLeft > 1 ? "them" : "it"}</span>);

  return (
    <section className="card">
      <h2><span className="n">3</span>Review &amp; submit</h2>
      {waiting && <div className="banner">There's a captcha in the browser window — solve it there, then press submit. oma-paster never solves captchas for you.</div>}
      <p className="summary">
        {!job.fields.length ? "No questions found. If the page needs a click first (like an “Apply” button), do that in the browser window, then press “rescan page”."
          : parts.length ? <>{parts.reduce((a: any, b: any) => [a, " · ", b] as any)}. Type below — it appears in the browser window as you type.</>
          : <><span className="ok">Nothing left to answer.</span> Check the browser window, then submit.</>}
        {summary}
      </p>
      <div className="group">{groups.need.map((f) => row(f, "need"))}</div>
      {groups.check.length > 0 && <div className="group"><h3>Check these — they look like questions you've answered before</h3>{groups.check.map((f) => row(f, "check"))}</div>}
      {groups.filled.length > 0 && <details className="group"><summary>✓ {groups.filled.length} filled from your resume / saved answers (click to review)</summary>{groups.filled.map((f) => row(f, "filled"))}</details>}
      {groups.optional.length > 0 && <details className="group"><summary>{groups.optional.length} optional question{groups.optional.length > 1 ? "s" : ""} left blank (click to answer)</summary>{groups.optional.map((f) => row(f, "optional"))}</details>}
      <div className="bar">
        <Primary onClick={submit}>submit application</Primary>
        <button className="btn" onClick={rescan}>rescan page</button>
        <span className="hint grow">Answers you give are pasted into the browser window as you go. Nothing is submitted until you press submit.</span>
      </div>
      {shot && <img className="shot" src={shot} alt="page after submit" />}
    </section>
  );
}
