# CloverBridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a macOS Swift menu bar app that watches `~/clover-inbox/` for outbound files and receives inbound article notifications from the openclaw AWS bot, both via Telegram Bot API.

**Architecture:** Pure Swift + SwiftUI menu bar app (no external dependencies). Business logic is split into focused, independently testable files. `TelegramClient` owns all network calls. `InboxWatcher` owns all file system events. `NotificationManager` owns all system notification delivery. `CloverBridgeApp` wires them together.

**Tech Stack:** Swift 5.9+, SwiftUI, AppKit (NSStatusItem), FSEventStream (CoreServices), URLSession, UserNotifications, ServiceManagement, XCTest, xcodegen

---

## File Map

| File | Responsibility |
|---|---|
| `CloverBridge/AppState.swift` | `ObservableObject`: holds articles, connectionState, InboxWatcher lifetime, timers |
| `CloverBridge/CloverBridgeApp.swift` | `@main`, `MenuBarExtra`, scenePhase → timer lifecycle |
| `CloverBridge/Models.swift` | `ArticleItem`, `AppConfig`, `TelegramUpdate`, `TelegramMessage` structs |
| `CloverBridge/AppConfig.swift` | UserDefaults read/write for all config keys |
| `CloverBridge/TelegramClient.swift` | `sendDocument`, `getUpdates`, `parseMessage` |
| `CloverBridge/InboxWatcher.swift` | FSEventStream wrapper, file filtering, retry timer |
| `CloverBridge/NotificationManager.swift` | NSObject + UNUserNotificationCenterDelegate |
| `CloverBridge/MenuBarView.swift` | SwiftUI popover: article list, connection dot, settings form |
| `CloverBridge/CloverBridge.entitlements` | No sandbox, no special keys |
| `CloverBridge/Info.plist` | LSUIElement=true (hides Dock icon) |
| `project.yml` | xcodegen spec |
| `CloverBridgeTests/ModelsTests.swift` | Decodable parsing tests |
| `CloverBridgeTests/AppConfigTests.swift` | UserDefaults load/save tests |
| `CloverBridgeTests/TelegramClientTests.swift` | Message parsing + multipart body tests |
| `CloverBridgeTests/InboxWatcherTests.swift` | File filtering logic tests |

**Project root:** `/Users/vladbrincoveanu/Desktop/Startup/CloverBridge/`

---

## Task 1: Project Scaffold

**Files:**
- Create: `project.yml`
- Create: `CloverBridge/CloverBridge.entitlements`
- Create: `CloverBridge/Info.plist`
- Create: `CloverBridgeTests/` (empty directory placeholder)

- [ ] **Step 1: Install xcodegen if needed**

```bash
which xcodegen || brew install xcodegen
```

- [ ] **Step 2: Create project directory**

```bash
mkdir -p /Users/vladbrincoveanu/Desktop/Startup/CloverBridge/CloverBridge
mkdir -p /Users/vladbrincoveanu/Desktop/Startup/CloverBridge/CloverBridgeTests
cd /Users/vladbrincoveanu/Desktop/Startup/CloverBridge
```

- [ ] **Step 3: Write `project.yml`**

```yaml
name: CloverBridge
options:
  bundleIdPrefix: com.clover
  deploymentTarget:
    macOS: "13.0"
  createIntermediateGroups: true
settings:
  SWIFT_VERSION: "5.9"
  MACOSX_DEPLOYMENT_TARGET: "13.0"
targets:
  CloverBridge:
    type: application
    platform: macOS
    sources: [CloverBridge]
    settings:
      PRODUCT_BUNDLE_IDENTIFIER: com.clover.CloverBridge
      CODE_SIGN_STYLE: Automatic
      CODE_SIGN_ENTITLEMENTS: CloverBridge/CloverBridge.entitlements
      INFOPLIST_FILE: CloverBridge/Info.plist
      ENABLE_HARDENED_RUNTIME: NO
  CloverBridgeTests:
    type: bundle.unit-test
    platform: macOS
    sources: [CloverBridgeTests]
    dependencies:
      - target: CloverBridge
    settings:
      PRODUCT_BUNDLE_IDENTIFIER: com.clover.CloverBridgeTests
      CODE_SIGN_STYLE: Automatic
```

- [ ] **Step 4: Write `CloverBridge/CloverBridge.entitlements`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
</dict>
</plist>
```

- [ ] **Step 5: Write `CloverBridge/Info.plist`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>CloverBridge</string>
    <key>CFBundleIdentifier</key>
    <string>com.clover.CloverBridge</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHumanReadableCopyright</key>
    <string></string>
</dict>
</plist>
```

- [ ] **Step 6: Generate the Xcode project**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/CloverBridge
xcodegen generate
```

Expected: `Generating project CloverBridge` and `CloverBridge.xcodeproj` appears.

- [ ] **Step 7: Verify build (empty project)**

Add a minimal placeholder so the target compiles:

`CloverBridge/CloverBridgeApp.swift`:
```swift
import SwiftUI

@main
struct CloverBridgeApp: App {
    var body: some Scene {
        Settings { EmptyView() }
    }
}
```

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/CloverBridge
xcodebuild -scheme CloverBridge -destination "platform=macOS" build 2>&1 | tail -5
```

Expected: `** BUILD SUCCEEDED **`

