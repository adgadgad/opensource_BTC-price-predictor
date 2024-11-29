import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import numpy as np
import pandas as pd
import requests
import schedule
import ta
from alpha_vantage.timeseries import TimeSeries
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
from ta import add_all_ta_features

api_keys = ["IOBHACZOQONDVU8B"]

def get_alpha_vantage_btc_history(api_keys):
    for api_key in api_keys:
        try:
            time.sleep(6)
            ts = TimeSeries(key=api_key)
            btc_data, meta_data = ts.get_daily(symbol='BTCUSD', outputsize='full')
            timestamps = list(btc_data.keys())
            open_prices = [float(btc_data[ts]['1. open']) for ts in timestamps]
            high_prices = [float(btc_data[ts]['2. high']) for ts in timestamps]
            low_prices = [float(btc_data[ts]['3. low']) for ts in timestamps]
            close_prices = [float(btc_data[ts]['4. close']) for ts in timestamps]
            volumes = [int(btc_data[ts]['5. volume']) for ts in timestamps]
            df = pd.DataFrame({
                "Timestamp": timestamps,
                "open": open_prices,
                "high": high_prices,
                "low": low_prices,
                "volume": volumes,
                "close": close_prices
            })
            df["Date"] = pd.to_datetime(df["Timestamp"])
            df.to_csv("btc_price_data_alpha_vantage.csv", index=False)
            dfr = df[::-1]
            dfr.to_csv("btc_price_data_alpha_vantage_ful.csv", index=False)
            print("Saved full BTC price data from Alpha Vantage to btc_price_data_alpha_vantage_full.csv")
            return dfr
        except Exception as e:
            print(f"Error fetching BTC price using {api_key}: {str(e)}")
            time.sleep(5)

    try:
        df = pd.read_csv("btc_price_data_alpha_vantage_ful.csv")
        todays_date = pd.to_datetime(pd.Timestamp.now().strftime('%Y-%m-%d'))
        if todays_date in df['Date'].values:
            yesterdays_volume = df[df['Date'] == (todays_date - pd.Timedelta(days=1))]['volume'].values[0]
            current_price = get_current_btc_price()
            df.loc[df['Date'] == todays_date, ['open', 'high', 'low', 'close']] = current_price
            df.loc[df['Date'] == todays_date, ['volume']] = yesterdays_volume
        else:
            current_price = get_current_btc_price()
            new_row = pd.DataFrame({
                "Timestamp": pd.Timestamp.now().strftime('%Y-%m-%d'),
                "open": current_price,
                "high": current_price,
                "low": current_price,
                "volume": 0,
                "close": current_price,
                "Date": todays_date
            }, index=[0])
            df = pd.concat([df, new_row], ignore_index=True)
        df.to_csv("btc_price_data_alpha_vantage_ful.csv", index=False)
        print("Updated BTC price data in btc_price_data_alpha_vantage_ful.csv")
        return df
    except Exception as e:
        print(f"Error updating BTC data: {str(e)}")
        raise

def get_current_btc_price():
    try:
        url = "https://api.coindesk.com/v1/bpi/currentprice.json"
        time.sleep(1)
        response = requests.get(url)
        data = response.json()
        btc_price = data["bpi"]["USD"]["rate"]
        return float(btc_price.replace(",", ""))
    except Exception as e:
        return f"Error fetching BTC price: {str(e)}"

btc_history = get_alpha_vantage_btc_history(api_keys)

btc_data = pd.read_csv("btc_price_data_alpha_vantage_ful.csv")

