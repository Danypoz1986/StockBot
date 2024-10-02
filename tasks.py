import yfinance as yf
import requests
from textblob import TextBlob
import boto3
import os
import json
from robocorp import task
from datetime import datetime

# Set up AWS services
s3 = boto3.client('s3')
ses = boto3.client('ses')
secretsmanager = boto3.client('secretsmanager')

BUCKET_NAME = os.getenv('S3_BUCKET_NAME')  # Ensure you set this environment variable
PREDICTIONS_FILE = "Stock_Predictions.json"

# Fetch API key from AWS Secrets Manager
def get_secret(secret_name):
    try:
        response = secretsmanager.get_secret_value(SecretId=secret_name)
        secret = json.loads(response['SecretString'])
        return secret
    except Exception as e:
        print(f"Error retrieving secret: {e}")
        return None

# Fetch stock data
def get_stock_data(ticker, name, period="1mo"):
    stock = yf.Ticker(ticker)
    stock_data = stock.history(period=period)[['Open', 'High', 'Low', 'Close']].tail(5)
    stock_data_str = f"\n\n{name}:\n\n"
    stock_data_str += f"{'Date':<25} {'Open':<10} {'High':<10} {'Low':<10} {'Close':<10}\n"

    for index, row in stock_data.iterrows():
        date_str = index.strftime('%d-%m-%Y')
        stock_data_str += f"{date_str:<25} {row['Open']:<10.2f} {row['High']:<10.2f} {row['Low']:<10.2f} {row['Close']:<10.2f}\n"
        
    return stock_data_str, stock_data.tail(1)['Close'].values[0]

# Check sentiment using a news API
def check_sentiment():
    # Fetch secrets from AWS Secrets Manager
    secrets = get_secret('wpmgIpa')  # Use your actual secret name: 'wpmgIpa'
    
    # Retrieve the API key from the secrets
    api_key = secrets.get('Api_Key')  # Make sure 'Api_Key' is the key you stored in Secrets Manager
    
    if not api_key:
        print("API key not found.")
        return None

    # Make the API request using the retrieved API key
    response = requests.get(f"https://newsapi.org/v2/everything?q=stock&apiKey={api_key}")
    
    if response.status_code != 200:
        print(f"Error fetching news: {response.status_code}")
        return None

    articles = response.json().get('articles', [])
    if not articles:
        print("No articles found.")
        return None

    # Analyze sentiment
    sentiments = [TextBlob(article['description']).sentiment.polarity for article in articles if article['description']]
    if not sentiments:
        return 0, "neutraali", "Pidä"
    
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
    
    try:
        ses.send_email(
            Source=sender_email,
            Destination={'ToAddresses': receiver_emails},
            Message={
                'Subject': {'Data': subject},
                'Body': {'Text': {'Data': body}}
            }
        )
        print("Email sent successfully.")
    except Exception as e:
        print(f"Error sending email: {e}")


# Save predictions to S3
def save_predictions(predictions):
    print(f"Saving predictions: {predictions}")
    try:
        s3.put_object(Bucket=BUCKET_NAME, Key=PREDICTIONS_FILE, Body=json.dumps(predictions))
        print("Predictions saved successfully.")
    except Exception as e:
        print(f"Error saving to S3: {e}")

# Load predictions from S3
def load_previous_predictions():
    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=PREDICTIONS_FILE)
        predictions = json.loads(response['Body'].read().decode('utf-8'))
        print("Previous predictions loaded successfully.")
        return predictions
    except Exception as e:
        print(f"No previous predictions available. Error: {e}")
        return None

# Compare predictions with actual stock data
def compare_predictions(prev_predictions, companies):
    if not prev_predictions:
        return "No previous predictions to compare."

    comparison_results = ""
    for ticker, data in prev_predictions.items():
        company_name = companies.get(ticker, ticker)
        prev_close = data['close']
        current_close = yf.Ticker(ticker).history(period="1d").tail(1)['Close'].values[0]

        if prev_close and current_close:
            if current_close > prev_close:
                comparison_results += f"{company_name}: Prediction was correct (Osta).\n"
            elif current_close < prev_close:
                comparison_results += f"{company_name}: Prediction was correct (Myy).\n"
            else:
                comparison_results += f"{company_name}: Prediction was correct (Pidä).\n"
        else:
            comparison_results += f"{company_name}: No previous data for comparison.\n"
    
    return comparison_results

@ task
 
def main(event, context):
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

    # Load previous predictions from S3
    prev_predictions = load_previous_predictions()

    # Compare the previous predictions with the current data
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
            print(f"Sentiment analysis failed for {name}, skipping...")

    # Save current predictions to S3
    save_predictions(predictions)

    # Prepare email content
    email_subject = "Stock Market Analysis Update"
    email_body = (
        f"Stock data (last 5 days):\n{stock_data_str}\n\n"
        f"Comparison with last week's predictions:\n{comparison_results}\n\n"
        f"Sentiment Score: {sentiment_word}\n\n"
        f"Market Recommendation: {suggestion}\n"
    )

    # Send email only at 18:00 or later, but only once per day
    current_time = datetime.now().time()
    last_run_time = os.getenv("LAST_RUN_TIME", None)

    if current_time >= datetime.strptime("18:00", "%H:%M").time():
        if not last_run_time or last_run_time != datetime.now().date().isoformat():
            send_email(email_subject, email_body)
            os.environ["LAST_RUN_TIME"] = datetime.now().date().isoformat()

# Call the main function when Lambda is triggered
if __name__ == "__main__":
    main({}, {})
