# Ödeme Çapraz Doğrulama Botu

Operasyon grubundaki çekim/ödeme mesajlarını tarayarak API/ödeme grubundaki durumlarla çapraz doğrulama yapan bot sistemi.

## Özellikler

- **Otomatik Tarama**: Belirli aralıklarla her iki grubu tarar
- **Mesaj Parser**: Müşteri ID, isim, tutar, işlem hash, IBAN, platform otomatik çıkarma
- **Otomatik Tutarsızlık Tespiti**:
  - 🔴 Çekim iptal edilmiş ama ödeme sağlanmış
  - 🔴 Personel onay vermiş ama API red döndü
  - 🔴 Ödeme yapılmış ama sistem red veriyor (manuel onay gerekli)
  - ⚠️ Tutar uyuşmazlığı
  - ⏳ Kaynak grupta işlem var ama doğrulama grubunda karşılığı yok
- **Çoklu Eşleştirme**: Müşteri ID, isim (fuzzy), tutar, işlem hash bazlı
- **Müşteri Sorgulama**: Belirli müşteriyi isim veya ID ile sorgulama
- **Bot Komutları**: Telegram üzerinden tarama, doğrulama, sorgulama ve rapor alma
- **Veritabanı**: SQLite ile mesaj ve doğrulama geçmişi

## Kurulum

### 1. Gereksinimler

```bash
pip install -r requirements.txt
```

### 2. Telegram API Ayarları

1. **Bot Token**: [@BotFather](https://t.me/BotFather) üzerinden yeni bot oluşturun
2. **API ID/Hash**: [my.telegram.org](https://my.telegram.org) adresinden alın
3. **Admin User ID**: [@userinfobot](https://t.me/userinfobot) ile öğrenin

### 3. Yapılandırma

`.env.example` dosyasını `.env` olarak kopyalayın ve değerleri doldurun:

```bash
cp .env.example .env
```

```env
BOT_TOKEN=123456:ABC-DEF...
API_ID=12345678
API_HASH=abcdef1234567890
ADMIN_USER_ID=123456789
SOURCE_GROUP=-1001234567890
VERIFY_GROUP=-1001234567891
SCAN_INTERVAL=5
MATCH_THRESHOLD=75
```

**Grup ID'lerini bulmak için**: Botu gruba ekleyin veya Pyrogram ile `get_chat()` kullanın.
Alternatif olarak grup username'i (`@grupadi`) da kullanabilirsiniz.

### 4. İlk Çalıştırma

```bash
python main.py
```

İlk çalıştırmada Pyrogram telefon numarası ve doğrulama kodu isteyecektir.
Session kaydedilecek, sonraki çalıştırmalarda tekrar sormaz.

## Kullanım

### Bot Komutları

| Komut | Açıklama |
|-------|----------|
| `/start` | Bot'u başlat, komut listesi |
| `/scan` | Grupları manuel tara |
| `/verify` | Doğrulama çalıştır (tutarsızlık + eşleşme) |
| `/report` | İstatistik raporu + kritik tutarsızlıklar |
| `/musteri <isim/ID>` | Müşteri bazlı işlem detayı |
| `/tutarsizlik` | Tüm aktif tutarsızlıkları listele |
| `/search <metin>` | Her iki grupta serbest arama |
| `/rules` | Aktif kuralları listele |
| `/addrule` | Yeni kural ekle |
| `/status` | Bot ve grup durumu |
| `/help` | Detaylı yardım |

### Kural Ekleme Örnekleri

```
/addrule odeme_kontrol user_claim ödeme|transfer|gönder
/addrule fiyat_check amount \d+\s*(TL|USD|EUR)
/addrule trade_verify keyword alım|satım|trade
/addrule duyuru_check pattern (toplantı|event|etkinlik)
```

### Doğrulama Mantığı

1. Bot, operasyon grubundaki mesajları tarar ve parse eder (müşteri ID, isim, tutar, işlem tipi)
2. API/ödeme grubundaki mesajları da aynı şekilde parse eder
3. Müşteri ID, isim, tutar veya işlem hash bazlı eşleştirme yapar
4. Çelişki kontrolleri çalıştırır:
   - İptal talep edilmiş ama ödeme yapılmış mı?
   - Personel onay vermiş ama API red dönmüş mü?
   - Ödeme sağlanmış ama sistem red veriyor mu?
5. Sonuçlar veritabanına kaydedilir ve rapor/alarm olarak bildirilir

### Durum Kodları

- ✅ **confirmed** – Her iki grupta da tutarlı onay
- ⚠️ **partial** – Kısmi eşleşme
- 🔴 **inconsistent** – Tutarsızlık tespit edildi (kritik)
- ❌ **denied** – Doğrulama bulunamadı
- ⏳ **pending** – İşlem beklemede

## Mimari

```
TelegramVerifier/
├── main.py          # Ana orchestrator, zamanlayıcı
├── bot.py           # Telegram Bot (komut alma/rapor/sorgulama)
├── scanner.py       # Pyrogram client (mesaj tarama)
├── verifier.py      # Doğrulama motoru (eşleştirme + tutarsızlık)
├── parser.py        # Mesaj parser (ID, tutar, işlem tipi çıkarma)
├── database.py      # SQLite veritabanı işlemleri
├── config.py        # Yapılandırma
├── .env.example     # Örnek env dosyası
├── requirements.txt # Python bağımlılıkları
└── data/            # Veritabanı + session + log
```

## Notlar

- Bot sadece `ADMIN_USER_ID` olarak tanımlanan kullanıcıdan komut kabul eder
- Pyrogram session dosyası `data/` klasöründe saklanır
- Tüm loglar `data/verifier.log` dosyasına yazılır
- Grup ID'leri negatif sayıdır (örn: `-1001234567890`)
- Supergroup/channel ID'leri `-100` ile başlar
