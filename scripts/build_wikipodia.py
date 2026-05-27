from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


SKIP_PREFIXES = (
    "podologica.net",
    "wikipodia.net",
    "wikipodia l’enciclopedia",
    "analisidelpiede",
    "inpiedi.net",
    "centrodiabete.net",
    "home ",
    "il mio piede     patologie",
)


@dataclass
class Article:
    page: int
    title: str
    category: str
    lines: list[str]


def normalize_line(line: str) -> str:
    line = line.replace("\u2022", " ")
    line = re.sub(r"\s+", " ", line).strip(" -\t")
    line = line.replace(" ,", ",").replace(" .", ".")
    line = line.replace(" :", ":").replace(" ;", ";")
    return line


def keep_line(line: str) -> bool:
    if not line:
        return False
    low = line.lower()
    if any(low.startswith(prefix) for prefix in SKIP_PREFIXES):
        return False
    if re.match(r"^[A-Z]$", line):
        return False
    if set(line) <= {"-", "_", "."}:
        return False
    if len(line) > 180 and ("contatti" in low or "plantari" in low and "wikipodia" in low):
        return False
    return True


def clean_lines(text: str) -> list[str]:
    raw_lines = [normalize_line(line) for line in text.replace("\r", "").splitlines()]
    lines: list[str] = []
    for line in raw_lines:
        if keep_line(line):
            if not lines or lines[-1] != line:
                lines.append(line)
    return lines


def category_for_page(page: int) -> str:
    if 5 <= page <= 19:
        return "Conosci il tuo piede"
    if 20 <= page <= 77:
        return "Enciclopedia delle patologie"
    if 78 <= page <= 156:
        return "Plantari e ortesi"
    if 157 <= page <= 163:
        return "Analisi e trattamento"
    if 164 <= page <= 184:
        return "Piede diabetico"
    if 185 <= page <= 207:
        return "Cura, movimento e news"
    if 208 <= page <= 209:
        return "Contatti"
    if page >= 210:
        return "Tecnica ortopedica"
    return "Introduzione"


def looks_like_continuation(line: str) -> bool:
    return bool(
        line.startswith("(")
        or line.lower().startswith(("soluzioni plantari", "scarpe ortopediche", "vieni a scoprire"))
        or (line[:1].islower())
    )


def title_from_lines(page: int, lines: list[str], previous_title: str | None = None) -> tuple[str, bool]:
    if page == 78:
        return "Indice dei plantari", True

    for i, line in enumerate(lines[:8]):
        candidate = line.strip()
        if len(candidate) < 2:
            continue
        if i == 0 and previous_title and looks_like_continuation(candidate):
            return f"{previous_title} (continua)"[:92], False
        if re.match(r"^\d+\)\s+PLANTAR[EI]$", candidate, re.I) and i + 1 < len(lines):
            return f"{candidate} {lines[i + 1]}".replace("  ", " ")[:92], True
        if re.match(r"^\d+\)\s*$", candidate) and i + 1 < len(lines):
            return lines[i + 1][:92], True
        if re.match(r"^\d+[).]\s+", candidate):
            return candidate[:92], True
        if candidate.isupper() and len(candidate) > 3:
            return candidate[:92], True
        if i == 0:
            return candidate[:92], True
    return f"Pagina {page}", True


def extract_articles(pdf_path: Path) -> list[Article]:
    reader = PdfReader(str(pdf_path))
    articles: list[Article] = []
    previous_by_category: dict[str, str] = {}
    for page_number, page in enumerate(reader.pages, start=1):
        if page_number <= 3:
            continue
        lines = clean_lines(page.extract_text() or "")
        if not lines:
            continue
        category = category_for_page(page_number)
        title, starts_new_entry = title_from_lines(page_number, lines, previous_by_category.get(category))
        if starts_new_entry:
            previous_by_category[category] = title
        articles.append(
            Article(
                page=page_number,
                title=title,
                category=category,
                lines=lines,
            )
        )
    return articles


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "voce"


