#!/usr/bin/env python3
"""companiesmarketcap.com'dan veriyi çekip docs/index.html üretir.

Kullanım:
    python3 update_data.py                 # ilk 600 şirket, docs/index.html
    python3 update_data.py --pool 800      # havuzu büyüt
    python3 update_data.py --tabs earnings # tek sekme

Ek paket gerekmez (yalnızca standart kütüphane). Sonra docs/index.html dosyasını
çift tıklayarak açın; veri HTML'in içine gömülüdür, tarayıcıda ağ isteği yoktur.
"""
import argparse, html, json, os, re, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

BASE = os.environ.get("CMC_BASE", "https://companiesmarketcap.com")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HERE = os.path.dirname(os.path.abspath(__file__))
SKIP = {"page", "time-machine", "total-marketcap", "de", "fr", "eur", "inr", "gbp",
        "cad", "aud", "nzd", "hkd", "sgd"}
TABS = {
    "marketcap": {
        "list": lambda p: f"{BASE}/" if p == 1 else f"{BASE}/page/{p}/",
        "hist": lambda slug: f"{BASE}/{slug}/marketcap/",
    },
    "earnings": {
        "list": lambda p: (f"{BASE}/most-profitable-companies/" if p == 1
                           else f"{BASE}/most-profitable-companies/page/{p}/"),
        "hist": lambda slug: f"{BASE}/{slug}/earnings/",
    },
}


# ---------------------------------------------------------------- ağ
def get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept": "text/html,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode("utf-8", "replace")
            if "<table" not in text.lower():
                raise RuntimeError("tablo yok (engellenmiş olabilir)")
            return text
        except urllib.error.HTTPError as e:
            last = RuntimeError(f"HTTP {e.code}")
            if e.code in (403, 404):
                time.sleep(1.5 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(2 * (i + 1))
    raise last


# ---------------------------------------------------------------- ayrıştırma
def money(s):
    if s is None:
        return None
    s = s.replace("\xa0", " ").replace("−", "-").strip()
    m = re.match(r"^(-)?\s*\$?\s*(-)?\s*([\d.,]+)\s*(Trillion|Billion|Million|Thousand|T|B|M|K)?", s, re.I)
    if not m:
        return None
    try:
        n = float(m.group(3).replace(",", ""))
    except ValueError:
        return None
    if m.group(4):
        n *= {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}[m.group(4)[0].upper()]
    return -n if (m.group(1) or m.group(2)) else n


def text(fragment):
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " ").strip()


def rows_of(page):
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, re.S | re.I):
        yield tr, re.findall(r"<t[dh]\b([^>]*)>(.*?)</t[dh]>", tr, re.S | re.I)


def parse_list(page):
    out = []
    for tr, cells in rows_of(page):
        if len(cells) < 4:
            continue
        slug = None
        name_idx = None
        for idx, (_, inner) in enumerate(cells):
            for href in re.findall(r'href="([^"]+)"', inner):
                m = re.match(r"^(?:https?://companiesmarketcap\.com)?/([^/?#]+)/", href)
                if m and m.group(1) not in SKIP:
                    slug, name_idx = m.group(1), idx
                    break
            if slug:
                break
        if not slug or name_idx + 1 >= len(cells):
            continue
        attrs, inner = cells[name_idx + 1]
        value = money(text(inner))
        ds = re.search(r'data-sort="(-?[\d.]+)"', attrs)
        if ds:
            d = float(ds.group(1))
            if value is None or abs(d - value) <= abs(value) * 0.02:
                value = d
        if value is None:
            continue
        rank = None
        m = re.search(r'class="[^"]*rank-td[^"]*"[^>]*>(.*?)</td>', tr, re.S)
        if m and text(m.group(1)).isdigit():
            rank = int(text(m.group(1)))
        else:
            for _, c in cells[:3]:
                if text(c).isdigit():
                    rank = int(text(c))
                    break
        nm = re.search(r'class="[^"]*company-name[^"]*"[^>]*>(.*?)</', tr, re.S)
        cd = re.search(r'class="[^"]*company-code[^"]*"[^>]*>(.*?)</', tr, re.S)
        out.append({
            "rank": rank, "slug": slug,
            "name": text(nm.group(1)) if nm else text(cells[name_idx][1]),
            "code": text(cd.group(1)) if cd else "",
            "country": text(cells[-1][1]),
            "value": value,
        })
    return out


