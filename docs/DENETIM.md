# Denetim: asset-provenance-toolkit (30 Eylül 2026)

Yenilemeden önce `main` (0.1.0, `0e187b2`) üzerinde, bu makinede (Windows 11, Python 3.12.14, uv 0.12.5, Git Bash) ölçüldü. Ölçülmeyen bir şey yazılmadı. Ham çıktılar depo dışında: `kanit/asset-provenance-toolkit/{once,sonra}/` (aynı 18 komut, iki sürüme karşı: `olc.py`). Denenen dosyalar `kanca` oyununun gerçek varlıklarının kopyaları (`docs/ekran/bolum_01.png`, `assets/audio/kanca_at.wav`, `873e573`); kanca deposuna yazılmadı.

## Temiz ortamda kurulum ve ilk sonuç

Her satır boş uv önbelleği / boş venv ile koşuldu (`docs/demo/kurulum.txt`).

| Yol | Süre | Sonuç |
|---|---|---|
| `uvx --from git+https://github.com/Furkiozknn/asset-provenance-toolkit aprov --version` (boş önbellek) | 13,1 s | `aprov 0.1.0` |
| aynısı, önbellek sıcak | 2,4 s | aynı |
| `uv tool install git+...` (izole `UV_TOOL_DIR`, boş önbellek) | 8,8 s; sonra `aprov --version` 0,9 s | `aprov 0.1.0` |
| `python -m venv` + `pip install git+...` | 7,3 s + 12,3 s; `aprov --version` 0,6 s | `aprov 0.1.0` |
| klon + `uv sync --group dev` (README "Quickstart") | ~4,5 s (uv önbelleği sıcaktı) | çalışıyor |

"Tek komutla kur, bir dakikada ilk sonuç" tutuyor: `uv tool install` + ilk `embed` + `extract` ~11 s. Kurulum süresi GitHub'a ve önbelleğe bağlı.

## README komutları

Klon yolundaki (`uv sync`, `uv run python -c "from PIL ..."`, `uv run aprov embed/extract/verify`), CLI kullanımındaki (`embed` PNG/JPEG/MP4, `extract`, `verify --json`, `strip`, `from-job`) komutların hepsi çalışıyor; bayraklar `--help`'te var (artık bir testle korunuyor: `tests/test_ilk_kullanim.py`, README'deki her `aprov ...` satırı). Kütüphane örneği çalışıyor. `from-job` gerçek bir ai-job-gateway gerektirdiği için sahte yanıtla testlerde sınanıyor; canlı sunucuyla **ölçülmedi**. `arac/gercek-video-dogrula.py` ffmpeg ile koştu: "gercek medya uzerinde her sey tutuyor" (m4a dahil, negatif kontrol dahil).