def paragraphize(lines: list[str]) -> str:
    chunks: list[str] = []
    buffer: list[str] = []
    for line in lines:
        if re.match(r"^(\d+\)|[A-Z][A-Z0-9 /'().-]{3,}|DEFINIZIONE|CAUSA|TRATTAMENTO)", line):
            if buffer:
                chunks.append("<p>" + html.escape(" ".join(buffer)) + "</p>")
                buffer = []
            chunks.append(f"<h4>{html.escape(line.title() if line.isupper() else line)}</h4>")
        elif len(line) < 42 and line.endswith(":"):
            if buffer:
                chunks.append("<p>" + html.escape(" ".join(buffer)) + "</p>")
                buffer = []
            chunks.append(f"<h4>{html.escape(line)}</h4>")
        else:
            buffer.append(line)
            if len(" ".join(buffer)) > 420:
                chunks.append("<p>" + html.escape(" ".join(buffer)) + "</p>")
                buffer = []
    if buffer:
        chunks.append("<p>" + html.escape(" ".join(buffer)) + "</p>")
    return "\n".join(chunks)


def grouped(articles: list[Article]) -> dict[str, list[Article]]:
    groups: dict[str, list[Article]] = {}
    for article in articles:
        groups.setdefault(article.category, []).append(article)
    return groups


def render_article(article: Article) -> str:
    article_id = f"p{article.page}-{slugify(article.title)}"
    body = paragraphize(article.lines[1:] if article.lines and article.lines[0] == article.title else article.lines)
    return f"""
          <article class="wiki-article" id="{article_id}" data-category="{html.escape(article.category)}" data-title="{html.escape(article.title.lower())}">
            <header>
              <span>Pagina {article.page:03d} · {html.escape(article.category)}</span>
              <h3>{html.escape(article.title)}</h3>
            </header>
            <div class="article-body">
              {body}
            </div>
          </article>
    """


