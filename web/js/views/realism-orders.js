// The orders log: one row per order, made, landed and finished (In-Tray follow-up, unit T4).
// contract stub: until T4 lands, the results panel as it is.

import { resultsPanel } from './realism-wake.js';

/** The log for the side column. `results` is view.realism.results, `orders` view.realism.orders. */
export function ordersLog(results, orders) {
  void orders;
  return resultsPanel(results);
}
