# Telegram Job Application Bot

This Telegram bot automates sending job applications with your CV via email and schedules follow-up reminders.

---

## Features

- Upload your CV as PDF via `/uploadcv`
- Apply to jobs with `/apply company_email job_title`
- Bot sends email with your CV attached via SendGrid
- Schedules a reminder to follow up after 3 days
- Check your application status `/status`
- Cancel reminders `/cancelreminder application_id`

---

## Setup

1. Clone/download this project.

2. Create and activate a Python 3.9+ virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows
