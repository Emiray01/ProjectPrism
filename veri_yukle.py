import pymongo
from google import genai

# --- 1. AYARLAR ---
# DİKKAT: Buraya kendi Gemini API anahtarını yazmalısın!
GEMINI_API_KEY = ""
client = genai.Client(api_key=GEMINI_API_KEY)

# MongoDB Bağlantısı (Senin kusursuz çalışan linkin)
mongo_client = pymongo.MongoClient("")
db = mongo_client["instabot_db"]

# Tablolarımız (Koleksiyonlar)
sirket_db = db["sirket_bilgileri"]
urunler_db = db["urunler"] # RAG (Vektör) araması için ürünleri ayırdık!

# Eski verileri temizle (Üst üste binmesin)
sirket_db.delete_many({})
urunler_db.delete_many({})

# --- 2. GENEL MAĞAZA BİLGİLERİ (Sabit Kurallar) ---
sirket_profili = {
    "_id": "genel_ayarlar",
    "magaza_adi": "Zarif Butik",
    "kargo_bilgisi": "500 TL ve üzeri alışverişlerde kargo ücretsizdir. 500 TL altı siparişlerde kargo ücreti 50 TL'dir. Yurtiçi Kargo ile çalışıyoruz. Kargolar 2 iş günü içinde yola çıkar.",
    "iade_sartlari": "İadelerimiz, ürün tesliminden itibaren 14 gün içinde, ürün kullanılmamış ve etiketi üzerinde olmak şartıyla kabul edilmektedir.",
    "konum": "Aydın / Efeler / Aydın Adnan Menderes Üniversitesi Meslek Yüksekokulu karşısı.",
    "kesin_kurallar": [
        "Müşteriye SADECE aşağıdaki ürün kataloğunda bulunan ürünleri öner.",
        "Katalogda olmayan bir ürün sorulursa: 'Maalesef şu an stoklarımızda sadece listemizdeki ürünler mevcuttur.' de.",
        "Fiyatlar sabittir, kesinlikle indirim veya pazarlık yapma.",
        "Sen bir yapay zeka botusun, ancak çok doğal ve insan gibi konuşmalısın. Gerekirse emoji kullan.",
        "Müşterinin sorusuna en fazla 2-3 cümle ile kısa ve net cevap ver. Destan yazma.",
        "Bilmediğin, mağaza veritabanında olmayan hiçbir soruya kendi kendine cevap uydurma. 'Bu konuda net bir bilgim yok, dilerseniz sizi insan temsilcimize aktarayım.' de."
    ]
}
sirket_db.insert_one(sirket_profili)
print("✅ Genel mağaza bilgileri ve kurallar kaydedildi.")

# --- 3. ÜRÜNLER VE EMBEDDING (Vektör) İŞLEMİ ---
urun_katalogu = [
    {"isim": "Siyah Basic Oversize Tişört", "fiyat": "250 TL", "bedenler": ["S", "M", "L", "XL"], "stok": "Var"},
    {"isim": "Mavi İspanyol Paça Kot Pantolon", "fiyat": "600 TL", "bedenler": ["30", "32", "34", "36"], "stok": "Var"},
    {"isim": "Kırmızı Çiçekli Yazlık Elbise", "fiyat": "450 TL", "bedenler": ["S", "M"], "stok": "Tükendi - Haftaya gelecek"}
]

print("⏳ Ürünler vektöre (embedding) çevriliyor, bu birkaç saniye sürebilir...")

for urun in urun_katalogu:
    # Yapay zekanın arama yaparken anlayacağı formatta bir metin oluşturuyoruz
    urun_metni = f"Ürün: {urun['isim']}, Fiyat: {urun['fiyat']}, Bedenler: {', '.join(urun['bedenler'])}, Stok Durumu: {urun['stok']}"
    
    # Gemini'dan bu metnin vektör karşılığını (koordinatlarını) alıyoruz
    result = client.models.embed_content(
        model="models/gemini-embedding-001",
        contents=urun_metni
    )
    vektor = result.embeddings[0].values
    
    # Vektörü ürüne ekleyip yepyeni 'urunler' tablosuna kaydediyoruz
    urun["embedding"] = vektor
    urun["arama_metni"] = urun_metni # Ne olur ne olmaz, düz metni de tutalım
    
    urunler_db.insert_one(urun)
    print(f"🪄 '{urun['isim']}' başarıyla vektörlenip buluta eklendi!")

print("🚀 BÜTÜN İŞLEMLER TAMAM! Veritabanı yapay zeka sistemine %100 hazır.")