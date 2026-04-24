#!/bin/bash
# AI24x7 - Setup Daily Reports Cron Job
# Run: bash /opt/cctv-finetune/output/ai24x7/setup_cron.sh

INSTALL_DIR="/opt/cctv-finetune/output/ai24x7"

echo "⏰ Setting up AI24x7 Daily Reports Cron..."

# Create cron entry
CRON_CMD="0 9 * * * cd $INSTALL_DIR && python3 $INSTALL_DIR/daily_reports.py >> /var/log/ai24x7_reports.log 2>&1"

# Remove existing ai24x7 cron entries first
crontab -l 2>/dev/null | grep -v "ai24x7" | crontab - 2>/dev/null || true

# Add new cron entry
echo "$CRON_CMD" | crontab -

# Also add twice-daily (9 AM and 6 PM)
CRON_CMD2="0 18 * * * cd $INSTALL_DIR && python3 $INSTALL_DIR/daily_reports.py >> /var/log/ai24x7_reports.log 2>&1"
echo "$CRON_CMD2" | crontab -

echo "✅ Cron installed!"
echo ""
echo "Scheduled reports:"
crontab -l 2>/dev/null | grep ai24x7
echo ""
echo "Log file: /var/log/ai24x7_reports.log"
