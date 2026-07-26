"""Demo ma'lumot generatori — 6 fan bo'yicha 30 tadan savol.

Har bir fan uchun alohida Test yaratiladi (single_choice, 4 variant:
A/B/C/D), so'ng darhol publish qilinadi — natijada `test.enwis.uz`da
sinab ko'rish uchun tayyor bo'ladi.

Ishlatish:
    python3 -m tests.seed_demo_subjects
    # yoki aniq userga bog'lab:
    python3 -m tests.seed_demo_subjects --owner-email demo@enwis.uz

Fanlar: Matematika, Fizika, Kimyo, Biologiya, Tarix, English.
"""

from __future__ import annotations

import asyncio
import random
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import engine
from app.modules.auth.models import User
from app.modules.notifications.models import Notification  # noqa: F401
from app.modules.tests.question_service import QuestionService
from app.modules.tests.service import TestService

# ─────────────────────────────────────────────────────────────────────
# 1) MATEMATIKA — algoritmik generatsiya (30 ta, hisoblangan to'g'ri javob)
# ─────────────────────────────────────────────────────────────────────


def _make_math_questions() -> list[dict]:
    rng = random.Random(42)  # deterministik — har safar bir xil savollar
    questions = []

    def choices_for(correct: int) -> list[dict]:
        wrongs = set()
        while len(wrongs) < 3:
            delta = rng.choice([-5, -3, -2, -1, 1, 2, 3, 5])
            candidate = correct + delta
            if candidate != correct:
                wrongs.add(candidate)
        options = [correct, *wrongs]
        rng.shuffle(options)
        letters = ["A", "B", "C", "D"]
        return [
            {"content": f"{letters[i]}) {val}", "is_correct": val == correct, "order": i}
            for i, val in enumerate(options)
        ]

    # 10 ta qo'shish/ayirish
    for _ in range(10):
        a, b = rng.randint(10, 99), rng.randint(1, 50)
        op = rng.choice(["+", "-"])
        result = a + b if op == "+" else a - b
        questions.append({
            "title": f"{a} {op} {b} = ?",
            "correct": result,
        })

    # 10 ta ko'paytirish
    for _ in range(10):
        a, b = rng.randint(2, 20), rng.randint(2, 12)
        questions.append({
            "title": f"{a} × {b} = ?",
            "correct": a * b,
        })

    # 10 ta foiz masalasi
    for _ in range(10):
        base = rng.choice([50, 80, 100, 120, 150, 200, 240, 300, 400, 500])
        pct = rng.choice([5, 10, 15, 20, 25, 30, 40, 50])
        result = base * pct // 100
        questions.append({
            "title": f"{base} ning {pct}% i nechaga teng?",
            "correct": result,
        })

    return [
        {
            "title": q["title"],
            "question_type": "single_choice",
            "difficulty": "easy",
            "score": 1,
            "choices": choices_for(q["correct"]),
        }
        for q in questions
    ]


# ─────────────────────────────────────────────────────────────────────
# 2) FIZIKA — 30 ta, qo'lda yozilgan
# ─────────────────────────────────────────────────────────────────────

