import os
import threading
import time
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

REGION = os.getenv("AWS_REGION", "ap-south-1")
SNS_TOPIC_ARN = os.getenv("SNS_TOPIC_ARN")
CPU_THRESHOLD = float(os.getenv("CPU_THRESHOLD", "80"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "15"))


def parse_instances():
    """INSTANCE_IDS=web:i-123,db:i-456  (label is optional).
    The old single INSTANCE_ID setting still works."""
    raw = os.getenv("INSTANCE_IDS") or os.getenv("INSTANCE_ID") or ""
    items = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        label, _, iid = part.rpartition(":")
        iid = iid.strip()
        items.append({"id": iid, "label": label.strip() or iid})
    return items


INSTANCES = parse_instances()
if not INSTANCES:
    raise SystemExit(
        "No instances configured. Set INSTANCE_IDS in your .env file (see .env.example)."
    )
LABELS = {i["id"]: i["label"] for i in INSTANCES}

# Credentials are NOT written here. boto3 picks them up from
# `aws configure` or from an IAM role if this runs on EC2.
cloudwatch = boto3.client("cloudwatch", region_name=REGION)
sns = boto3.client("sns", region_name=REGION)

app = Flask(__name__)

# key -> (statistic, CloudWatch metric name)
METRICS = {
    "cpu": ("Average", "CPUUtilization"),
    "network_in": ("Sum", "NetworkIn"),
    "network_out": ("Sum", "NetworkOut"),
    "status_check": ("Maximum", "StatusCheckFailed"),
}


def fetch_metric(instance_id, key, minutes=60, period=300):
    stat, name = METRICS[key]
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)
    resp = cloudwatch.get_metric_statistics(
        Namespace="AWS/EC2",
        MetricName=name,
        Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        StartTime=start,
        EndTime=end,
        Period=period,
        Statistics=[stat],
    )
    points = sorted(resp["Datapoints"], key=lambda p: p["Timestamp"])
    return [
        {"time": p["Timestamp"].isoformat(), "value": round(p[stat], 2)}
        for p in points
    ]


def latest(instance_id, key, minutes=15):
    pts = fetch_metric(instance_id, key, minutes)
    return pts[-1]["value"] if pts else None


# ---------------------------------------------------------------- alerting
alert_lock = threading.Lock()
alert_history = []   # newest first, max 50
alert_state = {}     # "instance:rule" -> {"active": bool, "last_sent": datetime|None}


def send_alert(instance_id, name, subject, message, kind="ALARM"):
    entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "instance": instance_id,
        "label": LABELS.get(instance_id, instance_id) if instance_id else "-",
        "name": name,
        "kind": kind,
        "message": message,
        "sent": False,
        "error": None,
    }
    if not SNS_TOPIC_ARN:
        entry["error"] = "SNS_TOPIC_ARN is not set in .env"
    else:
        try:
            sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject[:100], Message=message)
            entry["sent"] = True
        except (ClientError, BotoCoreError) as e:
            entry["error"] = str(e)
    with alert_lock:
        alert_history.insert(0, entry)
        del alert_history[50:]
    return entry


def evaluate(instance_id, rule, breached, subject, message, ok_message):
    """ALARM when a rule is breached (respecting the cooldown),
    OK when it returns to normal. Tracked separately for every instance."""
    now = datetime.now(timezone.utc)
    key = f"{instance_id}:{rule}"
    with alert_lock:
        state = alert_state.setdefault(key, {"active": False, "last_sent": None})
        was_active, last_sent = state["active"], state["last_sent"]

    if breached:
        cooled = last_sent is None or now - last_sent >= timedelta(minutes=COOLDOWN_MINUTES)
        if cooled:
            entry = send_alert(instance_id, rule, subject, message, "ALARM")
            with alert_lock:
                if entry["sent"]:
                    state["last_sent"] = now
                state["active"] = True
        else:
            with alert_lock:
                state["active"] = True
    elif was_active:
        send_alert(instance_id, rule, f"[OK] {subject}", ok_message, "OK")
        with alert_lock:
            state["active"] = False
            state["last_sent"] = None


