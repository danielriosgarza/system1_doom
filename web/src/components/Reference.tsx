import { type KeyboardEvent, type ReactNode, useEffect, useId, useLayoutEffect, useRef } from 'react'
import type { ExplainerContext } from '../content/explainers'
import type { EpisodeBundle } from '../data/loader'
import { type DrawerSection, closeDrawer, openDrawer, useApp } from '../store'

const TABS: Array<{ id: DrawerSection; label: string }> = [
  { id: 'glossary', label: 'Glossary' },
  { id: 'principles', label: 'Principles' },
  { id: 'recording', label: 'This recording' },
  { id: 'keys', label: 'Keyboard' },
]

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

function focusables(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.getClientRects().length > 0)
}

/** Where focus goes back to when nothing was focused at open, as when a key opened the drawer. */
function fallbackOpener(section: DrawerSection): HTMLElement | null {
  return (
    document.querySelector<HTMLElement>(`[data-opens="${section}"]`) ??
    document.querySelector<HTMLElement>('[data-opens="glossary"]')
  )
}

/** The reference drawer: glossary, principles, this recording and the keys, over whatever screen is showing. */
export function Reference({ bundle, ctx }: { bundle: EpisodeBundle; ctx: ExplainerContext }) {
  const section = useApp((s) => s.drawer)
  return section ? <Drawer section={section} bundle={bundle} ctx={ctx} /> : null
}

function Drawer({ section, bundle, ctx }: { section: DrawerSection; bundle: EpisodeBundle; ctx: ExplainerContext }) {
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const openedAs = useRef(section)
  const headingId = useId()
  const tabsId = useId()

  // Focus moves in on open and goes back to the opener on close. A layout effect, so the opener is
  // read before any tab moves focus in its own effect.
  useLayoutEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    const active = document.activeElement
    const opener = active instanceof HTMLElement && active !== document.body ? active : null
    const fallback = openedAs.current
    const first =
      dialog.querySelector<HTMLElement>('[data-autofocus]') ??
      dialog.querySelector<HTMLElement>('[aria-selected="true"]')
    first?.focus({ preventScroll: true })
    // Focus that escapes (a click on the page behind, a screen reader jump) is brought back.
    const keepInside = (e: FocusEvent) => {
      if (e.target instanceof Node && !dialog.contains(e.target)) focusables(dialog)[0]?.focus()
    }
    document.addEventListener('focusin', keepInside)
    return () => {
      document.removeEventListener('focusin', keepInside)
      const back = opener?.isConnected ? opener : fallbackOpener(fallback)
      back?.focus({ preventScroll: true })
    }
  }, [])

  // Sit under the top bar on a desktop; the phone layout ignores this and fills the screen.
  useEffect(() => {
    const place = () => {
      const bar = document.querySelector('.topbar')
      dialogRef.current?.style.setProperty('--drawer-top', `${Math.max(0, bar?.getBoundingClientRect().bottom ?? 0)}px`)
    }
    place()
    window.addEventListener('resize', place)
    return () => window.removeEventListener('resize', place)
  }, [])

  // Tab wraps inside the dialog.
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const dialog = dialogRef.current
    if (e.key !== 'Tab' || !dialog) return
    const items = focusables(dialog)
    const first = items[0]
    const last = items[items.length - 1]
    if (!first || !last) return
    const active = document.activeElement
    if (e.shiftKey && (active === first || !items.includes(active as HTMLElement))) {
      last.focus()
      e.preventDefault()
    } else if (!e.shiftKey && (active === last || !items.includes(active as HTMLElement))) {
      first.focus()
      e.preventDefault()
    }
  }

  // Arrow keys move between the tabs, as in any tablist.
  const onTabKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const at = TABS.findIndex((t) => t.id === section)
    const next =
      e.key === 'ArrowRight'
        ? (at + 1) % TABS.length
        : e.key === 'ArrowLeft'
          ? (at - 1 + TABS.length) % TABS.length
          : e.key === 'Home'
            ? 0
            : e.key === 'End'
              ? TABS.length - 1
              : null
    if (next === null) return
    e.preventDefault()
    const tab = TABS[next]
    if (!tab) return
    openDrawer(tab.id)
    window.requestAnimationFrame(() => document.getElementById(`${tabsId}-${tab.id}`)?.focus())
  }

  return (
    <>
      <div className="reference-backdrop" aria-hidden onClick={closeDrawer} />
      <div
        className="reference"
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        ref={dialogRef}
        onKeyDown={onKeyDown}
      >
        <header className="reference-head">
          <h2 id={headingId}>Reference</h2>
          <button type="button" className="icon-button" onClick={closeDrawer} aria-label="Close the reference">
            ✕
          </button>
        </header>
        <div className="reference-tabs" role="tablist" aria-label="Reference sections">
          {TABS.map((t) => (
            <button
              key={t.id}
              id={`${tabsId}-${t.id}`}
              type="button"
              role="tab"
              aria-selected={t.id === section}
              aria-controls={`${tabsId}-panel`}
              tabIndex={t.id === section ? 0 : -1}
              onClick={() => openDrawer(t.id)}
              onKeyDown={onTabKey}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div
          className="reference-body"
          role="tabpanel"
          id={`${tabsId}-panel`}
          aria-labelledby={`${tabsId}-${section}`}
          data-section={section}
        >
          <SectionBody section={section} bundle={bundle} ctx={ctx} />
        </div>
      </div>
    </>
  )
}

function SectionBody({
  section,
  bundle,
  ctx,
}: {
  section: DrawerSection
  bundle: EpisodeBundle
  ctx: ExplainerContext
}): ReactNode {
  void bundle
  void ctx
  switch (section) {
    case 'glossary':
      return <p className="empty-note">The glossary.</p>
    case 'principles':
      return <p className="empty-note">The seven principles.</p>
    case 'recording':
      return <p className="empty-note">This recording.</p>
    case 'keys':
      return <p className="empty-note">The keys.</p>
  }
}
