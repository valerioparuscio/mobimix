// User-facing Italian wording for the closed choices. Draft copy: edit freely, nothing else
// depends on these strings.

import type { AreaType, Frequency, Occupation } from '../api/types.ts'
import type { TwoWheelsUse } from './types.ts'

export const OCCUPATION_LABELS: Record<Occupation, string> = {
  WORKER: 'Lavora',
  STUDENT: 'Studia',
  RETIRED: 'In pensione',
  OTHER: 'Altro',
}

export const TWO_WHEELS_LABELS: Record<TwoWheelsUse, string> = {
  ANY_WEATHER: 'Sì, con ogni tempo',
  FAIR_WEATHER_ONLY: 'Sì, ma non con pioggia o freddo',
  NONE: 'No, non li usa',
  UNSURE: 'Dipende',
}

export const TWO_WHEELS_ORDER: TwoWheelsUse[] = [
  'ANY_WEATHER',
  'FAIR_WEATHER_ONLY',
  'NONE',
  'UNSURE',
]

export const AREA_LABELS: Record<AreaType, string> = {
  CITY_CENTER: 'Centro città',
  URBAN: 'Città',
  SUBURBAN: 'Cintura',
  PERIPHERAL: 'Periferia o campagna',
}

export const AREA_DESCRIPTIONS: Record<AreaType, string> = {
  CITY_CENTER: 'Tutto a portata di mano, mezzi pubblici frequenti, parcheggio difficile.',
  URBAN: 'Quartiere residenziale con servizi e buoni collegamenti.',
  SUBURBAN: 'Comuni attorno alla città: si usa molto l’auto, trasporto pubblico di base.',
  PERIPHERAL: 'Servizi lontani e trasporto pubblico scarso.',
}

export const AREA_ORDER: AreaType[] = ['CITY_CENTER', 'URBAN', 'SUBURBAN', 'PERIPHERAL']

export const FREQUENCY_LABELS: Record<Frequency, string> = {
  NEVER: 'Mai',
  RARELY: 'Raramente',
  SOMETIMES: 'A volte',
  OFTEN: 'Spesso',
  ALMOST_DAILY: 'Quasi ogni giorno',
}

export const FREQUENCY_ORDER: Frequency[] = [
  'NEVER',
  'RARELY',
  'SOMETIMES',
  'OFTEN',
  'ALMOST_DAILY',
]
