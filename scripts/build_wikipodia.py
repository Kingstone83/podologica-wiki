from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


ASSET_VERSION = "20260527-wiki-restore"


SKIP_PREFIXES = (
    "podologica.net",
    "wikipodia.net",
    "wikipodia l'enciclopedia",
    "wikipodia l’enciclopedia",
    "analisidelpiede",
    "inpiedi.net",
    "centrodiabete.net",
    "home ",
    "il mio piede     patologie",
)

DEFAULT_IMAGES = {
    "Introduzione": "assets/podologica/page-004-1.jpg",
    "Conosci il tuo piede": "assets/podologica/page-012-1.jpg",
    "Enciclopedia delle patologie": "assets/podologica/page-059-1.jpg",
    "Plantari e ortesi": "assets/podologica/page-006-2.jpg",
    "Analisi e trattamento": "assets/podologica/page-009-1.jpg",
    "Piede diabetico": "assets/podologica/page-164-1.jpg",
    "Cura, movimento e news": "assets/podologica/page-190-1.jpg",
    "Contatti": "assets/podologica/page-205-1.jpg",
    "Tecnica ortopedica": "assets/podologica/page-016-1.jpg",
}


@dataclass
class Article:
    page: int
    title: str
    category: str
    lines: list[str]
    slug: str = ""

    @property
    def filename(self) -> str:
        return f"{self.slug}.html"

    @property
    def text(self) -> str:
        return " ".join(self.lines)

    @property
    def excerpt(self) -> str:
        text = self.text
        return text[:230].rsplit(" ", 1)[0] + ("..." if len(text) > 230 else "")


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
    if len(line) > 180 and ("contatti" in low or ("plantari" in low and "wikipodia" in low)):
        return False
    return True


def clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r", "").splitlines():
        line = normalize_line(raw)
        if keep_line(line) and (not lines or lines[-1] != line):
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
        or line[:1].islower()
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


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower())
    return value.strip("-") or "voce"


def unique_slug(base: str, used: set[str]) -> str:
    slug = base
    counter = 2
    while slug in used:
        slug = f"{base}-{counter}"
        counter += 1
    used.add(slug)
    return slug


def extract_articles(pdf_path: Path) -> list[Article]:
    reader = PdfReader(str(pdf_path))
    articles: list[Article] = []
    previous_by_category: dict[str, str] = {}
    used_slugs: set[str] = set()

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
        article = Article(page=page_number, title=title, category=category, lines=lines)
        article.slug = unique_slug(f"{page_number:03d}-{slugify(title)}", used_slugs)
        articles.append(article)

    return articles


def grouped(articles: list[Article]) -> dict[str, list[Article]]:
    groups: dict[str, list[Article]] = {}
    for article in articles:
        groups.setdefault(article.category, []).append(article)
    return groups


def rel(path: str, depth: int = 0) -> str:
    return "../" * depth + path


def page_image(article: Article | None, category: str | None = None) -> str:
    if article:
        assets = Path("assets/podologica")
        for ext in ("jpg", "png", "jp2"):
            candidate = assets / f"page-{article.page:03d}-1.{ext}"
            if candidate.exists():
                return str(candidate)
    return DEFAULT_IMAGES.get(category or "", "assets/podologica/page-004-1.jpg")


def paragraphize(lines: list[str]) -> str:
    chunks: list[str] = []
    buffer: list[str] = []
    for line in lines:
        heading = bool(re.match(r"^(\d+\)|[A-Z][A-Z0-9 /'().-]{3,}|DEFINIZIONE|CAUSA|TRATTAMENTO)", line))
        if heading or (len(line) < 42 and line.endswith(":")):
            if buffer:
                chunks.append("<p>" + html.escape(" ".join(buffer)) + "</p>")
                buffer = []
            label = line.title() if line.isupper() else line
            chunks.append(f"<h2>{html.escape(label)}</h2>")
        else:
            buffer.append(line)
            if len(" ".join(buffer)) > 520:
                chunks.append("<p>" + html.escape(" ".join(buffer)) + "</p>")
                buffer = []
    if buffer:
        chunks.append("<p>" + html.escape(" ".join(buffer)) + "</p>")
    return "\n".join(chunks)


