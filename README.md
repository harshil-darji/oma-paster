<div align="center">

# ✦ oma-paster

### A local-first workspace for thoughtful job applications.

Fill application forms from your resume, remember the answers that matter, and review everything before it is submitted.

[⭐ Star on GitHub](https://github.com/harshil-darji/oma-paster) · [Report an issue](https://github.com/harshil-darji/oma-paster/issues)

</div>

## ✨ What it does

- Reads a PDF, link, or pasted resume locally
- Opens a real browser and fills application fields for review
- Remembers answers to recurring questions and recognises reworded versions
- Keeps your resume, profile, and memory on your machine
- Follows your active Omarchy theme

## 🚀 Install

**Requires:** Omarchy, Python 3.12, [uv](https://docs.astral.sh/uv/), and Chromium.

```bash
git clone https://github.com/harshil-darji/oma-paster.git
cd oma-paster
uv sync
uv run oma-paster
```

On first launch, the local models download once. Then open **oma-paster** from your terminal or Walker.

## 🧭 How it works

1. Add your resume and correct any extracted details.
2. Paste a job application URL and choose **open & fill**.
3. Review suggestions in the browser and answer anything left over.
4. Open **memory** to search, edit, or remove remembered answers.
5. Submit only when you are ready.

## 🔒 Your data

Your resume, profile, remembered answers, and settings live in `~/.local/share/oma-paster` with owner-only permissions. Model downloads, the application page you open, and any submission you choose to make use the network. There is no telemetry.

## 🎬 Demo forms

Two fictional forms are included for a safe memory demo. Serve them locally, then paste each URL into oma-paster:

```bash
cd demo
python -m http.server 8080
```

Start with `http://127.0.0.1:8080/01-first-application.html`, answer the sponsorship question, then open `http://127.0.0.1:8080/02-memory-application.html` to show the reworded memory suggestion.

## 🛠 Development

The Python server serves the built UI from `static/`. To work on the React UI:

```bash
cd web
npm install
npm run dev
```

Build production assets with `npm run build`.

## 📄 License

[MIT](LICENSE)
