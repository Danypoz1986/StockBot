import yfinance as yf
from robocorp.tasks import task
from RPA.Robocorp.Vault import Vault
import requests
from textblob import TextBlob
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from robocorp import storage
from datetime import datetime
import sys


# Optional UTF-8 reconfiguration
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

# Set a threshold for significant stock price changes
THRESHOLD_PERCENTAGE = 5  # 5% change

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
    
    # Get the API key from the vault
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
    receiver_emails = ["dap00004@laurea.fi", "janne.juote@student.laurea.fi", "kati.tuukkanen@student.laurea.fi"]

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

def send_threshold_email(company_name, direction, prev_close, current_close, percentage_change):
    subject = f"Tärkeä ilmoitus: {company_name} osake on {direction}"
    body = (
        f"Yritys: {company_name}\n"
        f"Edellinen Close: {prev_close}\n"
        f"Nykyinen Close: {current_close}\n"
        f"Muutosprosentti: {percentage_change:.2f}%\n"
        f"Osake on {direction} merkittävästi."
    )

    # Send the email immediately with the stock details
    send_email(subject, body)

def save_predictions(predictions):
    print(f"Tallennetaan ennusteet: {predictions}")

    # Save the predictions as a JSON asset in the cloud
    storage.set_json("Stock_Predictions", predictions)
    print("Ennusteet tallennettu onnistuneesti.")

# Load the previous predictions from an asset
def load_previous_predictions():
    try:
        predictions = storage.get_json("Stock_Predictions")
        print("Aikaisemmat ennusteet ladattu onnistuneesti.")
        return predictions
    except Exception as e:
        print(f"Ei aiempia ennusteita vertailtavaksi. Error: {e}")
        return None

def compare_predictions(prev_predictions, companies):
    if not prev_predictions:
        return "Ei aiempia ennusteita vertailtavaksi."

    comparison_results = ""
    for ticker, data in prev_predictions.items():
        company_name = companies.get(ticker, ticker)
        prev_close = data['close']
        current_close = yf.Ticker(ticker).history(period="1d").tail(1)['Close'].values[0]

        percentage_change = ((current_close - prev_close) / prev_close) * 100

        if percentage_change > THRESHOLD_PERCENTAGE:
            send_threshold_email(company_name, "noussut merkittävästi", prev_close, current_close, percentage_change)
            comparison_results += f"{company_name}: Osake on noussut merkittävästi (Muutos: +{percentage_change:.2f}%).\n"
        elif percentage_change < -THRESHOLD_PERCENTAGE:
            send_threshold_email(company_name, "laskenut merkittävästi", prev_close, current_close, percentage_change)
            comparison_results += f"{company_name}: Osake on laskenut merkittävästi (Muutos: {percentage_change:.2f}%).\n"
        else:
            comparison_results += f"{company_name}: Ennuste oli oikea (Pidä).\n"

    return comparison_results

@task 
def main():
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

    save_predictions(predictions)

    email_subject = "Pörssimarkkinoiden analyysipäivitys"
    email_body = (
        f"Osakedata (viimeiset 5 päivää):\n{stock_data_str}\n\n"
        f"Viime viikon ennusteiden vertailu:\n{comparison_results}\n\n"
        f"Sentimenttipisteet: {sentiment_word}\n\n"
        f"Markkinasuositus: {suggestion}\n"
    )

    current_hour = datetime.now().hour
    if current_hour == 18:
        send_email(email_subject, email_body)

if __name__ == "__main__":
    main()
