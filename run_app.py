"""Launcher để đóng gói app.py thành file .exe bằng PyInstaller (xem build_exe.bat)."""
import os
import sys

from streamlit.web import cli as stcli

# Các thư viện app.py dùng - import ở đây để PyInstaller đóng gói kèm (app.py được nhúng dạng file dữ liệu)
import numpy  # noqa: F401
import requests  # noqa: F401
import truststore  # noqa: F401


def main():
    # Khi chạy từ .exe, PyInstaller giải nén file vào thư mục tạm sys._MEIPASS
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    sys.argv = [
        "streamlit", "run", os.path.join(base_dir, "app.py"),
        "--global.developmentMode=false",
        "--server.headless=false",          # tự mở trình duyệt
        "--browser.gatherUsageStats=false",
        "--client.toolbarMode=viewer",      # ẩn nút Deploy/menu dành cho lập trình viên
        # Giao diện tối (giống .streamlit/config.toml)
        "--theme.base=dark",
        "--theme.backgroundColor=#0d1117",
        "--theme.secondaryBackgroundColor=#161b22",
        *sys.argv[1:],                      # tùy chọn thêm, vd: StockBoard.exe --server.port 8600
    ]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
