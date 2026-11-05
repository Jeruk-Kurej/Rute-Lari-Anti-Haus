"""Semua pengaturan program di satu tempat: area, CRS, landmark, jenis jalan, titik hidrasi, pencarian, dan toleransi."""
from pathlib import Path

# --- Area dan CRS ---
AREA_PLACE = "Surabaya, Indonesia"  # seluruh kota diunduh sekali dari OSM lalu disimpan di cache
SOURCE_CRS = "EPSG:4326"
ANALYSIS_CRS = "EPSG:32749"  # UTM 49S, satuan meter

# --- Cache (data OSM hasil unduhan; jangan dihapus, titik/landmark baru di bawah tetap terbaca) ---
CACHE_DIR = Path(__file__).resolve().parent / "cache"

# --- Landmark favorit: muncul paling atas di pencarian. Kata kunci OSM, atau (lat, lon) dari Google Maps ---
LANDMARKS = {
    "UC": "Universitas Ciputra Surabaya",
    "G-Walk": "Gwalk Citraland Surabaya",
    "JJ Lake": (-7.2977668, 112.6492071),
    "Patung Singapore": (-7.2967084, 112.6515294),
    "Bukit Golf": "Bukit Golf Citraland Surabaya",
    "Pasar Modern TPR": "Pasar Modern Citraland",
    "Taman Puspa Raya": (-7.276653, 112.642786),
    "Citraland Utara": (-7.2601695, 112.633441),
}
DEFAULT_STOPS = ("UC", "G-Walk")  # titik awal dan akhir saat program dibuka

# --- Tempat yang bisa dicari: tag OSM -> nama jenis yang tampil di hasil pencarian ---
PLACE_TAGS = {
    "amenity": ["university", "college", "school", "hospital", "clinic", "place_of_worship", "marketplace",
                "restaurant", "cafe", "fast_food", "fuel", "bank", "police", "townhall", "library", "cinema",
                "bus_station", "community_centre"],
    "leisure": ["park", "stadium", "sports_centre", "golf_course", "garden", "fitness_centre", "playground"],
    "tourism": ["attraction", "museum", "hotel", "viewpoint", "zoo", "theme_park"],
    "shop": ["mall", "department_store", "supermarket", "convenience"],
    "place": ["suburb", "neighbourhood", "quarter", "village"],
    "railway": ["station"],
}
PLACE_KINDS = {
    "university": "Kampus", "college": "Kampus", "school": "Sekolah", "hospital": "Rumah sakit", "clinic": "Klinik",
    "place_of_worship": "Tempat ibadah", "marketplace": "Pasar", "restaurant": "Restoran", "cafe": "Kafe",
    "fast_food": "Restoran", "fuel": "SPBU", "bank": "Bank", "police": "Kantor polisi", "townhall": "Kantor pemerintah",
    "library": "Perpustakaan", "cinema": "Bioskop", "bus_station": "Terminal", "community_centre": "Balai warga",
    "park": "Taman", "stadium": "Stadion", "sports_centre": "Olahraga", "golf_course": "Lapangan golf",
    "garden": "Taman", "fitness_centre": "Olahraga", "playground": "Taman bermain", "attraction": "Wisata",
    "museum": "Museum", "hotel": "Hotel", "viewpoint": "Wisata", "zoo": "Wisata", "theme_park": "Wisata",
    "mall": "Mal", "department_store": "Mal", "supermarket": "Supermarket", "convenience": "Minimarket",
    "suburb": "Kawasan", "neighbourhood": "Kawasan", "quarter": "Kawasan", "village": "Kelurahan", "station": "Stasiun",
}
SEARCH_RESULTS = 7
SEARCH_MIN_CHARS = 2

# --- Kelas jalan dari tag OSM highway (urutan = prioritas) ---
ROAD_CLASSES = {
    "Jl. raya": ("trunk", "primary", "secondary", "tertiary"),
    "Jl. perumahan": ("residential", "living_street", "unclassified"),
}
OTHER_ROAD_CLASS = "Setapak/servis"
STREET_SEARCH_M = 150

# --- Titik hidrasi permanen ---
OSM_HYDRATION_TAGS = {"shop": ["convenience", "supermarket", "beverages", "coffee", "tea"], "amenity": "cafe"}
OSM_SHOP_KINDS = {
    "convenience": "Minimarket",
    "supermarket": "Supermarket",
    "beverages": "Kedai minuman",
    "coffee": "Kedai minuman",
    "tea": "Kedai minuman",
}
DUPLICATE_RADIUS_M = 50
MANUAL_POINTS = {
    "Indomaret Sentra Niaga": ("Minimarket", (-7.2919116, 112.6353231)),
    "Alfamart Sentra Niaga": ("Minimarket", (-7.2915148, 112.6353466)),
    "Alfamart North Junction": ("Minimarket", (-7.2794595, 112.6457160)),
    "Alfamidi Puri Sentra": ("Minimarket", (-7.2844910, 112.6472174)),
    "Fore Coffee G-Walk": ("Kedai minuman", (-7.2924440, 112.6542076)),
    "Chatime Ruko G-Walk": ("Kedai minuman", (-7.2884249, 112.6555929)),
    "Kopi Kenangan Ruko G-Walk": ("Kedai minuman", (-7.2963842, 112.6543427)),
    "Fore Coffee Bukit Palma": ("Kedai minuman", (-7.2617827, 112.6346938)),
    "Alfamart Raya Beringin": ("Minimarket", (-7.2596574, 112.6471561)),
    "Indomaret Bringin": ("Minimarket", (-7.2589510, 112.6477580)),
    "Alfamart Dukuh Bungkal": ("Minimarket", (-7.2759774, 112.6530311)),
    "Alfamart Raya Jelidro": ("Minimarket", (-7.2669862, 112.6562715)),
    "Indomaret Sambikerep": ("Minimarket", (-7.2678572, 112.6555185)),
}

# --- Analisis ---
DEFAULT_TOLERANCE_M = 550
ZONE_MODES = ("Radius", "Lewat jalan")
TOLERANCE_STEP_M = 25
TOLERANCE_SEARCH_M = range(50, 1501, TOLERANCE_STEP_M)
SAMPLE_STEP_M = 10
CORRIDOR_PADDING_M = 2000  # zona hanya dihitung di kotak sekitar titik rute, ditambah jarak ini
MAX_STOPS = 5  # stop di antara titik awal dan akhir
ROUTE_OPTIONS = 3  # rute anti-haus utama + alternatif
ALTERNATIVE_PENALTY = 1.6  # ruas rute sebelumnya dibuat "lebih panjang" segini supaya alternatif lewat jalan lain
ALTERNATIVE_MAX_RATIO = 1.4  # alternatif yang lebih panjang dari ini (dibanding rute utama) tidak ditampilkan
ALTERNATIVE_MIN_NEW = 0.25  # alternatif harus punya minimal 25% jalan yang berbeda
ON_ROUTE_M = 60  # titik hidrasi sedekat ini dari rute dihitung sebagai "pos minum" di rute
NEAREST_COUNT = 5  # jumlah titik hidrasi terdekat yang ditampilkan untuk pelari
NEAREST_SEARCH_M = 5000  # titik hidrasi lebih jauh dari ini (lewat jalan) tidak dicari
