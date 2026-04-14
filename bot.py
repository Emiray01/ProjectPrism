import os
import time
import json
import random
from datetime import datetime
from dotenv import load_dotenv
from instagrapi import Client
import pymongo
import sys
import traceback

# YENİ GOOGLE KÜTÜPHANESİ VE TİPLERİ
from google import genai
from google.genai import types

# .env dosyasındaki verileri yükle
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
INSTA_USER = os.getenv("INSTA_USERNAME")
INSTA_PASS = os.getenv("INSTA_PASSWORD")
MONGO_URI = os.getenv("MONGO_URI")

LOG_FILE = os.path.join(os.path.dirname(__file__), "hata_log.txt")

def log_error(error_code, context, exc=None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    exc_type = type(exc).__name__ if exc else "UnknownError"
    exc_msg = str(exc) if exc else "Detay yok"
    stack = traceback.format_exc().strip() if exc else ""

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{error_code}] [{context}] {exc_type}: {exc_msg}\\n")
            if stack and stack != "NoneType: None":
                f.write(f"TRACEBACK:\\n{stack}\\n")
            f.write("-" * 80 + "\\n")
    except Exception:
        # Log yazımı da hata verirse bot akışını durdurma.
        pass

# --- MONGODB BAĞLANTISI ---
try:
    mongo_client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = mongo_client["instabot_db"]
    mongo_client.server_info() 
    
    sohbetler = db["sohbet_gecmisi"]
    aktif_kullanicilar = db["aktif_kullanicilar"]
    sirket_db = db["sirket_bilgileri"]
    urunler_db = db["urunler"] # YENİ: Ürünler tablosunu bağladık
    print("✅ MongoDB Atlas bağlantısı başarılı!")

except pymongo.errors.ServerSelectionTimeoutError as e:
    log_error("DB_TIMEOUT_001", "MongoDB serverSelectionTimeout", e)
    print("🔴 HATA: MongoDB Atlas servisine ulaşılamıyor!")
    sys.exit() 
except Exception as e:
    log_error("DB_GENERAL_002", "MongoDB initial connection", e)
    print(f"⚠️ Beklenmedik veritabanı hatası: {e}")

sohbetler.create_index("_id")
aktif_kullanicilar.create_index("_id")

# --- ŞİRKET BİLGİLERİNİ VE ÜRÜNLERİ ÇEKME ---
print("[SİSTEM] Şirket bilgileri ve katalog veritabanından çekiliyor...")
sirket_verisi = sirket_db.find_one({"_id": "genel_ayarlar"})

if not sirket_verisi:
    print("🔴 HATA: Şirket bilgileri bulunamadı! Lütfen 'veri_yukle.py' dosyasını çalıştırın.")
    sys.exit()

# YENİ: Ürünleri artık "urunler" isimli yeni tablodan çekiyoruz!
tum_urunler = list(urunler_db.find({}))
urunler_metni = "\n".join([f"- {u['isim']} ({u['fiyat']}) | Bedenler: {', '.join(u['bedenler'])} | Stok: {u['stok']}" for u in tum_urunler])
kurallar_metni = "\n".join([f"{i+1}. {kural}" for i, kural in enumerate(sirket_verisi["kesin_kurallar"])])

# --- ZIRHLI SİSTEM PROMPTU ---
kati_sistem_promptu = f"""
Sen "{sirket_verisi['magaza_adi']}" mağazasının resmi müşteri ilişkileri uzmanısın.
Aşağıda sana verilen MAĞAZA VERİTABANI dışındaki hiçbir bilgiyi kullanamazsın. 

--- KESİN KURALLAR ---
{kurallar_metni}

--- ÜRÜN KATALOĞUMUZ ---
{urunler_metni}

--- KARGO VE İADE BİLGİSİ ---
Kargo: {sirket_verisi['kargo_bilgisi']}
İade: {sirket_verisi['iade_sartlari']}
Konum: {sirket_verisi['konum']}

ÇOK ÖNEMLİ YASAKLAR (HALÜSİNASYON ENGELİ):
1. KESİNLİKLE telefon numarası, e-posta adresi, web sitesi linki veya fiziksel adres UYDURMA.
2. Müşteriyi yetkiliye aktarırken SADECE "Sizi yetkilimize aktarıyorum, lütfen bekleyin." de.
3. EĞER KULLANICI mağaza, ürünler, kargo, iade politikası dışında ALAKASIZ BİR ŞEY SORARSA veya hakaret ederse:
   - "cevap" kısmına KESİNLİKLE sadece şunu yaz: "Maalesef sadece mağazamız ve ürünlerimiz hakkında yardımcı olabilirim."
   - "ihlal_var" değerini "true" yap.

ÖNEMLİ GÖREV (DUYGU ANALİZİ):
Müşterinin mesajını analiz et. Eğer müşteri sinirliyse, şikayetçiyse veya açıkça "yetkiliyle, gerçek biriyle, patronla" görüşmek istiyorsa "insana_aktar" değerini true yap. Normal durumlarda false kalsın.

ÇIKTINI KESİNLİKLE SADECE AŞAĞIDAKİ JSON FORMATINDA VER:
{{
  "cevap": "Müşteriye yazılacak mesaj",
  "insana_aktar": true veya false,
  "ihlal_var": true veya false
}}
"""