def check_instance(inst):
    iid, label = inst["id"], inst["label"]
    cpu = fetch_metric(iid, "cpu", 15)
    if cpu:
        v = cpu[-1]["value"]
        evaluate(iid, "High CPU", v >= CPU_THRESHOLD,
                 f"[ALARM] High CPU on {label}",
                 f"CPU utilization is {v}% (threshold {CPU_THRESHOLD}%) on {label} ({iid}) in {REGION}.",
                 f"CPU is back to {v}% (below {CPU_THRESHOLD}%) on {label} ({iid}).")
    status = fetch_metric(iid, "status_check", 15)
    if status:
        v = status[-1]["value"]
        evaluate(iid, "Status check failed", v >= 1,
                 f"[ALARM] Status check failed on {label}",
                 f"EC2 status check FAILED on {label} ({iid}) in {REGION}.",
                 f"Status checks are passing again on {label} ({iid}).")


def alert_loop():
    print(f"[alerts] checking {len(INSTANCES)} instance(s): CPU>{CPU_THRESHOLD}% every {CHECK_INTERVAL}s")
    while True:
        for inst in INSTANCES:
            try:                      # one failing instance must not stop the others
                check_instance(inst)
            except Exception as e:
                print(f"[alerts] check failed for {inst['id']}:", e)
        time.sleep(CHECK_INTERVAL)


# ---------------------------------------------------------------- overview
_overview_cache = {"time": 0, "data": None}


def build_overview():
    rows = []
    for inst in INSTANCES:
        iid = inst["id"]
        row = {"id": iid, "label": inst["label"], "cpu": None, "network_in": None,
               "network_out": None, "status": None, "alerting": False, "error": None}
        try:
            row["cpu"] = latest(iid, "cpu")
            row["network_in"] = latest(iid, "network_in")
            row["network_out"] = latest(iid, "network_out")
            row["status"] = latest(iid, "status_check")
        except (ClientError, BotoCoreError) as e:
            row["error"] = str(e)
        with alert_lock:
            row["alerting"] = any(s["active"] for k, s in alert_state.items()
                                  if k.startswith(iid + ":"))
        rows.append(row)
    return rows


# ------------------------------------------------------------------ routes
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "region": REGION, "instances": len(INSTANCES)})


@app.route("/api/instances")
def instances():
    return jsonify({"region": REGION, "instances": INSTANCES})


@app.route("/api/overview")
def overview():
    now = time.time()
    if _overview_cache["data"] is None or now - _overview_cache["time"] > 20:
        _overview_cache["data"] = build_overview()
        _overview_cache["time"] = now
    return jsonify({"instances": _overview_cache["data"]})


@app.route("/api/metrics/<key>")
def metrics(key):
    if key not in METRICS:
        return jsonify({"error": f"unknown metric '{key}'"}), 404
    iid = request.args.get("instance", INSTANCES[0]["id"])
    if iid not in LABELS:
        return jsonify({"error": f"unknown instance '{iid}'"}), 404
    try:
        minutes = int(request.args.get("minutes", 60))
    except ValueError:
        return jsonify({"error": "minutes must be a number"}), 400
    return jsonify({"metric": key, "instance": iid, "data": fetch_metric(iid, key, minutes)})


@app.route("/api/alerts")
def alerts():
    with alert_lock:
        history = list(alert_history)
    return jsonify({
        "config": {"cpu_threshold": CPU_THRESHOLD, "check_interval": CHECK_INTERVAL,
                   "cooldown_minutes": COOLDOWN_MINUTES, "sns_configured": bool(SNS_TOPIC_ARN)},
        "history": history,
    })


@app.route("/api/alerts/test", methods=["POST"])
def alerts_test():
    entry = send_alert(
        None, "Test alert", "[TEST] EC2 monitoring dashboard",
        f"This is a test alert from your EC2 monitoring dashboard "
        f"({len(INSTANCES)} instance(s), region {REGION}).", "TEST")
    return jsonify(entry), (200 if entry["sent"] else 500)


@app.errorhandler(ClientError)
@app.errorhandler(BotoCoreError)
def aws_error(e):
    return jsonify({"error": "AWS request failed", "details": str(e)}), 500


if __name__ == "__main__":
    # In debug mode Flask starts two processes; only start the checker in the
    # one that serves requests, so you don't get duplicate emails.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Thread(target=alert_loop, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=True)