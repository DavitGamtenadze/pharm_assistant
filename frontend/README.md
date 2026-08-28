# Medical Document Assistant frontend

React, TypeScript, and Vite client for the medical document workspace. Upload
PDFs, ask questions about the selected sources, inspect page-level citations,
and optionally search Europe PMC.

## Local development

```powershell
npm install
npm run dev
```

Open `http://localhost:5173`, drop a PDF into the source library, then ask a
question. Copy `.env.example` to `.env` when the backend is not running at
`http://localhost:8000`. The client sends `VITE_API_KEY` as `X-API-Key` when
configured.

Europe PMC access is keyless and needs no frontend environment variable.

## Checks

```powershell
npm run lint
npm run build
```
