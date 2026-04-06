# CloverBridge — macOS Swift Menu Bar App

**Date:** 2026-04-06
**Status:** Approved

## Overview

A lightweight macOS menu bar app that acts as a two-way Telegram bridge between your Mac and the openclaw AWS bot.

- **Inbound (AWS → Mac):** openclaw finds an interesting article, sends it via Telegram → CloverBridge receives it, shows a macOS notification with title/snippet, click opens URL in browser.
- **Outbound (Mac → AWS):** User drops files (portfolio work, thoughts, notes) into `~/clover-inbox/` → CloverBridge detects them and sends the full file contents to the AWS bot via Telegram → bot ingests them as memory.

## Architecture

Single `.app` bundle, no external dependencies, not sandboxed (see Entitlements), runs as a Login Item.

```
CloverBridge.app
├── MenuBarApp          — entry point, NSStatusItem in macOS menu bar
├── InboxWatcher        — FSEventStream on ~/clover-inbox/, fires on new files
├── TelegramClient      — URLSession wrapper: sendDocument() + getUpdates()
├── NotificationManager — UNUserNotificationCenter + delegate for click handling
└── MenuBarView         — SwiftUI popover: recent articles list + connection status
```

## Components

### InboxWatcher
- Wraps `FSEventStream` with `kFSEventStreamCreateFlagFileEvents` watching `~/clover-inbox/` (the top-level directory only — `processed/` subdirectory is excluded by filtering paths that contain `/processed/`)
- On event, scans for files directly in the inbox root: ignores dotfiles, directories, and any path containing `/processed/`
- Tracks in-memory `Set<String>` of file paths currently being sent, to avoid double-sends on rapid FSEvents for the same file
- Before emitting a file, checks its size via `FileManager.attributesOfItem(atPath:)[.size]`. If size > 50 MB (52_428_800 bytes): does not send, does not add to in-flight set, appends a permanent error `ArticleItem` to the recent list with title "Too large: {filename}" and `url = nil`
- Emits each qualifying file path via an `async` callback (called on `MainActor`)
- On successful send, moves the file to `~/clover-inbox/processed/` (creates the directory if absent)
- On send failure: file stays in inbox, `pendingRetry` flag set; a separate `DispatchSourceTimer` fires every 60 seconds to retry all files still in the inbox root

If `~/clover-inbox/` does not exist on first launch, `InboxWatcher.start()` creates it before registering the stream. The `processed/` subdirectory is also created at this point (not deferred to first send).

**FSEventStream callback bridging:** Use a `@convention(c)` free function as the callback. Pass `Unmanaged.passRetained(self).toOpaque()` as the `info` pointer in `FSEventStreamContext`; inside the callback, recover the instance via `Unmanaged<InboxWatcher>.fromOpaque(info!).takeUnretainedValue()`. Call `Unmanaged.passRetained(self).release()` in `deinit`.

### TelegramClient
Two methods:

**`sendDocument(fileURL:chatId:botToken:) async throws`**
- Multipart POST to `https://api.telegram.org/bot{token}/sendDocument`
- Body construction: generate a UUID boundary string; set `Content-Type: multipart/form-data; boundary={boundary}` on the request. Each part is framed as `--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{value}\r\n`. The file part uses `Content-Disposition: form-data; name="document"; filename="{fileURL.lastPathComponent}"\r\nContent-Type: application/octet-stream\r\n\r\n{fileData}\r\n`. End with `--{boundary}--\r\n`.
- Fields: `chat_id` (string value), `document` (file data as described above)
- No `caption` field
- Throws on HTTP error or Telegram `ok: false` response

**`getUpdates(offset: Int, botToken: String) async throws -> [TelegramUpdate]`**
- GET `https://api.telegram.org/bot{token}/getUpdates?offset={offset}&limit=10&timeout=0`
- Returns decoded `[TelegramUpdate]` (see Models)
- Throws on network or decode error

