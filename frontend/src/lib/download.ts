/**
 * Client-side file download.
 *
 * Every export in the app built the same anchor and then revoked the blob
 * URL in the SAME tick as click(). Chrome tolerates that; Firefox and
 * Safari cancel the download, because the URL is gone before the browser
 * has started reading it. The anchor also has to be in the document for
 * the click to count in some engines.
 *
 * Presentation only — this changes nothing about what is exported.
 */
export function downloadBlob(content: BlobPart, filename: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  // Give the browser a tick to pick the URL up before it is revoked.
  window.setTimeout(() => {
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }, 0)
}

/** RFC 4180: a quote inside a field is doubled. */
export const csvCell = (value: unknown): string =>
  `"${String(value ?? '').replace(/"/g, '""')}"`

export const csvRows = (rows: unknown[][]): string =>
  rows.map((r) => r.map(csvCell).join(',')).join('\n')
