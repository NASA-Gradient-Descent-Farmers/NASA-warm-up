// Line icons for the home cards: 48 x 48, drawn with currentColor.

const common = { viewBox: '0 0 48 48', fill: 'none', stroke: 'currentColor', strokeWidth: 2.6, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, focusable: false } as const

export const SeedlingIcon = () => (
  <svg {...common}>
    <path d="M24 43V23" />
    <path d="M24 28C24 18 17 12 7 12c0 10 6 16 17 16z" />
    <path d="M24 23c0-8 5-12 15-12 0 9-5 13-15 13z" />
    <path d="M15 43h18" />
  </svg>
)

export const CoinIcon = () => (
  <svg {...common}>
    <circle cx="24" cy="24" r="17" />
    <path d="M30 18c-1.5-4-11.5-3.6-11.5 1.8 0 5.6 11.5 3 11.5 8.6 0 5.2-10.5 5.4-12.5 1.2" />
    <path d="M24 10.5v4.5M24 33v4.5" />
  </svg>
)

export const MagnifierIcon = () => (
  <svg {...common}>
    <circle cx="21" cy="21" r="13" />
    <path d="M31 31l11 11" />
    <path d="M14.5 21.5l4.5 4.5 8-9" />
  </svg>
)

export const PinGlyph = () => (
  <svg viewBox="0 0 20 26" width="14" height="18" aria-hidden="true" focusable="false" style={{ verticalAlign: '-3px' }}>
    <path d="M10 25S2 16.5 2 10a8 8 0 0 1 16 0c0 6.500-8 15-8 15z" fill="#d4532a" stroke="#12392a" strokeWidth="1.8" strokeLinejoin="round" />
    <circle cx="10" cy="10" r="2.8" fill="#f5ecd6" />
  </svg>
)

export const RainIcon = () => (
  <svg {...common}>
    <path d="M13 29a8.5 8.5 0 0 1 1.5-16.9A11.5 11.5 0 0 1 36.5 15 7.2 7.2 0 0 1 35 29z" />
    <path d="M16 35l-2.5 6M25 35l-2.5 6M34 35l-2.5 6" />
  </svg>
)
