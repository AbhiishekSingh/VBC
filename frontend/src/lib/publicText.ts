/**
 * Strip our plumbing out of text a client or an analyst reads on screen.
 *
 * WHY THIS EXISTS AT ALL
 * ----------------------
 * The backend builds `detail` for engineers, and it is right to:
 *
 *   "filesure.master: the provider returned data, but this adapter could
 *    not read 1 field(s) from it — class_of_company. The response shape has
 *    probably changed."
 *
 *   "whoisxml: HTTP 403 on https://whois-history.whoisxmlapi.com/api/v1
 *    — {'code': 403, 'messages': 'Access restricted'}"
 *
 * Those strings are exactly what someone fixing the adapter needs. They are
 * also the names of our suppliers, our endpoints and our internal check ids,
 * and they were rendering straight onto the findings screen and into the
 * client report. Which supplier we buy a filing from is a commercial detail
 * of ours, not a fact about the vendor being assessed.
 *
 * NOTHING IS DESTROYED. This rewrites what is DISPLAYED on the status line.
 * The untouched original is still in three places: `rawResponse` (one click
 * away on the same row, under `_parse_gap`), the `error` column in the
 * database, and the audit log. An engineer loses nothing; a reader stops
 * seeing a supplier's name attached to a vendor's file.
 *
 * It is deliberately a display-layer fix rather than a backend one, because
 * results ALREADY STORED carry these strings. Changing the backend would
 * only clean up future runs and leave every existing row as it is. The
 * backend should be changed too — this keeps working when it is, since a
 * string with no prefix and no URL passes through unaltered.
 */

/** `filesure.master: `, `whoisxml: `, `mca_v3: ` — a leading source tag. */
const SOURCE_PREFIX = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*:\s*/i

/** Any absolute URL, with or without surrounding punctuation. */
const URL_ANYWHERE = /\s*(?:\bon\s+|\bat\s+)?https?:\/\/\S+/gi

/** A bare hostname that survived, e.g. `whois-history.whoisxmlapi.com`. */
const BARE_HOST = /\s*\b[a-z0-9-]+(\.[a-z0-9-]+)+\.(com|in|io|net|org|dev)\b/gi

/**
 * Make one line of provider text safe to show.
 *
 * Returns an empty string for empty input, so callers can keep using
 * `publicDetail(x) || fallback`.
 *
 * CASE IS NOT TOUCHED BY DEFAULT. Most of these strings are interpolated
 * into the middle of a sentence in the report — "...raised a point for
 * attention — ${detail}" — where an imposed capital reads as a typo. Pass
 * `{ capitalise: true }` at the few sites where the text stands alone or
 * opens a sentence.
 */
export function publicDetail(
  text: string | null | undefined,
  options: { capitalise?: boolean } = {},
): string {
  if (!text) return ''

  let out = text.replace(SOURCE_PREFIX, '')
  out = out.replace(URL_ANYWHERE, '')
  out = out.replace(BARE_HOST, '')

  // Tidy what the removals left behind: a dangling dash, doubled spaces,
  // a space before punctuation, a leading separator.
  out = out
    .replace(/\s{2,}/g, ' ')
    .replace(/\s+([.,;:])/g, '$1')
    .replace(/[\s—–-]+$/, '')
    .replace(/^[\s—–:-]+/, '')
    .trim()

  if (!out) return ''
  if (!options.capitalise) return out
  return out.charAt(0).toUpperCase() + out.slice(1)
}