**Message parsing** (applied to `message.text` field only):
1. Split text by newlines
2. Find the first line that begins with `http://` or `https://` — that is the URL
3. All lines before that line, joined with a space, form the title (trimmed). If empty, title = the URL host
4. If no URL found in any line: no notification; stored as plain-text entry in the recent list
5. Multiple URLs in one message: only the first one is used

**`update_id` offset persistence:**
- After each successful `getUpdates`, store `max(update_id) + 1` in `UserDefaults` under key `lastUpdateOffset`
- On app launch, read this value (default 0) and pass as the starting offset
- This prevents re-notifying on restart

### NotificationManager
`NotificationManager` is a class (inherits `NSObject`) that also conforms to `UNUserNotificationCenterDelegate`. It is instantiated once in `CloverBridgeApp` and assigned as `UNUserNotificationCenter.current().delegate = notificationManager` in the `@main` struct's initializer.

- On first launch, calls `UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])`
- Implements `userNotificationCenter(_:didReceive:withCompletionHandler:)`: reads `response.notification.request.content.userInfo["url"]` as `String`, constructs a `URL`, calls `NSWorkspace.shared.open(url)`, then calls `completionHandler()`
- Posts notification via `UNUserNotificationCenter.current().add(request)`: `title` = article title, `body` = URL string, `userInfo = ["url": urlString]`

### MenuBarView
SwiftUI `Popover` attached to the status bar item:
- Last 10 received articles (`ArticleItem` list), each row shows title + relative timestamp, tap opens URL via `NSWorkspace.shared.open()`
- Status line: "Watching: {inboxPath}"
- Connection indicator dot with three states (see State Machine below)
- Login Item toggle (`SMAppService.mainApp.register()` / `.unregister()`)
- First-run settings form: shown when `botToken` or `chatId` is empty in `UserDefaults`; has two text fields + a "Save & Start" button; on tap, saves values and starts `InboxWatcher` + polling timer

### Connection Indicator State Machine

| State | Color | Condition |
|---|---|---|
| `healthy` | green | Last `getUpdates` succeeded AND was within the last 2 minutes |
| `stale` | yellow | Last `getUpdates` succeeded but was more than 2 minutes ago |
| `error` | red | Last `getUpdates` threw an error |

Transitions: any successful poll → `healthy`; poll error → `error`; time elapsed >2min since last success → `stale`. Evaluated on each poll result and on a 15-second UI refresh timer.

### Polling Timer
- Created in `MenuBarApp` (the `@main` struct) as a `DispatchSourceTimer` on a background `DispatchQueue`
- Fires every 30 seconds; handler calls `Task { await pollTelegram() }` to bridge into async context
- Starts only after config is valid (both `botToken` and `chatId` non-empty)
- Lifecycle: observed via `.onChange(of: scenePhase)` in the `@main` body — `active` resumes the timer, `background`/`inactive` suspends it. Timer is created once and never torn down.

## Data Flow

### Outbound (Mac → AWS)
```
User drops file into ~/clover-inbox/
    → FSEventStream fires (kFSEventStreamCreateFlagFileEvents)
    → InboxWatcher filters: file in inbox root, not dotfile, not in-flight
    → TelegramClient.sendDocument(fileURL:chatId:botToken:)
    → On success: move to ~/clover-inbox/processed/
    → On failure: file stays, status dot → red, retry timer picks it up in ≤60s
```

### Inbound (AWS → Mac)
```
DispatchSourceTimer fires every 30s
    → TelegramClient.getUpdates(offset: lastUpdateOffset)
    → Parse each message.text for URL + title
    → If URL found: NotificationManager posts UNUserNotification
    → User clicks notification → UNUserNotificationCenterDelegate → NSWorkspace.open(url)
    → Article prepended to MenuBarView recent list (capped at 10)
    → lastUpdateOffset updated in UserDefaults
    → Connection dot → green
```

## Edge Cases

