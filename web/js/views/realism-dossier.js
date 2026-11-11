// The two dossiers behind the header (Train 2 unit D): the character the seat plays, and
// the setting. Text from the desk and from the world's sidecar (realism_api.py Dossier, Setting).

/** The initials of the first and last word: "Franklin D. Roosevelt" gives "FR". */
export function monogram(name) { // contract stub
  return '';
}

/**
 * The character's sections, in this order and only those with content: Office, Answers to
 * (the principals joined by ", "), As history had it, Biography, Powers (`powersSentence`),
 * Limits, Personal, Aims, How far ahead you see (`horizonWords`), In their words, A fact.
 * Each `{ heading, lines }`; In their words is “<quote>” then "— <source>", and is left out
 * when the quote has no source.
 */
export function dossierSections(desk, dossier) { // contract stub
  return [];
}

/** The setting's sections, only those with content: The date, The situation, The sides, On history's clock ("<on>: <what>"). */
export function settingSections(setting, date) { // contract stub
  return [];
}

/**
 * A `<dialog class="rl-dos">` headed with `name`: the portrait (`/assets/portraits/<file>`,
 * alt the name) or the monogram, the sections, the credit line under a portrait, and Close.
 */
export function characterDossier({ name, desk, dossier, onClose }) { // contract stub
  return null;
}

/** A `<dialog class="rl-dos">` headed with the game's `name`: the setting's sections and Close. */
export function settingDossier({ name, setting, date, onClose }) { // contract stub
  return null;
}
