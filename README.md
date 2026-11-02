# ROVEN — voice-operated AI desktop agent for Windows

Say **"Roven"**. A dock appears at the top of the screen and ROVEN takes over the PC for you: it opens and operates apps, sees the screen, runs system tasks, reads your browser history, handles Gmail, Slack, ClickUp, Calendar and Drive, researches the web, writes reports and answers out loud in your language. Every conversation is saved daily to **Documents\\Roven (DD-MM-YYYY).txt**.

**Version 1.1** — about 6,400 lines of application code, 99 tools and 87 automated tests (all passing). It is not yet run on a real Windows PC or against your live accounts, so expect a short shakedown.

## Install — one file

ROVEN ships as a single installer, **`ROVEN-Setup-1.3.0.exe`**. Double-click it, click Next, and you're done:

* It installs for your user only, so no admin rights are needed.
* It adds Start-menu entries and starts ROVEN at sign-in.
* The speech models are bundled inside, so it works right away.
* On first launch a short wizard asks for your AI key, tests the microphone and sets up the wake word.

To produce the installer once, pick **either** route:

| Route | What you do | Needs on your PC |
|---|---|---|
| **A. Cloud build (easiest)** | Upload this folder to a GitHub repository. Open **Actions → Build ROVEN installer → Run workflow**. After about 20 minutes, download `ROVEN-Setup` from the run's *Artifacts*. | Nothing but a browser |
| **B. Build on your PC** | Install Python 3.11 and Inno Setup 6 (both free), then double-click `scripts\\build_installer.bat`. | Python, Inno Setup |

Both routes run the tests, build `ROVEN.exe`, bundle the speech models, check that the EXE starts, and package everything into one installer of about 700 MB. *The build recipe has not been executed yet. PyInstaller builds often need one or two extra hidden imports the first time; the cloud build log shows exactly what's missing.*

Developer mode (no installer): `powershell -ExecutionPolicy Bypass -File scripts\\setup.ps1`, then `.venv\\Scripts\\pythonw main.py`.

## Choosing the AI: Gemini (free) or Claude

ROVEN works with either **Google Gemini**, which has a free tier, or **Anthropic Claude**, which is paid and the most capable at long multi-step work. Set it up with one command; it tests the key live before saving anything:

```powershell
.venv\\Scripts\\python scripts\\configure_ai.py gemini
```