- [ ] **Step 8: Commit**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/CloverBridge
git init && git add .
git commit -m "chore: scaffold CloverBridge Xcode project"
```

---

## Task 2: Models

**Files:**
- Create: `CloverBridge/Models.swift`
- Create: `CloverBridgeTests/ModelsTests.swift`

- [ ] **Step 1: Write the failing test**

`CloverBridgeTests/ModelsTests.swift`:
```swift
import XCTest
@testable import CloverBridge

final class ModelsTests: XCTestCase {

    func test_telegramUpdate_decodesFromJSON() throws {
        let json = """
        {"update_id": 42, "message": {"text": "hello"}}
        """.data(using: .utf8)!
        let update = try JSONDecoder().decode(TelegramUpdate.self, from: json)
        XCTAssertEqual(update.update_id, 42)
        XCTAssertEqual(update.message?.text, "hello")
    }

    func test_telegramUpdate_decodesNilMessage() throws {
        let json = """
        {"update_id": 7}
        """.data(using: .utf8)!
        let update = try JSONDecoder().decode(TelegramUpdate.self, from: json)
        XCTAssertEqual(update.update_id, 7)
        XCTAssertNil(update.message)
    }

    func test_articleItem_nilUrl_isNotClickable() {
        let item = ArticleItem(id: UUID(), title: "plain text", url: nil, receivedAt: Date())
        XCTAssertNil(item.url)
    }
}
```

- [ ] **Step 2: Run test — expect failure (type not found)**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/CloverBridge
xcodebuild test -scheme CloverBridgeTests -destination "platform=macOS" 2>&1 | grep -E "error:|FAILED|PASSED"
```

Expected: error about `TelegramUpdate` not found.

- [ ] **Step 3: Write `CloverBridge/Models.swift`**

```swift
import Foundation

struct TelegramUpdate: Decodable {
    let update_id: Int
    let message: TelegramMessage?
}

struct TelegramMessage: Decodable {
    let text: String?
}

struct ArticleItem: Identifiable {
    let id: UUID
    let title: String
    let url: URL?       // nil for plain-text messages; rows with nil url are not clickable
    let receivedAt: Date
}
```

- [ ] **Step 4: Run tests — expect pass**

```bash
xcodebuild test -scheme CloverBridgeTests -destination "platform=macOS" 2>&1 | grep -E "Test.*passed|FAILED|error:"
```

Expected: 3 tests passed.

- [ ] **Step 5: Commit**

```bash
git add CloverBridge/Models.swift CloverBridgeTests/ModelsTests.swift
git commit -m "feat: add Models (TelegramUpdate, ArticleItem)"
```

---

## Task 3: AppConfig

**Files:**
- Create: `CloverBridge/AppConfig.swift`
- Create: `CloverBridgeTests/AppConfigTests.swift`

- [ ] **Step 1: Write the failing test**

`CloverBridgeTests/AppConfigTests.swift`:
```swift
import XCTest
@testable import CloverBridge

final class AppConfigTests: XCTestCase {

    var suiteName: String!
    var defaults: UserDefaults!

    override func setUp() {
        suiteName = "test-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suiteName)!
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suiteName)
    }

    func test_defaultValues() {
        let config = AppConfig(defaults: defaults)
        XCTAssertEqual(config.botToken, "")
        XCTAssertEqual(config.chatId, "")
        XCTAssertEqual(config.inboxPath, "~/clover-inbox")
        XCTAssertEqual(config.lastUpdateOffset, 0)
    }

    func test_savesAndLoadsValues() {
        var config = AppConfig(defaults: defaults)
        config.botToken = "abc123"
        config.chatId = "9999"
        config.inboxPath = "~/custom-inbox"
        config.lastUpdateOffset = 42

        let loaded = AppConfig(defaults: defaults)
        XCTAssertEqual(loaded.botToken, "abc123")
        XCTAssertEqual(loaded.chatId, "9999")
        XCTAssertEqual(loaded.inboxPath, "~/custom-inbox")
        XCTAssertEqual(loaded.lastUpdateOffset, 42)
    }

    func test_isConfigured_requiresBothTokenAndChatId() {
        var config = AppConfig(defaults: defaults)
        XCTAssertFalse(config.isConfigured)
        config.botToken = "tok"
        XCTAssertFalse(config.isConfigured)
        config.chatId = "123"
        XCTAssertTrue(config.isConfigured)
    }

    func test_expandedInboxPath_expandsTilde() {
        var config = AppConfig(defaults: defaults)
        config.inboxPath = "~/clover-inbox"
        XCTAssertFalse(config.expandedInboxPath.contains("~"))
        XCTAssertTrue(config.expandedInboxPath.contains("/clover-inbox"))
    }
}
```

- [ ] **Step 2: Run test — expect failure**

```bash
xcodebuild test -scheme CloverBridgeTests -destination "platform=macOS" 2>&1 | grep -E "error:|FAILED"
```

Expected: `AppConfig` not found.

- [ ] **Step 3: Write `CloverBridge/AppConfig.swift`**

```swift
import Foundation

struct AppConfig {
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    var botToken: String {
        get { defaults.string(forKey: "botToken") ?? "" }
        set { defaults.set(newValue, forKey: "botToken") }
    }

    var chatId: String {
        get { defaults.string(forKey: "chatId") ?? "" }
        set { defaults.set(newValue, forKey: "chatId") }
    }

    var inboxPath: String {
        get { defaults.string(forKey: "inboxPath") ?? "~/clover-inbox" }
        set { defaults.set(newValue, forKey: "inboxPath") }
    }

    var lastUpdateOffset: Int {
        get { defaults.integer(forKey: "lastUpdateOffset") }
        set { defaults.set(newValue, forKey: "lastUpdateOffset") }
    }

    var isConfigured: Bool {
        !botToken.isEmpty && !chatId.isEmpty
    }

    var expandedInboxPath: String {
        (inboxPath as NSString).expandingTildeInPath
    }
}
```

- [ ] **Step 4: Run tests — expect pass**

```bash
xcodebuild test -scheme CloverBridgeTests -destination "platform=macOS" 2>&1 | grep -E "Test.*passed|FAILED|error:"
```

Expected: all tests passed.

- [ ] **Step 5: Commit**

```bash
git add CloverBridge/AppConfig.swift CloverBridgeTests/AppConfigTests.swift
git commit -m "feat: add AppConfig with UserDefaults persistence"
```

---

## Task 4: TelegramClient — Message Parsing

**Files:**
- Create: `CloverBridge/TelegramClient.swift` (parsing only for now)
- Create: `CloverBridgeTests/TelegramClientTests.swift`

- [ ] **Step 1: Write the failing tests**

`CloverBridgeTests/TelegramClientTests.swift`:
```swift
import XCTest
@testable import CloverBridge

final class TelegramClientTests: XCTestCase {

    // MARK: - Message Parsing

    func test_parseMessage_urlOnlyLine() {
        let result = TelegramClient.parseMessage("https://example.com/article")
        XCTAssertEqual(result?.url, URL(string: "https://example.com/article"))
        XCTAssertEqual(result?.title, "example.com")   // falls back to host
    }

    func test_parseMessage_titleThenUrl() {
        let text = "Great article about Swift\nhttps://swift.org/blog"
        let result = TelegramClient.parseMessage(text)
        XCTAssertEqual(result?.title, "Great article about Swift")
        XCTAssertEqual(result?.url, URL(string: "https://swift.org/blog"))
    }

    func test_parseMessage_multilineTitleThenUrl() {
        let text = "Line one\nLine two\nhttps://example.com"
        let result = TelegramClient.parseMessage(text)
        XCTAssertEqual(result?.title, "Line one Line two")
    }

    func test_parseMessage_noUrl_returnsNilUrl() {
        let result = TelegramClient.parseMessage("Just a plain text message")
        XCTAssertNotNil(result)
        XCTAssertNil(result?.url)
        XCTAssertEqual(result?.title, "Just a plain text message")
    }

    func test_parseMessage_firstUrlUsedWhenMultiple() {
        let text = "Pick one\nhttps://first.com\nhttps://second.com"
        let result = TelegramClient.parseMessage(text)
        XCTAssertEqual(result?.url, URL(string: "https://first.com"))
    }

    func test_parseMessage_httpUrl() {
        let result = TelegramClient.parseMessage("http://example.com")
        XCTAssertNotNil(result?.url)
    }

    func test_parseMessage_emptyTextReturnsNil() {
        XCTAssertNil(TelegramClient.parseMessage(""))
    }

    func test_parseMessage_whitespaceOnlyReturnsNil() {
        XCTAssertNil(TelegramClient.parseMessage("   \n  "))
    }

    // MARK: - Multipart Body

    func test_buildMultipartBody_containsChatIdField() {
        let (data, boundary) = TelegramClient.buildMultipartBody(
            chatId: "123",
            fileURL: URL(fileURLWithPath: "/tmp/test.txt"),
            fileData: Data("hello".utf8)
        )
        let body = String(data: data, encoding: .utf8)!
        XCTAssertTrue(body.contains("--\(boundary)"))
        XCTAssertTrue(body.contains("name=\"chat_id\""))
        XCTAssertTrue(body.contains("123"))
    }

    func test_buildMultipartBody_containsDocumentField() {
        let fileData = Data("file contents".utf8)
        let (data, boundary) = TelegramClient.buildMultipartBody(
            chatId: "456",
            fileURL: URL(fileURLWithPath: "/tmp/myfile.pdf"),
            fileData: fileData
        )
        let body = String(data: data, encoding: .utf8)!
        XCTAssertTrue(body.contains("name=\"document\""))
        XCTAssertTrue(body.contains("filename=\"myfile.pdf\""))
        XCTAssertTrue(body.contains("application/octet-stream"))
        XCTAssertTrue(body.contains("--\(boundary)--"))
    }
}
```

- [ ] **Step 2: Run test — expect failure**

```bash
xcodebuild test -scheme CloverBridgeTests -destination "platform=macOS" 2>&1 | grep -E "error:|FAILED"
```

Expected: `TelegramClient` not found.

- [ ] **Step 3: Write `CloverBridge/TelegramClient.swift`** (parsing + body only, network in next task)

