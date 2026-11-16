// The game menu's "Notices: your email": where the wake notices go and in which time zone
// (the game action `notice-address`: no keys reads, `address` and `zone` set).

import { h } from '../dom.js';

/**
 * The section's nodes and its `load`. `api.game('notice-address', body)` resolves to
 * `{ reply, refused, address, zone }`; `run(fn)` is the menu's one-call-at-a-time guard, which
 * Save goes through. Reading is not held by it, so a slow read never blocks Pause or Leave. The
 * section says its own results. An empty address clears it; an empty zone is left out, so the
 * stored zone stays. A refusal keeps what was typed.
 */
export function noticesSection({ api, run }) {
  const says = h('p', { class: 'hint rl-notice-says', role: 'status', 'aria-live': 'polite' });
  const address = h('input', { id: 'rl-notice-address', name: 'address', type: 'email', autocomplete: 'email', maxlength: 254 });
  const zone = h('input', { id: 'rl-notice-zone', name: 'zone', type: 'text', placeholder: 'America/New_York', autocomplete: 'off' });
  const show = (r, fill) => {
    if (fill) {
      address.value = r.address ?? '';
      zone.value = r.zone ?? '';
    }
    says.replaceChildren(r.reply ?? '');
  };
  const load = async () => {
    try {
      show(await api.game('notice-address'), true);
    } catch (ex) {
      says.replaceChildren(ex.message);
    }
  };
  const save = (e) => {
    e.preventDefault();
    const body = { address: address.value.trim() };
    if (zone.value.trim()) body.zone = zone.value.trim();
    return run(async () => {
      const r = await api.game('notice-address', body);
      show(r, !r.refused);
    });
  };
  const nodes = [
    h('h3', {}, 'Notices: your email'),
    h('p', { class: 'hint' }, 'When a wake opens, one email lists what is waiting on you and when the wake closes. Leave the address empty for none.'),
    h('form', { class: 'rl-notice rl-field', onsubmit: save },
      h('label', { for: 'rl-notice-address' }, 'Email address'), address,
      h('label', { for: 'rl-notice-zone' }, 'Time zone'), zone,
      h('div', { class: 'row' }, h('button', { type: 'submit', class: 'ghost' }, 'Save'))),
    says,
  ];
  return { nodes, load };
}