| Scenario | Handling |
|---|---|
| Send fails (network down) | File stays in inbox, status dot red, retry timer retries all pending inbox files every 60s |
| File >50MB (Telegram limit) | No send attempted; menu bar shows inline error entry: "Too large: {filename}" |
| `getUpdates` fails | Status dot → red, next tick retries automatically |
| `getUpdates` succeeds but stale (>2min gap) | Status dot → yellow |
| Message has no URL | Stored as plain text in recent list, no system notification |
| Duplicate Telegram updates | Prevented by `update_id` offset stored in `UserDefaults` |
| First launch, no config | Popover shows settings form; watching and polling do not start until "Save & Start" is tapped |
| `~/clover-inbox/` missing on launch | Created automatically by `InboxWatcher.start()` before stream is registered |
| Rapid FSEvents for same file | In-flight `Set<String>` prevents duplicate sends |

## Models

```swift
// Models.swift

struct AppConfig {
    // All stored in UserDefaults
    var botToken: String      // key: "botToken"
    var chatId: String        // key: "chatId"
    var inboxPath: String     // key: "inboxPath", default: "~/clover-inbox"
    var lastUpdateOffset: Int // key: "lastUpdateOffset", default: 0
}

struct ArticleItem: Identifiable {
    let id: UUID
    let title: String
    let url: URL?       // nil for plain-text messages with no URL; rows with nil url are not clickable
    let receivedAt: Date
}

struct TelegramUpdate: Decodable {
    let update_id: Int
    let message: TelegramMessage?
}

struct TelegramMessage: Decodable {
    let text: String?
}
```

## Configuration

Stored in `UserDefaults` (no external file):

| Key | Type | Default | Description |
|---|---|---|---|
| `botToken` | String | "" | Telegram bot token |
| `chatId` | String | "" | Telegram chat ID |
| `inboxPath` | String | `~/clover-inbox` | Watched folder path (tilde-prefixed; all code must expand via `(inboxPath as NSString).expandingTildeInPath` before use with `FileManager` or `FSEventStream`) |
| `lastUpdateOffset` | Int | 0 | Next `getUpdates` offset |

## Entitlements & Sandboxing

The app is **not sandboxed** to allow:
- Arbitrary file system access to `~/clover-inbox/`
- Outbound HTTP to `api.telegram.org`

`.entitlements` file requires no special keys. `NSAppTransportSecurity` is not needed since all requests go to `https://` endpoints.

## Tech Decisions

- **Language:** Swift + SwiftUI
- **Transport:** Telegram Bot API (HTTP, no SDK)
- **Networking:** `URLSession` only, no third-party packages
- **File watching:** `FSEventStream` (CoreServices) with `kFSEventStreamCreateFlagFileEvents`
- **Notifications:** `UserNotifications` framework + `UNUserNotificationCenterDelegate`
- **Polling timer:** `DispatchSourceTimer` on background queue
- **Login Item:** `SMAppService.mainApp` (macOS 13+) — requires `import ServiceManagement`
- **Min OS:** macOS 13 Ventura
- **Sandboxing:** Disabled

## File Structure (target)

```
CloverBridge/
├── CloverBridgeApp.swift       — @main entry, NSStatusItem, polling timer setup
├── InboxWatcher.swift          — FSEventStream wrapper, retry timer
├── TelegramClient.swift        — sendDocument + getUpdates, message parsing
├── NotificationManager.swift   — UNUserNotificationCenter + delegate
├── MenuBarView.swift           — SwiftUI popover, connection dot, settings form
├── Models.swift                — ArticleItem, AppConfig, TelegramUpdate structs
├── CloverBridge.entitlements   — no sandbox, no special keys
└── CloverBridge.xcodeproj

Runtime artifacts (not in source):
~/clover-inbox/                 — created by InboxWatcher.start() on first launch
~/clover-inbox/processed/       — created by InboxWatcher.start() on first launch (same time as parent)
```
