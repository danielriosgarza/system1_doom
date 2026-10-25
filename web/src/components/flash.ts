import { useEffect } from 'react'
import { setState, useApp } from '../store'

/** Scroll a panel into view and flash its outline once. */
export function flashPanel(panel: string): void {
  flashElement(`panel-${panel}`)
}

/**
 * Scroll an element into view and flash its outline once. With `ifNeeded`, an element whose top already sits in the
 * upper half of the window stays where it is, so what is around it stays in view too.
 */
export function flashElement(id: string, ifNeeded = false): void {
  const el = document.getElementById(id)
  if (!el) return
  const top = el.getBoundingClientRect().top
  const inView = ifNeeded && top >= 0 && top <= window.innerHeight / 2
  // The timeline is pinned to the bottom of the window: flash it where it is.
  if (!inView && getComputedStyle(el).position !== 'sticky') el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  el.classList.remove('flash')
  void el.offsetWidth
  el.classList.add('flash')
}

/** On a screen with panels: flash the one another screen asked for, once it is on the page. */
export function useFocusPanel(): void {
  const focusPanel = useApp((s) => s.focusPanel)
  useEffect(() => {
    if (!focusPanel) return
    flashPanel(focusPanel)
    setState({ focusPanel: null })
  }, [focusPanel])
}
