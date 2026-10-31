# Generator Rute Lari Anti-Haus (Citraland Surabaya)

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

Kontrol: W/A/S/D gerak pelari, H hitung jarak ke titik hidrasi, R reset pelari, scroll = zoom, drag = geser peta, 0 = reset zoom, Esc keluar.

Panel kanan berurutan sesuai alur: 1. Atur rute, 2. Hasil, 3. Skenario tutup titik, 4. Demo pelari, lalu Tambahan (mode zona). Legenda ada di tombol pojok kanan bawah peta.

Kalau pelari keluar dari rute anjuran, jejaknya muncul (magenta putus-putus) dan rute anti-haus baru dihitung ulang dari posisi pelari ke titik akhir (kuning), seperti Google Maps. Kalau pelari di luar zona, rute baru mengarah ke zona terdekat dulu. Tabel Hasil membandingkan jejak + rute baru dengan rute awal. Bolak-balik di ruas yang sama tidak menambah panjang jejak. Jalan digambar sesuai kelas OSM: jalan raya tebal, jalan perumahan tipis, setapak/servis putus-putus.

Tombol "Zona" mengganti cara ukur toleransi: Radius (buffer lingkaran) atau Lewat jalan (jarak menyusuri jalan dari titik hidrasi). Saat peta di-zoom, nama titik hidrasi dan nama jalan ikut ditampilkan.

Data OSM sudah ada di `afl2_rute/cache/`, jadi tidak perlu internet. Hapus folder itu jika landmark/titik hidrasi di `afl2_rute/config.py` diubah.
