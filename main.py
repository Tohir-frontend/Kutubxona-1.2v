"""
Xorazm pedagogika texnikumi elektron kutubxonasi
Bo'limlar: Umumta'lim fanlar, Umumkasbiy fanlar, Maxsus fanlar, Badiiy adabiyotlar
"""

import os
import json

DATA_FILE = "Kutubxona/kutubxona.json"

BO_LIMLAR = [
    "Umumta'lim fanlar",
    "Umumkasbiy fanlar",
    "Maxsus fanlar",
    "Badiiy adabiyotlar",
]


def yuklash():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {bolim: [] for bolim in BO_LIMLAR}


def saqlash(malumot):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(malumot, f, ensure_ascii=False, indent=2)


def bolimlarni_korish(malumot):
    print("\n=== KUTUBXONA BO'LIMLARI ===")
    for i, bolim in enumerate(BO_LIMLAR, 1):
        print(f"{i}. {bolim} ({len(malumot[bolim])} ta kitob)")
    print()


def kitob_qoshish(malumot):
    bolimlarni_korish(malumot)
    tanlov = int(input("Bo'lim raqamini tanlang: ")) - 1
    if tanlov < 0 or tanlov >= len(BO_LIMLAR):
        print("Noto'g'ri tanlov!")
        return
    bolim = BO_LIMLAR[tanlov]
    nomi = input("Kitob nomi: ")
    muallif = input("Muallif: ")
    yil = input("Yili: ")
    malumot[bolim].append({"nomi": nomi, "muallif": muallif, "yili": yil})
    saqlash(malumot)
    print(f"'{nomi}' kitobi {bolim} bo'limiga qo'shildi.")


def kitoblarni_korish(malumot):
    bolimlarni_korish(malumot)
    tanlov = int(input("Bo'lim raqamini tanlang: ")) - 1
    if tanlov < 0 or tanlov >= len(BO_LIMLAR):
        print("Noto'g'ri tanlov!")
        return
    bolim = BO_LIMLAR[tanlov]
    print(f"\n=== {bolim} ===")
    if not malumot[bolim]:
        print("Bu bo'limda kitob yo'q.")
        return
    for i, kitob in enumerate(malumot[bolim], 1):
        print(f"{i}. {kitob['nomi']} - {kitob['muallif']} ({kitob['yili']})")


def qidirish(malumot):
    so_rov = input("Qidiruv so'zi: ").lower()
    topildi = False
    for bolim, kitoblar in malumot.items():
        for kitob in kitoblar:
            if so_rov in kitob["nomi"].lower() or so_rov in kitob["muallif"].lower():
                print(f"[{bolim}] {kitob['nomi']} - {kitob['muallif']} ({kitob['yili']})")
                topildi = True
    if not topildi:
        print("Hech narsa topilmadi.")


def asosiy():
    malumot = yuklash()
    while True:
        print("\n=== XORAZM PEDAGOGIKA TEXNIKUMI KUTUBXONASI ===")
        print("1. Bo'limlarni ko'rish")
        print("2. Kitob qo'shish")
        print("3. Bo'lim kitoblarini ko'rish")
        print("4. Kitob qidirish")
        print("5. Chiqish")
        tanlov = input("Tanlang: ")
        if tanlov == "1":
            bolimlarni_korish(malumot)
        elif tanlov == "2":
            kitob_qoshish(malumot)
        elif tanlov == "3":
            kitoblarni_korish(malumot)
        elif tanlov == "4":
            qidirish(malumot)
        elif tanlov == "5":
            print("Xayr!")
            break
        else:
            print("Noto'g'ri tanlov.")


if __name__ == "__main__":
    asosiy()