def predict_price_trend(btc_data, period=5):
    btc_data["SMA_20"] = btc_data["close"].rolling(window=20).mean()
    btc_data["EMA_50"] = btc_data["close"].ewm(span=50, adjust=False).mean()
    btc_data = add_all_ta_features(btc_data, "open", "high", "low", "close", "volume", fillna=True)
    btc_data["RSI"] = btc_data["momentum_rsi"]
    btc_data["EMA_12"] = btc_data["close"].ewm(span=12, adjust=False).mean()
    btc_data["EMA_26"] = btc_data["close"].ewm(span=26, adjust=False).mean()
    btc_data["MACD"] = btc_data["EMA_12"] - btc_data["EMA_26"]
    btc_data["Signal_Line"] = btc_data["MACD"].ewm(span=9, adjust=False).mean()
    btc_data["Upper_Band"], btc_data["Lower_Band"] = (
        btc_data["SMA_20"] + 2 * btc_data["close"].rolling(window=20).std(),
        btc_data["SMA_20"] - 2 * btc_data["close"].rolling(window=20).std(),
    )
    btc_data["ADX"] = ta.trend.ADXIndicator(
        btc_data["high"], btc_data["low"], btc_data["close"], window=14
    ).adx()
    btc_data["Stochastic_K"] = (
        (btc_data["close"] - btc_data["low"].rolling(window=14).min())
        / (btc_data["high"].rolling(window=14).max() - btc_data["low"].rolling(window=14).min())
    ) * 100
    X = btc_data[["SMA_20", "EMA_50", "RSI", "MACD", "ADX", "Stochastic_K"]]
    y = btc_data["close"]
    imputer = SimpleImputer(strategy="mean", missing_values=np.nan)
    X = imputer.fit_transform(X)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = RandomForestRegressor(n_estimators=270, max_depth=14)
    model.fit(X_train, y_train)
    next_price = model.predict([[btc_data["SMA_20"].iloc[-1], btc_data["EMA_50"].iloc[-1], btc_data["RSI"].iloc[-1],
                                 btc_data["MACD"].iloc[-1], btc_data["ADX"].iloc[-1], btc_data["Stochastic_K"].iloc[-1]]])

    if period == 5:
        five_day_prices = [next_price[0]]
        for i in range(1, period):
            next_price = model.predict([[five_day_prices[i-1], btc_data["EMA_50"].iloc[-1], btc_data["RSI"].iloc[-1],
                                         btc_data["MACD"].iloc[-1], btc_data["ADX"].iloc[-1], btc_data["Stochastic_K"].iloc[-1]]])
            five_day_prices.append(next_price[0])
        return five_day_prices
    return next_price[0]


def update_predictions():
    current_price = get_current_btc_price()
    btc_history = get_alpha_vantage_btc_history(api_keys)
    tomorrow_price = predict_price_trend(btc_data)
    five_day_prices = predict_price_trend(btc_data, period=5)
    tomorrow_price = float(tomorrow_price[0])
    five_day_prices = [float(price) for price in five_day_prices]
    five_day_prices_with_index = enumerate(five_day_prices)
    price_comparison = ""
    recommendation = ""
    if tomorrow_price > current_price:
        percentage_increase = round(((tomorrow_price - current_price) / current_price) * 100, 2)
        price_comparison = f"Tomorrow's price is predicted to be {percentage_increase}% higher than today's price."
        if percentage_increase > 0.2:
            recommendation = "Buy 10% of your BTC amount."
        else:
            recommendation = "Buy a small percentage of your current BTC like 4 to 2 percent, or nothing."

    elif tomorrow_price < current_price:
        percentage_decrease = round(((current_price - tomorrow_price) / current_price) * 100, 2)
        price_comparison = f"Tomorrow's price is predicted to be {percentage_decrease}% lower than today's price."
        if percentage_decrease > 0.1:
            recommendation = "Sell 5% of your BTC."
        else:
            recommendation = "Do nothing or sell a really small percentage of BTC like 2% or do nothing."
    else:
        price_comparison = "Tomorrow's price is predicted to remain the same."
    global current_price_global, tomorrow_price_global, five_day_prices_with_index_global, price_comparison_global, recommendation_global
    current_price_global = current_price
    tomorrow_price_global = tomorrow_price
    five_day_prices_with_index_global = five_day_prices_with_index
    price_comparison_global = price_comparison
    recommendation_global = recommendation

schedule.every(200).minutes.do(update_predictions)

update_predictions()

class S(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET')
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        response = {
            'current_price': current_price_global,
            'tomorrow_price': tomorrow_price_global,
            'price_comparison': price_comparison_global,
            'recommendation': recommendation_global
        }
        self.wfile.write(json.dumps(response).encode('utf-8'))

    def do_POST(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET')
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status": "POST request received"}')

def run_server(server_class=HTTPServer, handler_class=S, port=8080):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f'Starting httpd server on port {port}')

    def handle_get_request():
        # Here is where the code for handling GET requests goes
        # You'll need to modify it to suit your specific needs
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET')
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        response = {
            'current_price': current_price_global,
            'tomorrow_price': tomorrow_price_global,
            'price_comparison': price_comparison_global,
            'recommendation': recommendation_global
        }
        self.wfile.write(json.dumps(response).encode('utf-8'))

    schedule.every(1).minutes.do(handle_get_request)

    httpd.serve_forever()

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(200)

if __name__ == '__main__':
    from threading import Thread
    scheduler_thread = Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    run_server()