def parse_history(page):
    out = {}
    for _, cells in rows_of(page):
        if len(cells) < 2:
            continue
        y = re.match(r"^(\d{4})\b", text(cells[0][1]))
        v = money(text(cells[1][1]))
        if y and v is not None and y.group(1) not in out:
            out[y.group(1)] = v
    return out


# ---------------------------------------------------------------- ana akış
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=int, default=600)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tabs", default="marketcap,earnings")
    ap.add_argument("--out", default=os.path.join(HERE, "docs"))
    a = ap.parse_args()

    year = datetime.now().year
    cache_path = os.path.join(HERE, "prior_cache.json")
    try:
        cache = json.load(open(cache_path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        cache = {}
    result = {"year": year, "updated": datetime.now(timezone.utc).isoformat(), "tabs": {}}

    for tab in [t for t in a.tabs.split(",") if t in TABS]:
        pages = -(-a.pool // 100)
        print(f"[{tab}] liste sayfaları çekiliyor ({pages})…", flush=True)
        seen, rows = set(), []
        for p in range(1, pages + 1):
            try:
                for r in parse_list(get(TABS[tab]["list"](p))):
                    if r["slug"] not in seen:
                        seen.add(r["slug"])
                        rows.append(r)
            except Exception as e:  # noqa: BLE001
                print(f"  sayfa {p} alınamadı: {e}", file=sys.stderr)
            time.sleep(0.5)
        if not rows:
            sys.exit(f"[{tab}] liste alınamadı; site isteği reddetmiş olabilir.")
        for i, r in enumerate(rows):
            if r["rank"] is None:
                r["rank"] = i + 1
        rows.sort(key=lambda r: r["rank"])
        rows = rows[:a.pool]
        print(f"[{tab}] {len(rows)} şirket; önceki yıl ({year - 1}) verileri çekiliyor…", flush=True)

        def work(r, tab=tab):
            key = f"{tab}:{r['slug']}:{year - 1}"
            c = cache.get(key)
            if c and c.get("s") == "ok":
                r["priorState"], r["priorVal"] = "ok", c["v"]
                return
            try:
                h = parse_history(get(TABS[tab]["hist"](r["slug"])))
                if not h:
                    raise RuntimeError("yıllık tablo yok")
                if str(year - 1) in h:
                    r["priorState"], r["priorVal"] = "ok", h[str(year - 1)]
                    cache[key] = {"s": "ok", "v": h[str(year - 1)]}
                else:
                    r["priorState"], r["priorVal"] = "missing", None
            except Exception as e:  # noqa: BLE001
                r["priorState"], r["priorVal"] = "error", None
                print(f"  {r['slug']}: {e}", file=sys.stderr)
            time.sleep(0.15)

        with ThreadPoolExecutor(a.workers) as ex:
            for n, _ in enumerate(ex.map(work, rows), 1):
                if n % 50 == 0:
                    print(f"  {n}/{len(rows)}", flush=True)
        errs = sum(r["priorState"] == "error" for r in rows)
        print(f"[{tab}] bitti. hata: {errs}")
        if errs > len(rows) * 0.5:
            sys.exit(f"[{tab}] şirketlerin yarısından fazlası alınamadı; yayınlanmadı.")
        result["tabs"][tab] = {"rows": rows}
        json.dump(cache, open(cache_path, "w", encoding="utf-8"))

    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    blob = json.dumps(result, ensure_ascii=False).replace("</", "<\\/")
    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, "index.html"), "w", encoding="utf-8").write(
        tpl.replace("/*__DATA__*/null", blob))
    open(os.path.join(a.out, "data.json"), "w", encoding="utf-8").write(
        json.dumps(result, ensure_ascii=False))
    print("Hazır:", os.path.join(a.out, "index.html"))


if __name__ == "__main__":
    main()