```swift
import Foundation

final class TelegramClient {

    // MARK: - Message Parsing

    static func parseMessage(_ text: String) -> (title: String, url: URL?)? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        let lines = trimmed.components(separatedBy: "\n")
        var urlLine: Int? = nil
        var foundURL: URL? = nil

        for (index, line) in lines.enumerated() {
            let l = line.trimmingCharacters(in: .whitespaces)
            if l.hasPrefix("http://") || l.hasPrefix("https://") {
                if let url = URL(string: l) {
                    urlLine = index
                    foundURL = url
                    break
                }
            }
        }

        if let urlLine = urlLine, let url = foundURL {
            let titleLines = lines[..<urlLine]
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
            let title = titleLines.isEmpty ? (url.host ?? url.absoluteString) : titleLines.joined(separator: " ")
            return (title: title, url: url)
        } else {
            // No URL found — return as plain text
            return (title: trimmed, url: nil)
        }
    }

    // MARK: - Multipart Body

    /// Returns (bodyData, boundary) for use in a multipart/form-data POST.
    static func buildMultipartBody(
        chatId: String,
        fileURL: URL,
        fileData: Data
    ) -> (Data, String) {
        let boundary = UUID().uuidString
        var body = Data()

        func append(_ string: String) {
            body.append(Data(string.utf8))
        }

        // chat_id field
        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"chat_id\"\r\n\r\n")
        append("\(chatId)\r\n")

        // document field
        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"document\"; filename=\"\(fileURL.lastPathComponent)\"\r\n")
        append("Content-Type: application/octet-stream\r\n\r\n")
        body.append(fileData)
        append("\r\n")

        // closing boundary
        append("--\(boundary)--\r\n")

        return (body, boundary)
    }
}
```

- [ ] **Step 4: Run tests — expect pass**

```bash
xcodebuild test -scheme CloverBridgeTests -destination "platform=macOS" 2>&1 | grep -E "Test.*passed|FAILED|error:"
```

Expected: all tests passed.

- [ ] **Step 5: Commit**

```bash
git add CloverBridge/TelegramClient.swift CloverBridgeTests/TelegramClientTests.swift
git commit -m "feat: add TelegramClient message parsing and multipart body builder"
```

---

## Task 5: TelegramClient — Network Methods

**Files:**
- Modify: `CloverBridge/TelegramClient.swift` (add `sendDocument` and `getUpdates`)

No unit tests for network calls — they hit a live API. Integration verified manually in Task 12.

- [ ] **Step 1: Add network methods to `TelegramClient.swift`**

Append to the existing `TelegramClient` class body:

```swift
    // MARK: - Network

    func sendDocument(fileURL: URL, chatId: String, botToken: String) async throws {
        let fileData = try Data(contentsOf: fileURL)
        let (body, boundary) = TelegramClient.buildMultipartBody(
            chatId: chatId,
            fileURL: fileURL,
            fileData: fileData
        )

        let url = URL(string: "https://api.telegram.org/bot\(botToken)/sendDocument")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw TelegramError.httpError
        }
        let result = try JSONDecoder().decode(TelegramResponse.self, from: data)
        guard result.ok else { throw TelegramError.apiError }
    }

    func getUpdates(offset: Int, botToken: String) async throws -> [TelegramUpdate] {
        let url = URL(string: "https://api.telegram.org/bot\(botToken)/getUpdates?offset=\(offset)&limit=10&timeout=0")!
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw TelegramError.httpError
        }
        let result = try JSONDecoder().decode(TelegramGetUpdatesResponse.self, from: data)
        guard result.ok else { throw TelegramError.apiError }
        return result.result
    }
```

Also add these private types to `Models.swift`:

```swift
// Add to Models.swift

struct TelegramResponse: Decodable {
    let ok: Bool
}

struct TelegramGetUpdatesResponse: Decodable {
    let ok: Bool
    let result: [TelegramUpdate]
}

enum TelegramError: Error {
    case httpError
    case apiError
}
```

- [ ] **Step 2: Build — expect success**

```bash
xcodebuild -scheme CloverBridge -destination "platform=macOS" build 2>&1 | tail -3
```

Expected: `** BUILD SUCCEEDED **`

- [ ] **Step 3: Run existing tests — still pass**

```bash
xcodebuild test -scheme CloverBridgeTests -destination "platform=macOS" 2>&1 | grep -E "Test.*passed|FAILED|error:"
```

- [ ] **Step 4: Commit**

```bash
git add CloverBridge/TelegramClient.swift CloverBridge/Models.swift
git commit -m "feat: add TelegramClient network methods (sendDocument, getUpdates)"
```

---

## Task 6: InboxWatcher — File Filtering

**Files:**
- Create: `CloverBridge/InboxWatcher.swift` (filtering logic only)
- Create: `CloverBridgeTests/InboxWatcherTests.swift`

- [ ] **Step 1: Write the failing tests**

