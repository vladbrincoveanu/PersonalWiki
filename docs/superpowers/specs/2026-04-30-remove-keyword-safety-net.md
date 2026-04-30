# Remove Keyword Safety Net — Design Spec

**Date:** 2026-04-30
**Status:** Implemented

## Overview

Remove the `confirm()` dialog when deleting a keyword from the personalWiki discovery panel. Deletion is already idempotent and cascade-delete is intentional.

## Context

When a user deletes a keyword from the discovery panel, the UI currently shows a browser `confirm()` dialog requiring explicit user acknowledgment before deletion proceeds. The dialog text is:

```
Remove keyword "<keyword>"?

This will delete all discovery articles tagged with this keyword.
```

This is a "safety net" that was added to prevent accidental deletions. However:
- The operation is logged server-side
- There's no undo mechanism (deletion is permanent)
- The user intentionally clicked delete
- The dialog creates friction without meaningful protection

## Decision

Remove the `confirm()` dialog entirely. Keyword deletion proceeds immediately on click.

## Changes

### `templates/index.html`

**Before (line ~788):**
```javascript
async function removeKeyword(kw) {
    if (!confirm('Remove keyword "' + kw + '"?\n\nThis will delete all discovery articles tagged with this keyword.')) return;
    try {
        const res = await fetch('/keywords/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword: kw })
        });
        if (res.ok) loadKeywords();
    } catch(e) { console.error('Failed to remove keyword', e); }
}
```

**After:**
```javascript
async function removeKeyword(kw) {
    try {
        const res = await fetch('/keywords/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword: kw })
        });
        if (res.ok) loadKeywords();
    } catch(e) { console.error('Failed to remove keyword', e); }
}
```

### Module: removeKeyword
- **Responsibility:** POST to `/keywords/remove` and refresh the keywords list
- **Interface:** `kw` (string) → triggers API call, refreshes UI on success
- **Dependencies:** `/keywords/remove` endpoint, `loadKeywords()`
- **Size target:** ~10 lines
