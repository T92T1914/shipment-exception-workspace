// Presentation preference only. This static page has no application session.
(() => {
  'use strict';
  const key = 'shipment-explainer.appearance.v1';
  const allowed = ['auto', 'clair', 'obscur'];
  let choice = 'obscur';
  try { const saved = localStorage.getItem(key); if (allowed.includes(saved)) choice = saved; } catch {}
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  const apply = () => {
    const appearance = choice === 'auto' ? (system.matches ? 'obscur' : 'clair') : choice;
    document.documentElement.dataset.appearance = appearance;
    document.documentElement.dataset.preference = choice;
    document.querySelectorAll('[data-appearance-choice]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.appearanceChoice === choice));
    });
  };
  apply();
  system.addEventListener('change', () => { if (choice === 'auto') apply(); });
  document.addEventListener('DOMContentLoaded', () => {
    const controls = document.querySelector('.appearance-controls');
    if (controls) controls.hidden = false;
    document.querySelectorAll('[data-appearance-choice]').forEach(button => {
      button.addEventListener('click', () => {
        choice = button.dataset.appearanceChoice;
        try { localStorage.setItem(key, choice); } catch {}
        apply();
      });
    });
    apply();
  });
})();
