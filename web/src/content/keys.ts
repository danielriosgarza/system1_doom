// Every key the app listens to, as the Keyboard tab lists them. App.tsx handles them.

export interface KeyRow {
  /** Each entry is one key cap; a row with several shows them side by side. */
  keys: string[]
  does: string
}

export const KEY_GROUPS: Array<{ title: string; rows: KeyRow[] }> = [
  {
    title: 'Moving through the episode',
    rows: [
      { keys: ['←', '→'], does: 'one tick back or forward' },
      { keys: ['Shift', '←', '→'], does: 'ten ticks back or forward' },
      { keys: ['Home'], does: 'the first tick' },
      { keys: ['End'], does: 'the last tick' },
      { keys: ['Space'], does: 'play or pause' },
    ],
  },
  {
    title: 'Screens and settings',
    rows: [
      { keys: ['1', '2', '3', '4', '5'], does: 'Overview, Tick, Hierarchy, Learning, Growing the menu' },
      { keys: ['f'], does: 'switch Depth between Plain and Formula' },
      { keys: ['t'], does: 'start the tour' },
    ],
  },
  {
    title: 'The reference',
    rows: [
      { keys: ['g'], does: 'open the glossary' },
      { keys: ['i'], does: 'open This recording' },
      { keys: ['?'], does: 'open these keys' },
      { keys: ['Esc'], does: 'close the reference' },
      { keys: ['Tab'], does: 'move within it; it keeps the focus until it closes' },
    ],
  },
  {
    title: 'During the tour',
    rows: [
      { keys: ['→'], does: 'the next step' },
      { keys: ['←'], does: 'the step before' },
      { keys: ['Esc'], does: 'leave the tour' },
    ],
  },
]

export const KEYS_NOTE =
  'No key fires while you type in a box, such as the glossary filter, or while Ctrl, Alt or ⌘ is held; while the reference is open, only Esc and Tab reach the app.'

export const SETTINGS_NOTE =
  'The two settings at the right of the top bar, Depth and the theme, are remembered in this browser.'
