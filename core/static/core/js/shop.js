// Progressive enhancement for the wishlist hearts: toggle in place instead of reloading the page.
// Without JavaScript the heart is a normal form that posts and redirects back.
document.addEventListener('submit', async (event) => {
  const form = event.target.closest('form[data-wishlist-toggle]');
  if (!form) return;
  event.preventDefault();
  const button = form.querySelector('.heart-btn');
  button.disabled = true;
  try {
    const response = await fetch(form.action, {
      method: 'POST',
      body: new FormData(form),
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
    });
    const data = await response.json();
    if (response.status === 401 && data.login_url) {
      window.location.href = data.login_url;
      return;
    }
    if (!response.ok) throw new Error(response.statusText);
    // Every heart for this record on the page (a card and the detail box, say) stays in sync.
    document.querySelectorAll(`form[action="${form.getAttribute('action')}"] .heart-btn`).forEach((heart) => {
      heart.setAttribute('aria-pressed', String(data.saved));
      heart.setAttribute('aria-label', data.saved ? 'Remove from wishlist' : 'Save to wishlist');
      heart.title = heart.getAttribute('aria-label');
    });
    const badge = document.querySelector('[data-wishlist-count]');
    if (badge) {
      badge.textContent = data.count;
      badge.hidden = data.count === 0;
    }
  } catch (error) {
    form.submit();
  } finally {
    button.disabled = false;
  }
});
