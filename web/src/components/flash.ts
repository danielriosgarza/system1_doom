import { useEffect } from 'react'
import { setState, useApp } from '../store'

/** Scroll a panel into view and flash its outline once. */
export function flashPanel(panel: string): void {
  const el = document.getElementById(`panel-${panel}`)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
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
