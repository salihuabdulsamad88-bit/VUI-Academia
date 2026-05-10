import os
from flask import Flask
from flask_mail import Mail, Message
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME'])

mail = Mail(app)

with app.app_context():
    try:
        msg = Message("Test Email from VUI Academia",
                      recipients=["salihuabdulsamad88@gmail.com"])
        msg.body = "This is a test email to verify SMTP configuration."
        mail.send(msg)
        print("Email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")