Sayılar: "164 tests" → koşudan 155 geçti + 9 atlandı = 164 (uyuştu; 9 test POSIX izin bitleri/symlink gerektiriyor, Windows'ta atlanıyor; README bunu söylemiyordu, söylüyor). Sonra: 196 (187 geçti + 9 atlandı, Windows).

## Hata mesajları ve `--help`

Çıkış kodları hep doğruydu. Sorun sözlerdeydi ve iki gerçek hata vardı:

| Girdi | Önce | Sorun |
|---|---|---|
| `aprov embed klasor --capability c --provider p` | `embedded provenance into klasor (sidecar backend)`, çıkış 0; yanına `klasor.provenance.json` yazıldı | **Hata.** Klasör "dosya" sayılıp sidecar yazılıyordu; `aprov verify klasor` sonra **`OK: klasor has provenance`** diyordu |
| salt okunur dosyaya `embed` (Windows) | `error: [WinError 5] Erişim engellendi: '...\.salt-okunur.png.cnszjor9.aprov-tmp' -> '...\salt-okunur.png'` | **Hata.** Hem iç geçici dosya adı kullanıcıya gösteriliyordu hem de geçici dosya **klasörde kalıyordu** (salt okunur biti geçici dosyaya kopyalanıyor, Windows onu silemiyor) |
| `--capability ''` | kabul edildi, boş kayıt yazıldı | sessiz yanlış girdi |
| `aprov embed` / `embed dosya` | `the following arguments are required: ...` | yazılacak komut yok |
| `aprov` (komutsuz) | `required: command` | `--help`'e yönlendirme yok |
| `--help` | tek satır açıklama; `file`, `--capability`, `--provider`, `--job-id`, `--source`, `--source-url` açıklamasız; örnek yok; çıkış kodları yok | ilk kullanıcı çıkış kodlarını README'den bulmak zorunda |
| bozuk `<dosya>.provenance.json` | `error: provenance data is not valid JSON: ...` | hangi dosya olduğu yazmıyor (kullanıcı `kanca_at.wav`'a bakmıştı, sorun yandaki `.json`'da) |
| `from-job --gateway-url localhost:9` | `UnsupportedProtocol: Request URL is missing an 'http://' or 'https://' protocol.` | httpx'in iç mesajı |
| `--params {bozuk` | `must be valid JSON: ...` | tırnaklama ipucu yok |
| sidecar `embed` çıktısı | `(sidecar backend)` | sidecar dosyasının adı yok |

Önce/sonra metinleri: `kanit/asset-provenance-toolkit/once/komutlar.txt`, `sonra/komutlar.txt`.

## README bulguları

- `assets/demo.gif` ("Real output") ve `docs/reel/reel.{gif,mp4}` ("15 saniyelik reel", "sesli MP4") için **üretici depoda yok**: yeniden üretilemedi, README'den ve depodan çıkarıldı (git geçmişinde duruyor). Yerine `scripts/demo-uret.py` ile gerçek çıktıdan üretilen demo geldi.
- Sıra: banner → 2 paragraf uzun tanım → reel → GIF → "Why" → "What it does" → "Quickstart" (klon gerektiriyordu, `uv tool install` sonra ve başka bir bölümdeydi). İlk ekranda kurulum komutu yoktu.
- Kurulum bölümü "Not on PyPI yet, so it runs from a clone" diyordu; `uv tool install git+...` ile klonsuz kurulum zaten çalışıyordu (ölçüldü).
- `assets/banner.svg` profil deposundaki üreticiden geliyor; bu depoda değiştirilmedi. `assets/backends.svg` ve `assets/c2pa.svg` çıktı iddiası taşımayan açıklama çizimleri; dokunulmadı.
- "Error" örneği bloğundaki `from-job ... Connection refused [Errno 111]` Linux'a özgü metindi; yerine bu makinede çıkan gerçek çıktılar kondu.

## Testler ve CI

Önce: 155 geçti, 9 atlandı, 2,8 s (Windows). CI: `ci.yml` (3 sürüm matrisi 3.11-3.13, `paket`, `gercek-video`) ve `yayinla.yml`. Sonra: Windows'ta 187 geçti + 9 atlandı; PR #19'daki CI (Linux, 3.11/3.12/3.13) her sürümde `196 passed`, `paket`, `gercek-video` ve CodeQL yeşil. Dal sürümünün kurulumu (`@yenileme/arayuz`) aynı yöntemle ölçüldü: `uvx` 11,6 s / 3,1 s, `uv tool install` 11,1 s (`kanit/.../sonra/kurulum.txt`); fark ağ değişkenliği, ek bağımlılık yok.

## Günlük "Ekosistem denetimi" (#19, profil deposu)

Bu depoya ait açık bulgular (28 Eylül denetimi) yalnızca profil deposundaki meta-source ayrışmasının parçaları: test sayısı (`project-meta.json` 164 ↔ `meta-source.json` 125), `summary` ↔ depo `description`, `topics` (dosyada 14, depoda 11). Furki'nin kararı beklendiği için (`/meta` birleşmiş içeriği geri alır) **kapatılmadı**; bu dalda `project-meta.json`'a yalnızca gerçekten değişen alanlar (medya yolu, test sayısı) işlendi.

## Çözülmeyenler

- `from-job` canlı bir ai-job-gateway ile denenmedi (ölçülmedi).
- WebM/Matroska hâlâ yalnız sidecar (bilinen sınır, README'de yazılı).
- Windows'ta salt okunur bir dosyaya yazmak bilerek reddediliyor (POSIX'te aynı dosya yeniden adlandırma yoluyla güncellenip modu korunuyor); ikisi de artık anlaşılır bir mesajla ya da başarıyla bitiyor, davranış farkı olduğu gibi bırakıldı.
- `project-meta.json` özeti/`meta-source.json` ve GitHub `description` bayat olabilir; dokunulmadı.