# YENİ GOOGLE SDK KURULUMU VE AYARLARI
client = genai.Client(api_key=GEMINI_API_KEY)

ai_config = types.GenerateContentConfig(
    system_instruction=kati_sistem_promptu,
    response_mime_type="application/json",
    temperature=0.3
)

cl = Client()
SESSION_FILE = "insta_session.json"

if os.path.exists(SESSION_FILE):
    cl.load_settings(SESSION_FILE)
    print("[SİSTEM] Mevcut oturum yüklendi.")

try:
    cl.login(INSTA_USER, INSTA_PASS)
    cl.dump_settings(SESSION_FILE)
    print("[SİSTEM] Instagram girişi başarılı!")
    
    PATRON_ID = os.getenv("PATRON_ID")
    print(f"[SİSTEM] İşletme sahibi ID'si ({PATRON_ID}) .env dosyasından çekildi.")
    
except Exception as e:
    log_error("INSTA_LOGIN_003", "Instagram login", e)
    print(f"[SİSTEM HATASI] Giriş yapılamadı: {e}")
    sys.exit()

processed_messages = set()
RAG_RUNTIME_ENABLED = True

def is_valid_incoming(msg, bot_id):
    return str(msg.user_id) != bot_id and msg.text and msg.text.strip() != ""

def update_active_user(msg):
    aktif_kullanicilar.update_one(
        {"_id": str(msg.user_id)},
        {"$set": {"son_islem": time.time(), "isim": getattr(msg, "user_name", "Bilinmiyor")}},
        upsert=True
    )

def get_query_embedding(text):
    try:
        result = client.models.embed_content(
            model="text-embedding-004",
            content=text
        )
        return result.embeddings[0].values
    except Exception as e:
        log_error("RAG_EMBED_011", "Generate embedding", e)
        return None

def retrieve_relevant_products(query_vector, limit=3):
    global RAG_RUNTIME_ENABLED

    if not RAG_RUNTIME_ENABLED:
        return []

    try:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "vector_index",
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": 100,
                    "limit": limit
                }
            }
        ]
        return list(urunler_db.aggregate(pipeline))
    except Exception as e:
        # Özellikle index yoksa her mesajda aynı hatayı almamak için RAG'i geçici kapat.
        RAG_RUNTIME_ENABLED = False
        log_error("RAG_RETRIEVE_012", "Mongo vector search", e)
        return []

def build_rag_context(product_docs):
    if not product_docs:
        return ""

    lines = []
    for doc in product_docs:
        isim = doc.get("isim") or doc.get("urun_adi") or "Bilinmeyen Ürün"
        fiyat = doc.get("fiyat", "Fiyat bilgisi yok")
        aciklama = doc.get("aciklama") or doc.get("detay") or ""
        bedenler = doc.get("bedenler", [])
        stok = doc.get("stok", "Bilinmiyor")

        beden_metin = ", ".join(bedenler) if isinstance(bedenler, list) and bedenler else "Beden bilgisi yok"
        satir = f"- {isim} | Fiyat: {fiyat} | Bedenler: {beden_metin} | Stok: {stok}"
        if aciklama:
            satir += f" | Detay: {aciklama}"
        lines.append(satir)

    return "\n".join(lines)