def sidebar(groups: dict[str, list[Article]], depth: int = 0) -> str:
    nav = "\n".join(
        f'<a href="{rel(f"categorie/{slugify(name)}.html", depth)}">{html.escape(name)} <span>{len(items)}</span></a>'
        for name, items in groups.items()
    )
    return f"""
    <aside class="sidebar" aria-label="Navigazione principale">
      <a class="brand" href="{rel("index.html", depth)}">
        <span class="wiki-mark">W</span>
        <strong>Wikipodia</strong>
        <small>Enciclopedia podologica</small>
      </a>
      <nav class="side-nav">
        <a href="{rel("index.html", depth)}">Pagina principale</a>
        <a href="{rel("indice.html", depth)}">Indice alfabetico</a>
        <a href="{rel("ricerca.html", depth)}">Ricerca</a>
        <button id="randomArticle" type="button">Una voce a caso</button>
      </nav>
      <h2>Categorie</h2>
      <nav class="side-nav side-categories">{nav}</nav>
      <h2>Informazioni legali</h2>
      <nav class="side-nav">
        <a href="{rel("privacy.html", depth)}">Privacy</a>
        <a href="{rel("cookie.html", depth)}">Cookie</a>
        <a href="{rel("note-legali.html", depth)}">Note legali</a>
        <a href="{rel("dichiarazione-cautelativa.html", depth)}">Dichiarazione cautelativa</a>
      </nav>
    </aside>
    """


def topbar(depth: int = 0) -> str:
    return f"""
    <header class="topbar">
      <nav>
        <a href="{rel("index.html", depth)}">Leggi</a>
        <a href="{rel("indice.html", depth)}">Indice</a>
        <a href="{rel("ricerca.html", depth)}">Cerca</a>
        <a href="{rel("privacy.html", depth)}">Privacy</a>
      </nav>
      <form class="quick-search" action="{rel("ricerca.html", depth)}">
        <input name="q" type="search" placeholder="Cerca in Wikipodia">
        <button type="submit">Cerca</button>
      </form>
    </header>
    """


def shell(title: str, body: str, groups: dict[str, list[Article]], depth: int = 0) -> str:
    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} · Wikipodia</title>
  <link rel="stylesheet" href="{rel("assets/wiki.css", depth)}?v={ASSET_VERSION}">
  <script src="{rel("assets/search-index.js", depth)}?v={ASSET_VERSION}" defer></script>
  <script src="{rel("assets/wiki.js", depth)}?v={ASSET_VERSION}" defer></script>
</head>
<body>
  <div class="wiki-shell">
    {sidebar(groups, depth)}
    <main class="main">
      {topbar(depth)}
      {body}
    </main>
  </div>
