English | [Tiếng Việt](ui-url-state.vi.md)

# URL state convention for list screens

This document is a mandatory rule when creating or changing a module that has a list, filters, search, sorting or pagination. The goal is that users can refresh, use Back/Forward and copy a link for someone else and still open exactly the context they were viewing.

## 1. Which state must be in the URL

- Every state that changes the result set, or a view that is meaningful to share, must be a query param: project/scope, status, target, priority, keyword, date, tab/view, sort and page position.
- State that only serves a temporary interaction does not go into the URL: an open dialog, a hovered row, an unsaved draft, loading and transient notices.
- Use stable, lowercase keys with business meaning. Shared values should prefer stable codes such as `project=<code>`; do not expose internal UUIDs when a public code exists.
- Default values must be omitted from the URL so the canonical link is short and there are not multiple URLs for the same screen.

## 2. Filters, search and browser history

- Choosing a filter, sort, tab or date through an explicit action must create a history entry (`push`) so Back/Forward restores each choice.
- Continuously typed keywords must be debounced and replace the current history entry (`replace`), not create one entry per keystroke.
- Whenever the filter, search, sort or page size changes, all pagination state must be cleared before calling the API.
- Old links may be read for compatibility, but must be normalized to the current keys/values using `replace`.
- Invalid values must be removed from the URL. A valid value the user has no permission for must show a clear empty/error state, not silently switch to another scope.

## 3. Keyset pagination

- The API keeps using the cursor as the source of truth; the UI does not turn `page` into an offset.
- From page 2 on, the URL must have both `page=<displayed number>` and `cursor=<opaque>`; `page` alone is not enough to restore the data.
- Page 1 omits both `page` and `cursor`. If one of the two params is missing, `page` is malformed, or the API returns `INVALID_CURSOR` for the cursor, normalize to page 1 using `replace` and briefly notify the user.
- The Next ("Tiếp") button writes the new page/cursor to the URL. The Previous ("Trước") button uses cursors seen during the session; if a deep page is opened directly and there is no cursor for the previous page, go back to the first page instead of guessing an offset or loading the wrong data.
- The cursor is an opaque string: do not parse it, modify it, log its content or use it as a business identifier.

## 4. Sharing and recoverability

- The "Copy link" ("Chép liên kết") button must copy the current canonical URL, including filters and page position if on a later page.
- Refreshing and opening the link in another tab/machine must call the API with exactly the params in the URL.
- Back/Forward must restore the screen from the URL, not rely solely on component state or `localStorage`.
- If data changes make the cursor expire, the screen returns to page 1 with a notice; do not leave the user stuck on a technical error.

## 5. Implementation and testing

- With React, use `useSearchParams`; the shared helper for keyset pagination is in `frontend/src/list-url.ts`.
- The query cache key must contain every URL state that affects the request, including the cursor.
- Minimum tests: no params by default; filter survives refresh; changing the filter clears page/cursor; page 2 has both page/cursor; a link with missing/invalid params goes to page 1; `INVALID_CURSOR` goes to page 1; Back/Forward restores; the copied link keeps the full state.
- A review of a new list module fails if shareable state still lives only in React state.
