import yfinance as yf
from robocorp.tasks import task
from RPA.Robocorp.Vault import Vault
import requests
from textblob import TextBlob
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
import os
import sys

# Optional UTF-8 reconfiguration
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

PREDICTIONS_FILE = "predictions.json"

# Set the artifact directory and path for the predictions file
ARTIFACTS_DIR = os.getenv("ROBOT_ARTIFACTS", "artifacts")  # Environment variable or default "artifacts"
PREDICTIONS_FILE = os.path.join(ARTIFACTS_DIR, "predictions.json")  # Set the path for the predictions.json file

def get_stock_data(ticker, name, period="1mo"):
    stock = yf.Ticker(ticker)
    stock_data = stock.history(period=period)[['Open', 'High', 'Low', 'Close']].tail(5)
    stock_data_str = f"\n\n{name}:\n\n"
    stock_data_str += f"{'Date':<25} {'Open':<10} {'High':<10} {'Low':<10} {'Close':<10}\n"
    
    for index, row in stock_data.iterrows():
        date_str = index.strftime('%d-%m-%Y')
        stock_data_str += f"{date_str:<25} {row['Open']:<10.2f} {row['High']:<10.2f} {row['Low']:<10.2f} {row['Close']:<10.2f}\n"
        
    return stock_data_str, stock_data.tail(1)['Close'].values[0]

def check_sentiment():
    
    # Access the Vault
    vault = Vault()
    
    # Get the Gmail password from Vault
    secrets = vault.get_secret("Api_Key")
    news_api_key = secrets.get("apiKey")  
    
    if not news_api_key:
        print("Virhe: API-avain ei löytynyt.")
        return None

    response = requests.get(f"https://newsapi.org/v2/everything?q=stock&apiKey={news_api_key}")
    if response.status_code != 200:
        print(f"Virhe: Uutisten haku epäonnistui, tilakoodi {response.status_code}")
        return None

    articles = response.json().get('articles', [])
    if not articles:
        print("Artikkeleita ei löytynyt API-vastauksesta.")
        return None

    sentiments = [TextBlob(article['description']).sentiment.polarity for article in articles if article['description']]
    if not sentiments:
        print("Artikkeleista ei löytynyt kelvollisia tunteita.")
        return 0, "neutraali", "Pidä"  # Return neutral sentiment and suggestion
    
    avg_sentiment = sum(sentiments) / len(sentiments)
    if avg_sentiment > 0.1:
        return avg_sentiment, "positiivinen", "Osta"
    elif avg_sentiment < -0.1:
        return avg_sentiment, "negatiivinen", "Myy"
    else:
        return avg_sentiment, "neutraali", "Pidä"

def send_email(subject, body):
    sender_email = "daniel.pozzoli86@gmail.com"
    receiver_emails = ["dap00004@laurea.fi"]

    # Access the Vault
    vault = Vault()

    # Get the Gmail password from Vault
    secrets = vault.get_secret("GMAIL_pw")
    gmail_password = secrets.get("GMAIL_PASSWORD")  # Ensure the key name matches the Vault

    if not gmail_password:
        print("Virhe: Salasanaa ei saatu haettua holvista.")
        return

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = ", ".join(receiver_emails)
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, gmail_password)  # Use the retrieved password
            server.sendmail(sender_email, receiver_emails, msg.as_string())
        print("Sähköpostit lähetetty onnistuneesti!")
    except smtplib.SMTPAuthenticationError as e:
        print(f"SMTP-todennusvirhe: {e}")
    except Exception as e:
        print(f"Sähköpostin lähetys epäonnistui: {e}")

# Save the current predictions to a file
def save_predictions(predictions):
    print(f"Saving predictions: {predictions}")  # Debugging print statement
    with open(PREDICTIONS_FILE, "w") as f:
        json.dump(predictions, f)
    print("Predictions saved successfully.")

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

@task 

def main():
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
    sentiment_word = "unknown"
    suggestion = "unknown"

    for ticker, name in companies.items():
        stock_str, latest_close = get_stock_data(ticker, name)
        stock_data_str += stock_str

        sentiment = check_sentiment()
        if sentiment:
            _, sentiment_word, suggestion = sentiment
            predictions[ticker] = {"suggestion": suggestion, "close": latest_close}
        else:
            print(f"Sentimenttianalyysi epäonnistui {name}, ohitetaan...")

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

if __name__ == "__main__":
    main()