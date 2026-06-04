"""Parser test scripti - gercek mesaj formatlariyla."""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from parser import MessageParser

parser = MessageParser()

# Test 1: Yapılandırılmış blok (kullanıcının verdiği format)
test1 = """mediha tekgöz
@tekmediha99
ID: 2026035075909
-
mediha tekgöz
TR890015700000000123516764
-₺22.000,00
Beklemede  
Talep: 02.06.2026 06:23


çek iptal lütfen"""

print("=" * 60)
print("TEST 1: Yapılandırılmış blok + çek iptal")
print("=" * 60)
r = parser.parse(test1)
print(f"  İsim: {r.musteri_adi}")
print(f"  Username: {r.musteri_username}")
print(f"  ID: {r.musteri_id}")
print(f"  IBAN: {r.iban}")
print(f"  Tutar: {r.tutar} ({r.tutar_yonu})")
print(f"  Durum: {r.durum}")
print(f"  Talep: {r.talep_tarihi}")
print(f"  İşlem tipi: {r.islem_tipi.value} (güven: {r.confidence})")
print(f"  Yapılandırılmış: {r.is_structured}")
print(f"  Keywords: {r.keywords}")

# Test 2: KT grubu formatı
test2 = """FATOM5858  737266144  Sebahattin  Kılıç   
Anında Havale dekont iletildi kt lütfen"""

print("\n" + "=" * 60)
print("TEST 2: KT grubu formatı")
print("=" * 60)
r = parser.parse(test2)
print(f"  İsim: {r.musteri_adi}")
print(f"  Username: {r.musteri_username}")
print(f"  ID: {r.musteri_id}")
print(f"  İşlem tipi: {r.islem_tipi.value}")
print(f"  Platform: {r.platform}")

# Test 3: Onay mesajı
test3 = "Onay ✅"
print("\n" + "=" * 60)
print("TEST 3: Onay mesajı")
print("=" * 60)
r = parser.parse(test3)
print(f"  İşlem tipi: {r.islem_tipi.value}")
print(f"  Keywords: {r.keywords}")

# Test 4: SHA256 hash
test4 = "59673b5303f67b170918ae25ad6a5521dbd2fc825cfad498c8f352e5bd6970fc"
print("\n" + "=" * 60)
print("TEST 4: SHA256 hash")
print("=" * 60)
r = parser.parse(test4)
print(f"  Hash: {r.islem_hash}")

# Test 5: Gün sonu raporu
test5 = """Bayi: SAHA7
Tarih: 03.06.2026 03:00
Devir: ₺0
Yatırım: ₺359.945,00
Çekim: ₺221.128,00
Bayi Komisyon: ₺7.148,48
Ödemeler: ₺0
Gün Sonu: ₺142.745,99"""

print("\n" + "=" * 60)
print("TEST 5: Gün sonu raporu")
print("=" * 60)
r = parser.parse(test5)
print(f"  İşlem tipi: {r.islem_tipi.value}")
print(f"  Tutar: {r.tutar}")
print(f"  Keywords: {r.keywords}")

# Test 6: Ödeme talimatı
test6 = "Aynı isme 10.500 ₺ atalım"
print("\n" + "=" * 60)
print("TEST 6: Ödeme talimatı")
print("=" * 60)
r = parser.parse(test6)
print(f"  Tutar: {r.tutar}")
print(f"  İşlem tipi: {r.islem_tipi.value}")

# Test 7: VIP formatı
test7 = """VIP
Ali1325  14688821  Ali  Kayar  

Anında Banka, dekont iletlidi. KT lütfen."""
print("\n" + "=" * 60)
print("TEST 7: VIP + KT formatı")
print("=" * 60)
r = parser.parse(test7)
print(f"  İsim: {r.musteri_adi}")
print(f"  Username: {r.musteri_username}")
print(f"  ID: {r.musteri_id}")
print(f"  İşlem tipi: {r.islem_tipi.value}")
print(f"  Platform: {r.platform}")

print("\n" + "=" * 60)
print("TAMAMLANDI")
print("=" * 60)