PHYSICS = [
    ("Yorug'lik tezligi vakuumda taxminan nechaga teng?", ["300 000 km/s", "150 000 km/s", "1 000 000 km/s", "30 000 km/s"], 0),
    ("Kuch birligi SI sistemasida qanday nomlanadi?", ["Nyuton", "Joul", "Vatt", "Paskal"], 0),
    ("Erkin tushish tezlanishi (g) taxminan nechaga teng?", ["9.8 m/s²", "8.9 m/s²", "10.5 m/s²", "7.2 m/s²"], 0),
    ("Elektr toki birligi qanday nomlanadi?", ["Amper", "Volt", "Om", "Vatt"], 0),
    ("Energiya birligi SI sistemasida qaysi?", ["Joul", "Nyuton", "Vatt", "Kelvin"], 0),
    ("Suvning muzlash harorati necha Selsiy darajada?", ["0°C", "-10°C", "100°C", "4°C"], 0),
    ("Massa va tezlanish ko'paytmasi nimani beradi?", ["Kuchni", "Energiyani", "Impulsni", "Quvvatni"], 0),
    ("Ovoz havoda taxminan qanday tezlikda tarqaladi?", ["343 m/s", "3000 m/s", "34 m/s", "34300 m/s"], 0),
    ("Amper qonuni nimani tavsiflaydi?", ["Elektr toki va magnit maydon aloqasini", "Issiqlik almashinuvini", "Yorug'lik sinishini", "Gravitatsion kuchni"], 0),
    ("Om qonuni formulasi qaysi?", ["U = IR", "F = ma", "E = mc²", "P = Fv"], 0),
    ("Quvvat birligi qanday nomlanadi?", ["Vatt", "Joul", "Nyuton", "Amper"], 0),
    ("Bosim birligi SI sistemasida qaysi?", ["Paskal", "Nyuton", "Joul", "Om"], 0),
    ("Issiqlik miqdorini o'lchash birligi?", ["Joul", "Kelvin", "Vatt", "Amper"], 0),
    ("Nyutonning birinchi qonuni nima haqida?", ["Inersiya haqida", "Kuch va tezlanish haqida", "Ta'sir va aks ta'sir haqida", "Energiya saqlanishi haqida"], 0),
    ("Elektr zaryadining birligi qaysi?", ["Kulon", "Amper", "Volt", "Om"], 0),
    ("Yassi ko'zguda tasvir qanday hosil bo'ladi?", ["Xayoliy va to'g'ri", "Haqiqiy va teskari", "Xayoliy va teskari", "Haqiqiy va to'g'ri"], 0),
    ("Magnit maydon birligi qaysi?", ["Tesla", "Volt", "Amper", "Om"], 0),
    ("Suv 1 atmosfera bosimda necha darajada qaynaydi?", ["100°C", "90°C", "120°C", "80°C"], 0),
    ("Radioaktiv yemirilishni birinchi kim kashf etgan?", ["Anri Bekkerel", "Isaak Nyuton", "Albert Eynshteyn", "Maykl Faradey"], 0),
    ("Nisbiylik nazariyasini kim yaratgan?", ["Albert Eynshteyn", "Isaak Nyuton", "Nils Bor", "Maks Plank"], 0),
    ("Elektromagnit induksiya hodisasini kim kashf etgan?", ["Maykl Faradey", "Jeyms Maksvell", "Georg Om", "Andre Amper"], 0),
    ("Massa va energiya orasidagi bog'liqlik formulasi?", ["E = mc²", "F = ma", "U = IR", "P = Fv"], 0),
    ("Issiqlik uzatilishining uch turi nima?", ["O'tkazuvchanlik, konveksiya, nurlanish", "Erish, bug'lanish, muzlash", "Siqilish, kengayish, aylanish", "Sinish, qaytish, yutilish"], 0),
    ("Optik linzalar nimani o'zgartiradi?", ["Yorug'lik yo'nalishini", "Tovush chastotasini", "Elektr toki kuchini", "Haroratni"], 0),
    ("Nyutonning uchinchi qonuni nima haqida?", ["Ta'sir va aks ta'sir haqida", "Inersiya haqida", "Kuch va tezlanish haqida", "Energiya saqlanishi haqida"], 0),
    ("Bir soniyada tebranishlar soni nima deyiladi?", ["Chastota", "Amplituda", "Davr", "Tezlik"], 0),
    ("Rezistorlar ketma-ket ulanganda umumiy qarshilik qanday topiladi?", ["Yig'indisi olinadi", "Ko'paytmasi olinadi", "O'rtachasi olinadi", "Ayirmasi olinadi"], 0),
    ("Yer sun'iy yo'ldoshi qanday kuch ta'sirida orbitada aylanadi?", ["Gravitatsiya kuchi", "Markazdan qochma kuch", "Ishqalanish kuchi", "Elektr kuchi"], 0),
    ("Zichlik formulasi qanday?", ["ρ = m/V", "ρ = m·V", "ρ = V/m", "ρ = m+V"], 0),
    ("Kinetik energiya formulasi qaysi?", ["E = mv²/2", "E = mgh", "E = mc²", "E = Fs"], 0),
]

# ─────────────────────────────────────────────────────────────────────
# 3) KIMYO — 30 ta
# ─────────────────────────────────────────────────────────────────────

