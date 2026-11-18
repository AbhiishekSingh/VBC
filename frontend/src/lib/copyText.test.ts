/**
 * "Copy JSON" has to work on THIS deployment, not just on localhost.
 *
 * THE BUG, found 18 Nov 2026 by somebody pressing the button:
 *
 *     void navigator.clipboard?.writeText(text).then(...)
 *
 * `navigator.clipboard` exists only on a secure origin. VBC is served
 * over plain http on a bare IP, so the expression short-circuited to
 * `undefined` and `.then(...)` threw. The button did nothing, in
 * silence, everywhere except a developer's machine.
 *
 * These tests run without a DOM, so the environment is stubbed. That
 * is the point: the branch which matters is the one taken when
 * `navigator.clipboard` is ABSENT, and nothing in a normal test
 * environment reproduces that by accident.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import { copyText } from './copyText'

const g = globalThis as Record<string, unknown>

/** A textarea with just enough surface for `legacyCopy`. */
function fakeArea() {
  return {
    value: '',
    style: {} as Record<string, string>,
    setAttribute: vi.fn(),
    select: vi.fn(),
    setSelectionRange: vi.fn(),
    remove: vi.fn(),
  }
}

/** Install a document whose `execCommand` reports `ok`. */
function stubDocument(ok: boolean) {
  const area = fakeArea()
  const appendChild = vi.fn()
  g.document = {
    createElement: () => area,
    body: { appendChild },
    execCommand: vi.fn(() => ok),
  }
  return { area, appendChild, execCommand: (g.document as any).execCommand }
}

function stubClipboard(writeText: ((t: string) => Promise<void>) | null) {
  // `globalThis.navigator` is getter-only under Node 22, so it is
  // defined rather than assigned.
  Object.defineProperty(globalThis, 'navigator', {
    value: writeText ? { clipboard: { writeText } } : {},
    configurable: true,
    writable: true,
  })
}

afterEach(() => {
  delete g.document
  Object.defineProperty(globalThis, 'navigator', {
    value: undefined, configurable: true, writable: true,
  })
})

describe('on a secure origin', () => {
  it('uses the Clipboard API', async () => {
    const writeText = vi.fn(async () => {})
    stubClipboard(writeText)
    stubDocument(true)

    expect(await copyText('{"a":1}')).toBe(true)
    expect(writeText).toHaveBeenCalledWith('{"a":1}')
  })

  it('falls back when the API rejects', async () => {
    // Permission denied, or the document is not focused — the legacy
    // route frequently still works, so it must be tried.
    stubClipboard(async () => {
      throw new Error('NotAllowedError')
    })
    const { execCommand } = stubDocument(true)

    expect(await copyText('x')).toBe(true)
    expect(execCommand).toHaveBeenCalledWith('copy')
  })
})

describe('on a plain-http origin — the deployed case', () => {
  it('does not throw when navigator.clipboard is undefined', async () => {
    // THE REGRESSION. The old code threw a TypeError here.
    stubClipboard(null)
    stubDocument(true)
    await expect(copyText('x')).resolves.toBe(true)
  })

  it('copies through execCommand', async () => {
    stubClipboard(null)
    const { execCommand, appendChild, area } = stubDocument(true)

    expect(await copyText('{"gstin":"29AANCB8469J1ZS"}')).toBe(true)
    expect(area.value).toBe('{"gstin":"29AANCB8469J1ZS"}')
    expect(appendChild).toHaveBeenCalled()
    expect(execCommand).toHaveBeenCalledWith('copy')
  })

  it('places the textarea off-screen rather than hiding it', () => {
    /* A `display: none` element cannot hold a selection, and the copy
       then succeeds with an EMPTY string — worse than failing, because
       the button says "Copied". */
    stubClipboard(null)
    const { area } = stubDocument(true)
    void copyText('x')
    expect(area.style.display).toBeUndefined()
    expect(area.style.position).toBe('fixed')
    expect(Number.parseInt(area.style.top, 10)).toBeLessThan(0)
  })

  it('selects the whole text', async () => {
    stubClipboard(null)
    const { area } = stubDocument(true)
    await copyText('abcdef')
    expect(area.select).toHaveBeenCalled()
    expect(area.setSelectionRange).toHaveBeenCalledWith(0, 6)
  })

  it('removes the textarea afterwards', async () => {
    stubClipboard(null)
    const { area } = stubDocument(true)
    await copyText('x')
    expect(area.remove).toHaveBeenCalled()
  })
})

describe('when it genuinely cannot copy', () => {
  it('reports false rather than claiming success', async () => {
    stubClipboard(null)
    stubDocument(false)
    expect(await copyText('x')).toBe(false)
  })

  it('survives a document that throws', async () => {
    stubClipboard(null)
    g.document = {
      createElement: () => {
        throw new Error('no DOM')
      },
    }
    expect(await copyText('x')).toBe(false)
  })

  it('survives a missing execCommand', async () => {
    stubClipboard(null)
    g.document = {
      createElement: () => fakeArea(),
      body: { appendChild: vi.fn() },
    }
    expect(await copyText('x')).toBe(false)
  })
})

describe('what it copies', () => {
  it('passes a large payload through untouched', async () => {
    /* A stored provider response is the thing being copied, and the
       one that prompted this was 14,657 characters. */
    const big = JSON.stringify({
      candidates: Array(400).fill({
        cin: 'U46909MH2021PTC368742',
        name: 'ZEPTO MARKETPLACE PRIVATE LIMITED',
        status: 'Active',
      }),
    })
    const writeText = vi.fn(async () => {})
    stubClipboard(writeText)
    stubDocument(true)

    await copyText(big)
    expect(writeText).toHaveBeenCalledWith(big)
    expect(big.length).toBeGreaterThan(10_000)
  })
})
