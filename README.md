# Şirket Büyüme Takibi

companiesmarketcap.com verisini (Market Cap ve Earnings) önceki yıl sonuyla karşılaştırır.

## Bilgisayarda (Python)
    python3 update_data.py
Sonra `docs/index.html` dosyasını çift tıklayın. Ek paket gerekmez. İlk çalıştırma birkaç dakika sürer.

## GitHub'da (otomatik, her gün)
1. Bu klasörün içeriğini yeni bir GitHub deposuna yükleyin (`.github` klasörü dahil).
2. Settings → Pages → Source: "Deploy from a branch", Branch: `main`, klasör: `/docs`.
3. Actions sekmesi → "Veriyi güncelle" → Run workflow (ilk çalıştırma). Sonra her gün 08:00'de kendiliğinden güncellenir.
4. Sayfa: https://KULLANICI.github.io/DEPO/
