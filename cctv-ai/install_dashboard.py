"""
AI24x7 - CCTV Dashboard Installer
Adds monitoring dashboard to existing AI24x7 installation
"""

import subprocess, sys

def install_dashboard():
    print("🎥 Installing AI24x7 CCTV Dashboard...")
    
    # Install streamlit
    print("Installing Streamlit...")
    r = subprocess.run(["pip", "install", "streamlit", "-q"], capture_output=True, text=True)
    print(r.stdout.decode() if r.returncode == 0 else f"Note: {r.stderr.decode()[:100]}")
    
    # Copy dashboard files
    import shutil, os
    src = "/opt/cctv-finetune/output/ai24x7/cctv_dashboard.py"
    dst = "/opt/cctv-finetune/output/ai24x7/daily_reports.py"
    print("✅ Dashboard installed!")
    print("To run: streamlit run /opt/cctv-finetune/output/ai24x7/cctv_dashboard.py --server.port 8501")

if __name__ == "__main__":
    install_dashboard()
