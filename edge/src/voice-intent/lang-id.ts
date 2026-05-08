/**
 * Language identification (Phase 7 Task 34).
 *
 * v1 placeholder: detects English vs non-English via a tiny bigram
 * frequency lookup over recognized text. Real implementation will use
 * a small local model (e.g. fastText-lid). Designed to be swapped.
 */

const ENGLISH_HINTS = [
  'the ',
  ' and ',
  ' is ',
  ' are ',
  ' you ',
  ' i ',
  ' to ',
  ' of ',
  'hello',
  'help',
  'please',
];

const SPANISH_HINTS = ['hola', 'gracias', 'por favor', 'usted', ' el ', ' la ', ' los '];
const FRENCH_HINTS = ['bonjour', 'merci', "s'il vous plaît", ' le ', ' la ', ' les '];

export type Lang = 'en' | 'es' | 'fr' | 'unknown';
type KnownLang = Exclude<Lang, 'unknown'>;

export function classifyLanguage(text: string): Lang {
  const lower = text.toLowerCase();
  const score: Record<KnownLang, number> = {
    en: ENGLISH_HINTS.reduce((s, h) => s + (lower.includes(h) ? 1 : 0), 0),
    es: SPANISH_HINTS.reduce((s, h) => s + (lower.includes(h) ? 1 : 0), 0),
    fr: FRENCH_HINTS.reduce((s, h) => s + (lower.includes(h) ? 1 : 0), 0),
  };
  const entries = Object.entries(score) as [KnownLang, number][];
  const best = entries.reduce((a, b) => (a[1] >= b[1] ? a : b));
  return best[1] > 0 ? best[0] : 'unknown';
}
