# gdoc-edit — setup

`gdoc-edit` talks to the Google Docs + Drive APIs through **`gws`** (the Google Workspace
CLI, shipped with the toolkit). Every call runs as **you** — your Google identity, your
document permissions. There is no shared secret and nothing per-person to deploy. Setup is
a one-time `gws auth login`.

If `gws` is already authenticated on your machine (`gws auth status` shows a `storage`
other than `none`), you're done — skip to the smoke test.

---

## Builder setup (the common case, ~2 min)

### 1. Make sure `gws` is installed

```bash
gws --version || curl --proto '=https' --tlsv1.2 -LsSf \
  https://github.com/googleworkspace/cli/releases/latest/download/google-workspace-cli-installer.sh | sh
```

### 2. Get the NSLS OAuth client

`gdoc-edit` uses one shared OAuth **client** (a Desktop client in the `nsls-gdocs-skill`
GCP project). The client file is *not* something you type — you fetch it once and drop it
in place. It only lets you *start* a Google sign-in; the actual access is your own
per-user token, minted in the next step.

> Why a shared file and not "download it from the console"? Google only shows a client
> secret **once, at creation** — it can never be viewed or re-downloaded afterwards. So
> the client JSON is distributed as a file instead.

1. Get `client_secret.json` from the NSLS builders shared location:
   https://drive.google.com/file/d/1fOu-0M35vgGO6mzbd0BInEt_sgkmgCn7/view
   (view-only, restricted to @nsls.org accounts, unlisted — not discoverable by search).
2. Save it as `~/.config/gws/client_secret.json`:

```bash
mkdir -p ~/.config/gws && cp ~/Downloads/client_secret*.json ~/.config/gws/client_secret.json
chmod 600 ~/.config/gws/client_secret.json
```

The file is low-sensitivity by design: it's a Desktop-type client on an **Internal**
consent screen, so it is useless to anyone without an @nsls.org Google account — all it
can do is start a sign-in that only NSLS accounts can complete. Still, don't commit it
to any repo.

### 3. Log in (per-user, minimal scopes)

```bash
gws auth login --services docs,drive
```

A browser opens for Google consent. Because the app is **Internal**, only `@nsls.org`
accounts can complete it. `--services docs,drive` requests only the Docs + Drive scopes
this skill needs — not the full Workspace surface. Your refresh token is stored **encrypted**
at `~/.config/gws`; you won't be asked again.

### 4. Smoke test

```bash
S=~/.claude/local-plugins/nsls-builder-toolkit/skills/gdoc-edit/scripts/gdoc.py
python3 $S read     --doc <ANY_DOC_ID_YOU_CAN_OPEN> | head
python3 $S comments --doc <ANY_DOC_ID_YOU_CAN_OPEN>
```

`read` prints the doc text; `comments` prints a JSON array. If you get **exit 2 / auth
error**, re-run step 3. If you get a **project / permission** error, you're missing read
access to `nsls-gdocs-skill` (step 2.1).

---

## What changed from the old webhook

Earlier versions of this skill used a personal Apps Script web app (a `/exec` URL + a
`SHARED_SECRET` in `~/.config/gdoc-edit/config.json`). That was tied to one person's
identity and couldn't be shared safely. **It's retired.** You no longer need
`~/.config/gdoc-edit/config.json` — delete it if you have one. The old Apps Script is kept
for reference at `references/legacy/gas-doc-webhook.gs` only.

---

## Admin: creating the shared OAuth client (one-time, done once for the org)

Only needed once, by whoever stands up the `nsls-gdocs-skill` project. Requires GCP access
to that project. **Done 2026-07-12** (client `gdoc-edit desktop client`,
ID `598752584124-4t7bdffqchrt8b6nlv1uuhpkl1b24vtc.apps.googleusercontent.com`) — recorded
here in case it ever has to be recreated.

1. **Reauth gcloud** (interactive): `gcloud auth login` and
   `gcloud config set project nsls-gdocs-skill`.
2. **Enable the Workspace APIs**: `gws auth setup --project nsls-gdocs-skill`. This enables
   the APIs, then **stops with a validation error at OAuth-client creation** — that part is
   console-only (Google removed API/CLI creation of desktop clients). Expected; continue.
3. **Create the consent screen** (console → Google Auth Platform → Overview → Get started,
   project `nsls-gdocs-skill`): App name `NSLS gdoc-edit`, support email an NSLS address,
   **Audience: Internal** ← the critical choice: only `@nsls.org` can authorize, and the
   sensitive Docs/Drive scopes need no Google verification review. Agree + Create.
4. **Create the client** (Clients → Create client): Application type **Desktop app**, name
   `gdoc-edit desktop client`. **Download the JSON immediately from the creation dialog** —
   Google shows/downloads a client secret **only at creation**; there is no retrieval later.
   (Missed the window? Open the client → **Add secret** → capture the new secret in the same
   dialog, disable+delete the old one. A client holds max 2 secrets.)
5. **Distribute**: save the JSON as `~/.config/gws/client_secret.json` (mode 600) and put a
   copy in the NSLS builders shared Drive location (restricted to @nsls.org) — that's what
   builder-setup step 2 points at.
6. **Log in and verify**: `gws auth login --services docs,drive`, then the smoke test. The
   `client_id` is the detail to register/track centrally.

Do **not** commit `client_secret.json` (or the id/secret) to the toolkit repo. It's a
Desktop-type client — low sensitivity by Google's model, useless outside @nsls.org thanks
to the Internal consent screen — but the NSLS pattern is that no credential lives in git.