CHEMISTRY = [
    ("Suvning kimyoviy formulasi qanday?", ["H2O", "CO2", "O2", "NaCl"], 0),
    ("Davriy sistemani kim yaratgan?", ["D.I.Mendeleyev", "A.Eynshteyn", "I.Nyuton", "M.Faradey"], 0),
    ("Osh tuzining kimyoviy formulasi?", ["NaCl", "KCl", "CaCl2", "NaOH"], 0),
    ("Kislorodning atom raqami nechaga teng?", ["8", "6", "16", "1"], 0),
    ("Havoning tarkibidagi eng ko'p gaz qaysi?", ["Azot", "Kislorod", "Argon", "Vodorod"], 0),
    ("Kislotalar lakmus qog'ozini qanday rangga bo'yaydi?", ["Qizil", "Ko'k", "Yashil", "Sariq"], 0),
    ("Vodorodning davriy sistemadagi belgisi?", ["H", "V", "Vd", "Hg"], 0),
    ("pH shkalasi nimani o'lchaydi?", ["Kislotalilik/ishqorlilikni", "Haroratni", "Bosimni", "Zichlikni"], 0),
    ("Oltin elementining kimyoviy belgisi?", ["Au", "Ag", "Fe", "Ol"], 0),
    ("Yonish reaksiyasida qaysi gaz ishtirok etadi?", ["Kislorod", "Azot", "Vodorod", "Geliy"], 0),
    ("Molekula nima?", ["Atomlar birikmasi", "Bitta atom", "Elektronlar to'plami", "Neytronlar yig'indisi"], 0),
    ("NaOH qanday modda hisoblanadi?", ["Ishqor", "Kislota", "Tuz", "Gaz"], 0),
    ("Uglerodning atom raqami nechaga teng?", ["6", "8", "12", "14"], 0),
    ("Temirning kimyoviy belgisi qaysi?", ["Fe", "Ti", "Tm", "Fr"], 0),
    ("Davriy sistemada nechta davr mavjud?", ["7", "8", "9", "6"], 0),
    ("Ammiakning kimyoviy formulasi?", ["NH3", "NO2", "N2O", "NH4"], 0),
    ("Eng yengil element qaysi?", ["Vodorod", "Geliy", "Kislorod", "Azot"], 0),
    ("Kumushning kimyoviy belgisi?", ["Ag", "Au", "Cu", "Ku"], 0),
    ("Kimyoviy reaksiya tezligiga nima ta'sir qilmaydi?", ["Idish rangi", "Harorat", "Katalizator", "Konsentratsiya"], 0),
    ("Uglerod dioksidining formulasi qaysi?", ["CO2", "CO", "C2O", "CO3"], 0),
    ("Metallarning umumiy xossasi qaysi?", ["Elektr o'tkazuvchanlik", "Shaffoflik", "Yumshoqlik", "Erimaslik"], 0),
    ("Kaliyning kimyoviy belgisi?", ["K", "Ka", "Kl", "Kn"], 0),
    ("Sirka kislotasining formulasi qaysi?", ["CH3COOH", "H2SO4", "HCl", "HNO3"], 0),
    ("Atom yadrosi nimalardan tashkil topgan?", ["Proton va neytrondan", "Faqat elektrondan", "Faqat protondan", "Molekulalardan"], 0),
    ("Mis elementining kimyoviy belgisi?", ["Cu", "Mi", "Ms", "My"], 0),
    ("Ishqorlar lakmusni qanday rangga bo'yaydi?", ["Ko'k", "Qizil", "Sariq", "Yashil"], 0),
    ("Xlorning atom raqami nechaga teng?", ["17", "16", "18", "15"], 0),
    ("Qaysi modda katalizator vazifasini bajaradi?", ["Reaksiya tezligini oshiruvchi modda", "Reaksiyani sekinlashtiruvchi modda", "Reaksiyada iste'mol bo'ladigan modda", "Reaksiyada hosil bo'ladigan modda"], 0),
    ("Sulfat kislotaning formulasi qaysi?", ["H2SO4", "HCl", "HNO3", "H3PO4"], 0),
    ("Davriy sistemada elementlar nima bo'yicha joylashgan?", ["Atom og'irligi/raqami bo'yicha", "Rangi bo'yicha", "Kashf etilgan yili bo'yicha", "Alifbo tartibida"], 0),
]

# ─────────────────────────────────────────────────────────────────────
# 4) BIOLOGIYA — 30 ta
# ─────────────────────────────────────────────────────────────────────

