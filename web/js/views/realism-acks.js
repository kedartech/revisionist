// The receipt on an order's ledger line: what a paper that only acknowledged the order said.

import { h } from '../dom.js';

/**
 * The receipt of one ledger line (`{ word, day, doc }`, `record.orders[].receipt`) as a button
 * that opens the paper `doc` through `onOpen({ id })`. Null when the order has no receipt.
 */
export function receiptLine(receipt, onOpen) {
  if (!receipt) return null;
  const text = `${receipt.word}, ${receipt.day}`;
  return h('button', {
    type: 'button', class: 'rl-receipt', 'aria-label': `Open the paper: ${text}`,
    onclick: () => onOpen?.({ id: receipt.doc }),
  }, text);
}