</body>
</html>
"""


def article_link(article: Article, depth: int = 0) -> str:
    return rel(f"voci/{article.filename}", depth)


def category_link(category: str, depth: int = 0) -> str:
    return rel(f"categorie/{slugify(category)}.html", depth)


def render_article_card(article: Article, depth: int = 0) -> str:
    return f"""
    <article class="entry-card">
      <a class="entry-title" href="{article_link(article, depth)}">{html.escape(article.title)}</a>
      <p>{html.escape(article.excerpt)}</p>
      <span>Pagina PDF {article.page:03d}</span>
    </article>
    """


def render_home(output_dir: Path, articles: list[Article], groups: dict[str, list[Article]]) -> None:
    featured = articles[3:7]
    category_panels = "\n".join(
        f"""
        <section class="portal-card">
          <h2><a href="{category_link(name)}">{html.escape(name)}</a></h2>
          <p>{len(items)} voci disponibili.</p>
          <ul>
            {"".join(f'<li><a href="{article_link(item)}">{html.escape(item.title)}</a></li>' for item in items[:5])}
          </ul>
        </section>
        """
        for name, items in groups.items()
    )
    body = f"""
      <section class="welcome">
        <div>
          <h1>Wikipodia</h1>
          <p>L'enciclopedia podologica organizzata in categorie, voci, indice alfabetico e ricerca interna.</p>
          <div class="stats">
            <strong>{len(articles)}</strong><span>voci</span>
            <strong>{len(groups)}</strong><span>categorie</span>
            <strong>{sum(1 for a in articles if "plantari" in a.title.lower())}</strong><span>voci sui plantari</span>
          </div>
        </div>
        <figure>
          <img src="assets/podologica/page-004-1.jpg" alt="Schema del piede">
          <figcaption>Materiali estratti dal documento sorgente.</figcaption>
        </figure>
      </section>

      <section class="portal-grid">
        <article class="portal-card portal-wide">
          <h2>Voci in evidenza</h2>
          <div class="compact-list">
            {"".join(render_article_card(article) for article in featured)}
          </div>
        </article>
        {category_panels}
      </section>

      <section class="notice">
        Le informazioni sono divulgative e non sostituiscono una valutazione professionale. Leggi anche <a href="note-legali.html">note legali</a>, <a href="privacy.html">privacy</a> e <a href="dichiarazione-cautelativa.html">dichiarazione cautelativa</a>.
      </section>
    """
    (output_dir / "index.html").write_text(shell("Pagina principale", body, groups), encoding="utf-8")


def render_category_pages(output_dir: Path, groups: dict[str, list[Article]]) -> None:
    category_dir = output_dir / "categorie"
    category_dir.mkdir(exist_ok=True)
    for category, items in groups.items():
        cards = "\n".join(render_article_card(article, depth=1) for article in items)
        body = f"""
        <article class="content-page">
          <p class="crumb"><a href="../index.html">Pagina principale</a> / Categoria</p>
          <h1>{html.escape(category)}</h1>
          <p class="lead">Portale con {len(items)} voci collegate alla categoria.</p>
          <div class="entry-grid">{cards}</div>
        </article>
        """
        (category_dir / f"{slugify(category)}.html").write_text(shell(category, body, groups, depth=1), encoding="utf-8")


def render_article_pages(output_dir: Path, articles: list[Article], groups: dict[str, list[Article]]) -> None:
    article_dir = output_dir / "voci"
    article_dir.mkdir(exist_ok=True)
    by_slug = {article.slug: i for i, article in enumerate(articles)}
    for article in articles:
        index = by_slug[article.slug]
        previous = articles[index - 1] if index > 0 else None
        next_article = articles[index + 1] if index + 1 < len(articles) else None
        category_items = groups[article.category]
        related = [item for item in category_items if item.slug != article.slug][:6]
        image = rel(page_image(article, article.category), depth=1)
        body_lines = article.lines[1:] if article.lines and article.lines[0] == article.title else article.lines
        prev_next = "".join(
            part
            for part in (
                f'<a href="{previous.filename}">Voce precedente</a>' if previous else "",
                f'<a href="{next_article.filename}">Voce successiva</a>' if next_article else "",
            )
            if part
        )
        body = f"""
        <article class="content-page article-page">
          <p class="crumb"><a href="../index.html">Pagina principale</a> / <a href="{category_link(article.category, depth=1)}">{html.escape(article.category)}</a></p>
          <header class="article-header">
            <div>
              <h1>{html.escape(article.title)}</h1>
              <p class="lead">Voce tratta dalla pagina {article.page:03d} del documento sorgente.</p>
            </div>
            <aside class="infobox">
              <h2>Scheda voce</h2>
              <img src="{image}" alt="">
              <dl>
                <dt>Categoria</dt><dd><a href="{category_link(article.category, depth=1)}">{html.escape(article.category)}</a></dd>
                <dt>Pagina fonte</dt><dd>{article.page:03d}</dd>
                <dt>Tipo</dt><dd>Voce enciclopedica</dd>
              </dl>
            </aside>
          </header>
          <nav class="article-tabs">
            <a aria-current="page" href="#">Voce</a>
            <a href="../ricerca.html?q={html.escape(article.title)}">Cerca correlati</a>
            <a href="{category_link(article.category, depth=1)}">Categoria</a>
          </nav>
          <div class="article-body">{paragraphize(body_lines)}</div>
          <section class="related">
            <h2>Voci correlate</h2>
            <ul>{"".join(f'<li><a href="{item.filename}">{html.escape(item.title)}</a></li>' for item in related)}</ul>
          </section>
          <nav class="prev-next">{prev_next}</nav>
        </article>
        """
        (article_dir / article.filename).write_text(shell(article.title, body, groups, depth=1), encoding="utf-8")


def render_index_page(output_dir: Path, articles: list[Article], groups: dict[str, list[Article]]) -> None:
    by_letter: dict[str, list[Article]] = {}
    for article in sorted(articles, key=lambda a: slugify(a.title)):
        letter = slugify(article.title)[:1].upper() or "#"
        if letter.isdigit():
            letter = "0-9"
        by_letter.setdefault(letter, []).append(article)
    blocks = "\n".join(
        f"""
        <section class="alpha-block">
          <h2>{html.escape(letter)}</h2>
          <ul>{"".join(f'<li><a href="{article_link(article)}">{html.escape(article.title)}</a></li>' for article in items)}</ul>
        </section>
        """
        for letter, items in by_letter.items()
    )
    body = f"""
      <article class="content-page">
        <h1>Indice alfabetico</h1>
        <p class="lead">Tutte le voci pubblicate in Wikipodia.</p>
        <div class="alpha-grid">{blocks}</div>
      </article>
    """
    (output_dir / "indice.html").write_text(shell("Indice alfabetico", body, groups), encoding="utf-8")


def render_search_page(output_dir: Path, groups: dict[str, list[Article]]) -> None:
    body = """
      <article class="content-page search-page">
        <h1>Ricerca</h1>
        <p class="lead">Cerca nelle voci, nelle categorie e nel testo estratto dal documento.</p>
        <form class="search-panel" id="searchForm">
          <input id="searchInput" name="q" type="search" placeholder="Es. alluce valgo, piede diabetico, plantari">
          <button type="submit">Cerca</button>
        </form>
        <div id="searchResults" class="search-results"></div>
      </article>
    """
    (output_dir / "ricerca.html").write_text(shell("Ricerca", body, groups), encoding="utf-8")


def render_disclaimer_page(output_dir: Path, groups: dict[str, list[Article]]) -> None:
    body = """
      <article class="content-page legal-page">
        <h1>Dichiarazione cautelativa</h1>
        <p class="lead">Nota sulla natura provvisoria dei testi e sulla necessità di verifica editoriale, legale e documentale prima della pubblicazione o dell'uso commerciale.</p>

        <section class="legal-text">
          <p>Dichiaro che i testi in oggetto sono stati prodotti come materiale provvisorio di supporto e non come contenuti originali definitivi.</p>

          <p>La loro redazione è stata effettuata anche con l'ausilio di strumenti di intelligenza artificiale, i quali possono generare contenuti basati su rielaborazioni linguistiche di informazioni diffuse pubblicamente. Non essendo stato mantenuto un tracciamento puntuale delle fonti durante la fase di generazione e revisione, non posso garantire che ogni parte del testo sia completamente originale o priva di analogie con contenuti già esistenti.</p>

          <p>Pertanto, i testi non devono essere considerati idonei alla pubblicazione o all'uso commerciale senza una preventiva verifica editoriale, legale e documentale. Non intendo rivendicare la paternità esclusiva di eventuali porzioni testuali riconducibili a fonti terze.</p>

          <p>L'utilizzo finale dei testi dovrà essere preceduto da revisione, eventuale riscrittura e verifica delle fonti, al fine di evitare violazioni di diritti d'autore, attribuzioni improprie o comunicazioni fuorvianti.</p>
        </section>
      </article>
    """
    (output_dir / "dichiarazione-cautelativa.html").write_text(shell("Dichiarazione cautelativa", body, groups), encoding="utf-8")


def render_privacy_page(output_dir: Path, groups: dict[str, list[Article]]) -> None:
    body = """
      <article class="content-page legal-page">
        <h1>Privacy</h1>
        <p class="lead">Informativa sintetica per un sito statico ospitato tramite GitHub Pages, senza registrazione utenti, newsletter, form di contatto o strumenti di analytics gestiti dal sito.</p>

        <section class="legal-text">
          <h2>Titolare e contatti</h2>
          <p>Il sito è pubblicato dal gestore del repository GitHub <strong>Kingstone83/podologica-wiki</strong>. Prima di un uso professionale o commerciale, questa sezione deve essere completata con i dati identificativi e un recapito effettivo del titolare del trattamento.</p>

          <h2>Dati trattati direttamente dal sito</h2>
          <p>Questo sito è composto da pagine statiche HTML, CSS e JavaScript. Non prevede account, commenti, moduli di contatto, newsletter, pagamenti o aree riservate. La ricerca interna funziona nel browser dell'utente usando un indice statico scaricato con il sito.</p>

          <h2>Dati tecnici di navigazione</h2>
          <p>La pubblicazione avviene tramite GitHub Pages. Durante l'accesso alle pagine, GitHub può trattare dati tecnici necessari all'erogazione e alla sicurezza del servizio, come indirizzo IP, data e ora della richiesta, risorsa richiesta, user agent e informazioni tecniche analoghe, secondo la propria informativa privacy.</p>

          <h2>Finalità</h2>
          <p>Le finalità sono: rendere disponibili le pagine del sito, consentire la navigazione, mantenere sicurezza e integrità del servizio di hosting, e permettere una ricerca locale tra i contenuti pubblicati.</p>

          <h2>Base giuridica</h2>
          <p>Per le attività tecniche essenziali alla visualizzazione del sito, la base giuridica può essere individuata nell'interesse legittimo alla pubblicazione, sicurezza e corretto funzionamento del sito. Eventuali trattamenti autonomi effettuati da GitHub sono disciplinati dalle informative e condizioni di GitHub.</p>

          <h2>Cookie e tracciamento</h2>
          <p>Il sito non installa cookie di profilazione, non usa strumenti di analytics propri e non incorpora contenuti pubblicitari o social plugin. Per maggiori dettagli consulta la <a href="cookie.html">cookie policy</a>.</p>

          <h2>Comunicazione e trasferimenti</h2>
          <p>I contenuti sono ospitati su infrastruttura GitHub Pages. GitHub può trattare dati tecnici anche attraverso società del proprio gruppo o fornitori, secondo le proprie condizioni e informative. Il gestore del sito non riceve statistiche nominative sugli utenti dal codice del sito.</p>

          <h2>Diritti dell'utente</h2>
          <p>Nei limiti applicabili, l'utente può chiedere accesso, rettifica, cancellazione, limitazione, opposizione o altre tutele previste dalla normativa privacy. Per trattamenti effettuati direttamente da GitHub occorre rivolgersi a GitHub secondo i canali indicati nella sua informativa.</p>

          <h2>Avvertenza</h2>
          <p>Questa informativa è una base prudenziale per un sito statico e deve essere verificata da un professionista prima dell'uso commerciale, sanitario, promozionale o quando vengano aggiunti form, analytics, newsletter, mappe, video incorporati, cookie o servizi di terze parti.</p>
        </section>
      </article>
    """
    (output_dir / "privacy.html").write_text(shell("Privacy", body, groups), encoding="utf-8")


def render_cookie_page(output_dir: Path, groups: dict[str, list[Article]]) -> None:
    body = """
      <article class="content-page legal-page">
        <h1>Cookie</h1>
        <p class="lead">Informazioni sull'uso di cookie e altri strumenti di tracciamento.</p>

        <section class="legal-text">
          <h2>Cookie usati dal sito</h2>
          <p>Il sito non imposta cookie propri, non usa cookie di profilazione, non utilizza sistemi pubblicitari e non integra analytics di prima parte o di terze parti.</p>

          <h2>Ricerca interna</h2>
          <p>La ricerca utilizza un file statico del sito e viene eseguita localmente nel browser. La query può comparire nell'indirizzo della pagina, ad esempio come parametro <code>?q=alluce</code>, ma non viene salvata dal sito in database o profili utente.</p>

          <h2>GitHub Pages</h2>
          <p>Il sito è ospitato da GitHub Pages. GitHub può trattare dati tecnici di navigazione per fornire, proteggere e mantenere il servizio. Per informazioni complete si rimanda alla documentazione e all'informativa privacy di GitHub.</p>

          <h2>Banner cookie</h2>
          <p>Poiché il sito non usa cookie di profilazione, strumenti pubblicitari, analytics o tecnologie assimilabili gestite dal sito, non viene mostrato un banner di consenso. Se in futuro verranno aggiunti servizi che installano cookie o tracciatori non tecnici, questa pagina e il meccanismo di consenso dovranno essere aggiornati prima della pubblicazione.</p>
        </section>
      </article>
    """
    (output_dir / "cookie.html").write_text(shell("Cookie", body, groups), encoding="utf-8")


def render_legal_page(output_dir: Path, groups: dict[str, list[Article]]) -> None:
    body = """
      <article class="content-page legal-page">
        <h1>Note legali</h1>
        <p class="lead">Condizioni e avvertenze generali per la consultazione del sito.</p>

        <section class="legal-text">
          <h2>Natura dei contenuti</h2>
          <p>I contenuti hanno finalità informative, divulgative e di supporto editoriale. Non costituiscono consulenza medica, diagnosi, prescrizione, parere professionale, pubblicità sanitaria o indicazione terapeutica personalizzata.</p>

          <h2>Uso dei contenuti</h2>
          <p>Le informazioni devono essere verificate con professionisti qualificati prima di assumere decisioni cliniche, sanitarie, commerciali o legali. In presenza di sintomi, dolore, lesioni o patologie, è necessario rivolgersi a un medico, podologo o altro professionista sanitario abilitato.</p>

          <h2>Originalità, fonti e revisione</h2>
          <p>I testi sono materiale provvisorio e devono essere sottoposti a revisione editoriale, legale e documentale prima dell'uso commerciale o promozionale. Per maggiori dettagli consulta la <a href="dichiarazione-cautelativa.html">dichiarazione cautelativa</a>.</p>

          <h2>Marchi, immagini e contenuti di terzi</h2>
          <p>Eventuali marchi, denominazioni, immagini o riferimenti riconducibili a terzi appartengono ai rispettivi titolari. La presenza nel sito non implica approvazione, affiliazione o autorizzazione, salvo diversa indicazione documentata.</p>

          <h2>Limitazione di responsabilità</h2>
          <p>Il gestore del sito non garantisce completezza, aggiornamento, accuratezza o idoneità dei contenuti per finalità specifiche. Il sito può essere modificato, sospeso o rimosso in qualsiasi momento.</p>

          <h2>Link e servizi esterni</h2>
          <p>Il sito può contenere collegamenti a pagine o servizi di terze parti. Tali soggetti sono responsabili dei propri contenuti, condizioni d'uso e trattamenti di dati personali.</p>

          <h2>Prima dell'uso pubblico definitivo</h2>
          <p>Prima di usare il sito per attività professionali, sanitarie o commerciali, è opportuno completare i dati del titolare, verificare diritti su testi e immagini, controllare fonti e autorizzazioni, e far validare le pagine legali da un consulente competente.</p>
        </section>
      </article>
    """
    (output_dir / "note-legali.html").write_text(shell("Note legali", body, groups), encoding="utf-8")


def render_assets(output_dir: Path, articles: list[Article]) -> None:
    index = [
        {
            "title": article.title,
            "category": article.category,
            "page": article.page,
            "url": f"voci/{article.filename}",
            "text": article.text,
        }
        for article in articles
    ]
    (output_dir / "assets" / "search-index.js").write_text(
        "window.WIKIPODIA_INDEX = " + json.dumps(index, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    (output_dir / "assets" / "wiki.js").write_text(WIKI_JS, encoding="utf-8")
    (output_dir / "assets" / "wiki.css").write_text(WIKI_CSS, encoding="utf-8")


def clean_generated(output_dir: Path) -> None:
    for name in ("voci", "categorie"):
        path = output_dir / name
        if path.exists():
            shutil.rmtree(path)
    for name in ("indice.html", "ricerca.html", "dichiarazione-cautelativa.html", "privacy.html", "cookie.html", "note-legali.html"):
        path = output_dir / name
        if path.exists():
            path.unlink()


def render(output_dir: Path, articles: list[Article]) -> None:
    groups = grouped(articles)
    clean_generated(output_dir)
    (output_dir / "assets").mkdir(exist_ok=True)
    render_assets(output_dir, articles)
    render_home(output_dir, articles, groups)
    render_category_pages(output_dir, groups)
    render_article_pages(output_dir, articles, groups)
    render_index_page(output_dir, articles, groups)
    render_search_page(output_dir, groups)
    render_disclaimer_page(output_dir, groups)
    render_privacy_page(output_dir, groups)
    render_cookie_page(output_dir, groups)
    render_legal_page(output_dir, groups)


WIKI_JS = """(() => {
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
      results.innerHTML = '<p class=\"muted\">Inserisci una parola per iniziare la ricerca.</p>';
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
      results.innerHTML = '<p class=\"muted\">Nessuna voce trovata.</p>';
      return;
    }
    results.innerHTML = matches.map(({ item }) => `
      <article class=\"search-result\">
        <a href=\"${item.url}\">${item.title}</a>
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
"""


WIKI_CSS = """:root {
  color-scheme: light;
  --page: #f8f9fa;
  --surface: #fff;
  --ink: #202122;
  --muted: #54595d;
  --border: #a2a9b1;
  --soft-border: #d8dce0;
  --blue: #0645ad;
  --blue-soft: #eaf3ff;
  --green-soft: #eef7ed;
  --yellow-soft: #fff8df;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  color: var(--ink);
  background: var(--page);
  font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
a { color: var(--blue); text-decoration: none; }
a:hover { text-decoration: underline; }
button, input { font: inherit; }

.wiki-shell {
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
  min-height: 100vh;
}
.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  overflow: auto;
  border-right: 1px solid var(--soft-border);
  background: #f4f6f8;
  padding: 20px 16px;
}
.brand {
  display: grid;
  gap: 8px;
  color: var(--ink);
  margin-bottom: 22px;
}
.brand:hover { text-decoration: none; }
.wiki-mark {
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  border: 1px solid var(--soft-border);
  border-radius: 4px;
  background: #fff;
  font: 2.5rem/1 Georgia, "Times New Roman", serif;
}
.brand strong {
  font: 1.55rem/1 Georgia, "Times New Roman", serif;
}
.brand small { color: var(--muted); }
.sidebar h2 {
  margin: 20px 8px 8px;
  font-size: .84rem;
  color: var(--muted);
  text-transform: uppercase;
}
.side-nav {
  display: grid;
  gap: 3px;
}
.side-nav a,
.side-nav button {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  border: 0;
  border-radius: 4px;
  background: transparent;
  padding: 8px 9px;
  color: var(--ink);
  cursor: pointer;
  text-align: left;
}
.side-nav a:hover,
.side-nav button:hover {
  background: var(--blue-soft);
  text-decoration: none;
}
.side-categories span {
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.main { min-width: 0; }
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--soft-border);
  background: var(--surface);
  padding: 10px 22px;
}
.topbar nav {
  display: flex;
  gap: 16px;
}
.quick-search {
  display: grid;
  grid-template-columns: minmax(160px, 380px) auto;
  gap: 6px;
}
.quick-search input,
.search-panel input {
  min-height: 38px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: #fff;
  padding: 0 12px;
}
.quick-search button,
.search-panel button {
  min-height: 38px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: #f8f9fa;
  cursor: pointer;
}
.welcome,
.content-page {
  width: min(100%, 1160px);
  margin: 0 auto;
  padding: 28px 22px 56px;
}
.welcome {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 330px;
  gap: 26px;
  align-items: start;
  border-bottom: 1px solid var(--border);
}
h1, .content-page > h2 {
  margin: 0 0 10px;
  font-family: Georgia, "Times New Roman", serif;
  font-weight: 400;
  letter-spacing: 0;
}
h1 {
  font-size: clamp(2.25rem, 5vw, 3.8rem);
  line-height: 1.05;
}
.lead {
  max-width: 760px;
  color: var(--muted);
  font-size: 1.08rem;
}
.stats {
  display: grid;
  grid-template-columns: repeat(3, auto 1fr);
  gap: 8px 10px;
  max-width: 620px;
  margin-top: 18px;
}
.stats strong { font-size: 1.5rem; }
.stats span { color: var(--muted); align-self: center; }
figure {
  margin: 0;
  border: 1px solid var(--border);
  background: var(--surface);
  padding: 8px;
  color: var(--muted);
  font-size: .84rem;
}
figure img,
.infobox img {
  display: block;
  width: 100%;
  height: auto;
}
.portal-grid {
  width: min(100%, 1160px);
  margin: 22px auto 0;
  padding: 0 22px 56px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}
.portal-card {
  border: 1px solid var(--soft-border);
  border-radius: 4px;
  background: var(--surface);
  padding: 16px;
}
.portal-card:nth-child(3n) { background: var(--green-soft); }
.portal-card:nth-child(4n) { background: var(--yellow-soft); }
.portal-wide {
  grid-column: 1 / -1;
}
.portal-card h2,
.entry-card h2,
.article-body h2,
.related h2,
.alpha-block h2 {
  margin: 0 0 8px;
  font-family: Georgia, "Times New Roman", serif;
  font-weight: 400;
}
.portal-card ul,
.related ul,
.alpha-block ul {
  margin: 0;
  padding-left: 20px;
}
.compact-list,
.entry-grid {
  display: grid;
  gap: 12px;
}
.entry-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.entry-card {
  border: 1px solid var(--soft-border);
  border-radius: 4px;
  background: #fff;
  padding: 13px 14px;
}
.entry-title {
  font-weight: 700;
}
.entry-card p,
.search-result p {
  margin: 6px 0;
}
.entry-card span,
.search-result span,
.crumb,
.muted {
  color: var(--muted);
  font-size: .9rem;
}
.notice {
  width: min(100% - 44px, 1160px);
  margin: 0 auto 48px;
  border-left: 4px solid #946200;
  background: var(--yellow-soft);
  padding: 12px 14px;
}
.content-page {
  background: var(--page);
}
.article-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 24px;
  align-items: start;
  border-bottom: 1px solid var(--border);
  padding-bottom: 18px;
}
.infobox {
  border: 1px solid var(--border);
  background: #fff;
  font-size: .9rem;
}
.infobox h2 {
  margin: 0;
  padding: 10px 12px;
  background: #dbe8fb;
  font: 700 1rem/1.2 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  text-align: center;
}
.infobox dl {
  display: grid;
  grid-template-columns: 110px 1fr;
  margin: 0;
}
.infobox dt,
.infobox dd {
  margin: 0;
  border-top: 1px solid var(--soft-border);
  padding: 8px 10px;
}
.infobox dt {
  background: #f1f3f5;
  font-weight: 700;
}
.article-tabs,
.prev-next {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  border-bottom: 1px solid var(--soft-border);
  margin: 14px 0 20px;
  padding-bottom: 9px;
}
.article-tabs a,
.prev-next a {
  border: 1px solid var(--soft-border);
  border-radius: 4px;
  background: #fff;
  padding: 6px 10px;
}
.article-body {
  max-width: 820px;
}
.article-body p {
  margin: 0 0 14px;
}
.article-body h2 {
  margin-top: 24px;
  border-bottom: 1px solid var(--soft-border);
}
.related {
  max-width: 820px;
  border-top: 1px solid var(--soft-border);
  margin-top: 28px;
  padding-top: 16px;
}
.alpha-grid {
  columns: 2;
  column-gap: 28px;
}
.alpha-block {
  break-inside: avoid;
  border-top: 1px solid var(--soft-border);
  margin-bottom: 18px;
  padding-top: 10px;
}
.search-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 120px;
  gap: 8px;
  max-width: 760px;
  margin: 20px 0;
}
.search-result {
  max-width: 840px;
  border-top: 1px solid var(--soft-border);
  padding: 13px 0;
}
.search-result a {
  display: block;
  font-size: 1.12rem;
  font-weight: 700;
}
.legal-text {
  max-width: 860px;
  border: 1px solid var(--soft-border);
  border-radius: 4px;
  background: #fff;
  padding: 18px 20px;
}
.legal-text p {
  margin: 0 0 14px;
}
.legal-text p:last-child {
  margin-bottom: 0;
}

@media (max-width: 920px) {
  .wiki-shell { grid-template-columns: 1fr; }
  .main { order: 1; }
  .sidebar {
    order: 2;
    position: static;
    height: auto;
    border-right: 0;
    border-bottom: 1px solid var(--soft-border);
  }
  .side-categories { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .welcome,
  .article-header,
  .portal-grid,
  .entry-grid {
    grid-template-columns: 1fr;
  }
  .portal-wide { grid-column: auto; }
}

@media (max-width: 640px) {
  .topbar,
  .quick-search,
  .search-panel {
    grid-template-columns: 1fr;
  }
  .topbar {
    display: grid;
    align-items: stretch;
  }
  .welcome,
  .content-page,
  .portal-grid {
    padding-left: 14px;
    padding-right: 14px;
  }
  .stats {
    grid-template-columns: auto 1fr;
  }
  .side-categories,
  .alpha-grid {
    columns: 1;
    grid-template-columns: 1fr;
  }
  .infobox dl { grid-template-columns: 1fr; }
}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a static wiki from podologica PDF text.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output_dir", type=Path, nargs="?", default=Path("."))
    args = parser.parse_args()

    articles = extract_articles(args.pdf)
    render(args.output_dir, articles)


if __name__ == "__main__":
    main()