BIOLOGY = [
    ("Hujayraning energiya markazi qaysi organoid?", ["Mitoxondriya", "Yadro", "Ribosoma", "Golji apparati"], 0),
    ("Fotosintez qaysi organoidda sodir bo'ladi?", ["Xloroplast", "Mitoxondriya", "Yadro", "Vakuola"], 0),
    ("DNK molekulasi qaysi shaklda joylashgan?", ["Qo'sh spiral", "Yagona zanjir", "Uch spiral", "Doira"], 0),
    ("Inson qon guruhlari nechta?", ["4 ta", "2 ta", "3 ta", "6 ta"], 0),
    ("Insonda nechta xromosoma bor?", ["46 ta", "44 ta", "48 ta", "23 ta"], 0),
    ("Fotosintez natijasida qaysi gaz ajraladi?", ["Kislorod", "Uglerod dioksid", "Azot", "Vodorod"], 0),
    ("Yurak necha bo'lmadan iborat?", ["4 ta", "2 ta", "3 ta", "5 ta"], 0),
    ("Genlar nimadan tashkil topgan?", ["DNKdan", "RNKdan", "Oqsildan", "Lipiddan"], 0),
    ("Hujayra bo'linishining oddiy turi qaysi?", ["Mitoz", "Meyoz", "Fermentatsiya", "Diffuziya"], 0),
    ("Odam tanasida eng katta organ qaysi?", ["Teri", "Jigar", "O'pka", "Yurak"], 0),
    ("Fermentlar nima vazifani bajaradi?", ["Reaksiyalarni tezlashtiradi", "Energiya saqlaydi", "Genetik axborot tashiydi", "Hujayrani himoya qiladi"], 0),
    ("O'simliklar suvni asosan qaysi qismidan oladi?", ["Ildizidan", "Bargidan", "Poyasidan", "Gulidan"], 0),
    ("Insonning asosiy nafas olish organi?", ["O'pka", "Yurak", "Jigar", "Buyrak"], 0),
    ("Charlz Darvin qaysi nazariyaning muallifi?", ["Evolyutsiya nazariyasi", "Nisbiylik nazariyasi", "Genetika qonunlari", "Hujayra nazariyasi"], 0),
    ("Bakteriyalar qaysi organizmlar turkumiga kiradi?", ["Prokariotlar", "Eukariotlar", "Viruslar", "Zamburug'lar"], 0),
    ("Insonning eng katta bezi qaysi?", ["Jigar", "Buyrak", "Taloq", "Qalqonsimon bez"], 0),
    ("Genetik kasalliklar nima orqali avloddan-avlodga o'tadi?", ["Genlar orqali", "Havo orqali", "Ovqat orqali", "Suv orqali"], 0),
    ("Xlorofill qaysi rangda bo'ladi?", ["Yashil", "Qizil", "Sariq", "Ko'k"], 0),
    ("Insonda ovqat hazm qilish qayerdan boshlanadi?", ["Og'iz bo'shlig'idan", "Oshqozondan", "Ichakdan", "Qizilo'ngachdan"], 0),
    ("Qaysi organ qonni tozalaydi?", ["Buyrak", "Yurak", "O'pka", "Taloq"], 0),
    ("RNK qaysi funksiyani bajaradi?", ["Oqsil sintezida ishtirok etadi", "Energiya ishlab chiqaradi", "Suvni tashiydi", "Hujayrani himoya qiladi"], 0),
    ("Ekosistemada quyosh energiyasini birinchi bo'lib kim o'zlashtiradi?", ["O'simliklar", "Yirtqichlar", "Zamburug'lar", "Bakteriyalar"], 0),
    ("Insonning tayanch-harakat tizimi nimalardan iborat?", ["Suyak va mushaklardan", "Nervlardan", "Qon tomirlaridan", "Bezlardan"], 0),
    ("Mendel qaysi fanning asoschisi hisoblanadi?", ["Genetika", "Evolyutsiya", "Ekologiya", "Anatomiya"], 0),
    ("Antibiotiklar nimaga qarshi ishlatiladi?", ["Bakteriyalarga", "Viruslarga", "Zaharga", "Allergiyaga"], 0),
    ("Odam skeletida nechta suyak bor?", ["206 ta", "150 ta", "300 ta", "180 ta"], 0),
    ("Fotosintez uchun nima zarur?", ["Yorug'lik, suv, CO2", "Faqat suv", "Faqat yorug'lik", "Faqat kislorod"], 0),
    ("Virus qanday organizm hisoblanadi?", ["Hujayrasiz shakl", "Bakteriya turi", "Zamburug' turi", "Ko'p hujayrali organizm"], 0),
    ("Insonning eng katta a'zosi (yuza jihatidan) qaysi?", ["Teri", "Jigar", "O'pka", "Ichak"], 0),
    ("Ekologiya nimani o'rganadi?", ["Organizmlar va muhit aloqasini", "Faqat hayvonlarni", "Faqat o'simliklarni", "Faqat iqlimni"], 0),
]

