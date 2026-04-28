"""
Wycena polskich obligacji skarbowych detalicznych.
Dane kuponów i dat wykupu na podstawie publicznych warunków emisji MF.
"""

from datetime import date, datetime

# Słownik: kod -> (data_wykupu, kupon_roczny_%, typ)
# typ: 'fixed' = stałoprocentowe, 'indexed' = indeksowane inflacją (przybliżenie)
BOND_PARAMS = {
    # TOS - 3-letnie stałoprocentowe
    "TOS0428": (date(2028, 4, 1),  6.20, "fixed"),
    "TOS0528": (date(2028, 5, 1),  6.20, "fixed"),
    "TOS0628": (date(2028, 6, 1),  6.20, "fixed"),
    "TOS0728": (date(2028, 7, 1),  6.20, "fixed"),
    "TOS0928": (date(2028, 9, 1),  5.90, "fixed"),
    "TOS1028": (date(2028, 10, 1), 5.75, "fixed"),
    "TOS1128": (date(2028, 11, 1), 5.75, "fixed"),
    "TOS1228": (date(2028, 12, 1), 5.75, "fixed"),
    "TOS0129": (date(2029, 1, 1),  5.75, "fixed"),
    "TOS0229": (date(2029, 2, 1),  5.75, "fixed"),
    "TOS0329": (date(2029, 3, 1),  5.75, "fixed"),
    # EDO - 10-letnie indeksowane inflacją
    "EDO1135": (date(2035, 11, 1), 2.00, "indexed"),
    "EDO0436": (date(2036, 4, 1),  2.00, "indexed"),
    "EDO0536": (date(2036, 5, 1),  2.00, "indexed"),
    # COI - 4-letnie indeksowane inflacją
    "COI0429": (date(2029, 4, 1),  1.50, "indexed"),
    "COI0529": (date(2029, 5, 1),  1.50, "indexed"),
    # ROS - 6-letnie oszczędnościowe
    "ROS0432": (date(2032, 4, 1),  6.80, "fixed"),
    "ROS0532": (date(2032, 5, 1),  6.80, "fixed"),
}

# Przybliżona inflacja do wyceny obligacji indeksowanych
APPROX_INFLATION = 4.5


def estimate_bond_price(ticker: str, quantity: float, avg_price: float) -> float | None:
    """
    Szacuje aktualną wartość obligacji na podstawie naliczonych odsetek.
    Zwraca wartość w PLN lub None jeśli ticker nieznany.
    """
    params = BOND_PARAMS.get(ticker.upper())
    if not params:
        return None

    maturity, coupon_rate, bond_type = params
    today = date.today()

    if today >= maturity:
        # Obligacja wygasła — wartość nominalna
        return quantity * 100.0

    # Koszt zakupu = ilość * cena (cena to wartość nominalna 100 PLN)
    cost = quantity * avg_price

    # Ile czasu minęło od zakupu (przybliżenie: liczymy od początku roku emisji)
    # Dla uproszczenia liczymy narosłe odsetki od daty zakupu
    # avg_price to cena zakupu per sztuka (≈100 PLN)

    # Lata do wykupu
    days_total = (maturity - today).days
    years_total = days_total / 365.25

    if bond_type == "fixed":
        effective_rate = coupon_rate / 100
    else:
        # Indeksowane inflacją: kupon + inflacja
        effective_rate = (coupon_rate + APPROX_INFLATION) / 100

    # Prosta wycena: wartość bieżąca przy założeniu trzymania do wykupu
    # Narosłe odsetki od momentu zakupu (przybliżenie liniowe)
    # Zakładamy że kupono jest wypłacane co rok i reinwestowane
    # Wartość = nominał * (1 + stopa)^lata_trzymania
    # Zakładamy że trzymamy od daty pierwszego zakupu

    # Uproszczenie: wartość = koszt * (1 + roczna_stopa * ułamek_roku_do_wykupu)
    # To nie jest dokładna wycena rynkowa — to szacunek wartości przy wykupie
    # Lepsza wycena: narosłe odsetki od zakupu

    # Bezpieczne uproszczenie: wartość nominalna + szacowane narosłe odsetki
    # Zakładamy zakup po 100 PLN, odsetki narastają liniowo w ciągu roku
    days_since_issue = 365 - days_total % 365
    accrued_per_unit = 100 * effective_rate * (days_since_issue / 365)
    current_value = quantity * (avg_price + accrued_per_unit)

    return round(current_value, 2)


def is_bond(ticker: str) -> bool:
    """Sprawdza czy ticker to obligacja skarbowa."""
    prefixes = ["TOS", "EDO", "COI", "ROS", "DOS", "OTS", "IKE", "IKZ"]
    return any(ticker.upper().startswith(p) for p in prefixes)


def get_bond_info(ticker: str) -> dict | None:
    """Zwraca informacje o obligacji."""
    params = BOND_PARAMS.get(ticker.upper())
    if not params:
        return None
    maturity, coupon, bond_type = params
    return {
        "maturity": maturity.strftime("%Y-%m-%d"),
        "coupon": coupon,
        "type": bond_type,
        "days_to_maturity": (maturity - date.today()).days,
    }