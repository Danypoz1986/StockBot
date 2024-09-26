import yfinance as yf
import requests
from textblob import TextBlob
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import keyring
import json
import os
from datetime import datetime, timedelta
import sys 
sys.stdout.reconfigure(encoding='utf-8')

# File to store previous predictions and stock data
PREDICTIONS_FILE = "predictions.json"

# Fetch stock data with proper alignment
def get_stock_data(ticker, name, period="1mo"):
    stock = yf.Ticker(ticker)
    stock_data = stock.history(period=period)[['Open', 'High', 'Low', 'Close']].tail(5)
    
    # Custom formatting for aligned output with more space between Date and Open
    stock_data_str = f"\n\n{name}:\n\n"
    stock_data_str += f"{'Date':<25} {'Open':<10} {'High':<10} {'Low':<10} {'Close':<10}\n"
    
    for index, row in stock_data.iterrows():
        date_str = index.strftime('%Y-%m-%d')
        stock_data_str += f"{date_str:<25} {row['Open']:<10.2f} {row['High']:<10.2f} {row['Low']:<10.2f} {row['Close']:<10.2f}\n"

    return stock_data_str, stock_data.tail(1)['Close'].values[0]  # Return the formatted string and latest close price

# Perform sentiment analysis on news articles
def check_sentiment():
    news_api_key = "619e6a7b71e64a37bbc4583d5b061eda"  # Replace with your API key
    response = requests.get(f"https://newsapi.org/v2/everything?q=stock&apiKey={news_api_key}")

    if response.status_code != 200:
        print(f"Error: Failed to fetch news, status code {response.status_code}")
        return None

    try:
        articles = response.json().get('articles', [])
        if not articles:
            print("No articles found in the API response.")
            return None

        # Perform sentiment analysis on the articles
        sentiments = [TextBlob(article['description']).sentiment.polarity for article in articles if article['description']]
        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0

        # Convert the sentiment score to a word (positive, negative, neutral)
        if avg_sentiment > 0.1:
            sentiment_word = "positiivinen"
            suggestion = "Osta"
        elif avg_sentiment < -0.1:
            sentiment_word = "negatiivinen"
            suggestion = "Myy"
        else:
            sentiment_word = "neutraali"
            suggestion = "Pidä"

        return avg_sentiment, sentiment_word, suggestion

    except KeyError as e:
        print(f"KeyError: {e} - The 'articles' key is missing from the API response.")
        return None

# Send an email with stock data and sentiment results
def send_email(subject, body):
    sender_email = "daniel.pozzoli86@gmail.com"
    receiver_email = "dap00004@laurea.fi"

    # Retrieve the password from keyring
    password = keyring.get_password("gmail", sender_email)
    
    if password is None:
        print("Error: Could not retrieve password from keyring.")
        return

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print("Sähköposti lähetetty onnistuneesti!")
    except smtplib.SMTPAuthenticationError as e:
        print(f"SMTP Authentication Error: {e}")
    except Exception as e:
        print(f"Sähköpostin lähetys epäonnistui: {e}")

# Save the current predictions to a file
def save_predictions(predictions):
    with open(PREDICTIONS_FILE, "w") as f:
        json.dump(predictions, f)

# Load the previous predictions from a file
def load_previous_predictions():
    if os.path.exists(PREDICTIONS_FILE):
        with open(PREDICTIONS_FILE, "r") as f:
            return json.load(f)
    return None

# Compare predictions with actual stock movements and return results in Finnish
def compare_predictions(prev_predictions, companies):
    if not prev_predictions:
        return "Ei aiempia ennusteita vertailtavaksi."

    comparison_results = ""
    for ticker, data in prev_predictions.items():
        company_name = companies.get(ticker, ticker)  # Fetch the company name using the ticker
        prev_close = data['close']
        current_close = yf.Ticker(ticker).history(period="1d").tail(1)['Close'].values[0]
        prediction = data['suggestion']

        if prediction == "Osta" and current_close > prev_close:
            comparison_results += f"{company_name}: Ennuste oli oikea (Osta).\n"
        elif prediction == "Myy" and current_close < prev_close:
            comparison_results += f"{company_name}: Ennuste oli oikea (Myy).\n"
        elif prediction == "Pidä" and abs(current_close - prev_close) < 0.5:  # Assume <0.5 difference means stable
            comparison_results += f"{company_name}: Ennuste oli oikea (Pidä).\n"
        else:
            comparison_results += f"{company_name}: Ennuste oli väärä (Ennustettu {prediction}, mutta hinta {'nousi' if current_close > prev_close else 'laski'}).\n"

    return comparison_results

if __name__ == "__main__":
    # List of company tickers and full names
    companies = {
        "NOKIA.HE": "Nokia Oyj",
        "KNEBV.HE": "Kone Oyj",
        "NESTE.HE": "Neste Oyj",
        "FORTUM.HE": "Fortum Oyj",
        "SAMPO.HE": "Sampo Oyj",
        "UPM.HE": "UPM-Kymmene Oyj",
        "OUT1V.HE": "Outokumpu Oyj",
        "ORNBV.HE": "Orion Oyj",
        "KESKOA.HE": "Kesko Oyj",
        "STERV.HE": "Stora Enso Oyj"
    }

    prev_predictions = load_previous_predictions()
    comparison_results = compare_predictions(prev_predictions, companies)

    # Fetch and format stock data for each company and save predictions
    stock_data_str = ""
    predictions = {}

    for ticker, name in companies.items():
        stock_str, latest_close = get_stock_data(ticker, name)
        stock_data_str += stock_str
        
        sentiment = check_sentiment()
        if sentiment:
            _, sentiment_word, suggestion = sentiment
            predictions[ticker] = {"suggestion": suggestion, "close": latest_close}
    
    # Save current predictions
    save_predictions(predictions)

    # Prepare email body
    email_subject = "Pörssimarkkinoiden analyysipäivitys"
    email_body = (
        f"Osakedata (viimeiset 5 päivää):\n{stock_data_str}\n\n"
        f"Viime viikon ennusteiden vertailu:\n{comparison_results}\n\n"
        f"Sentimenttipisteet: {sentiment_word}\n\n"
        f"Markkinasuositus: {suggestion}\n"
    )

    # Send the email
    send_email(email_subject, email_body)