* **Model "auto"** (the default) asks Google which models your key can use and picks the newest stable Flash model. If Google reports no free quota for it, ROVEN switches to the next model, such as Flash-Lite, automatically.
* **Free-tier limits:** each step of a task is one request. A simple command uses 1–2 requests; a report can use 10–20. Daily quotas reset at midnight Pacific time, around 1 PM Pakistan time. Your exact limits are on the rate-limit page in Google AI Studio.
* **Privacy:** on Gemini's free tier, Google's terms allow your prompts to be used to improve its products and read by human reviewers. With ROVEN that can include emails, Slack messages and screenshots. Enabling billing on the Google project moves you to the paid tier, where it's not used for training.
* **Web search** (Claude's research tool) is unavailable with Gemini; ROVEN researches through its browser tools instead.
* **Switching later:** Dashboard → Settings → AI provider, or run `configure_ai.py anthropic`.

## Daily conversation log

* Every exchange is saved as plain text to your Windows **Documents** folder, one file per day: `Roven (02-11-2026).txt`. OneDrive-redirected Documents folders are supported.
* Each file records what you said (with the detected language), what ROVEN replied, every action it took (done, failed or not done), and every permission it asked for with your answer.
* Lines are written instantly, so nothing is lost if the PC crashes. A new file starts after midnight.
* Urdu and Hindi display correctly in Notepad.
* API keys and passwords are blanked out as `[REDACTED]`.
* To open today's log, use tray → **Open today's conversation log**.
* To turn logging off or change the folder, name or date format, use Dashboard → Settings, or edit `daily_log_folder`, `daily_log_name` and `daily_log_date_format` in `%APPDATA%\\ROVEN\\config.json`.

The log contains everything you say to ROVEN, so treat it like a diary. Anyone who can open your Documents folder can read it.

## Full PC control — "do anything"

ROVEN picks the most reliable way to get each thing done:

1. **Dedicated tools**: apps, windows, volume, files, Gmail, Slack, ClickUp, browser history, reminders and more.
2. **In-app control**: reads and clicks the buttons, menus and fields that apps expose to Windows.
3. **Scripts**: writes and runs PowerShell or Python for anything else, such as system info, Wi-Fi, installed programs, disk space, bulk renames, startup apps or Office automation.
4. **Screen vision**: takes a screenshot, looks at it, then clicks or types exactly where needed, in any app. This uses screen capture only; there is no webcam.
5. **Show it**: anything you ask to *see* opens in a ROVEN results window (a sortable table or text, with links you can double-click).

Examples:

```text
Show my Chrome search history from this week.        → table of searches with times; links open on double-click
What did I search on YouTube yesterday?               | Show my Edge history about flights.
What's on my screen? / Click the blue Download button. | Scroll down and open the second result.
Which programs start with Windows? Disable Spotify.   | How much space is left on C drive?
What's my Wi-Fi name and IP address?                  | List installed programs I haven't used.
Rename all photos in Downloads to their date taken.   | Remind me at 5 to call Ahmed.
Notepad is frozen — close it.                         | Copy this to the clipboard.
Take a screenshot.                                    | Show the 10 apps using the most memory.
```

## Honest status

| Area | Status |
|---|---|
| Wake word, multilingual speech in and out, dock, tray, dashboard, onboarding | Code-complete; matching and formatting logic tested |
| Apps, windows, keyboard, files, system controls, documents and reports | Code-complete; file and path safety tested |
| In-app UI control, browser agent | Code-complete; risk rules tested |
| **New:** screen vision (look, click, drag) with DPI-correct coordinates | Code-complete; screenshot handling in the AI conversation tested |
| **New:** scripts (PowerShell/Python) with a safety check | Tested (28 safety cases) |
| **New:** browser history: Chrome, Edge, Brave, Firefox; visits and search terms | Tested against a real Chrome-format database |
| **New:** results window, clipboard, processes, reminders | Code-complete; reminders tested |
| **New:** daily conversation log in Documents | Tested (naming, midnight rollover, Urdu, redaction) |
| Gmail, Slack, ClickUp, Calendar, Drive, workflows, crash recovery | Tested against simulated APIs |
| **New:** single installer and cloud build | Untested recipe |

## Wake word

No ready-made "Roven" model exists. Choose one of these:

1. **Zero setup (fallback).** A tiny local Whisper model transcribes short bursts of speech and listens for "Roven". It works immediately, uses more CPU and mishears more often.
2. **openWakeWord (recommended).** Train a custom "roven" model with openWakeWord's automatic training notebook. It uses synthetic voices and takes about an hour on a free Colab GPU. Put the `.onnx` in `%APPDATA%\ROVEN\models\` and select it in onboarding or Dashboard → Settings. Raise the threshold (0.6–0.7) if it wakes falsely.
3. **Porcupine.** Create "Roven" in the Picovoice Console, download the Windows `.ppn`, then run `python scripts\setup_keys.py porcupine`.

Ctrl+Alt+Space or tray → *Activate* always works. **Privacy mode** closes the microphone entirely.

## Connecting your accounts

### Google — Gmail, Calendar, Drive (about 10 minutes, once)

1. Go to console.cloud.google.com and create a project.
2. In **APIs & Services → Library**, enable the **Gmail API**, **Google Calendar API** and **Google Drive API**.
3. Configure the **OAuth consent screen**: External, app name "ROVEN", and add yourself as a test user.
4. Under **Credentials**, choose **Create credentials → OAuth client ID → Desktop app**, then download the JSON file.
5. In ROVEN, open Dashboard → Integrations → Browse, pick the JSON and click **Connect Google**. Approve in the browser that opens.

> **Important:** while the consent screen is in "Testing" mode, Google expires refresh tokens after **7 days**. On the consent screen, click **Publish app** (it's for your own use, so verification isn't required; you'll see an "unverified app" warning you can accept). Otherwise ROVEN will ask you to reconnect weekly.

Scopes used: `gmail.modify` (read, draft, send, label; never permanent delete), `calendar.readonly` and `drive.readonly`.

### Slack (about 5 minutes; may need workspace-admin approval)

1. Go to api.slack.com/apps and choose **Create New App → From scratch**, then pick your workspace.
2. Open **OAuth & Permissions → User Token Scopes** and add: `channels:read`, `channels:history`, `groups:read`, `groups:history`, `im:read`, `im:history`, `im:write`, `mpim:read`, `mpim:history`, `users:read`, `search:read`, `chat:write` and `files:write`.
3. Click **Install to Workspace**, then copy the **User OAuth Token** (`xoxp-…`).
4. In ROVEN, open Dashboard → Integrations → Slack, paste the token and click Save. ROVEN validates it before storing it.
5. Optionally, list channels for the daily briefing (e.g. `mintsy, dev-team`).

A *user* token means ROVEN sees exactly what you can see in Slack and nothing more.

### ClickUp (1 minute)

1. In ClickUp, open your avatar → **Settings → Apps → API Token → Generate**, then copy the `pk_…` token.
2. In ROVEN, open Dashboard → Integrations → ClickUp, paste the token and click Save.
3. Optionally, adjust the task title format (default `{prefix} - {title}`, e.g. `BF - Wallet login fails`).

## What you can say

```text
Roven, check my emails.                    | Roven, meri emails check karo.
Did Ahmed reply to my last email?          | Write an email to Ahmed saying the report comes tomorrow.
Make it shorter.  /  Send it.              | Forward this to Sara.
Slack ke Mintsy channel mein aaj kya discussion hui?
What did Osama say today? Explain everything in Roman Urdu.
Was the wallet issue fixed?  Is anything pending from QA?
Create a ClickUp task for the remaining work and assign it to Hareem, due Friday.
Check Mintsy and tell me what is pending.  |  What is Muqeet working on?  |  Which tasks are overdue?
Prepare today's Mintsy progress report and save it as PDF.
Give me my daily work briefing.            | Prepare me for my next meeting.
Check the latest client email and see if anyone discussed it in Slack.
Research the latest automated testing tools, compare them and make a report.
Open Excel and create a spreadsheet of this week's tasks.
Open Slack, go to the Mintsy channel and read what's on screen.
In this window, click "Export".            | Open YouTube and play a Python tutorial.
Find the file I worked on yesterday and read it in Urdu.
Open Task Manager — which apps use the most memory?
Set volume to 30 percent.                  | Lock the computer.
Bas, shukriya.                             → ends the conversation
```

## Safety model

| Level | Behaviour | Examples |
|---|---|---|
| Low | Runs automatically | Read email or Slack, search, summarise, open apps, read pages, click ordinary buttons |
| Medium | Asks, unless you tick it as trusted in Settings | Create or update ClickUp tasks, post to internal Slack channels, move or rename files, save reports, downloads |
| High | Always asks | Send external email, Slack shared or external channels, click Send/Pay/Delete/Submit, browser uploads, file sharing, recycle bin, shutdown or restart, typing into terminals |
| Scripts | Read-only scripts are medium (ask, unless you trust `run_script`). Scripts that change anything are high. **Any** script after ROVEN read a web page, email, chat or the screen is high | "How much disk space?" vs "rename these files" |
| Never | Refused outright | Typing passwords, card numbers, IDs or one-time codes; scripts that read saved passwords or cookies, request admin rights, weaken Windows security, wipe disks or delete system files; bypassing UAC or 2FA |

Further protections:

* Email goes out only after **draft → confirm**. Recipients must be exact addresses, and an ambiguous name means ROVEN asks you.
* Repeating a side effect within 10 minutes always asks again.
* Instructions found inside web pages, emails, chats or on screen are treated as information, never as commands.
* Every script ROVEN runs is kept in `%APPDATA%\\ROVEN\\scripts\\` so you can see exactly what ran.
* Silence or an unclear answer counts as **no**.
* Emergency stop works from **Ctrl+Alt+Shift+X**, the tray, or by moving the mouse into a screen corner.
* The activity log redacts secrets. Credentials are kept only in Windows Credential Manager.

## Architecture

```text
main.py                       UI thread: onboarding, dock, dashboard, tray, hotkeys
core/assistant.py             worker thread: wake → listen → reason/act → speak → follow-up
core/reasoning_engine.py      Claude tool loop + web search, prompt caching, step persistence
core/tool_registry.py         allowlist, schema validation, risk/permissions, duplicate guard, audit
core/tools_builtin.py         desktop tools          core/tools_integrations.py  account/browser/UIA/workflow tools
core/workflows.py             briefing, meeting prep, project status, email↔Slack collectors
core/tools_general.py         screen vision, scripts, browser history, results window, clipboard, processes, reminders
storage/conversation_log.py   daily Documents\\Roven (date).txt log
security/script_guard.py      forbidden / read-only / changes classification for scripts
integrations/                 base (HTTP), google_auth, gmail, google_calendar, google_drive, slack, clickup, manager
automation/                   apps, windows, ui_automation, browser_agent, keyboard_mouse, files, documents, system
speech/                       microphone, wake_word, VAD, speech_to_text, text_to_speech
security/                     permissions, validation, audit log, credentials
storage/                      SQLite: audit log, memory, workflow history
interface/                    floating_dock, dashboard (Activity, Tasks, Integrations, Memory, Settings), onboarding, tray
packaging/                    PyInstaller spec, Inno Setup installer, icon, model bundling
.github/workflows/            cloud build that produces ROVEN-Setup.exe
tests/                        95 tests
```

## Acceptance checklist (run on your PC)

| # | Criterion | How to check |
|---|---|---|
| 1–2 | Wake word, dock | Say "Roven" |
| 3 | EN / Urdu / Roman Urdu | "Chrome kholo", "volume kam karo", "open Notepad" |
| 4–5 | Apps and in-app UI | "Open Excel" → "list what's on this screen" → "click Blank workbook" |
| 6–7 | Gmail read, draft, send | "Summarise today's emails" → "Reply that we'll deliver tomorrow" → "send it" |
| 8–9 | Slack threads, language | "What did Osama say in Mintsy today? Explain in Roman Urdu" |
| 10 | ClickUp | "What's overdue in Mintsy?" → "Move the wallet task to QA" |
| 11 | Files | "Find the Excel file I edited yesterday" |
| 12 | Workflows | "Daily briefing", "Prepare today's Mintsy report as PDF" |
| 13 | Context | Follow-ups without repeating the project name |
| 14 | Voice | Every reply is spoken |
| 15 | Background | Reboot; ROVEN is in the tray after sign-in |
| 16–17 | Permissions, emergency stop | Ask to shut down → say "no"; Ctrl+Alt+Shift+X mid-task |
| 18 | No false success | Disconnect Wi-Fi, ask to send a Slack message, and ROVEN reports the failure |

## Known limits

* `small` Whisper is weak on Urdu and Punjabi; use `medium` or `large-v3` if possible. Punjabi uses the Urdu voice.
* Screen vision is slower than other methods (each look is a round trip to the AI) and can misjudge tiny targets. ROVEN uses it last and looks again after acting. It can't operate UAC prompts or the lock screen; Windows blocks that by design.
* Scripts run with your normal permissions. Anything that needs administrator rights must be done by you.
* Python scripts inside the installed app can use only the libraries bundled with ROVEN; PowerShell has no such limit and is preferred.
* The browser agent uses its own Edge profile. Sign in to websites there once yourself.
* The daily briefing reads the Slack channels you list, not every DM.
* Drafts updated with `gmail_update_draft` keep only the attachments you list again.
* With every integration connected, ROVEN offers 99 tools to the AI. Prompt caching keeps this fast and cheap after the first request of a session.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Never wakes | Check the mic in Settings, try Ctrl+Alt+Space, and see `%APPDATA%\ROVEN\roven.log` |
| Google stops working after a week | Publish the OAuth consent screen (see Google setup) and reconnect |
| Slack says "lacks permission X" | Add that scope in your Slack app, reinstall it, and paste the new token |
| Browser tools fail | `python -m playwright install chromium`, or set browser channel to `chromium` in `config.json` |
| PDF conversion fails | Requires Microsoft Office; save as docx instead |
| Hotkeys don't work in admin windows | Expected; Windows blocks this and ROVEN won't bypass UAC |

## Tests

```powershell
python -m pytest -q
```

## Changes in 1.3 (final)
* **The island:** the dock is now a rectangle attached to the top edge of the screen. It drops down when ROVEN wakes, resizes smoothly as text appears, slides back up when done, and is exactly centred on scaled (125% / 150%) displays.
* **Speed with Gemini:** low "thinking" effort on every request, an automatic switch away from overloaded models, slow models moved to the back of the list, and a speed test in `configure_ai.py` that picks the fastest model. "Open Notepad" went from 72 s to about 1–2 s.
* **Better hearing:** with Gemini, your spoken command is transcribed by Gemini, which handles Urdu, Roman Urdu and mixed speech far better, with offline Whisper as a fallback. The wake listener expects "Roven", accepts common mishearings (Rowan, Raven, Roben…), only wakes when "Roven" comes first, and logs near misses.
* **Reliability:** display errors can no longer freeze the dock; rate-limit waits are shown on the island and capped at 45 s; noise no longer starts or ends a recording; each step is logged (Heard → Asking Gemini → Action → Reply).
* **New tool:** `scripts\\ask.py "open notepad"` tests the AI and actions without the microphone.

## Changes in 1.2
* Google Gemini support (free tier) with automatic model selection, quota fallback and live key testing (`scripts\\configure_ai.py`).

## Changes in 1.1
* Single installer (`ROVEN-Setup-1.3.0.exe`) with bundled speech models, plus a cloud build.
* Daily conversation log in Documents.
* Full PC control: screen vision, scripts with a safety check, browser history, a results window, clipboard, processes and reminders.
* **Fixed:** build 1.0's `requirements.txt` was missing the integration, UI-automation and browser packages (a cleanup step had deleted them). A test now guards against this.
