import yfinance as yf
import time

def get_nse_data(symbol):
    try:
        print(f"📡 Fetch NSE: {symbol}")

        for i in range(3):
            df = yf.download(
                symbol,
                period="6mo",
                interval="1d",
                progress=False,
                threads=False
            )

            if df is not None and not df.empty:
                df = df.dropna()

                if len(df) >= 150:
                    print(f"✅ Data OK: {symbol}")
                    return df

            print(f"⚠️ Retry {i+1}: {symbol}")
            time.sleep(1)

        print(f"❌ Failed: {symbol}")
        return None

    except Exception as e:
        print(f"⚠️ Error: {symbol} | {e}")
        return None