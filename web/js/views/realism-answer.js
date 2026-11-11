// "Needs your answer" (Train 2 unit M1): what is waiting on the seat, leader requests
// first, then the desk's own matters, each with its choices (realism_api.py AgendaBlock).

/**
 * Every live item, leader requests (`issuer` set) first, then desk matters, each as
 * `{ id, heading, text, dates, choices }`: `heading` from `itemHeading`, `dates` from
 * `itemDates` (realism-wake.js), `choices` from `requestChoices(agenda.style, item)`
 * (realism-requests.js). Under the free style too: a free player answers with an order.
 */
export function answerItems(agenda) { // contract stub
  return [];
}

/** An offered option's control: `{ word: 'Choose', button: true }`, or `{ word: 'Filed', button: false }` once `taken`. */
export function optionAction(option) { // contract stub
  return { word: 'Choose', button: true };
}

/**
 * The section headed "Needs your answer". An option's "Choose" calls
 * `act('Filing it…', 'option', { pick })`; a guided plan has one "File this plan"; no
 * choices reads "Answer it with an order of your own."; with nothing waiting,
 * "Nothing is waiting on you. Your ideas are below.".
 */
export function needsAnswer(agenda, { act }) { // contract stub
  return null;
}