# ─────────────────────────────────────────────────────────────────────
# 5) TARIX — 30 ta
# ─────────────────────────────────────────────────────────────────────

HISTORY = [
    ("Amir Temur qachon tug'ilgan?", ["1336-yilda", "1405-yilda", "1370-yilda", "1300-yilda"], 0),
    ("Amir Temur qaysi shaharni poytaxt qilgan?", ["Samarqand", "Buxoro", "Xiva", "Toshkent"], 0),
    ("Ikkinchi jahon urushi qaysi yili boshlangan?", ["1939-yilda", "1941-yilda", "1914-yilda", "1945-yilda"], 0),
    ("O'zbekiston mustaqilligini qachon e'lon qilgan?", ["1991-yil 1-sentabr", "1990-yil 1-sentabr", "1992-yil 1-sentabr", "1989-yil 1-sentabr"], 0),
    ("Ipak yo'li nimani bog'lagan?", ["Sharq va G'arbni", "Shimol va Janubni", "Yevropa va Afrikani", "Amerikani Osiyo bilan"], 0),
    ("Birinchi jahon urushi qaysi yili boshlangan?", ["1914-yilda", "1918-yilda", "1939-yilda", "1900-yilda"], 0),
    ("Mirzo Ulug'bek nimasi bilan mashhur?", ["Astronomiya bilan", "Harbiy yurishlar bilan", "Savdo bilan", "Musiqa bilan"], 0),
    ("Qadimgi Misr piramidalari nima maqsadda qurilgan?", ["Fir'avnlarni dafn etish uchun", "Ibodat qilish uchun", "Yashash uchun", "Savdo uchun"], 0),
    ("Rim imperiyasi qachon ikkiga bo'lingan?", ["395-yilda", "476-yilda", "330-yilda", "100-yilda"], 0),
    ("Fransiya inqilobi qaysi yili boshlangan?", ["1789-yilda", "1799-yilda", "1804-yilda", "1750-yilda"], 0),
    ("Buyuk Ipak yo'li qaysi asrda gullab-yashnagan?", ["II asr–XV asr oralig'ida", "Faqat I asrda", "Faqat XX asrda", "Faqat V asrda"], 0),
    ("Sohibqiron laqabi kimga tegishli?", ["Amir Temurga", "Ulug'bekka", "Boburga", "Bobirga"], 0),
    ("Amerika qit'asini kim kashf etgan (Yevropa uchun)?", ["Xristofor Kolumb", "Vasko da Gama", "Marko Polo", "Magellan"], 0),
    ("Berlin devori qaysi yili qulagan?", ["1989-yilda", "1991-yilda", "1985-yilda", "1975-yilda"], 0),
    ("Chingizxon qaysi imperiyaga asos solgan?", ["Mo'g'ullar imperiyasi", "Rim imperiyasi", "Usmonli imperiyasi", "Fors imperiyasi"], 0),
    ("Zahiriddin Muhammad Bobur qaysi imperiyaga asos solgan?", ["Boburiylar (Hindiston)", "Usmoniylar", "Safaviylar", "Mo'g'ullar"], 0),
    ("Sovet Ittifoqi qachon tarqatib yuborilgan?", ["1991-yilda", "1989-yilda", "1985-yilda", "1993-yilda"], 0),
    ("Qadimgi Yunonistonda demokratiya qayerda paydo bo'lgan?", ["Afinada", "Spartada", "Rimda", "Fivada"], 0),
    ("Islom dini qaysi asrda paydo bo'lgan?", ["VII asrda", "V asrda", "X asrda", "III asrda"], 0),
    ("Sanoat inqilobi qaysi mamlakatdan boshlangan?", ["Angliyadan", "Fransiyadan", "Germaniyadan", "AQShdan"], 0),
    ("Yevropada Uyg'onish davri qaysi asrlarni qamrab oladi?", ["XIV–XVII asrlar", "I–III asrlar", "XIX–XX asrlar", "VIII–X asrlar"], 0),
    ("Usmonli imperiyasi qaysi yili tugatilgan?", ["1922-yilda", "1918-yilda", "1900-yilda", "1945-yilda"], 0),
    ("Guttenberg nimani ixtiro qilgan?", ["Bosmaxonani", "Kompasni", "Poroxni", "Teleskopni"], 0),
    ("Buyuk Britaniya sanoat inqilobida nimadan foydalangan?", ["Bug' dvigatelidan", "Elektr energiyasidan", "Yadro energiyasidan", "Shamol energiyasidan"], 0),
    ("Amir Temur qaysi yilda vafot etgan?", ["1405-yilda", "1370-yilda", "1336-yilda", "1450-yilda"], 0),
    ("Qadimgi Xitoy devori nima maqsadda qurilgan?", ["Himoya uchun", "Savdo uchun", "Ibodat uchun", "Yashash uchun"], 0),
    ("Rossiya imperiyasi qachon qulagan?", ["1917-yilda", "1905-yilda", "1922-yilda", "1900-yilda"], 0),
    ("Markaziy Osiyoda ilk davlatlar qachon paydo bo'lgan?", ["Miloddan avvalgi davrlarda", "XX asrda", "XV asrda", "X asrda"], 0),
    ("Vasko da Gama nimani kashf etgan?", ["Hindistonga dengiz yo'lini", "Amerikani", "Avstraliyani", "Antarktidani"], 0),
    ("BMT (Birlashgan Millatlar Tashkiloti) qachon tuzilgan?", ["1945-yilda", "1918-yilda", "1939-yilda", "1991-yilda"], 0),
]

