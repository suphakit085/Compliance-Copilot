# Compliance Copilot — web

Next.js 16 + shadcn/ui front end. The browser only talks to this app; route handlers in
`src/app/api` keep the session token in an httpOnly cookie and proxy an allow-list of
calls to the FastAPI service (`COPILOT_API_URL`, default `http://localhost:8000`).

```bash
npm install
npm run dev      # http://localhost:3000
```

Pages: `/` Q&A with citation panel · `/documents` corpus browser · `/gap` policy gap
analysis · `/audit` hash-chained audit trail · `/eval` evaluation dashboard.
