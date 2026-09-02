from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import os
import smtplib

# load secrets (API key, Gmail creds) from the .env file into the environment
load_dotenv()

api_key = os.environ.get("ANTHROPIC_API_KEY")
gmail_address = os.environ.get("GMAIL_ADDRESS")
gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD")

import anthropic
client = anthropic.Anthropic(api_key=api_key)

import pandas as pd

# load the data into df
try:
    df = pd.read_excel("/Users/shreeyanakarmi/Desktop/anamoly-agent/raw_business_metrics.xlsx")
except Exception as e:
    # if no file is found, print an error message and exit the program
    print(f"Error loading the file: {e}")
    exit(1)

# format the date column 
df['Date'] = pd.to_datetime(df['Date'])

# every meteric we want to analyze for anomalies
metrics = ['Website_Sessions', 'Conversion_Rate_%', 'Orders', 'Avg_Order_Value_$', 'Revenue_$', 'Marketing_Spend_$', 'New_Customers', 'Support_Tickets']

# Calucalate z-scores for each metric and find anomalies
def cal_zscores(df, column_name, window=14):
    s = df[column_name]
    rolling_mean = s.rolling(window=window).mean().shift(1)
    rolling_std = s.rolling(window=window).std().shift(1)
    z_score = (s - rolling_mean) / rolling_std
    return z_score


def find_anomalies(df, column_name, threshold=3, window=14):
    z_score = cal_zscores(df, column_name, window)
    # keep only the rows where the z-score crosses the threshold;
    # .copy() makes this a fully independent DataFrame, not just a view into df,
    # so adding a new column below doesn't risk touching df or triggering a warning
    anomalies = df[abs(z_score) > threshold].copy()
    anomalies['z_score'] = z_score[abs(z_score) > threshold]
    return anomalies[['Date', column_name, 'z_score']]

# laod all the anomalies into a list 
all_anomalies = []

for metric in metrics:
    result = find_anomalies(df, metric)
    for _, row in result.iterrows():
        all_anomalies.append({
            "Date": row["Date"],
            "Metrics": metric,
            "Value": row[metric],
            "Z-scores": row["z_score"]
        })

# Build the prompt for the LLM
def build_prompt(all_anomalies):
    lines = []

    for anomaly in all_anomalies:
        lines.append(f"{anomaly['Metrics']} on {anomaly['Date']}: value {anomaly['Value']}, z-score {anomaly['Z-scores']:.1f}")

    anomaly_text = "\n".join(lines)

    prompt = f"""You are analyzing anomalies detected in a DTC (direct-to-consumer) e-commerce business's daily metrics.

    The following anomalies were detected today:
    {anomaly_text}

    Write a short, business-facing summary (3-5 sentences) explaining what likely happened, connecting related metrics where relevant, and suggesting one next step to investigate. Do not just restate the numbers -- add interpretation."""

    return prompt

# call the LLM to generate a summary of the anomalies
def llm_summary(all_anomalies):
    prompt = build_prompt(all_anomalies)
    try:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=400, # ceiling on how long the response can be, not a target
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    
    except Exception as e:
        print(f"Error connecting to API: {e}")
        return "Error generating summary. Please check the API connection and try again."

# Format the email and send it to the user
def send_email(subject, body):
    msg = MIMEMultipart()
    msg["From"] = gmail_address
    msg["To"] = gmail_address
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_address, gmail_app_password)
            server.sendmail(gmail_address, gmail_address, msg.as_string())

        print("Email sent successfully!")

    except Exception as e:
        print(f"Check the email credentials and try again. Error: {e}")

# Attach the email with the alert
def build_email(all_anomalies):
    subject = f"[Anomaly Alert] {len(all_anomalies)} metric(s) flagged."
    body = llm_summary(all_anomalies)
    print("SUBJECT:", subject, "\n")
    print("BODY:", "\n")
    print(body)
    send_email(subject, body)

#only bother generating a summary + sending an email if something was actually flagged
if (len(all_anomalies) == 0):
    print(f"No anomalies detected today.")

else:
    build_email(all_anomalies)