`CloverBridgeTests/InboxWatcherTests.swift`:
```swift
import XCTest
@testable import CloverBridge

final class InboxWatcherTests: XCTestCase {

    func test_shouldProcess_regularFile_returnsTrue() {
        XCTAssertTrue(InboxWatcher.shouldProcess("/Users/vlad/clover-inbox/note.txt",
                                                  inboxRoot: "/Users/vlad/clover-inbox"))
    }

    func test_shouldProcess_dotfileReturnsFalse() {
        XCTAssertFalse(InboxWatcher.shouldProcess("/Users/vlad/clover-inbox/.DS_Store",
                                                   inboxRoot: "/Users/vlad/clover-inbox"))
    }

    func test_shouldProcess_processedSubdirReturnsFalse() {
        XCTAssertFalse(InboxWatcher.shouldProcess("/Users/vlad/clover-inbox/processed/old.txt",
                                                   inboxRoot: "/Users/vlad/clover-inbox"))
    }

    func test_shouldProcess_nestedFileReturnsFalse() {
        // Only top-level files in inbox root are processed
        XCTAssertFalse(InboxWatcher.shouldProcess("/Users/vlad/clover-inbox/subfolder/file.txt",
                                                   inboxRoot: "/Users/vlad/clover-inbox"))
    }

    func test_shouldProcess_inboxRootItselfReturnsFalse() {
        XCTAssertFalse(InboxWatcher.shouldProcess("/Users/vlad/clover-inbox",
                                                   inboxRoot: "/Users/vlad/clover-inbox"))
    }

    func test_fileSizeExceedsLimit() {
        XCTAssertTrue(InboxWatcher.exceedsLimit(bytes: 52_428_801))
        XCTAssertFalse(InboxWatcher.exceedsLimit(bytes: 52_428_800))
        XCTAssertFalse(InboxWatcher.exceedsLimit(bytes: 1024))
    }
}
```

- [ ] **Step 2: Run test — expect failure**

```bash
xcodebuild test -scheme CloverBridgeTests -destination "platform=macOS" 2>&1 | grep -E "error:|FAILED"
```

Expected: `InboxWatcher` not found.

- [ ] **Step 3: Write `CloverBridge/InboxWatcher.swift`** (filtering logic + FSEventStream stub)

```swift
import Foundation
import CoreServices

final class InboxWatcher {

    private let config: AppConfig
    private let onFile: @Sendable (URL) async -> Void      // called per qualifying file
    private let onError: @Sendable (String) async -> Void  // called for oversized files

    private var eventStream: FSEventStreamRef?
    private var retryTimer: DispatchSourceTimer?
    private var inFlight = Set<String>()

    init(config: AppConfig,
         onFile: @escaping @Sendable (URL) async -> Void,
         onError: @escaping @Sendable (String) async -> Void) {
        self.config = config
        self.onFile = onFile
        self.onError = onError
    }

    // MARK: - Pure helpers (static, testable without FSEventStream)

    /// Returns true if this path is a top-level file in the inbox root (not dotfile, not in processed/).
    static func shouldProcess(_ path: String, inboxRoot: String) -> Bool {
        guard path != inboxRoot else { return false }
        let filename = (path as NSString).lastPathComponent
        guard !filename.hasPrefix(".") else { return false }
        guard !path.contains("/processed/") else { return false }
        // Must be a direct child (no extra path separators after root)
        let relative = String(path.dropFirst(inboxRoot.count))
        let components = relative.split(separator: "/", omittingEmptySubsequences: true)
        return components.count == 1
    }

    /// Returns true if file byte count exceeds Telegram's 50 MB document limit.
    static func exceedsLimit(bytes: Int) -> Bool {
        bytes > 52_428_800
    }

    // MARK: - Lifecycle

    func start() {
        let expandedPath = config.expandedInboxPath
        let fm = FileManager.default
        try? fm.createDirectory(atPath: expandedPath, withIntermediateDirectories: true)
        try? fm.createDirectory(atPath: expandedPath + "/processed", withIntermediateDirectories: true)

        startFSEventStream(path: expandedPath)
        startRetryTimer(inboxRoot: expandedPath)
    }

    func stop() {
        if let stream = eventStream {
            FSEventStreamStop(stream)
            FSEventStreamInvalidate(stream)
            FSEventStreamRelease(stream)
            eventStream = nil
        }
        retryTimer?.cancel()
        retryTimer = nil
    }

    deinit {
        // Release the retained self pointer passed to FSEventStreamContext.info
        // (must happen before stop() sets eventStream to nil)
        Unmanaged.passUnretained(self).release()
        stop()
    }

    // MARK: - FSEventStream

    private func startFSEventStream(path: String) {
        var ctx = FSEventStreamContext(
            version: 0,
            info: Unmanaged.passRetained(self).toOpaque(),
            retain: nil,
            release: nil,
            copyDescription: nil
        )

        let callback: FSEventStreamCallback = { _, info, numEvents, eventPaths, _, _ in
            guard let info = info else { return }
            let watcher = Unmanaged<InboxWatcher>.fromOpaque(info).takeUnretainedValue()
            let paths = unsafeBitCast(eventPaths, to: NSArray.self) as! [String]
            Task { await watcher.handlePaths(paths) }
        }

        let stream = FSEventStreamCreate(
            nil,
            callback,
            &ctx,
            [path] as CFArray,
            FSEventStreamEventId(kFSEventStreamEventIdSinceNow),
            0.5,
            FSEventStreamCreateFlags(kFSEventStreamCreateFlagFileEvents | kFSEventStreamCreateFlagUseCFTypes)
        )!

        FSEventStreamScheduleWithRunLoop(stream, CFRunLoopGetMain(), CFRunLoopMode.defaultMode.rawValue)
        FSEventStreamStart(stream)
        eventStream = stream
    }

    private func handlePaths(_ paths: [String]) async {
        let inboxRoot = config.expandedInboxPath
        for path in paths {
            guard InboxWatcher.shouldProcess(path, inboxRoot: inboxRoot) else { continue }
            guard !inFlight.contains(path) else { continue }
            await processFile(at: path)
        }
    }

    // MARK: - Retry Timer

    private func startRetryTimer(inboxRoot: String) {
        let timer = DispatchSource.makeTimerSource(queue: .global(qos: .background))
        timer.schedule(deadline: .now() + 60, repeating: 60)
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            Task { await self.retryPendingFiles(inboxRoot: inboxRoot) }
        }
        timer.resume()
        retryTimer = timer
    }

    private func retryPendingFiles(inboxRoot: String) async {
        let fm = FileManager.default
        guard let contents = try? fm.contentsOfDirectory(atPath: inboxRoot) else { return }
        for filename in contents {
            let path = inboxRoot + "/" + filename
            guard InboxWatcher.shouldProcess(path, inboxRoot: inboxRoot) else { continue }
            guard !inFlight.contains(path) else { continue }
            await processFile(at: path)
        }
    }

    // MARK: - File Processing

    private func processFile(at path: String) async {
        let url = URL(fileURLWithPath: path)
        let attrs = try? FileManager.default.attributesOfItem(atPath: path)
        let size = (attrs?[.size] as? Int) ?? 0

        if InboxWatcher.exceedsLimit(bytes: size) {
            await onError("Too large: \(url.lastPathComponent)")
            return
        }

        inFlight.insert(path)
        await onFile(url)
        // Caller is responsible for calling fileDidSend(path:) or fileDidFail(path:)
    }

    func fileDidSend(path: String) {
        inFlight.remove(path)
        let processed = config.expandedInboxPath + "/processed/" + (path as NSString).lastPathComponent
        try? FileManager.default.moveItem(atPath: path, toPath: processed)
    }

    func fileDidFail(path: String) {
        inFlight.remove(path)
    }
}
```