def render(output_path: Path, articles: list[Article]) -> None:
    groups = grouped(articles)
    total_pathologies = len(groups.get("Enciclopedia delle patologie", []))
    total_plantari = len(groups.get("Plantari e ortesi", []))
    nav = "\n".join(
        f'<a href="#{slugify(name)}">{html.escape(name)} <span>{len(items)}</span></a>'
        for name, items in groups.items()
    )
    toc = "\n".join(
        f'<li><a href="#{slugify(name)}">{html.escape(name)}</a></li>'
        for name in groups
    )
    sections = []
    for name, items in groups.items():
        cards = "\n".join(render_article(article) for article in items)
        sections.append(
            f"""
        <section class="wiki-section" id="{slugify(name)}">
          <div class="section-heading">
            <h2>{html.escape(name)}</h2>
            <p>{len(items)} voci estratte e ordinate dal documento originale.</p>
          </div>
          <div class="article-grid">
            {cards}
          </div>
        </section>
            """
        )

    document = f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wikipodia · Enciclopedia del piede</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f8f9fa;
      --surface: #fff;
      --ink: #202122;
      --muted: #54595d;
      --border: #a2a9b1;
      --soft-border: #d8dce0;
      --wiki-blue: #0645ad;
      --wiki-blue-dark: #3366cc;
      --green: #2f6f4e;
      --amber: #946200;
      --red: #8f2f2f;
    }}

    * {{ box-sizing: border-box; }}

    html {{ scroll-behavior: smooth; }}

    body {{
      margin: 0;
      color: var(--ink);
      background: var(--page);
      font: 16px/1.58 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}

    a {{ color: var(--wiki-blue); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    .site-shell {{
      display: grid;
      grid-template-columns: 248px minmax(0, 1fr);
      min-height: 100vh;
    }}

    .sidebar {{
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
      border-right: 1px solid var(--soft-border);
      background: #f4f6f8;
      padding: 20px 16px;
    }}

    .brand {{
      display: grid;
      gap: 10px;
      margin-bottom: 22px;
    }}

    .wiki-mark {{
      display: grid;
      place-items: center;
      width: 64px;
      height: 64px;
      border: 1px solid var(--soft-border);
      border-radius: 4px;
      background: #fff;
      color: var(--ink);
      font-family: Georgia, "Times New Roman", serif;
      font-size: 2.4rem;
      line-height: 1;
    }}

    .brand strong {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1.5rem;
      line-height: 1;
    }}

    .brand span {{
      color: var(--muted);
      font-size: .84rem;
    }}

    .side-nav {{
      display: grid;
      gap: 3px;
      margin-top: 14px;
    }}

    .side-nav a {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      border-radius: 4px;
      padding: 8px 9px;
      color: var(--ink);
      font-size: .92rem;
    }}

    .side-nav a:hover {{
      background: #eaf3ff;
      text-decoration: none;
    }}

    .side-nav span {{
      color: var(--muted);
      font-variant-numeric: tabular-nums;
    }}

    .main {{
      min-width: 0;
    }}

    .top-strip {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      border-bottom: 1px solid var(--soft-border);
      background: var(--surface);
      padding: 10px 22px;
    }}

    .top-strip a {{
      font-size: .9rem;
    }}

    .search {{
      flex: 1;
      max-width: 520px;
    }}

    .search input {{
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--border);
      border-radius: 4px;
      background: #fff;
      padding: 0 12px;
      font: inherit;
    }}

    .search input:focus {{
      outline: 2px solid rgba(51, 102, 204, .24);
      border-color: var(--wiki-blue-dark);
    }}

    .page {{
      width: min(100%, 1180px);
      margin: 0 auto;
      padding: 24px 22px 56px;
    }}

    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 320px;
      gap: 24px;
      align-items: start;
      border-bottom: 1px solid var(--border);
      padding-bottom: 22px;
    }}

    h1, h2 {{
      font-family: Georgia, "Times New Roman", serif;
      font-weight: 400;
      letter-spacing: 0;
    }}

    h1 {{
      margin: 0 0 8px;
      font-size: clamp(2.15rem, 5vw, 3.7rem);
      line-height: 1.05;
    }}

    .subtitle {{
      margin: 0 0 18px;
      max-width: 760px;
      color: var(--muted);
      font-size: 1.05rem;
    }}

    .hero-figure {{
      border: 1px solid var(--border);
      background: var(--surface);
      padding: 8px;
      font-size: .82rem;
      color: var(--muted);
    }}

    .hero-figure img {{
      display: block;
      width: 100%;
      height: auto;
      aspect-ratio: 16 / 9;
      object-fit: cover;
      border: 1px solid var(--soft-border);
    }}

    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin: 18px 0;
    }}

    .summary-card {{
      border: 1px solid var(--soft-border);
      border-radius: 4px;
      background: var(--surface);
      padding: 12px;
    }}

    .summary-card span {{
      display: block;
      color: var(--muted);
      font-size: .76rem;
      text-transform: uppercase;
    }}

    .summary-card strong {{
      display: block;
      margin-top: 5px;
      color: var(--ink);
      font-size: 1.4rem;
      line-height: 1.1;
    }}

    .notice {{
      border-left: 4px solid var(--amber);
      background: #fff8e6;
      padding: 12px 14px;
      color: #453400;
      margin: 18px 0 0;
    }}

    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 310px;
      gap: 24px;
      align-items: start;
      margin-top: 24px;
    }}

    .toc {{
      border: 1px solid var(--border);
      background: var(--surface);
      padding: 14px 18px;
      width: min(100%, 430px);
    }}

    .toc h2 {{
      margin: 0 0 8px;
      font-family: inherit;
      font-size: 1rem;
      font-weight: 700;
    }}

    .toc ol {{
      margin: 0;
      padding-left: 22px;
      columns: 2;
    }}

    .infobox {{
      position: sticky;
      top: 18px;
      border: 1px solid var(--border);
      background: var(--surface);
      font-size: .92rem;
    }}

    .infobox h2 {{
      margin: 0;
      padding: 10px 12px;
      background: #dbe8fb;
      font-family: inherit;
      font-size: 1.05rem;
      font-weight: 700;
      text-align: center;
    }}

    .infobox img {{
      display: block;
      width: 100%;
      border-bottom: 1px solid var(--soft-border);
    }}

    .infobox dl {{
      display: grid;
      grid-template-columns: 112px 1fr;
      gap: 0;
      margin: 0;
    }}

    .infobox dt,
    .infobox dd {{
      border-top: 1px solid var(--soft-border);
      margin: 0;
      padding: 8px 10px;
    }}

    .infobox dt {{
      background: #f1f3f5;
      font-weight: 700;
    }}

    .wiki-section {{
      margin-top: 32px;
    }}

    .section-heading {{
      border-bottom: 1px solid var(--border);
      margin-bottom: 14px;
    }}

    .section-heading h2 {{
      margin: 0;
      font-size: 1.8rem;
    }}

    .section-heading p {{
      margin: 4px 0 9px;
      color: var(--muted);
    }}

    .article-grid {{
      display: grid;
      gap: 12px;
    }}

    .wiki-article {{
      border: 1px solid var(--soft-border);
      border-radius: 4px;
      background: var(--surface);
      padding: 15px 16px 13px;
    }}

    .wiki-article header span {{
      display: block;
      color: var(--muted);
      font-size: .78rem;
      text-transform: uppercase;
    }}

    .wiki-article h3 {{
      margin: 2px 0 8px;
      color: var(--wiki-blue);
      font-size: 1.18rem;
      line-height: 1.25;
    }}

    .wiki-article h4 {{
      margin: 14px 0 4px;
      font-size: 1rem;
      color: var(--green);
    }}

    .wiki-article p {{
      margin: 0 0 9px;
    }}

    .media-row {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 22px;
    }}

    .media-row figure {{
      margin: 0;
      border: 1px solid var(--soft-border);
      background: var(--surface);
      padding: 8px;
    }}

    .media-row img {{
      display: block;
      width: 100%;
      aspect-ratio: 4 / 3;
      object-fit: cover;
    }}

    .media-row figcaption {{
      margin-top: 7px;
      color: var(--muted);
      font-size: .82rem;
    }}

    .empty-state {{
      display: none;
      border: 1px solid var(--soft-border);
      background: var(--surface);
      padding: 18px;
      color: var(--muted);
      margin-top: 18px;
    }}

    .empty-state.is-visible {{ display: block; }}
    .is-hidden {{ display: none; }}

    @media (max-width: 920px) {{
      .site-shell {{ grid-template-columns: 1fr; }}
      .sidebar {{
        position: static;
        height: auto;
        border-right: 0;
        border-bottom: 1px solid var(--soft-border);
      }}
      .side-nav {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .hero,
      .layout {{
        grid-template-columns: 1fr;
      }}
      .infobox {{ position: static; }}
    }}

    @media (max-width: 640px) {{
      .top-strip {{
        align-items: stretch;
        flex-direction: column;
      }}
      .summary-grid,
      .media-row {{
        grid-template-columns: 1fr;
      }}
      .toc ol {{ columns: 1; }}
      .page {{ padding: 18px 14px 42px; }}
      .side-nav {{ grid-template-columns: 1fr; }}
      .infobox dl {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="site-shell">
    <aside class="sidebar" aria-label="Navigazione principale">
      <div class="brand">
        <div class="wiki-mark" aria-hidden="true">W</div>
        <strong>Wikipodia</strong>
        <span>Enciclopedia del piede strutturata dal documento podologico.</span>
      </div>
      <nav class="side-nav">
        {nav}
      </nav>
    </aside>

    <main class="main">
      <div class="top-strip">
        <a href="index.html">Pagina iniziale</a>
        <label class="search">
          <input id="wikiSearch" type="search" placeholder="Cerca una voce, una patologia o un plantare">
        </label>
      </div>

      <div class="page">
        <header class="hero">
          <div>
            <h1>Il piede</h1>
            <p class="subtitle">Il piede umano e le sue principali patologie, organizzati in forma enciclopedica: anatomia, tipologie di appoggio, dolore, ortesi plantari, analisi del passo, piede diabetico e prevenzione.</p>
            <div class="summary-grid" aria-label="Riepilogo contenuti">
              <div class="summary-card"><span>Voci totali</span><strong>{len(articles)}</strong></div>
              <div class="summary-card"><span>Patologie</span><strong>{total_pathologies}</strong></div>
              <div class="summary-card"><span>Plantari e ortesi</span><strong>{total_plantari}</strong></div>
            </div>
            <p class="notice">Le informazioni hanno scopo divulgativo e non sostituiscono la valutazione di un medico, podologo o professionista sanitario qualificato.</p>
          </div>
          <figure class="hero-figure">
            <img src="assets/podologica/page-004-1.jpg" alt="Illustrazione introduttiva sui punti del piede">
            <figcaption>Materiale visuale estratto dal PDF sorgente.</figcaption>
          </figure>
        </header>

        <div class="layout">
          <div>
            <section class="toc" aria-labelledby="toc-title">
              <h2 id="toc-title">Indice</h2>
              <ol>
                {toc}
              </ol>
            </section>

            <div class="media-row" aria-label="Immagini tematiche">
              <figure>
                <img src="assets/podologica/page-006-2.jpg" alt="Mappa pressoria plantare">
                <figcaption>Distribuzione delle pressioni plantari.</figcaption>
              </figure>
              <figure>
                <img src="assets/podologica/page-012-1.jpg" alt="Tipi di piede egizio greco romano">
                <figcaption>Tipologie morfologiche del piede.</figcaption>
              </figure>
              <figure>
                <img src="assets/podologica/page-016-1.jpg" alt="Pronazione postura e supinazione">
                <figcaption>Pronazione, postura corretta e supinazione.</figcaption>
              </figure>
            </div>

            <div id="emptyState" class="empty-state">Nessuna voce corrisponde alla ricerca.</div>
            {"".join(sections)}
          </div>

          <aside class="infobox" aria-label="Scheda enciclopedica">
            <h2>Wikipodia</h2>
            <img src="assets/podologica/page-009-1.jpg" alt="Scansione e appoggio del piede">
            <dl>
              <dt>Argomento</dt><dd>Piede, postura, plantari</dd>
              <dt>Fonte</dt><dd>podologica.pdf</dd>
              <dt>Struttura</dt><dd>Enciclopedia con ricerca</dd>
              <dt>Lingua</dt><dd>Italiano</dd>
              <dt>Uso</dt><dd>Informativo</dd>
            </dl>
          </aside>
        </div>
      </div>
    </main>
  </div>

  <script>
    const input = document.getElementById('wikiSearch');
    const emptyState = document.getElementById('emptyState');
    const articles = Array.from(document.querySelectorAll('.wiki-article'));
    const sections = Array.from(document.querySelectorAll('.wiki-section'));

    input.addEventListener('input', () => {{
      const query = input.value.trim().toLowerCase();
      let visibleCount = 0;

      articles.forEach((article) => {{
        const text = article.innerText.toLowerCase();
        const visible = !query || text.includes(query);
        article.classList.toggle('is-hidden', !visible);
        if (visible) visibleCount += 1;
      }});

      sections.forEach((section) => {{
        const hasVisibleArticle = Boolean(section.querySelector('.wiki-article:not(.is-hidden)'));
        section.classList.toggle('is-hidden', !hasVisibleArticle);
      }});

      emptyState.classList.toggle('is-visible', visibleCount === 0);
    }});
  </script>
</body>
</html>
"""
    output_path.write_text(document, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Wikipedia-style page from podologica PDF text.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    articles = extract_articles(args.pdf)
    render(args.output, articles)


if __name__ == "__main__":
    main()