# ─────────────────────────────────────────────────────────────────────
# 6) ENGLISH — 30 ta (grammar & vocabulary)
# ─────────────────────────────────────────────────────────────────────

ENGLISH = [
    ("Choose the correct form: She ___ to school every day.", ["goes", "go", "going", "gone"], 0),
    ("What is the past tense of 'go'?", ["went", "goed", "gone", "going"], 0),
    ("Choose the correct article: I saw ___ elephant at the zoo.", ["an", "a", "the", "no article"], 0),
    ("Which word is a synonym of 'happy'?", ["Joyful", "Sad", "Angry", "Tired"], 0),
    ("Choose the correct sentence.", ["He doesn't like coffee.", "He don't likes coffee.", "He not like coffee.", "He no like coffee."], 0),
    ("What is the plural of 'child'?", ["Children", "Childs", "Childes", "Child"], 0),
    ("Choose the correct comparative: This book is ___ than that one.", ["better", "gooder", "more good", "best"], 0),
    ("Which is a question word?", ["Where", "There", "Here", "Near"], 0),
    ("Choose the correct preposition: The book is ___ the table.", ["on", "in", "at", "by"], 0),
    ("What is the opposite of 'big'?", ["Small", "Tall", "Long", "Wide"], 0),
    ("Choose the correct sentence in Present Continuous.", ["She is reading a book.", "She reading a book.", "She reads a book now.", "She read a book now."], 0),
    ("What is the past participle of 'write'?", ["Written", "Wrote", "Writing", "Writes"], 0),
    ("Choose the correct modal verb: You ___ study harder.", ["should", "will", "did", "was"], 0),
    ("Which word means 'very tired'?", ["Exhausted", "Excited", "Amused", "Confused"], 0),
    ("Choose the correct sentence: I have ___ money.", ["little", "a few", "many", "much are"], 0),
    ("What is the superlative form of 'good'?", ["Best", "Better", "Goodest", "More good"], 0),
    ("Choose the correct passive form: The letter ___ written yesterday.", ["was", "is", "has", "did"], 0),
    ("Which word is an adjective?", ["Beautiful", "Beauty", "Beautifully", "Beautify"], 0),
    ("Choose the correct conjunction: I stayed home ___ it was raining.", ["because", "but", "or", "so"], 0),
    ("What does 'to postpone' mean?", ["To delay", "To cancel", "To start", "To finish"], 0),
    ("Choose the correct future form: They ___ arrive tomorrow.", ["will", "would", "did", "was"], 0),
    ("Which sentence is grammatically correct?", ["Neither of them is right.", "Neither of them are right.", "Neither of them be right.", "Neither of them was right."], 0),
    ("What is a synonym for 'begin'?", ["Start", "End", "Stop", "Pause"], 0),
    ("Choose the correct sentence: If it rains, I ___ stay home.", ["will", "would", "did", "was"], 0),
    ("What is the plural of 'mouse'?", ["Mice", "Mouses", "Mices", "Mouse"], 0),
    ("Choose the correct word: She is ___ than her sister.", ["taller", "tall", "tallest", "more tall"], 0),
    ("Which word means 'to look for'?", ["Search", "Find", "See", "Watch"], 0),
    ("Choose the correct sentence: He has been working ___ 2020.", ["since", "for", "from", "at"], 0),
    ("What is the opposite of 'difficult'?", ["Easy", "Hard", "Complex", "Simple"], 0),
    ("Choose the correct reported speech: He said he ___ tired.", ["was", "is", "be", "been"], 0),
]