def generate_reply(sender_id, incoming_text):
    musteri_kaydi = sohbetler.find_one({"_id": sender_id})
    gecmis_mesajlar = musteri_kaydi.get("gecmis", []) if musteri_kaydi else []
    
    # YENİ SDK: Sohbet geçmişini yeni formata dönüştürüyoruz
    formatted_history = []
    for msg in gecmis_mesajlar:
        formatted_history.append(
            types.Content(
                role=msg["role"],
                parts=[types.Part.from_text(text=msg["parts"][0])]
            )
        )

    rag_context = ""
    query_vector = get_query_embedding(incoming_text)
    if query_vector:
        rag_docs = retrieve_relevant_products(query_vector, limit=3)
        rag_context = build_rag_context(rag_docs)

    final_input_text = incoming_text
    if rag_context:
        final_input_text = (
            "Aşağıdaki RAG bağlamı, müşterinin sorusuyla en ilgili ürünlerden derlenmiştir. "
            "Cevabını öncelikle bu bilgiye dayandır:\n\n"
            f"RAG BAĞLAMI:\n{rag_context}\n\n"
            f"MÜŞTERİ SORUSU: {incoming_text}"
        )
    
    try:
        chat = client.chats.create(
            model="gemini-2.5-flash",
            config=ai_config,
            history=formatted_history
        )
        response = chat.send_message(final_input_text)
        return json.loads(response.text)
    except Exception as e:
        log_error("AI_REPLY_004", "Gemini generate_reply", e)
        print(f"Yapay Zeka Hatası: {e}")
        return {"cevap": "Sistemsel bir hata oluştu.", "insana_aktar": False, "ihlal_var": False}

def send_reply(thread_id, user_id, reply_text):
    bekleme_suresi = random.uniform(3, 8)
    print(f"  ⏳ [ANTI-BAN] Gerçekçilik için {bekleme_suresi:.1f} saniye bekleniyor...")
    time.sleep(bekleme_suresi)
    
    try:
        cl.direct_answer(thread_id, reply_text)
        return True
    except Exception as e:
        log_error("SEND_PRIMARY_005", "Instagram direct_answer", e)
        print("  [SİSTEM] Normal yanıt engellendi, direct_send deneniyor...")
        time.sleep(2) 
        try:
            cl.direct_send(reply_text, user_ids=[int(user_id)])
            return True
        except Exception as send_err:
            log_error("SEND_FALLBACK_006", "Instagram direct_send fallback", send_err)
            print(f"  [SİSTEM] Yanıt gönderilemedi: {send_err}")
            return False

def save_dialog(sender_id, user_text, reply_text):
    sohbetler.update_one(
        {"_id": sender_id},
        {
            "$push": {
                "gecmis": {
                    "$each": [
                        {"role": "user", "parts": [user_text]},
                        {"role": "model", "parts": [reply_text]}
                    ]
                }
            },
            "$set": {"son_islem": time.time()}
        },
        upsert=True
    )

