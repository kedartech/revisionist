// The seat's own capital line as the server would send it for a view a test builds by hand: one
// question for each measure on the floor, office question, held order and ask in that view, pointing at its block.
// A held order's decider is one person when the roster names him, else a council at its table.

const named = (rv, name) => ['yours', 'others', 'opponents'].some((tab) => (rv?.people?.[tab] ?? []).some((l) => l.name === name));

/** `rv.capitals` for the view `rv`: the own nation's line (its place `place`), then `others` as given. */
export function capitalLines(rv, { place = null, others = [] } = {}) {
  const nation = { key: 'N-own', name: rv?.home?.nation ?? 'Norra', relation: 'own' };
  const questions = [];
  for (const c of rv?.home?.chambers ?? []) {
    for (const m of c.measures ?? []) {
      questions.push({ kind: 'measure', title: m.title, day: null, decider: { shape: 'body', who: c.key, members: [] }, at: 'home.chambers', ref: m.order_id });
    }
  }
  for (const q of rv?.home?.office ?? []) {
    questions.push({ kind: 'office', title: q.office, day: q.sits, decider: { shape: 'body', who: q.chamber ?? 'the court', members: [] }, at: 'home.office', ref: q.question_id });
  }
  for (const l of rv?.locks?.held ?? []) {
    const decider = named(rv, l.who) ? { shape: 'person', who: l.who, members: [l.who] } : { shape: 'council', who: l.who, members: [] };
    questions.push({ kind: 'held', title: l.words, day: null, decider, at: 'locks.held', ref: l.id });
  }
  for (const a of rv?.locks?.asks ?? []) {
    questions.push({ kind: 'ask', title: a.words, day: null, decider: { shape: 'person', who: a.by, members: [a.by] }, at: 'locks.asks', ref: a.id });
  }
  return [{ nation, place, questions }, ...others];
}
