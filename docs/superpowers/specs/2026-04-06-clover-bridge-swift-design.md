# CloverBridge — macOS Swift Menu Bar App

**Date:** 2026-04-06
**Status:** Approved

## Overview

A lightweight macOS menu bar app that acts as a two-way Telegram bridge between your Mac and the openclaw AWS bot.

- **Inbound (AWS → Mac):** openclaw finds an interesting article, sends it via Telegram → CloverBridge receives it, shows a macOS notification with title/snippet, click opens URL in browser.
- **Outbound (Mac → AWS):** User drops files (portfolio work, thoughts, notes) into `~/clover-inbox/` → CloverBridge detects them and sends the full file contents to the AWS bot via Telegram → bot ingests them as memory.

## Architecture

Single `.app` bundle, no external dependencies, runs as a Login Item.

```
CloverBridge.app
├── MenuBarApp          — entry point, NSStatusItem in macOS menu bar
├── InboxWatcher        — FSEventStream on ~/clover-inbox/, fires on new files
├── TelegramClient      — URLSession wrapper: sendDocument() + getUpdates()
├── NotificationManager — posts UNUserNotificationCenter notifications for articles
└── MenuBarView         — SwiftUI popover: recent articles list + connection status
```

## Components

### InboxWatcher
- Wraps `FSEventStream` watching `~/clover-inbox/`
- On event, scans for new files (ignores dotfiles and already-processed items)
- Emits each new file path via callback to `TelegramClient.sendDocument()`
- On successful send, moves the file to `~/clover-inbox/processed/`

### TelegramClient
Two methods only:
- `sendDocument(fileURL:)` — multipart POST to Telegram `/sendDocument` with raw file bytes
- `getUpdates(offset:)` — GET `/getUpdates?offset=&limit=10`, returns array of messages

Parses incoming messages: URL on its own line = article link, preceding text = title. No URL = plain text stored silently in the recent list.

Tracks `update_id` offset to prevent duplicate processing.

### NotificationManager
- Requests `UNUserNotificationCenter` permission on first launch
- Posts notification: title = article title, body = URL
- `userInfo` carries the URL; clicking opens it via `NSWorkspace.open()`

### MenuBarView
SwiftUI `Popover` attached to the status bar item:
- Last 10 received articles (title + timestamp), each row is clickable (opens URL)
- Status line: "Watching: ~/clover-inbox/"
- Connection indicator dot: green (healthy), yellow (last poll >2min ago), red (error)
- Login Item toggle (registers via `SMAppService.mainApp`, requires macOS 13+)
- First-run settings form: bot token + chat ID fields, saved to `UserDefaults`

## Data Flow

### Outbound (Mac → AWS)
```
User drops file into ~/clover-inbox/
    → FSEventStream fires
    → InboxWatcher scans, finds new file
    → TelegramClient.sendDocument(fileURL:)
    → On success: file moved to ~/clover-inbox/processed/
    → On failure: file stays, status dot turns red, retries on next event
```

### Inbound (AWS → Mac)
```
Timer fires every 30 seconds
    → TelegramClient.getUpdates(offset:)
    → Parse messages for URL + title
    → NotificationManager posts UNUserNotification
    → User clicks notification → NSWorkspace.open(url)
    → Article added to MenuBarView recent list
```

## Edge Cases

| Scenario | Handling |
|---|---|
| Send fails (network down) | File stays in inbox, status dot red, auto-retry on next FSEvent |
| File >50MB (Telegram limit) | Menu bar notification: "File too large: filename" — no send attempted |
| `getUpdates` fails | Status dot yellow, silent retry next tick |
| Message has no URL | Stored as plain text in recent list, no system notification |
| Duplicate Telegram updates | Deduplicated via `update_id` offset |
| First launch, no config | Popover shows settings form (bot token + chat ID) before watching starts |

## Configuration

Stored in `UserDefaults`:
- `botToken` — Telegram bot token
- `chatId` — Telegram chat ID
- `inboxPath` — watched folder path (default: `~/clover-inbox/`)

No external config file. Settings editable from the menu bar popover.

## Tech Decisions

- **Language:** Swift + SwiftUI
- **Transport:** Telegram Bot API (HTTP, no SDK)
- **Networking:** `URLSession` only, no third-party packages
- **File watching:** `FSEventStream` (CoreServices)
- **Notifications:** `UserNotifications` framework
- **Login Item:** `SMAppService.mainApp` (macOS 13+)
- **Min OS:** macOS 13 Ventura

## File Structure (target)

```
CloverBridge/
├── CloverBridgeApp.swift       — @main entry, MenuBarApp setup
├── InboxWatcher.swift          — FSEventStream wrapper
├── TelegramClient.swift        — Telegram API calls
├── NotificationManager.swift   — UNUserNotificationCenter wrapper
├── MenuBarView.swift           — SwiftUI popover
├── Models.swift                — ArticleItem, AppConfig structs
└── CloverBridge.xcodeproj
```