- [ ] **Step 4: Run tests — expect pass**

```bash
xcodebuild test -scheme CloverBridgeTests -destination "platform=macOS" 2>&1 | grep -E "Test.*passed|FAILED|error:"
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add CloverBridge/InboxWatcher.swift CloverBridgeTests/InboxWatcherTests.swift
git commit -m "feat: add InboxWatcher with FSEventStream and file filtering"
```

---

## Task 7: NotificationManager

**Files:**
- Create: `CloverBridge/NotificationManager.swift`

No unit tests — wraps OS API directly. Verified manually in Task 12.

- [ ] **Step 1: Write `CloverBridge/NotificationManager.swift`**

```swift
import Foundation
import UserNotifications
import AppKit

final class NotificationManager: NSObject, UNUserNotificationCenterDelegate {

    override init() {
        super.init()
        UNUserNotificationCenter.current().delegate = self
    }

    func requestPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    func post(title: String, urlString: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = urlString
        content.userInfo = ["url": urlString]
        let request = UNNotificationRequest(
            identifier: UUID().uuidString,
            content: content,
            trigger: nil
        )
        UNUserNotificationCenter.current().add(request)
    }

    // MARK: - UNUserNotificationCenterDelegate

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        if let urlString = response.notification.request.content.userInfo["url"] as? String,
           let url = URL(string: urlString) {
            NSWorkspace.shared.open(url)
        }
        completionHandler()
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound])
    }
}
```

- [ ] **Step 2: Build — expect success**

```bash
xcodebuild -scheme CloverBridge -destination "platform=macOS" build 2>&1 | tail -3
```

- [ ] **Step 3: Commit**

```bash
git add CloverBridge/NotificationManager.swift
git commit -m "feat: add NotificationManager (UNUserNotificationCenterDelegate)"
```

---

## Task 8: MenuBarView

**Files:**
- Create: `CloverBridge/MenuBarView.swift`

No unit tests — SwiftUI view. Verified visually in Task 12.

- [ ] **Step 1: Write `CloverBridge/MenuBarView.swift`**

