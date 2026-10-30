# Cloud-Based AWS EC2 Server Monitoring and Alerting Dashboard

A lightweight Flask dashboard for monitoring Amazon EC2 instances with metrics from Amazon CloudWatch and email notifications through Amazon SNS.

## Features

- View CPU utilization, network traffic, and EC2 status check metrics.
- Monitor multiple instances in one overview and select an instance for detailed charts.
- Browse metric history for the last hour, 3 hours, 12 hours, or 24 hours.
- Check CPU and status-check alarms, with configurable thresholds and cooldowns.
- Send alarm, recovery, and test notifications through an SNS topic.
- Use a responsive dashboard with automatic refresh.

## Requirements

- Python 3
- An AWS account with EC2 instances publishing metrics to CloudWatch
- AWS credentials configured locally or an IAM role when running on AWS
- An SNS topic and a confirmed email subscription if you want to receive alerts

## Setup

1. Clone the repository and enter its directory.
2. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   ```

   Windows PowerShell:

   ```powershell
   .venv\Scripts\Activate.ps1
   ```

   macOS/Linux:

   ```bash
   source .venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Copy `env.example` to `.env` and configure your AWS region, EC2 instance ID, and SNS topic ARN. For example:

   ```dotenv
   AWS_REGION=ap-south-1
   INSTANCE_IDS=web:i-0123456789abcdef0,worker:i-0abcdef1234567890
   SNS_TOPIC_ARN=arn:aws:sns:ap-south-1:123456789012:ec2-alerts
   CPU_THRESHOLD=80
   CHECK_INTERVAL=60
   COOLDOWN_MINUTES=15
   ```

   `INSTANCE_IDS` accepts comma-separated instance IDs; an optional label can be supplied before each ID, separated by a colon. For a single instance, the legacy `INSTANCE_ID` setting is also supported.

5. Configure AWS credentials using a standard AWS credentials profile (for example, `aws configure`) or an IAM role. The app does not store AWS credentials in the project. Its AWS identity needs permission to read CloudWatch metrics and publish to the configured SNS topic. Confirm the SNS email subscription before testing notifications.

## Run

```bash
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser. The app uses Flask's development server and is configured to listen on the local machine; use a production WSGI server and appropriate access controls before deploying it for shared use.

## Dashboard and API

The dashboard displays an overview of configured instances, metric charts, and recent alert history. It refreshes automatically and also includes a manual refresh button and a test-alert button.

Available JSON endpoints:

| Endpoint | Description |
| --- | --- |
| `GET /api/health` | Application health, region, and configured instance count |
| `GET /api/instances` | Configured instances |
| `GET /api/overview` | Latest metrics and alert state for all instances |
| `GET /api/metrics/<key>?instance=<id>&minutes=<n>` | Metric history (`cpu`, `network_in`, `network_out`, or `status_check`) |
| `GET /api/alerts` | Alert settings and recent alert history |
| `POST /api/alerts/test` | Send a test notification through SNS |

## Alert configuration

| Variable | Default | Description |
| --- | --- | --- |
| `CPU_THRESHOLD` | `80` | CPU utilization percentage that triggers an alarm |
| `CHECK_INTERVAL` | `60` | Seconds between alert checks |
| `COOLDOWN_MINUTES` | `15` | Minimum time between repeated alarm notifications for the same rule and instance |

Alarm checks run for CPU utilization and EC2 status checks. Recovery notifications are sent when an active alarm returns to normal. Notifications require `SNS_TOPIC_ARN`; without it, alerts are recorded locally but are not sent.

## Project files

- `app.py` — Flask application, CloudWatch metric queries, and alert checks.
- `static/index.html` — Dashboard UI and charts.
- `env.example` — Example environment configuration.
- `main.java` — Standalone Java inheritance example.
- `requirements.txt` — Python dependencies.

Keep `.env` files and private keys out of version control. The repository's `.gitignore` excludes them.
