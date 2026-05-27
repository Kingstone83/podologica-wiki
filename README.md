# Wikipodia

Sito enciclopedico statico sul piede e sulle principali tematiche podologiche, generato a partire dal documento `podologica.pdf`.

## Pubblicazione

Il sito e pronto per GitHub Pages. La pagina principale e `index.html`.

## Aggiornare il sito

Per rigenerare `index.html` da un PDF aggiornato:

```bash
python3 scripts/build_wikipodia.py /percorso/al/podologica.pdf index.html
```