```swift
import SwiftUI
import ServiceManagement

enum ConnectionState {
    case healthy, stale, error

    var color: Color {
        switch self {
        case .healthy: return .green
        case .stale:   return .yellow
        case .error:   return .red
        }
    }
}

struct MenuBarView: View {
    @Binding var articles: [ArticleItem]
    @Binding var connectionState: ConnectionState
    @Binding var config: AppConfig
    var onSaveAndStart: () -> Void

    @State private var isLoginItem: Bool = (try? SMAppService.mainApp.status == .enabled) ?? false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if !config.isConfigured {
                settingsForm
            } else {
                articleList
                Divider()
                footer
            }
        }
        .frame(width: 320)
        .padding(.vertical, 8)
    }

    // MARK: - Settings Form (first run)

    private var settingsForm: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("CloverBridge Setup")
                .font(.headline)
                .padding(.horizontal)

            VStack(alignment: .leading, spacing: 6) {
                Text("Bot Token").font(.caption).foregroundColor(.secondary)
                TextField("8504388100:AAH...", text: $config.botToken)
                    .textFieldStyle(.roundedBorder)
            }
            .padding(.horizontal)

            VStack(alignment: .leading, spacing: 6) {
                Text("Chat ID").font(.caption).foregroundColor(.secondary)
                TextField("1790488473", text: $config.chatId)
                    .textFieldStyle(.roundedBorder)
            }
            .padding(.horizontal)

            Button("Save & Start") {
                onSaveAndStart()
            }
            .buttonStyle(.borderedProminent)
            .disabled(config.botToken.isEmpty || config.chatId.isEmpty)
            .padding(.horizontal)
        }
        .padding(.vertical, 8)
    }

    // MARK: - Article List

    private var articleList: some View {
        Group {
            if articles.isEmpty {
                Text("No articles yet")
                    .foregroundColor(.secondary)
                    .font(.caption)
                    .padding()
            } else {
                ForEach(articles) { item in
                    articleRow(item)
                    Divider()
                }
            }
        }
    }

    private func articleRow(_ item: ArticleItem) -> some View {
        Button {
            if let url = item.url {
                NSWorkspace.shared.open(url)
            }
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.title)
                        .lineLimit(2)
                        .font(.system(size: 12))
                    Text(item.receivedAt, style: .relative)
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                Spacer()
            }
            .padding(.horizontal)
            .padding(.vertical, 4)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(item.url == nil)
    }

    // MARK: - Footer

    private var footer: some View {
        HStack {
            Circle()
                .fill(connectionState.color)
                .frame(width: 8, height: 8)
            Text("Watching: \(config.inboxPath)")
                .font(.caption)
                .foregroundColor(.secondary)
            Spacer()
            Toggle("Login Item", isOn: $isLoginItem)
                .toggleStyle(.checkbox)
                .font(.caption)
                .onChange(of: isLoginItem) { enabled in
                    if enabled {
                        try? SMAppService.mainApp.register()
                    } else {
                        try? SMAppService.mainApp.unregister()
                    }
                }
        }
        .padding(.horizontal)
        .padding(.top, 6)
    }
}
```

- [ ] **Step 2: Build — expect success**

```bash
xcodebuild -scheme CloverBridge -destination "platform=macOS" build 2>&1 | tail -3
```

- [ ] **Step 3: Commit**

```bash
git add CloverBridge/MenuBarView.swift
git commit -m "feat: add MenuBarView SwiftUI popover"
```

---

## Task 9: CloverBridgeApp — Wiring

**Files:**
- Create: `CloverBridge/AppState.swift` (ObservableObject holding all mutable state + watcher lifetime)
- Modify: `CloverBridge/CloverBridgeApp.swift` (replace placeholder with wired-up entry point)

- [ ] **Step 1: Create `CloverBridge/AppState.swift`** (holds mutable app state + watcher lifetime)

`AppState` is a class (reference type) so it can be stored as `@StateObject` and hold the `InboxWatcher` reference across SwiftUI redraws.

```swift
import Foundation
import SwiftUI

@MainActor
final class AppState: ObservableObject {

    @Published var articles: [ArticleItem] = []
    @Published var connectionState: ConnectionState = .stale
    @Published var config = AppConfig()

    let notificationManager = NotificationManager()
    let telegramClient = TelegramClient()

    private var inboxWatcher: InboxWatcher?
    private var pollTimer: DispatchSourceTimer?
    private var refreshTimer: DispatchSourceTimer?
    private var lastSuccessDate: Date?

    init() {
        notificationManager.requestPermission()
        setupRefreshTimer()
        if config.isConfigured { startWatchingAndPolling() }
    }

    // MARK: - Start

    func startWatchingAndPolling() {
        startInboxWatcher()
        startPollTimer()
    }

    // MARK: - Inbox Watcher

    private func startInboxWatcher() {
        let watcher = InboxWatcher(
            config: config,
            onFile: { [weak self] url in
                guard let self else { return }
                await self.sendFile(url: url)
            },
            onError: { [weak self] message in
                guard let self else { return }
                // @MainActor class — assign directly on main actor
                let item = ArticleItem(id: UUID(), title: message, url: nil, receivedAt: Date())
                self.articles.insert(item, at: 0)
                if self.articles.count > 10 { self.articles = Array(self.articles.prefix(10)) }
            }
        )
        watcher.start()
        inboxWatcher = watcher   // ← stored; watcher now lives as long as AppState
    }

    private func sendFile(url: URL) async {
        guard let watcher = inboxWatcher else { return }
        do {
            try await telegramClient.sendDocument(
                fileURL: url,
                chatId: config.chatId,
                botToken: config.botToken
            )
            watcher.fileDidSend(path: url.path)
            // Already on @MainActor — assign directly, no MainActor.run needed
            connectionState = .healthy
            lastSuccessDate = Date()
        } catch {
            watcher.fileDidFail(path: url.path)
            connectionState = .error
        }
    }

    // MARK: - Polling Timer

    func startPollTimer() {
        let timer = DispatchSource.makeTimerSource(queue: .global(qos: .background))
        timer.schedule(deadline: .now() + 1, repeating: 30)
        timer.setEventHandler { [weak self] in Task { await self?.pollTelegram() } }
        timer.resume()
        pollTimer = timer
    }

    func suspendPollTimer() { pollTimer?.suspend() }
    func resumePollTimer()  { pollTimer?.resume() }

    private func pollTelegram() async {
        do {
            let updates = try await telegramClient.getUpdates(
                offset: config.lastUpdateOffset,
                botToken: config.botToken
            )
            // Already on @MainActor — assign directly
            processUpdates(updates)
            connectionState = .healthy
            lastSuccessDate = Date()
        } catch {
            connectionState = .error
        }
    }

    @MainActor
    private func processUpdates(_ updates: [TelegramUpdate]) {
        guard !updates.isEmpty else { return }
        for update in updates {
            guard let text = update.message?.text,
                  let parsed = TelegramClient.parseMessage(text) else { continue }
            let item = ArticleItem(id: UUID(), title: parsed.title, url: parsed.url, receivedAt: Date())
            articles.insert(item, at: 0)
            if articles.count > 10 { articles = Array(articles.prefix(10)) }
            if let url = parsed.url {
                notificationManager.post(title: parsed.title, urlString: url.absoluteString)
            }
        }
        if let maxId = updates.map(\.update_id).max() {
            config.lastUpdateOffset = maxId + 1
        }
    }

    // MARK: - Staleness Refresh Timer (15s)

    private func setupRefreshTimer() {
        let timer = DispatchSource.makeTimerSource(queue: .main)
        timer.schedule(deadline: .now() + 15, repeating: 15)
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            // Transition healthy → stale if last success was >2 minutes ago
            if connectionState == .healthy,
               let last = lastSuccessDate,
               Date().timeIntervalSince(last) > 120 {
                connectionState = .stale
            }
        }
        timer.resume()
        refreshTimer = timer
    }
}
```

