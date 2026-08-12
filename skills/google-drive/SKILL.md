---
name: google-drive
description: >-
  Google Drive file management — upload, download, share, search, organize
  files and folders. Converts .docx to native Google Docs with formatting.
  Use when the user says "upload to Drive", "share this file", "put this in
  Google Docs", "convert to Google Doc", "create a folder", "find file in
  Drive", or any Google Drive operation. Also triggers on drive.google.com
  URLs. For reading/editing Google Docs content, use the gws skill instead.
category: productivity
version: 2.0.0
key_capabilities: upload-and-convert, resolve-folder, upload, download, share, search, create-folder, move, copy, delete
when_to_use: Drive file management, sharing files, uploading documents, converting .docx to Google Docs, organizing Drive folders
---

# Google Drive Management Skill

> **Scope of the gws note:** only the operations here that shell out to `gws` follow the
> toolkit-profile rules (`../gws/references/multi-secret-profiles.md`) — on a 403 naming a
> project other than `nsls-gdocs-skill`, run `python3 <plugin>/skills/gws/scripts/gws_doctor.py --services docs,drive`.
> The doctor heals its own profile, not the default gws dir — after `DOCTOR: HEALTHY`, run the
> gws-backed commands with the profile chained in the SAME shell command:
> `export GOOGLE_WORKSPACE_CLI_CONFIG_DIR=~/.config/gws-profiles/nsls-gdocs-skill; gws …`
> (Windows: `$env:GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$env:USERPROFILE\.config\gws-profiles\nsls-gdocs-skill"; gws …`)
> This skill's primary engine uses its own Ruby OAuth files under `~/.claude/.google`;
> failures there are UNRELATED to gws — do not apply gws profile repair to them.


## Purpose

Manage Google Drive files with comprehensive operations:

- Upload files to Drive (including .docx → Google Doc auto-conversion)
- Download and export files from Drive
- Search and list files
- Share files with users or publicly
- Create and resolve folder hierarchies
- Move, copy, and delete files
- Get file metadata

**Integration**: The `drive_manager.rb` script shares OAuth credentials with other Google skills (sheets, calendar, contacts, gmail).

## When to Use This Skill

Use this skill when:
- User wants to upload a file to Google Drive
- User wants to create a native Google Doc from a .docx file
- User wants to share a Drive file with someone
- User wants to search for files in Drive
- User wants to organize files into folders
- User wants to download or export a Drive file
- Keywords: "Google Drive", "upload", "share", "Drive folder", "upload and convert"

**For Google Doc content operations** (read, find/replace):
- Use the GAS webhook (`$GOOGLE_APPS_SCRIPT_WEBHOOK_URL`) with `read` or `replace` actions
- For creating styled Google Docs: build Markdown → create .docx via `docx_creator.py` → upload via `upload-and-convert`

## Core Workflows

### 1. Upload and Convert (.docx → Google Doc)

Upload a local .docx file to Google Drive and auto-convert it to a native Google Doc in one step. The Google Drive API handles the conversion — no intermediate .docx remains on Drive.

```bash
# Upload and convert a .docx file
scripts/drive_manager.rb upload-and-convert \
  --file /tmp/2026-02-18-agenda.docx \
  --folder-id {folder_id} \
  --name "2026-02-18 - SLT Meeting - Agenda"
```

**Supported conversions**:
- `.docx` → Google Doc (`application/vnd.google-apps.document`)
- `.xlsx` → Google Sheet (`application/vnd.google-apps.spreadsheet`)
- `.pptx` → Google Slides (`application/vnd.google-apps.presentation`)

**Returns**:
```json
{
  "status": "success",
  "operation": "upload_and_convert",
  "file": {
    "id": "1abc...",
    "name": "Document Name",
    "mime_type": "application/vnd.google-apps.document",
    "web_view_link": "https://docs.google.com/document/d/1abc.../edit"
  }
}
```

### 2. Resolve Folder Path

Walk (or create) a folder hierarchy by path, returning the leaf folder ID. Creates any missing segments automatically.

```bash
# Resolve an existing path (or create missing segments)
scripts/drive_manager.rb resolve-folder \
  --path "SLT Meetings/2026/February"

# Resolve under a specific parent folder
scripts/drive_manager.rb resolve-folder \
  --path "Agendas/Q1" \
  --folder-id {parent_folder_id}
```

**Returns**:
```json
{
  "status": "success",
  "operation": "resolve_folder",
  "path": "SLT Meetings/2026/February",
  "folder_id": "1xyz...",
  "web_view_link": "https://drive.google.com/drive/folders/1xyz...",
  "segments": [
    { "name": "SLT Meetings", "id": "1aaa...", "created": false },
    { "name": "2026", "id": "1bbb...", "created": false },
    { "name": "February", "id": "1xyz...", "created": true }
  ]
}
```

### 3. Upload Files

```bash
# Upload a file to Drive root
scripts/drive_manager.rb upload --file ./document.pdf

# Upload to specific folder
scripts/drive_manager.rb upload --file ./diagram.excalidraw --folder-id abc123

# Upload with custom name
scripts/drive_manager.rb upload --file ./local.txt --name "Remote Name.txt"
```

### 4. Download Files

```bash
# Download a file
scripts/drive_manager.rb download --file-id abc123 --output ./local_copy.pdf

# Export Google Doc as PDF
scripts/drive_manager.rb download --file-id abc123 --output ./doc.pdf --export-as pdf

# Export Google Sheet as CSV
scripts/drive_manager.rb download --file-id abc123 --output ./data.csv --export-as csv
```

