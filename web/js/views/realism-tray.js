// The in-tray as a message list with a reading pane (In-Tray follow-up, unit T1).
// contract stub: until T1 lands, the folder grid, and an opened paper replaces it.

import { dossier, inTray } from './realism.js';

/** The tray panel. `opts`: { filter, sort, onFilter, onSort, page, onClose, onFlag, wide }. */
export function trayView(listing, onOpen, opts = {}) {
  if (opts.page) return dossier(opts.page, { onClose: opts.onClose, onFlag: opts.onFlag });
  return inTray(listing, onOpen, opts);
}
