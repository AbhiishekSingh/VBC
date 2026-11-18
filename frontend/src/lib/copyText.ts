/**
 * Put text on the clipboard, on this deployment as well as on localhost.
 *
 * WHY THIS IS NOT A ONE-LINER
 * ---------------------------
 * "Copy JSON" on Step 3 was:
 *
 *     void navigator.clipboard?.writeText(text).then(...)
 *
 * `navigator.clipboard` exists only on a SECURE ORIGIN — https, or
 * localhost. VBC is served over plain http on a bare IP, so on the
 * deployed site that expression short-circuits to `undefined` and
 * `.then(...)` throws a TypeError. `void` does not catch it.
 *
 * The button therefore did nothing, silently, on every machine except a
 * developer's. That is the shape of bug that survives every demo and is
 * only ever found by the person trying to use the thing — and the thing
 * here is sending a provider payload to whoever has to fix an adapter.
 *
 * So: the Clipboard API when it is there, and `execCommand('copy')`
 * when it is not. The second is deprecated and works everywhere, which
 * between the two is the property that matters.
 *
 * RETURNS WHETHER IT WORKED, and the caller is expected to say so. A
 * copy that silently did not happen is how a parse gap gets reported
 * with no payload attached to it.
 */
export async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Permission denied, or the document is not focused. The legacy
      // route often still works, so it is tried before giving up.
    }
  }
  return legacyCopy(text)
}

/**
 * The pre-Clipboard-API route: select a throwaway textarea and let the
 * browser's own copy command take it.
 */
function legacyCopy(text: string): boolean {
  try {
    const area = document.createElement('textarea')
    area.value = text
    // OFF-SCREEN, NOT HIDDEN. A `display: none` element cannot hold a
    // selection, and the copy then succeeds with an empty string —
    // which is worse than failing, because the button says "Copied".
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.top = '-1000px'
    area.style.opacity = '0'

    document.body.appendChild(area)
    area.select()
    // iOS ignores `select()` on a readonly field without this.
    area.setSelectionRange?.(0, text.length)

    const ok = document.execCommand('copy')
    area.remove()
    return ok
  } catch {
    return false
  }
}
