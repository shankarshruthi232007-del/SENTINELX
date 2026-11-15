# SENTINELX — Unified Cyber Defence Platform

A configurable classroom prototype combining login prevention, an isolated deception portal, behavioural event analysis, SOC monitoring and session-level containment. It uses one common interface for banking, healthcare, education, corporate and general organisations.

> **Demo only:** all accounts, organisations, events and documents are fictional. This is not a production security gateway or a real honeypot deployment. Do not connect it to real organisation login systems or real customer/medical/student data.

## What is included

- Organisation-configurable login page and sector-specific decoy resource catalogue.
- Backend authentication with a three-consecutive-failure temporary lockout (15 minutes).
- SOC event generated for failed attempts and a lockout notification shown in the SOC console.
- Three demo routes: employee workspace, isolated deception portal and protected SOC administrator dashboard. An employee session can be risk-routed to the decoy after repeated failed sign-ins or an unusual resource-access sequence.
- Search, preview and download interactions recorded as telemetry.
- Risk scoring and behavioural classifications from combinations of events (not from a single download alone).
- Live SOC refresh, event timeline, alert metrics, event distribution, audit table and session management.
- Session-level containment: the selected deception session is blocked without stopping other sessions.
- Supabase-backed persistence for multi-device Vercel deployment, plus in-memory local fallback for quick local testing.

## Demo accounts

| Role | Username | Password | Result |
|---|---|---|---|
| Employee | `employee` | `Employee@2026` | Normal demo workspace |
| Deception simulation | `analyst` | `Sentinel@2026` | Isolated fake-resource portal |
| SOC administrator | `socadmin` | `Admin@2026` | Protected SOC dashboard |

For a presentation, use one browser/profile for the deception account and a separate browser/profile (or an incognito window) for the SOC administrator. The SOC login is not exposed to the deception session.

## Run locally

Requirements: Python 3.10+.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

Local mode stores events in process memory. It is suitable for a single-computer demonstration; restarting the app clears the local event store.

## Deploy to Vercel (persistent multi-device mode)

The Flask app is compatible with Vercel's Python runtime. The project root contains `app.py`, `requirements.txt`, `public/` assets and `vercel.json`.

### 1. Create a Supabase project

1. Create a project in Supabase.
2. Open **SQL Editor**.
3. Copy and run `sql/supabase_schema.sql`.
4. In Supabase project settings, copy the project URL and the server-side service-role key.
5. Keep the service-role key private. Never put it in `public/`, HTML, JavaScript, GitHub commits or screenshots.

The schema enables Row Level Security and intentionally creates no browser-facing policies for the internal SENTINELX tables. Only the backend should use the server-side key.

### 2. Push this folder to GitHub

Create a new empty GitHub repository, then upload/push the contents of this folder (the files inside `SENTINELX_Vercel_Final`, not an extra parent folder).

### 3. Import into Vercel

1. Open Vercel and choose **Add New → Project**.
2. Import the GitHub repository.
3. Keep the project root at the repository root.
4. Vercel should detect the Flask/Python application. No custom build command is required.

### 4. Add environment variables in Vercel

Open **Project → Settings → Environment Variables** and add:

| Variable | Value |
|---|---|
| `SESSION_SECRET` | A long random secret string |
| `ADMIN_PASSWORD` | A new, unique SOC admin password |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Your private server-side service-role key |
| `EMPLOYEE_PASSWORD` | Optional; otherwise demo default is used |
| `ANALYST_PASSWORD` | Optional; otherwise demo default is used |

Set these for the Production environment (and Preview if needed), then redeploy. Change the default demo passwords before sharing a public deployment. The sample employee and deception identities are for classroom simulation only.

### 5. Verify the deployment

- Open `/api/health` on your deployed domain. It should report `database: persistent`.
- Sign in as `socadmin` using the new `ADMIN_PASSWORD` and select the same organisation used in the other browser.
- In another browser/profile, sign in as `analyst`, search resources, preview files and request downloads.
- Return to the SOC console; the events should appear automatically.
- Select the session and choose **CONTAIN**. The deception session should show **Session unavailable** on its next action/page load.

Vercel documentation: https://vercel.com/kb/guide/ship-a-flask-app-on-vercel

## Behaviour demonstration

1. Choose an organisation sector and enter its organisation name.
2. Enter an incorrect password three consecutive times for the same username from the same browser/network. The third attempt applies a 15-minute temporary lockout and creates a SOC alert.
3. Use the deception demo account to enter the isolated decoy portal.
4. To demonstrate a valid credential being misused, sign in as `employee` in the user browser. Make several resource searches and preview/download sample files; a repeated search + file-access pattern routes that session to the isolated deception portal. Two failed sign-ins followed by valid employee credentials also create a risk-based review and route to the decoy.
5. Alternatively, sign in as `analyst` to open the deception portal immediately, then search categories, preview decoy documents, request multiple downloads and try the restricted administration directory.
6. Watch the SOC risk indicators, classification and live event timeline update.
7. Contain only the selected session.

A failed login is a security signal, not proof of an attacker. A single file download is not automatically classified as malicious; the risk engine considers a sequence of indicators.

## Important deployment notes

- Vercel Functions are request-driven/serverless. The SOC uses short-interval polling (about 1.8 seconds), not a permanently running Python process or guaranteed WebSocket connection.
- Supabase is required for durable, shared events across Vercel function instances and separate devices. Without it, the local in-memory fallback is not suitable for public multi-device monitoring.
- The owner notification in this build is an in-app SOC alert. Email/SMS delivery is not configured.
- The demo login accounts are not real organisation identity-provider integrations. A real deployment would require an organisation's approved identity provider, MFA, rate limiting at the edge, monitoring, security review and incident-response procedures.
- Do not use the sample admin password on a public deployment. Set a unique `ADMIN_PASSWORD` and `SESSION_SECRET` in Vercel.

## Project structure

```text
SENTINELX_Vercel_Final/
├── app.py
├── requirements.txt
├── vercel.json
├── .python-version
├── .env.example
├── templates/
│   ├── login.html
│   ├── deception.html
│   ├── workspace.html
│   ├── contained.html
│   └── soc.html
├── public/
│   ├── style.css
│   ├── login.js
│   ├── portal.js
│   ├── workspace.js
│   └── soc.js
└── sql/
    └── supabase_schema.sql
```
