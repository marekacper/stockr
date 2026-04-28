import pandas as pd
import re
import os
from services.portfolio import get_transactions, TRANSACTIONS_FILE
import csv

FIELDNAMES = ["ticker", "date", "type", "quantity", "price", "commission"]


def parse_xtb_xlsx(filepath: str) -> list[dict]:
    """Parsuje eksport z XTB (Cash Operations)."""
    df = pd.read_excel(filepath, sheet_name='Cash Operations', header=3)
    df.columns = ['Type', 'Ticker', 'Instrument', 'Time', 'Amount', 'ID', 'Comment', 'Product']

    purchases = df[df['Type'] == 'Stock purchase'].copy()
    if purchases.empty:
        return []

    purchases['Time'] = pd.to_datetime(purchases['Time'])
    purchases['date'] = purchases['Time'].dt.strftime('%Y-%m-%d')
    purchases['Amount'] = purchases['Amount'].astype(float).abs()
    purchases['second'] = purchases['Time'].dt.floor('s')

    def parse_price(comment):
        m = re.search(r'@ ([\d.]+)', str(comment))
        return float(m.group(1)) if m else None

    purchases['price'] = purchases['Comment'].apply(parse_price)
    purchases['qty'] = purchases.apply(
        lambda r: abs(r['Amount']) / r['price'] if r['price'] else 0, axis=1
    )

    grouped = purchases.groupby(['Ticker', 'second', 'date']).agg(
        quantity=('qty', 'sum'),
        price=('price', 'first'),
    ).reset_index()

    result = []
    for _, row in grouped.iterrows():
        result.append({
            "ticker": row['Ticker'],
            "date": row['date'],
            "type": "buy",
            "quantity": round(float(row['quantity']), 4),
            "price": round(float(row['price']), 2),
            "commission": 0.0,
        })
    return result


def merge_transactions(new_rows: list[dict]) -> dict:
    """Scala nowe transakcje z istniejącymi, pomija duplikaty."""
    existing = get_transactions()

    # Klucz unikalności: ticker + date + type + quantity + price
    def make_key(t):
        return (t['ticker'], t['date'], t['type'], str(t['quantity']), str(t['price']))

    existing_keys = {make_key(t) for t in existing}

    added = 0
    skipped = 0

    os.makedirs("data", exist_ok=True)
    with open(TRANSACTIONS_FILE, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        for row in new_rows:
            key = make_key(row)
            if key not in existing_keys:
                writer.writerow(row)
                existing_keys.add(key)
                added += 1
            else:
                skipped += 1

    return {"added": added, "skipped": skipped}

def parse_obligacje_xls(filepath: str) -> list[dict]:
    """Parsuje eksport historii dyspozycji obligacji skarbowych (PKO/BOS)."""
    df = pd.read_excel(filepath, sheet_name=0)
    df.columns = [c.strip().upper() for c in df.columns]

    # Zostaw tylko zrealizowane zakupy papierów
    df = df[
        (df['STATUS'].str.strip().str.lower() == 'zrealizowana') &
        (df['RODZAJ DYSPOZYCJI'].str.strip().str.lower() == 'zakup papierów')
    ].copy()

    if df.empty:
        return []

    df['DATA DYSPOZYCJI'] = pd.to_datetime(df['DATA DYSPOZYCJI']).dt.strftime('%Y-%m-%d')
    df['KWOTA OPERACJI'] = df['KWOTA OPERACJI'].astype(str).str.replace(' ', '').str.replace(',', '.').str.replace('\xa0', '').astype(float)
    df['LICZBA OBLIGACJI'] = pd.to_numeric(df['LICZBA OBLIGACJI'], errors='coerce')

    result = []
    for _, row in df.iterrows():
        qty = float(row['LICZBA OBLIGACJI'])
        kwota = float(row['KWOTA OPERACJI'])
        if qty <= 0:
            continue
        price = round(kwota / qty, 4)
        ticker = str(row['KOD OBLIGACJI']).strip()

        result.append({
            "ticker": ticker,
            "date": row['DATA DYSPOZYCJI'],
            "type": "buy",
            "quantity": qty,
            "price": price,
            "commission": 0.0,
        })

    return result