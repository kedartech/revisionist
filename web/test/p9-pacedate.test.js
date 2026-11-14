// S5: the date shows once. The next wake's reason may already carry its date (history
// events are named "Greer and U-652 exchange fire (4 Sep)"), and the clock line added
// ", about 4 Sep" after it, so a phone, where the line wraps in full, read the date twice.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { paceLine } from '../js/realism-rules.js';

const clock = (waiting_on, next_world_date) => ({
  world_date: '1941-09-01', next_world_date, waiting_on, days_collapsed: 0, next_wake_at: null,
});

test('paceLine names the next date once when the reason already carries it', () => {
  const line = paceLine(clock('Greer and U-652 exchange fire (4 Sep)', '1941-09-04'));
  assert.equal(line, 'Monday 1 September 1941 · next: Greer and U-652 exchange fire (4 Sep)');
  assert.equal(line.match(/4 Sep/g).length, 1);
});

test('paceLine still adds the date when the reason carries a different one', () => {
  // 14 Sep holds "4 Sep" as text: a different day, so the about-date stays
  assert.equal(paceLine(clock('Konoe cabinet resigns (14 Sep)', '1941-09-04')),
    'Monday 1 September 1941 · next: Konoe cabinet resigns (14 Sep), about 4 Sep');
  assert.equal(paceLine(clock('Hull note delivered to Nomura (26 Nov)', '1941-11-24')),
    'Monday 1 September 1941 · next: Hull note delivered to Nomura (26 Nov), about 24 Nov');
});

test('paceLine still adds the date when the reason carries none', () => {
  assert.equal(paceLine(clock('Answer from Sam Rayburn', '1941-09-04')),
    'Monday 1 September 1941 · next: Answer from Sam Rayburn, about 4 Sep');
});