SUBJECTS: dict[str, list[tuple[str, list[str], int]]] = {
    "Fizika": PHYSICS,
    "Kimyo": CHEMISTRY,
    "Biologiya": BIOLOGY,
    "Tarix": HISTORY,
    "English": ENGLISH,
}


def _to_question_payload(title: str, options: list[str], correct_idx: int) -> dict:
    letters = ["A", "B", "C", "D"]
    return {
        "title": title,
        "question_type": "single_choice",
        "difficulty": "medium",
        "score": 1,
        "choices": [
            {
                "content": f"{letters[i]}) {opt}",
                "is_correct": i == correct_idx,
                "order": i,
            }
            for i, opt in enumerate(options)
        ],
    }


async def _get_or_create_owner(session: AsyncSession, email: str | None) -> User:
    if email:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            return user

    result = await session.execute(
        select(User).where(User.username == "demo_seed_teacher")
    )
    user = result.scalar_one_or_none()
    if user:
        return user

    from app.core.security import hash_password

    user = User(
        id=uuid.uuid4(),
        username="demo_seed_teacher",
        phone=f"+998900000{uuid.uuid4().int % 1000:03d}",
        email=email or "demo_seed_teacher@enwis.uz",
        full_name="Demo Seed Teacher",
        password_hash=hash_password("DemoPass123!"),
        is_active=True,
        is_verified=True,
    )
    session.add(user)
    await session.flush()
    return user


async def seed(owner_email: str | None = None, db_engine=None) -> None:
    from app.core.database import engine as default_engine

    factory = async_sessionmaker(
        bind=db_engine or default_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with factory() as session:
        owner = await _get_or_create_owner(session, owner_email)
        owner_id = owner.id
        await session.commit()
        print(f"Demo owner: {owner.username} ({owner_id})")

    all_subjects: dict[str, list[dict]] = {"Matematika": _make_math_questions()}
    for name, rows in SUBJECTS.items():
        all_subjects[name] = [_to_question_payload(t, o, c) for t, o, c in rows]

    for subject_name, questions_data in all_subjects.items():
        assert len(questions_data) == 30, f"{subject_name}: {len(questions_data)} ta savol (30 kerak)"

        async with factory() as session:
            test_service = TestService(session)
            test = await test_service.create_test(
                {
                    "title": f"{subject_name} — Demo test (30 savol)",
                    "description": f"{subject_name} fanidan namunaviy test, A/B/C/D variantli.",
                    "test_type": "quiz",
                    "visibility": "public",
                    "shuffle_questions": True,
                    "shuffle_answers": True,
                },
                owner_id=owner_id,
            )
            test_id = test.id
            await session.commit()

        async with factory() as session:
            created = await QuestionService(session).bulk_create_questions(
                questions_data, owner_id,
            )
            from app.modules.tests.repository import TestQuestionRepository

            tq_repo = TestQuestionRepository(session)
            for q in created:
                await tq_repo.add_question(test_id, q.id, points=1)
            await session.commit()

        async with factory() as session:
            test = await TestService(session).publish_test(test_id, owner_id)
            await session.commit()

        print(f"✔ {subject_name}: test yaratildi ({test_id}), 30 savol qo'shildi, publish qilindi.")

    print("\nTayyor! 6 ta fan × 30 ta savol = 180 ta savol yaratildi.")


def main() -> None:
    owner_email = None
    if "--owner-email" in sys.argv:
        idx = sys.argv.index("--owner-email")
        owner_email = sys.argv[idx + 1]
    asyncio.run(seed(owner_email))


if __name__ == "__main__":
    main()