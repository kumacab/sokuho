"""Page « Reels à publier » (servie par GitHub Pages, pensée pour le téléphone).

Pour chaque reel : aperçu vidéo, bouton de téléchargement, son à chercher dans Instagram,
légende à copier. Les reels non publiés à la main partent automatiquement avec un jingle.
"""
import html
from datetime import datetime
from zoneinfo import ZoneInfo


def build(reels, brand, tz, timeout_hours=3):
    cards = []
    for r in sorted(reels, key=lambda x: -x["ts"]):
        when = datetime.fromtimestamp(r["ts"], ZoneInfo(tz))
        deadline = datetime.fromtimestamp(r["ts"] + timeout_hours * 3600, ZoneInfo(tz))
        video = "../" + r["video"]
        cards.append(f"""
<article class="card" data-id="{html.escape(r['id'])}">
  <video src="{html.escape(video)}" controls playsinline preload="metadata" poster="../{html.escape(r['cover'])}"></video>
  <div class="body">
    <p class="meta">Préparé le {when:%d/%m à %Hh%M} · publié automatiquement avec un jingle à {deadline:%Hh%M} si tu ne l'as pas fait</p>
    <h2>{html.escape(r['headline'])}</h2>
    <a class="btn primary" href="{html.escape(video)}" download>1 · Télécharger la vidéo</a>
    <div class="row">
      <span class="label">2 · Son à chercher dans Instagram</span>
      <code>{html.escape(r['sound'])}</code>
      <button class="btn" data-copy="{html.escape(r['sound'])}">Copier</button>
    </div>
    <div class="row">
      <span class="label">3 · Légende</span>
      <textarea readonly>{html.escape(r['caption'])}</textarea>
      <button class="btn" data-copy-from="prev">Copier la légende</button>
    </div>
    <label class="done"><input type="checkbox"> Je l'ai publié</label>
  </div>
</article>""")
    body = "\n".join(cards) or '<p class="empty">Aucun reel en attente. Le robot en prépare un toutes les deux actus.</p>'
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Reels à publier · {html.escape(brand['name'])}</title>
<style>
:root{{--bg:#0d0d12;--card:#17171f;--ink:#f5f3ee;--muted:#a8a8b4;--red:#e63946;--yellow:#ffd10a}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
header{{position:sticky;top:0;background:var(--bg);padding:14px 16px;border-bottom:1px solid #26262f;z-index:2}}
header b{{background:var(--red);padding:2px 8px;border-radius:6px;margin-right:6px}}
header p{{margin:6px 0 0;color:var(--muted);font-size:14px}}
main{{max-width:560px;margin:0 auto;padding:16px}}
.card{{background:var(--card);border-radius:16px;overflow:hidden;margin-bottom:20px}}
.card.is-done{{opacity:.45}}
video{{width:100%;display:block;background:#000;aspect-ratio:9/16;max-height:70vh}}
.body{{padding:14px}} h2{{font-size:18px;margin:4px 0 12px}} .meta{{color:var(--muted);font-size:13px;margin:0}}
.row{{margin-top:12px;display:flex;flex-direction:column;gap:6px}} .label{{font-weight:600;font-size:14px}}
code{{background:#0d0d12;padding:8px 10px;border-radius:8px;color:var(--yellow);font-size:15px}}
textarea{{width:100%;min-height:130px;background:#0d0d12;color:var(--ink);border:1px solid #2c2c36;border-radius:8px;padding:8px;font:inherit;font-size:14px}}
.btn{{display:block;text-align:center;border:0;border-radius:10px;padding:12px;font:600 15px system-ui;background:#2c2c36;color:var(--ink);text-decoration:none;cursor:pointer}}
.btn.primary{{background:var(--yellow);color:#0d0d12}} .btn.ok{{background:#2d6a4f}}
.done{{display:flex;gap:8px;align-items:center;margin-top:14px;color:var(--muted)}}
.empty{{color:var(--muted);text-align:center;padding:40px 0}}
</style></head><body>
<header><b>速報</b><strong>Reels à publier</strong>
<p>Télécharge la vidéo → dans Instagram « Ajouter un son » avec le nom indiqué → colle la légende → publie.</p></header>
<main>{body}</main>
<script>
document.addEventListener('click', async e => {{
  const b = e.target.closest('button'); if (!b) return;
  const text = b.dataset.copy ?? b.previousElementSibling.value;
  try {{ await navigator.clipboard.writeText(text); }} catch (_) {{
    const t = document.createElement('textarea'); t.value = text; document.body.append(t); t.select();
    document.execCommand('copy'); t.remove(); }}
  const old = b.textContent; b.textContent = 'Copié ✓'; b.classList.add('ok');
  setTimeout(() => {{ b.textContent = old; b.classList.remove('ok'); }}, 1500);
}});
const KEY = 'sokuho-reels-done';
let done = []; try {{ done = JSON.parse(localStorage.getItem(KEY) || '[]'); }} catch (_) {{}}
document.querySelectorAll('.card').forEach(c => {{
  const box = c.querySelector('.done input'); box.checked = done.includes(c.dataset.id);
  c.classList.toggle('is-done', box.checked);
  box.addEventListener('change', () => {{
    done = box.checked ? [...new Set([...done, c.dataset.id])] : done.filter(x => x !== c.dataset.id);
    try {{ localStorage.setItem(KEY, JSON.stringify(done)); }} catch (_) {{}}
    c.classList.toggle('is-done', box.checked);
  }});
}});
</script></body></html>
"""