- [ ] **Step 2: Replace `CloverBridgeApp.swift` with the wired-up entry point**

```swift
import SwiftUI

@main
struct CloverBridgeApp: App {

    @StateObject private var appState = AppState()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        MenuBarExtra("CloverBridge", systemImage: "leaf.fill") {
            MenuBarView(
                articles: $appState.articles,
                connectionState: $appState.connectionState,
                config: $appState.config,
                onSaveAndStart: appState.startWatchingAndPolling
            )
            .environmentObject(appState)
        }
        .menuBarExtraStyle(.window)
        .onChange(of: scenePhase) { _, phase in
            switch phase {
            case .active:   appState.resumePollTimer()
            default:        appState.suspendPollTimer()
            }
        }
    }
}
```

- [ ] **Step 2: Build — expect success**

```bash
xcodebuild -scheme CloverBridge -destination "platform=macOS" build 2>&1 | tail -5
```

Expected: `** BUILD SUCCEEDED **`

- [ ] **Step 3: Run all tests — expect pass**

```bash
xcodebuild test -scheme CloverBridgeTests -destination "platform=macOS" 2>&1 | grep -E "Test.*passed|FAILED|error:"
```

- [ ] **Step 3: Build — expect success**

```bash
xcodebuild -scheme CloverBridge -destination "platform=macOS" build 2>&1 | tail -5
```

Expected: `** BUILD SUCCEEDED **`

- [ ] **Step 4: Run all tests — expect pass**

```bash
xcodebuild test -scheme CloverBridgeTests -destination "platform=macOS" 2>&1 | grep -E "Test.*passed|FAILED|error:"
```

- [ ] **Step 5: Commit**

```bash
git add CloverBridge/AppState.swift CloverBridge/CloverBridgeApp.swift
git commit -m "feat: wire up CloverBridgeApp with AppState, polling, and inbox watching"
```

---

## Task 10: Manual Integration Test

**Prerequisites:** LLM Studio does NOT need to be running. You need:
- The bot token: `8504388100:AAHwbvNUOosAHPtgbZ1d51OcJOiHNVtPyAc`
- The chat ID: `1790488473`
- The openclaw bot running on AWS (or a test message sent directly via Telegram)

- [ ] **Step 1: Build and run the app**

Open in Xcode (Cmd+R is the simplest path). Or find the built app via:
```bash
xcodebuild -scheme CloverBridge -destination "platform=macOS" -derivedDataPath /tmp/cb-build build 2>&1 | tail -3
open /tmp/cb-build/Build/Products/Debug/CloverBridge.app
```

- [ ] **Step 2: Configure via menu bar**

Click the 🍀 icon in the menu bar → fill in bot token and chat ID → click "Save & Start". The status dot should turn green.

- [ ] **Step 3: Test outbound — drop a file**

```bash
echo "Hello from Mac" > ~/clover-inbox/test-note.txt
```

Expected within 2 seconds: the file appears as a document in your Telegram bot chat. Then `~/clover-inbox/test-note.txt` moves to `~/clover-inbox/processed/test-note.txt`.

- [ ] **Step 4: Test inbound — send an article from Telegram**

Send this message to your bot from Telegram (same chat):
```
Interesting article about AI
https://example.com/ai-article
```

Expected within 30 seconds: macOS notification appears with title "Interesting article about AI". Clicking it opens `https://example.com/ai-article` in the browser.

- [ ] **Step 5: Test oversized file rejection**

```bash
dd if=/dev/zero of=~/clover-inbox/bigfile.bin bs=1m count=55
```

Expected: no send attempted; menu bar shows "Too large: bigfile.bin" in the article list.

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: CloverBridge v1.0 — two-way Telegram bridge menu bar app"
```

---

## Notes

- **`TelegramClient` methods:** `sendDocument` and `getUpdates` are written as instance methods in Task 5. `AppState` instantiates `TelegramClient()` and calls them as instance methods — this is consistent throughout the plan.
- **`dd` unit on macOS:** `bs=1m` uses lowercase `m` (megabytes) — correct for macOS/BSD `dd`. GNU `dd` uses `M`. The command in Task 10 Step 5 is correct for macOS.
