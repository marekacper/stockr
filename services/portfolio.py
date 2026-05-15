TRANSACTIONS_FILE = "data/stockr.db"
 
 
def ensure_file():
    from services.portfolios import ensure_setup
    ensure_setup()
 
 
def get_transactions() -> list[dict]:
    from services.portfolios import get_transactions_for
    return get_transactions_for("default")
 
 
def add_transaction(ticker, date, type, quantity, price, commission):
    from services.portfolios import add_transaction_to
    add_transaction_to("default", ticker, date, type, quantity, price, commission)
 
 
def get_portfolio() -> dict:
    from services.portfolios import get_portfolio_holdings
    return get_portfolio_holdings("default")
 