/** Scroll an inspector panel into view and flash its outline once. */
export function flashPanel(panel: string): void {
  const el = document.getElementById(`panel-${panel}`)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  el.classList.remove('flash')
  void el.offsetWidth
  el.classList.add('flash')
}
