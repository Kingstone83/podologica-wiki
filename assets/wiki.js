(() => {
  const articles = window.WIKIPODIA_INDEX || [];
  const randomButton = document.getElementById('randomArticle');
  if (randomButton && articles.length) {
    randomButton.addEventListener('click', () => {
      const item = articles[Math.floor(Math.random() * articles.length)];
      const prefix = location.pathname.includes('/voci/') || location.pathname.includes('/categorie/') ? '../' : '';
      location.href = prefix + item.url;
    });
  }

  const form = document.getElementById('searchForm');
  const input = document.getElementById('searchInput');
  const results = document.getElementById('searchResults');
  if (!form || !input || !results) return;

  const params = new URLSearchParams(location.search);
  input.value = params.get('q') || '';

  function renderSearch(query) {
    const q = query.trim().toLowerCase();
    if (!q) {
      results.innerHTML = '<p class="muted">Inserisci una parola per iniziare la ricerca.</p>';
      return;
    }
    const matches = articles
      .map((item) => {
        const haystack = `${item.title} ${item.category} ${item.text}`.toLowerCase();
        const score = (item.title.toLowerCase().includes(q) ? 5 : 0) + (item.category.toLowerCase().includes(q) ? 2 : 0) + (haystack.includes(q) ? 1 : 0);
        return { item, score };
      })
      .filter((entry) => entry.score > 0)
      .sort((a, b) => b.score - a.score || a.item.title.localeCompare(b.item.title))
      .slice(0, 60);

    if (!matches.length) {
      results.innerHTML = '<p class="muted">Nessuna voce trovata.</p>';
      return;
    }
    results.innerHTML = matches.map(({ item }) => `
      <article class="search-result">
        <a href="${item.url}">${item.title}</a>
        <span>${item.category} · Pagina ${String(item.page).padStart(3, '0')}</span>
        <p>${item.text.slice(0, 220)}${item.text.length > 220 ? '...' : ''}</p>
      </article>
    `).join('');
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const q = input.value.trim();
    history.replaceState(null, '', q ? `?q=${encodeURIComponent(q)}` : location.pathname);
    renderSearch(q);
  });
  input.addEventListener('input', () => renderSearch(input.value));
  renderSearch(input.value);
})();
