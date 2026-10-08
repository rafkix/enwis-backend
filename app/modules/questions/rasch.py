"""Rasch model (1-parameter logistic IRT).

Ikki narsa uchun ishlatiladi:

1. **Kalibratsiya** — savollarning haqiqiy qiyinlik parametri (b, logit
   shkalada) foydalanuvchilarning haqiqiy javoblari (to'g'ri/noto'g'ri)
   asosida hisoblanadi (Joint Maximum Likelihood Estimation / JMLE).
2. **Test yig'ish** — kalibratsiya qilingan savollar orasidan, berilgan
   maqsadli qobiliyat darajasiga (theta) eng mos (eng ko'p axborot
   beradigan) savollar tanlanadi.

Rasch modeli:
    P(to'g'ri | theta, b) = 1 / (1 + exp(-(theta - b)))

Faqat standart kutubxona (`math`) ishlatiladi — tashqi bog'liqlik yo'q,
shuning uchun bu modul har qanday muhitda ishlaydi.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# ── Sozlamalar ───────────────────────────────────────────────────────

MAX_ITERATIONS = 100
CONVERGENCE_THRESHOLD = 0.001
# Logit shkalasi cheklovi — cheksizlikka (hamma to'g'ri/hamma noto'g'ri
# javob bergan savol/foydalanuvchi uchun) chiqib ketmasligi uchun.
LOGIT_CLAMP = 6.0


def _prob_correct(theta: float, b: float) -> float:
    """P(to'g'ri javob | qobiliyat theta, qiyinlik b)."""
    x = theta - b
    if x > 35:
        return 1.0
    if x < -35:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class RaschCalibrationResult:
    item_difficulty: dict[str, float] = field(default_factory=dict)
    person_ability: dict[str, float] = field(default_factory=dict)
    n_iterations: int = 0
    converged: bool = False
    n_items: int = 0
    n_persons: int = 0
    n_responses: int = 0
    skipped_items: list[str] = field(default_factory=list)
    skipped_persons: list[str] = field(default_factory=list)


def calibrate(
    responses: list[tuple[str, str, bool]],
) -> RaschCalibrationResult:
    """JMLE (Joint Maximum Likelihood Estimation) orqali Rasch modelini
    kalibrlaydi.

    Args:
        responses: (person_id, item_id, is_correct) uchtaliklar ro'yxati
            — har bir yakunlangan urinishdagi har bir savolga javob.

    Returns:
        RaschCalibrationResult — har bir savol uchun qiyinlik (b) va
        har bir foydalanuvchi uchun taxminiy qobiliyat (theta).

    Eslatma: hamma savoliga to'g'ri yoki hammasiga noto'g'ri javob
    bergan foydalanuvchilar, va hech kim xato/tog'ri qilmagan (ya'ni
    variatsiya bo'lmagan) savollar JMLE'da baholab bo'lmaydi — ular
    `skipped_*` ro'yxatlariga tushadi va natijaviy hisobdan chetlab
    o'tiladi (aks holda baho cheksizlikka chiqib ketadi).
    """
    persons: dict[str, dict[str, bool]] = {}
    items: dict[str, dict[str, bool]] = {}
    for person_id, item_id, is_correct in responses:
        persons.setdefault(person_id, {})[item_id] = is_correct
        items.setdefault(item_id, {})[person_id] = is_correct

    result = RaschCalibrationResult(n_responses=len(responses))

    # Faqat variatsiyaga ega (kamida bitta to'g'ri va bitta noto'g'ri
    # javobi bo'lgan) savol va foydalanuvchilarni baholaymiz.
    usable_items = []
    for item_id, item_responses in items.items():
        vals = item_responses.values()
        if any(vals) and not all(vals):
            usable_items.append(item_id)
        else:
            result.skipped_items.append(item_id)

    usable_persons = []
    for person_id, person_responses in persons.items():
        vals = person_responses.values()
        if any(vals) and not all(vals):
            usable_persons.append(person_id)
        else:
            result.skipped_persons.append(person_id)

    result.n_items = len(usable_items)
    result.n_persons = len(usable_persons)

    if not usable_items or not usable_persons:
        return result

    # Boshlang'ich qiymatlar: logit(to'g'ri javob nisbati)ning teskarisi.
    theta = {}
    for p in usable_persons:
        vals = [v for k, v in persons[p].items() if k in usable_items]
        if not vals:
            continue
        p_correct = sum(vals) / len(vals)
        p_correct = min(max(p_correct, 0.05), 0.95)
        theta[p] = math.log(p_correct / (1 - p_correct))

    b = {}
    for it in usable_items:
        vals = [v for k, v in items[it].items() if k in theta]
        if not vals:
            continue
        p_correct = sum(vals) / len(vals)
        p_correct = min(max(p_correct, 0.05), 0.95)
        # Qiyinroq savol -> kam to'g'ri javob -> katta b.
        b[it] = -math.log(p_correct / (1 - p_correct))

    usable_items = [it for it in usable_items if it in b]
    usable_persons = [p for p in usable_persons if p in theta]

    # ── JMLE: navbatma-navbat theta va b ni Newton-Raphson bilan
    #    yangilaymiz, konvergensiyaga qadar. ─────────────────────────
    converged = False
    it_count = 0
    for it_count in range(1, MAX_ITERATIONS + 1):
        max_delta = 0.0

        # Person qobiliyatlarini yangilash (b ni doim ushlab turib)
        for p in usable_persons:
            observed = sum(1 for it, val in persons[p].items() if it in b and val)
            expected = sum(_prob_correct(theta[p], b[it]) for it in persons[p] if it in b)
            info = sum(
                _prob_correct(theta[p], b[it]) * (1 - _prob_correct(theta[p], b[it]))
                for it in persons[p] if it in b
            )
            if info <= 1e-6:
                continue
            delta = (observed - expected) / info
            delta = max(min(delta, 2.0), -2.0)  # qadam kattaligini cheklash
            theta[p] = max(min(theta[p] + delta, LOGIT_CLAMP), -LOGIT_CLAMP)
            max_delta = max(max_delta, abs(delta))

        # Savol qiyinliklarini yangilash (theta ni ushlab turib)
        for i_id in usable_items:
            observed = sum(1 for p, val in items[i_id].items() if p in theta and val)
            expected = sum(_prob_correct(theta[p], b[i_id]) for p in items[i_id] if p in theta)
            info = sum(
                _prob_correct(theta[p], b[i_id]) * (1 - _prob_correct(theta[p], b[i_id]))
                for p in items[i_id] if p in theta
            )
            if info <= 1e-6:
                continue
            # b ortadi <=> to'g'ri javob kamayadi, shuning uchun ishora teskari.
            delta = (expected - observed) / info
            delta = max(min(delta, 2.0), -2.0)
            b[i_id] = max(min(b[i_id] + delta, LOGIT_CLAMP), -LOGIT_CLAMP)
            max_delta = max(max_delta, abs(delta))

        if max_delta < CONVERGENCE_THRESHOLD:
            converged = True
            break

    # ── Identifikatsiya cheklovi: b ning o'rtachasini 0 ga markazlash
    #    (Rasch modelida shkala erkin joylashadi — odatiy konventsiya). ──
    if b:
        mean_b = sum(b.values()) / len(b)
        b = {k: v - mean_b for k, v in b.items()}
        theta = {k: v - mean_b for k, v in theta.items()}

    result.item_difficulty = {k: round(v, 4) for k, v in b.items()}
    result.person_ability = {k: round(v, 4) for k, v in theta.items()}
    result.n_iterations = it_count
    result.converged = converged
    return result


def item_information(theta: float, b: float) -> float:
    """Rasch modelida savolning berilgan theta nuqtasidagi Fisher
    axboroti: I(theta) = P(1-P). Eng katta qiymatga theta == b da
    erishiladi — shuning uchun test yig'ishda shu mezon ishlatiladi.
    """
    p = _prob_correct(theta, b)
    return p * (1 - p)


def select_items_for_ability(
    candidates: list[tuple[str, float]],
    target_theta: float,
    n_items: int,
    min_gap: float = 0.0,
) -> list[str]:
    """Berilgan (item_id, b) nomzodlar orasidan, `target_theta` uchun
    eng ko'p axborot beradigan `n_items` tasini tanlaydi (Rasch
    modelida bu shunchaki |b - theta| bo'yicha eng yaqinlarini
    tanlashga teng keladi).

    `min_gap` — tanlangan savollarning qiyinliklari orasidagi minimal
    farq; berilsa, test faqat bitta tor qiyinlik nuqtasida
    to'planib qolmaydi (masalan, bosqichma-bosqich adaptiv test uchun
    emas, balki bir martalik "shu darajaga mos" test uchun foydali).
    """
    ranked = sorted(candidates, key=lambda c: abs(c[1] - target_theta))
    selected: list[tuple[str, float]] = []
    for item_id, b in ranked:
        if min_gap > 0 and any(abs(b - sb) < min_gap for _, sb in selected):
            continue
        selected.append((item_id, b))
        if len(selected) >= n_items:
            break

    # Agar min_gap tufayli yetarlicha savol topilmasa, qolganini
    # cheklovsiz to'ldiramiz.
    if len(selected) < n_items:
        chosen_ids = {i for i, _ in selected}
        for item_id, b in ranked:
            if item_id in chosen_ids:
                continue
            selected.append((item_id, b))
            chosen_ids.add(item_id)
            if len(selected) >= n_items:
                break

    return [item_id for item_id, _ in selected]


def test_information_curve(
    item_bs: list[float], theta_range: tuple[float, float] = (-4, 4), step: float = 0.5
) -> list[dict]:
    """Diagnostika/UI uchun: test axborot funksiyasi (TIF) — tanlangan
    savollar to'plami turli qobiliyat darajalarida qanchalik aniq
    o'lchay olishini ko'rsatadi. Eng foydali (aniq) nuqta — TIF eng
    baland bo'lgan joy.
    """
    curve = []
    theta = theta_range[0]
    while theta <= theta_range[1] + 1e-9:
        info = sum(item_information(theta, b) for b in item_bs)
        curve.append({"theta": round(theta, 2), "information": round(info, 4)})
        theta += step
    return curve
