# Tasarım: asset-provenance-toolkit ilk kullanım ve README yenilemesi (30 Eylül 2026)

## Hedef

Videodan ya da profilden gelen biri ilk dakikada şunu yapabilmeli: aracın ne yaptığını tek cümlede anlamak, tek komutla kurmak, gerçek bir dosyaya kayıt yazıp geri okumak; yanlış yazarsa doğrusunu ekranda görmek. Çekirdek davranış (kayıt şeması `schema_version: 1`, dört backend, dosya içine yazma, atomik yazma, çıkış kodları, `verify --json` sözleşmesi) değişmedi; sürüm numarası artmadı (0.1.0).

## Önce / sonra

| Konu | Önce | Sonra |
|---|---|---|
| README ilk ekranı | banner, uzun iki cümlelik tanım, reel (GIF + "sesli MP4"), elle üretilmiş demo GIF, "Why", "What it does"; kurulum "Quickstart"ta klon gerektiriyordu | banner, tek cümle, üç satırlık `uv tool install` + `embed` + `extract`, ölçülmüş kurulum süreleri, 24 sn gerçek çıktılı terminal demosu, "ne zaman kullanılır / kullanılmaz" tablosu, sonra eski gövde |
| Demo | üreticisi depoda olmayan `assets/demo.gif` ve `docs/reel/*` | `scripts/demo-uret.py`: 9 komut gerçekten koşulur, `docs/demo/komutlar.txt` kayıttır, sayfa o kaydı yazma animasyonuyla oynatır; `demo-kayit.js` mp4/gif alır. Dosyalar `kanca` oyununun iki gerçek varlığı |
| Klasöre `embed`/`verify` | `<klasor>.provenance.json` yazar, `verify` **OK** der | `error: ... is a directory, not a file`, hiçbir şey yazılmaz |
| Salt okunur dosya (Windows) | ham `[WinError 5] ... .aprov-tmp -> ...` ve geride kalan geçici dosya | `error: dosya: permission denied - is it read-only ...`; geçici dosya temizlenir |
| Boş `--capability`/`--provider` | sessizce kabul | kullanım hatası (çıkış 2) |
| `--help` | tek satır açıklama, açıklamasız bayraklar | ne yaptığı, "kanıt değildir" uyarısı, örnek, çıkış kodları; her alt komutta örnek ve bayrak açıklamaları |
| Eksik/yanlış argüman | `required: ...` | aynı satır + `hint:` ile yazılacak komut (çıkış kodu 2 aynı) |
| Bozuk sidecar | dosya adı yok | `<dosya>.provenance.json` adı hatada |
| `from-job` şemasız URL | httpx iç mesajı | istek atmadan `--gateway-url must start with http:// or https://` |
| sidecar `embed` çıktısı | `(sidecar backend)` | `(sidecar backend: <dosya>.provenance.json)` |
| Test | 164 (155 geçti + 9 atlandı, Windows) | 196 (187 + 9): +32, hepsi `tests/test_ilk_kullanim.py` (klasör, kullanım hatası ve ipucu, `--help`, sidecar, geçici dosya temizliği, `from-job` şeması, README'deki her `aprov` komutu) |

## CLI akışı

```
kur                  uv tool install git+https://github.com/Furkiozknn/asset-provenance-toolkit
                     (ya da hiç kurmadan: uvx --from git+... aprov ...)
yaz                  aprov embed cover.png --capability image-generate --provider flux-2 --params '{...}'
oku                  aprov extract cover.png            aprov verify cover.png   (çıkış 0/1, --json)
temizle              aprov strip cover.png
yanlış komut         hata satırı + hint:, çıkış 2 (kullanım) ya da 1 (dosya/girdi)
```

Kurulum ve ilk sonuç süresi ölçüldü (`DENETIM.md`): `uv tool install` 8,8 s, `uvx` boş önbellekle 13,1 s.

## Görsel dil (video sisteminden alınanlar)

Demo FRK-OS terminal sahnesinde; `mcp-vet` yenilemesindeki sayfanın uyarlanmış hâli (`sosyal/uret/tema.mjs` `klasik`, `sahne.js` terminal tekniği).

| Ne | Nereden | Nerede |
|---|---|---|
| `zemin #0e0d0b`, panel `#14120e`, `yazi #f1ece2`, ilk vurgu `#ffc21a` | `tema.mjs` `klasik.akis` | zemin, panel, metin, sarı `$` isteği / sol çizgi / `hint:` |
| `#ff4d6d` (mercan), `#ff7a1a` (turuncu), `#19d3e6` (camgöbeği) | `tema.mjs` klasik vurgular | yalnızca boyama: `FAIL:`/`error:` mercan, `OK:` camgöbeği, `removed provenance` turuncu |
| `doku: "izgara"` | `tema.mjs` klasik | soluk sabit ızgara (`rgba(241,236,226,.045)`, 48 px) |
| JetBrains Mono | `tema.mjs` `F.jb` | tüm terminal metni; SIL OFL 1.1, `assets/yazi/` (OFL metni yanında) |
| `terminal: "koyu"`, 22 ms/harf, satır satır çıktı | `tema.mjs`, `sahne.js` | `scripts/demo-uret.py` sayfası |

Bilerek alınmayanlar: League Gothic başlık (README'nin görsel başlığı yok; banner profil üreticisinden), geçişler (çıktı okunmalı). `prefers-reduced-motion`'da imleç yanıp sönmesi kapalı.

Kontrast (panel `#14120e` üstünde, WCAG göreli parlaklıktan hesaplandı; `mcp-vet` yenilemesinde aynı renkler için ölçüldü): krem 15,9:1, sönük metin `#b6ae9d` 8,5:1, sarı 11,6:1, mercan 5,8:1, turuncu 7,2:1, camgöbeği 10,3:1; hepsi ≥ 4,5:1.

## Kararlar ve sınırlar

- **Banner değişmedi.** `assets/banner.svg` hesabın banner üreticisinden geliyor; elle değiştirmek üreticinin bir sonraki çıktısında silinir.
- **`assets/demo.gif`, `docs/reel/reel.{gif,mp4}` çıkarıldı**: üreticileri depoda yoktu, yeniden üretilemedi (`DENETIM.md`). Git geçmişinde duruyorlar.
- Demo `kanca`nın gerçek varlıklarını (kopya) etiketler; sesin parametreleri oyunun kendi tarif satırıdır (`tools/ses_uret.gd`). PNG için `--provider godot-4.7 --params '{"scene": "bolum_01"}'` yalnızca oyunun gerçek motor sürümü ve sahne adıdır; `rfxgen` ön ayarı da oyunun tarifinden.
- Kütüphane davranışı: `embed`/`extract`/`strip` bir klasörle `IsADirectoryError` (OSError) verir; CLI bunu zaten `error:` olarak gösteriyordu. Boş `capability` yalnızca CLI'da reddedilir; şema okuma tarafı değişmedi (eski dosyalar okunabilir kalmalı).
- Demo dikey kaydı (1080x1920, sessiz) depoya girmedi; günlük video hattı için `sosyal/medya/projeler/asset-provenance-toolkit/terminal.mp4` altında.
- Sürüm, etiket, PyPI, dizin/awesome-list, Pages, GitHub description/homepage **yapılmadı** (onay kapısı).