### 5. Search and List Files

```bash
# List recent files
scripts/drive_manager.rb list --max-results 20

# Search by name
scripts/drive_manager.rb search --query "name contains 'Report'"

# Search by type
scripts/drive_manager.rb search --query "mimeType='application/vnd.google-apps.document'"

# Search in folder
scripts/drive_manager.rb search --query "'folder_id' in parents"

# Combine queries
scripts/drive_manager.rb search --query "name contains '.excalidraw' and modifiedTime > '2024-01-01'"
```

### 6. Share Files

```bash
# Share with specific user (reader)
scripts/drive_manager.rb share --file-id abc123 --email user@example.com --role reader

# Share with write access
scripts/drive_manager.rb share --file-id abc123 --email user@example.com --role writer

# Make publicly accessible (anyone with link)
scripts/drive_manager.rb share --file-id abc123 --type anyone --role reader

# Share with entire domain
scripts/drive_manager.rb share --file-id abc123 --type domain --domain example.com --role reader
```

### 7. Folder Management

```bash
# Create a folder
scripts/drive_manager.rb create-folder --name "Project Documents"

# Create folder inside another folder
scripts/drive_manager.rb create-folder --name "Diagrams" --parent-id abc123

# Move file to folder
scripts/drive_manager.rb move --file-id file123 --folder-id folder456
```

### 8. Other Operations

```bash
# Get file metadata
scripts/drive_manager.rb get-metadata --file-id abc123

# Copy a file
scripts/drive_manager.rb copy --file-id abc123 --name "Copy of Document"

# Update file content (replace)
scripts/drive_manager.rb update --file-id abc123 --file ./new_content.pdf

# Delete file (moves to trash)
scripts/drive_manager.rb delete --file-id abc123
```

## Creating Styled Google Docs (DOCX Pipeline)

The recommended workflow for creating well-formatted Google Docs:

```bash
# Step 1: Build content as Markdown, create styled .docx
echo "$markdown" | python3 scripts/docx_creator.py \
  --output /tmp/document.docx \
  --title "Document Title"

# Step 2: Resolve target folder (creates missing segments)
scripts/drive_manager.rb resolve-folder --path "Folder/Subfolder"

# Step 3: Upload and auto-convert to native Google Doc
scripts/drive_manager.rb upload-and-convert \
  --file /tmp/document.docx \
  --folder-id {folder_id} \
  --name "Document Title"

# Step 4: Share with collaborators
scripts/drive_manager.rb share --file-id {doc_id} --email user@example.com --role writer

# Step 5: Clean up temp file
rm /tmp/document.docx
```

**Fallback**: If the DOCX pipeline fails, fall back to the GAS webhook CREATE action (produces a less-styled but functional Google Doc).

## Output Format

All commands return JSON with consistent structure:
```json
{
  "status": "success",
  "operation": "upload",
  "file": {
    "id": "1abc...",
    "name": "document.pdf",
    "mime_type": "application/pdf",
    "web_view_link": "https://drive.google.com/file/d/1abc.../view",
    "web_content_link": "https://drive.google.com/uc?id=1abc...",
    "created_time": "2024-01-15T10:30:00Z",
    "modified_time": "2024-01-15T10:30:00Z",
    "size": 12345
  }
}
```

## Authentication Setup

**Shared with Other Google Skills**:
- Uses same OAuth credentials and token
- Located at: `~/.claude/.google/client_secret.json` and `~/.claude/.google/token.json`
- Shares token with email, calendar, contacts, sheets skills
- Requires Drive, Sheets, Calendar, Contacts, and Gmail API scopes

**First Time Setup**:
1. Run any drive operation
2. Script will prompt for authorization URL
3. Visit URL and authorize all Google services
4. Enter authorization code when prompted
5. Token stored for all Google skills

**Re-authorization**:
- Token automatically refreshes when expired
- If refresh fails, re-run authorization flow
- All Google skills will work after single re-auth

## Error Handling

| Error | Action |
|-------|--------|
| `AUTH_ERROR` | Guide user through re-authorization flow |
| `FILE_NOT_FOUND` | Verify local file path exists |
| `API_ERROR` | Check file ID, permissions, quota |
| `UNSUPPORTED_CONVERSION` | Only .docx, .xlsx, .pptx supported for upload-and-convert |
| `EMPTY_PATH` | Provide a non-empty folder path to resolve-folder |
| `MISSING_FILE` | Provide --file argument |
| `MISSING_PATH` | Provide --path argument |

## Version History

- **2.0.0** (2026-02-17) - Major rewrite: Removed `docs_manager.rb` and all Google Docs API operations. Google Doc content is now created via the DOCX pipeline (`docx_creator.py` + `upload-and-convert`). Content reading and find/replace handled by GAS webhook. Added `upload-and-convert` command (auto-converts .docx/.xlsx/.pptx to native Google Apps format). Added `resolve-folder` command (walks/creates folder hierarchies by path). Added .docx/.xlsx/.pptx MIME type detection.
- **1.2.1** (2026-02-16) - Documented critical API behavior learnings for docs_manager.rb operations.
- **1.2.0** (2025-12-25) - Added markdown support documentation for docs_manager.rb.
- **1.1.0** (2025-12-20) - Added Google Drive operations via drive_manager.rb.
- **1.0.0** (2025-11-10) - Initial Google Docs skill with docs_manager.rb.

---

**Dependencies**: Ruby with `google-apis-drive_v3`, `googleauth` gems (shared with other Google skills)