def process_message(thread_id, msg):
    sender_id = str(msg.user_id)
    kullanici_adi = getattr(msg, "user_name", sender_id)
    musteri_kaydi = sohbetler.find_one({"_id": sender_id})
    
    if musteri_kaydi and musteri_kaydi.get("banli", False):
        print(f"🚫 [BLOKE] Banlı kullanıcı (@{kullanici_adi}) mesaj attı, reddedildi.")
        return True

    susturma_bitis = musteri_kaydi.get("susturma_bitis", 0) if musteri_kaydi else 0
    if time.time() < susturma_bitis:
        kalan_dakika = int((susturma_bitis - time.time()) / 60)
        print(f"[BOT] Kullanıcı @{kullanici_adi} yetkiliyle görüşüyor. Bot atladı. (Kalan süre: {kalan_dakika} dk)")
        return True

    print(f"[BOT] Kullanıcı @{kullanici_adi} mesajı işleniyor: '{msg.text}'")

    try:
        update_active_user(msg)
        ai_karari = generate_reply(sender_id, msg.text)
        
        reply_text = ai_karari.get("cevap", "")
        insana_aktar = ai_karari.get("insana_aktar", False)
        ihlal_var = ai_karari.get("ihlal_var", False) 

        if "Maalesef sadece mağazamız" in reply_text:
            ihlal_var = True
        if str(ihlal_var).lower() == "true":
            ihlal_var = True

        if ihlal_var:
            ihlal_sayisi = musteri_kaydi.get("ihlal_sayisi", 0) if musteri_kaydi else 0
            ihlal_sayisi += 1
            if ihlal_sayisi >= 3:
                print(f"🔨 [BAN ÇEKİCİ] Kullanıcı @{kullanici_adi} BANLANDI!")
                sohbetler.update_one({"_id": sender_id}, {"$set": {"banli": True, "ihlal_sayisi": ihlal_sayisi}}, upsert=True)
                send_reply(thread_id, msg.user_id, "Sistemi amacı dışında kullandığınız tespit edilmiştir. Otomatik destek hizmetinden kalıcı olarak engellendiniz.")
                return True
            else:
                kalan_hak = 3 - ihlal_sayisi
                print(f"⚠️ [UYARI] Kullanıcı @{kullanici_adi} kural ihlali yaptı. (Kalan Hak: {kalan_hak})")
                sohbetler.update_one({"_id": sender_id}, {"$set": {"ihlal_sayisi": ihlal_sayisi}}, upsert=True)
        
        if not reply_text:
            return True

        if not send_reply(thread_id, msg.user_id, reply_text):
            return False

        print(f"[BOT] ✅ Yanıt gönderildi: {reply_text}")
        save_dialog(sender_id, msg.text, reply_text)
        
        if insana_aktar and not ihlal_var:
            print(f"🚨 DİKKAT: Müşteri (@{kullanici_adi}) patrona yönlendiriliyor!")
            on_bes_dk_sonrasi = time.time() + 900
            sohbetler.update_one({"_id": sender_id}, {"$set": {"susturma_bitis": on_bes_dk_sonrasi}})
            bildirim_mesaji = f"🚨 ACİL DURUM: Müşteri Müdahale Bekliyor!\n\n👤 Müşteri: @{kullanici_adi}\n💬 Son Mesajı: '{msg.text}'"
            try:
                cl.direct_send(bildirim_mesaji, user_ids=[int(PATRON_ID)])
            except Exception as e:
                log_error("OWNER_NOTIFY_007", "Owner notification send", e)

        return True
    except Exception as e:
        log_error("PROCESS_MSG_008", "process_message main flow", e)
        print(f"[BOT] 🔴 Mesaj işleme hatası: {e}")
        return False

def bootstrap_processed_messages():
    print("[SİSTEM] Başlangıç taraması yapılıyor (geçmiş mesajlar atlanacak)...")
    try:
        for thread in cl.direct_threads(20) + cl.direct_pending_inbox(20):
            for msg in thread.messages:
                processed_messages.add(msg.id)
                update_active_user(msg)
        print(f"[SİSTEM] {len(processed_messages)} eski mesaj atlandı.")
    except Exception as e:
        log_error("BOOTSTRAP_009", "bootstrap_processed_messages", e)

def find_new_message(thread, bot_id):
    if not thread.messages: return None
    for msg in thread.messages:
        if is_valid_incoming(msg, bot_id) and msg.id not in processed_messages:
            return msg
    return None

def respond_to_messages():
    bot_id = str(cl.user_id)
    bootstrap_processed_messages()

    print("\n===========================================")
    print(f"--- 🤖 BOT AKTİF: {sirket_verisi['magaza_adi']} (Yeni Motor Devrede) ---")
    print("===========================================\n")

    while True:
        try:
            su_an = datetime.now()
            if 2 <= su_an.hour < 8:
                print(f"🌙 [UYKU MODU] Saat {su_an.strftime('%H:%M')}. Bot dinleniyor...")
                time.sleep(300)
                continue

            new_count = 0
            all_threads = cl.direct_threads(50) + cl.direct_pending_inbox(20)
            for thread in all_threads:
                msg = find_new_message(thread, bot_id)
                if not msg: continue
                is_ok = process_message(thread.id, msg)
                if is_ok:
                    processed_messages.add(msg.id)
                    new_count += 1

            if new_count > 0:
                print(f"[SİSTEM] Bu döngüde {new_count} yeni mesaj işlendi.")

        except Exception as e:
            log_error("MAIN_LOOP_010", "respond_to_messages while loop", e)

        time.sleep(20)

if __name__ == "__main__":
    respond_to_messages()