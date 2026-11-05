# Generator Rute Lari Anti-Haus (Surabaya)

Butuh Python 3.10+.

macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Windows (PowerShell):
```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Saat program terbuka, panduan "Cara pakai" muncul otomatis (bisa dibuka lagi lewat tombol "? Bantuan").

Kontrol: W/A/S/D gerak pelari, H daftar titik hidrasi terdekat, R reset pelari, / langsung ke pencarian, scroll = zoom, drag = geser peta, 0 = kembali ke rute, Esc keluar.

Peta mencakup seluruh Surabaya dan jendela bisa diperbesar. Panel kiri dibaca dari atas ke bawah seperti Google Maps:

1. **Mau lari dari mana ke mana?** Klik kotak A (mulai) atau B (tujuan), ketik nama tempat (kampus, mal, taman, nama jalan, atau landmark favorit di `config.py`), lalu pilih hasilnya. "Tambah tempat singgah" menambah tempat yang mau dilewati (urutannya bisa diubah dengan tombol panah), "Kembali ke awal" membuat rute kembali ke titik mulai. Kalau tempat tidak ada di peta, tekan Enter untuk mencari lewat internet.
2. **Seberapa jauh boleh dari tempat minum?** Jarak maksimal rute ke minimarket/kedai minuman (toleransi). "Cari jarak terkecil" mencari angka terkecil yang masih menghasilkan rute.
3. **Hasil:** panjang rute aman minum (garis biru) dibandingkan dengan rute tercepat (garis oranye), plus pilihan rute alternatif.
4. **Tempat minum di rute** (toko yang dilewati dan jarak terpanjang tanpa toko) atau **Simulasi lari** (5 tempat minum terdekat lewat jalan dari titik ungu).
5. **Ukur jarak ke tempat minum:** Garis lurus (buffer lingkaran) atau Lewat jalan. Klik ikon tempat minum di peta untuk menandainya tutup.

Legenda warna selalu tampil di pojok kiri bawah peta; tombol zoom dan "kembali ke rute" ada di kanan atas.

Zona aman hanya dihitung di kotak sekitar rute (garis putus-putus di peta) supaya tetap cepat untuk satu kota. Saat peta di-zoom jauh, jalan kecil, bangunan, dan nama disembunyikan.

Kalau pelari keluar dari rute anjuran, jejaknya muncul (magenta putus-putus) dan rute anti-haus baru dihitung ulang dari posisi pelari ke stop berikutnya (kuning), seperti Google Maps. Kalau pelari di luar zona, rute baru mengarah ke zona terdekat dulu. Tabel Hasil membandingkan jejak + rute baru dengan rute awal. Jalan digambar sesuai kelas OSM: jalan raya tebal, jalan perumahan tipis, setapak/servis putus-putus.

Tombol "Zona" mengganti cara ukur toleransi: Radius (buffer lingkaran) atau Lewat jalan (jarak menyusuri jalan dari titik hidrasi). Klik ikon titik hidrasi di peta untuk menutup/membukanya.

## Struktur kode (`afl2_rute/`)

| File | Isi |
|---|---|
| `config.py` | Semua pengaturan: area, CRS, landmark favorit, tag tempat yang bisa dicari, jenis jalan, titik hidrasi manual, toleransi |
| `data.py` | Muat data satu kota dari OSM/cache: jalan, titik hidrasi, tempat untuk pencarian, landmark, bangunan; toko dan stop dijadikan node di ruas jalan terdekat |
| `search.py` | Kelas `PlaceIndex`: pencarian tempat dari data lokal, atau online (geocoding OSM) |
| `network.py` | Kelas `RoadNetwork`: graph jalan, memecah ruas, node sementara untuk jarak terdekat |
| `zones.py` | Kelas `Zone` dengan turunan `RadiusZone` (buffer) dan `RoadZone` (lewat jalan) |
| `analysis.py` | Kelas `RoutePlanner`: zona per area rute, rute terpendek vs anti-haus lewat stop, rute alternatif, pos minum, rute ulang, daftar titik hidrasi terdekat |
| `runner.py` | Kelas `Runner`: pelari virtual W/A/S/D |
| `render.py`, `widgets.py` | Menggambar peta (dengan level of detail), tombol, dan kotak ketik |
| `panel.py`, `game.py`, `main.py` | Panel kiri, aplikasi utama (jendela bisa diubah ukurannya), dan pintu masuk |
| `fonts.py` | Memuat font Avenir Next di macOS (font sistem biasa di komputer lain) |

Menambah jenis zona baru: buat kelas turunan `Zone` di `zones.py` dengan method `build()`, lalu daftarkan namanya di `ZONE_MODES` (config) dan di `make_zones` (zones).

Data OSM seluruh Surabaya sudah ada di `afl2_rute/cache/`, jadi tidak perlu internet (kecuali pencarian online). Kalau sebuah file cache tidak ada, file itu diunduh ulang dari OSM sekali (jalan sekitar 2–3 menit). Bangunan (`bangunan.gpkg`) hanya hiasan peta untuk area Citraland dan opsional: data bangunan satu kota terlalu besar. Titik hidrasi manual dan landmark berkoordinat `(lat, lon)` yang ditambah di `afl2_rute/config.py` langsung terbaca tanpa menghapus cache.
