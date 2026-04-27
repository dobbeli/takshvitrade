from .nse import get_nse_data

def get_stock_data(symbol):

    if symbol.endswith(".NS"):
        return get_nse_data(symbol)

    print(f"Unsupported symbol: {symbol}")
    return None