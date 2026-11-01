"""Semua pengaturan program di satu tempat: CRS, landmark, jenis jalan, titik hidrasi, dan toleransi."""
from pathlib import Path

# --- CRS ---
SOURCE_CRS = "EPSG:4326"
ANALYSIS_CRS = "EPSG:32749"  # UTM 49S, satuan meter

# --- Cache (hapus folder ini setiap LANDMARKS atau titik hidrasi diubah) ---
CACHE_DIR = Path(__file__).resolve().parent / "cache"

# --- Landmark: kata kunci pencarian OSM, atau (lat, lon) dari Google Maps ---
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
AREA_PADDING_M = 600

# --- Kelas jalan dari tag OSM highway (urutan = prioritas) ---
ROAD_CLASSES = {
    "Jl. raya": ("trunk", "primary", "secondary", "tertiary"),
    "Jl. perumahan": ("residential", "living_street", "unclassified"),
}
OTHER_ROAD_CLASS = "Setapak/servis"
STREET_SEARCH_M = 150

# --- Titik hidrasi permanen ---
OSM_SHOP_KINDS = {
    "convenience": "Minimarket",
    "supermarket": "Supermarket",
    "beverages": "Kedai minuman",
    "coffee": "Kedai minuman",
    "tea": "Kedai minuman",
}
OSM_DRINK_TAGS = {"amenity": "cafe"}
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
