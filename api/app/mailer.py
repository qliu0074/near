import smtplib
import ssl
from email.message import EmailMessage


def deliver(settings, email: str, code: str):
    if settings.email_mode == 'development':
        return {'message': 'Development mailbox only; no email was sent', 'development_code': code}
    message = EmailMessage()
    message['From'] = settings.smtp_from
    message['To'] = email
    message['Subject'] = 'Your Near sign-in code'
    message.set_content(f'Your sign-in code is {code}. It expires in 10 minutes.')
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        server.ehlo()
        if settings.smtp_tls:
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)
    return {'message': 'If delivery is available, a code will arrive shortly'}
