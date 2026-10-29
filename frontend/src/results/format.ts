// How numbers are shown to people (Italian). Estimates are rounded to what they can support
// (CLAUDE.md section 11): nobody should read "7.683,24 €" for a figure that is a good guess.
// The rounding is the one of the backend wording (backend/app/services/recommendations/wording.py),
// so a figure on a card and the same figure in a sentence agree.

const MINUS = '−' // a real minus sign, not a hyphen

function groupThousands(whole: number): string {
  // Italian groups from 1,000 ("1.234"); Intl leaves 4-digit numbers alone, so do it by hand.
  return Math.round(whole)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, '.')
}

export function roundMoney(value: number): number {
  const size = Math.abs(value)
  const step = size >= 1000 ? 50 : size >= 100 ? 10 : size >= 20 ? 5 : 1
  return Math.round(value / step) * step
}

/** An amount of money without a sign: 3537 -> "3.550 €". */
export function euros(value: number): string {
  return `${groupThousands(Math.abs(roundMoney(value)))} €`
}

/** With a sign, for differences: -3537 -> "−3.550 €", 610 -> "+610 €". */
export function signedEuros(value: number): string {
  const rounded = roundMoney(value)
  if (rounded === 0) return '0 €'
  return `${rounded < 0 ? MINUS : '+'}${groupThousands(Math.abs(rounded))} €`
}

/** "tra 2.900 e 4.550 €"; where the range is too narrow to matter, nothing. */
export function euroRange(low: number, high: number): string | null {
  if (high - low < 10) return null
  const sign = (v: number) => `${roundMoney(v) < 0 ? MINUS : ''}${groupThousands(Math.abs(roundMoney(v)))}`
  return `tra ${sign(low)} e ${sign(high)} €`
}

function roundHours(value: number): number {
  const size = Math.abs(value)
  return size < 100 ? Math.round(value) : Math.round(value / 5) * 5
}

/** Travel time a year: 283.4 -> "285 h". */
export function hours(value: number): string {
  return `${groupThousands(Math.abs(roundHours(value)))} h`
}

/** Travel time inside a sentence: 9 -> "9 ore", 1 -> "1 ora". */
export function hoursInText(value: number): string {
  const rounded = Math.abs(roundHours(value))
  return `${groupThousands(rounded)} ${rounded === 1 ? 'ora' : 'ore'}`
}

export function signedHours(value: number): string {
  const rounded = roundHours(value)
  if (rounded === 0) return '0 h'
  return `${rounded < 0 ? MINUS : '+'}${groupThousands(Math.abs(rounded))} h`
}

/** A comfort score out of 10, with a decimal comma: 7.84 -> "7,8". */
export function score(value: number): string {
  return value.toFixed(1).replace('.', ',')
}

export function signedScore(value: number): string {
  const rounded = Math.round(value * 10) / 10
  if (rounded === 0) return '0,0'
  return `${rounded < 0 ? MINUS : '+'}${Math.abs(rounded).toFixed(1).replace('.', ',')}`
}

/** Kilometres, to the hundred above a thousand: 10389 -> "10.400 km". */
export function kilometres(value: number): string {
  const step = value >= 1000 ? 100 : 10
  return `${groupThousands(Math.round(value / step) * step)} km`
}

/** Whether a difference is worth showing as a change at all. */
export function isNegligible(value: number, scale: number): boolean {
  return Math.abs(value) < scale
}
