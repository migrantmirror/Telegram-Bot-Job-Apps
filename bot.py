import os
import base64
from datetime import datetime, timedelta
import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from sqlalchemy.future import select

from db import init_db, AsyncSessionLocal
from models import User, JobApplication, Reminder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL")
DB_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./jobs_bot.db")

UPLOAD_CV = range(1)

jobstores = {
    'default': SQLAlchemyJobStore(url=DB_URL)
}
scheduler = AsyncIOScheduler(jobstores=jobstores)

user_cv_files = {}

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    reminder_id = job.id
    async with AsyncSessionLocal() as session:
        reminder = await session.get(Reminder, int(reminder_id))
        if reminder and not reminder.is_sent:
            application = await session.get(JobApplication, reminder.application_id)
            if application:
                chat_id = application.user_id
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⏰ Reminder: Follow up on your job application to {application.company_email} for {application.job_title}."
                )
                reminder.is_sent = True
                await session.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome! Use /uploadcv to upload your CV before applying to jobs."
    )

async def upload_cv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Please send your CV as a PDF document."
    )
    return UPLOAD_CV

async def receive_cv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    document = update.message.document

    if not document or document.mime_type != 'application/pdf':
        await update.message.reply_text("Please send a PDF file.")
        return UPLOAD_CV

    cv_dir = 'cvs'
    os.makedirs(cv_dir, exist_ok=True)
    cv_path = os.path.join(cv_dir, f"{user.id}_cv.pdf")
    await document.get_file().download_to_drive(cv_path)
    user_cv_files[user.id] = cv_path

    await update.message.reply_text("CV uploaded successfully! Now apply using /apply company_email job_title (underscores for spaces).")
    return ConversationHandler.END

def send_email(to_email, subject, content, attachment_path=None):
    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=to_email,
        subject=subject,
        plain_text_content=content
    )
    if attachment_path:
        with open(attachment_path, 'rb') as f:
            data = f.read()
        encoded = base64.b64encode(data).decode()
        filename = os.path.basename(attachment_path)
        attachment = Attachment(
            FileContent(encoded),
            FileName(filename),
            FileType('application/pdf'),
            Disposition('attachment')
        )
        message.attachment = attachment

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info(f"Email sent with status {response.status_code}")
        return True
    except Exception as e:
        logger.error(f"SendGrid error: {e}")
        return False

async def apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /apply company_email job_title (underscores for spaces)")
        return

    company_email = args[0]
    job_title = ' '.join(args[1:]).replace('_', ' ')
    async with AsyncSessionLocal() as session:
        user_obj = await session.get(User, user.id)
        if not user_obj:
            user_obj = User(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
            session.add(user_obj)
            await session.commit()

        cv_path = user_cv_files.get(user.id)
        if not cv_path or not os.path.exists(cv_path):
            await update.message.reply_text("Please upload your CV first with /uploadcv")
            return

        await update.message.reply_text(f"Sending job application to {company_email} for '{job_title}'...")

        email_subject = f"Job Application: {job_title}"
        email_content = f"Dear Hiring Team,\n\nPlease find my application for the position of {job_title}.\n\nBest regards."

        sent = send_email(company_email, email_subject, email_content, cv_path)
        email_status = 'sent' if sent else 'failed'

        application = JobApplication(
            user_id=user.id,
            company_email=company_email,
            job_title=job_title,
            email_status=email_status,
            cv_file_path=cv_path
        )
        session.add(application)
        await session.commit()
        await session.refresh(application)

        if not sent:
            await update.message.reply_text("Failed to send the email. Try again later.")
            return

        await update.message.reply_text("Application sent! Scheduling reminder in 3 days.")

        remind_at = datetime.utcnow() + timedelta(days=3)
        reminder = Reminder(application_id=application.id, remind_at=remind_at)
        session.add(reminder)
        await session.commit()
        await session.refresh(reminder)

        scheduler.add_job(
            send_reminder,
            'date',
            run_date=remind_at,
            id=str(reminder.id),
            args=[context],
            replace_existing=True,
            misfire_grace_time=3600
        )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(JobApplication).where(JobApplication.user_id == user.id)
        )
        applications = result.scalars().all()
        if not applications:
            await update.message.reply_text("You have no job applications.")
            return

        lines = []
        for app in applications:
            status = app.email_status or 'unknown'
            date = app.date_applied.strftime("%Y-%m-%d")
            lines.append(f"To: {app.company_email}\nTitle: {app.job_title}\nDate: {date}\nStatus: {status}\n")

        await update.message.reply_text("\n\n".join(lines))

async def cancel_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /cancelreminder application_id")
        return

    application_id = args[0]
    async with AsyncSessionLocal() as session:
        reminder = await session.execute(
            select(Reminder)
            .join(JobApplication)
            .where(Reminder.application_id == int(application_id))
            .where(JobApplication.user_id == user.id)
            .where(Reminder.is_sent == False)
        )
        reminder_obj = reminder.scalars().first()

        if not reminder_obj:
            await update.message.reply_text("No pending reminder found for that application ID.")
            return

        job = scheduler.get_job(str(reminder_obj.id))
        if job:
            job.remove()

        reminder_obj.is_sent = True
        await session.commit()

        await update.message.reply_text(f"Reminder for application ID {application_id} canceled.")

async def main():
    await init_db()

    # Start scheduler inside the async event loop
    scheduler.start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('uploadcv', upload_cv)],
        states={UPLOAD_CV: [MessageHandler(filters.Document.PDF, receive_cv)]},
        fallbacks=[]
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('apply', apply))
    app.add_handler(CommandHandler('status', status))
    app.add_handler(CommandHandler('cancelreminder', cancel_reminder))

    logger.info("Bot started...")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
