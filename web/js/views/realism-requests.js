// Requests from named leaders and their choices, as pure helpers: "Needs your answer"
// (realism-answer.js) draws them with the desk's own matters.

const TITLE_MAX = 120;

/** The live matters a named leader has asked of the seat, under any play style. */
export function requests(agenda) {
  return (agenda?.items ?? []).filter((item) => item.issuer);
}

/** What the answer sheet says about when an answer lands [proposed]. */
export const ANSWER_AT_CLOSE = 'Your answer goes out on the day it is due; you can change it until then.';

/**
 * What the paper offers: a beginner's options, a guided plan filed in one go, or nothing.
 * Another seat's request (kind \"Request\") is answered with Accept or Decline under any style.
 */
export function requestChoices(style, item) {
  if (item.kind === 'Request') return { kind: 'request', options: [] };
  if (style === 'beginner' && item.options.length) return { kind: 'options', options: item.options };
  if (style === 'guided' && item.plan.length) return { kind: 'plan', options: item.plan };
  return { kind: 'none', options: [] };
}

/** The request's own words, cut to fit a row; the row names the leader beside it. */
export function requestTitle(item) {
  const full = item.text;
  return full.length <= TITLE_MAX ? full : `${full.slice(0, TITLE_MAX - 1).trimEnd()}…`;
}
