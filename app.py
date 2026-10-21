import streamlit as st
import numpy as np
import requests
import threading
import time
import truststore
from datetime import datetime

# Dùng kho chứng chỉ của Windows để xác thực SSL (cần khi mạng công ty có proxy kiểm tra SSL)
truststore.inject_into_ssl()

# Cho phép chạy bằng "python app.py" (nút ▶ của VS Code): tự khởi động lại qua "streamlit run"
if __name__ == "__main__":
    from streamlit import runtime
    if not runtime.exists():
        import sys
        from streamlit.web import cli as stcli
        sys.argv = ["streamlit", "run", __file__]
        sys.exit(stcli.main())

# Nguồn dữ liệu realtime: API bảng giá của Vietcap (cùng nguồn vnstock sử dụng, không cần đăng nhập)
PRICE_BOARD_URL = "https://trading.vietcap.com.vn/api/price/symbols/getList"
PRICE_BOARD_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json",
    "Referer": "https://trading.vietcap.com.vn/",
    "Origin": "https://trading.vietcap.com.vn",
}
POLL_SECONDS = 3  # Chu kỳ lấy dữ liệu mới và làm mới bảng

# 1. Cấu hình trang Streamlit
st.set_page_config(
    page_title="Bảng Giá Chứng Khoán Phân Ngành - FireAnt Style",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 2. Định nghĩa CSS custom cho giao diện Dark Mode chuẩn chứng khoán
st.markdown("""
    <style>
    .stApp {
        background-color: #0d1117;
        color: #f0f6fc;
    }
    .stApp h1, .stApp [data-testid="stCaptionContainer"] {
        color: #f0f6fc;
    }
    .block-container {
        padding-top: 3.5rem;
        padding-bottom: 2rem;
    }
    .sector-card {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 10px;
        margin-bottom: 12px;
    }
    .sector-header {
        font-weight: 700;
        color: #f0f6fc;
        font-size: 13px;
        letter-spacing: 0.5px;
        border-bottom: 1px solid #30363d;
        padding-bottom: 6px;
        margin-bottom: 8px;
        display: flex;
        justify-content: space-between;
    }
    .stock-row {
        font-family: 'Roboto Mono', monospace, monospace;
        font-size: 12px;
        font-weight: 600;
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 4px 6px;
        border-radius: 4px;
        margin-bottom: 3px;
    }
    .ceil { background-color: rgba(156, 39, 176, 0.25); color: #e040fb; border-left: 3px solid #e040fb; }
    .up { background-color: rgba(46, 125, 50, 0.25); color: #4caf50; border-left: 3px solid #4caf50; }
    .ref { background-color: rgba(245, 124, 0, 0.2); color: #ffb74d; border-left: 3px solid #ffb74d; }
    .down { background-color: rgba(198, 40, 40, 0.25); color: #ef5350; border-left: 3px solid #ef5350; }
    .floor { background-color: rgba(2, 136, 209, 0.25); color: #29b6f6; border-left: 3px solid #29b6f6; }
    </style>
""", unsafe_allow_html=True)

# 3. Danh sách các nhóm ngành và mã cổ phiếu tương ứng
SECTOR_MAP = {
    "NGÂN HÀNG": ["EIB", "STB", "TPB", "MSB", "VIB", "BID", "CTG", "MBB", "TCB", "VCB", "ACB", "VPB"],
    "CHỨNG KHOÁN": ["ORS", "VIX", "MBS", "VDS", "SHS", "VCI", "BSI", "SSI", "VND", "CTS", "FTS", "HCM"],
    "BẤT ĐỘNG SẢN": ["HDC", "CEO", "NLG", "DIG", "VHM", "HDG", "VIC", "DXG", "PDR", "NVL", "KDH", "TCH"],
    "VLXD - ĐẦU TƯ CÔNG": ["C4G", "G36", "HBC", "LCG", "CII", "HHV", "FCN", "HUT", "CTD", "KSB", "VCG", "HT1"],
    "BĐS KCN - CAO SU": ["SZC", "DRC", "TDC", "DPR", "KBC", "PHR", "LHG", "VGC", "TIP", "GVR", "IDC", "BCM"],
    "ĐIỆN NƯỚC": ["GEE", "GEX", "GEL", "PC1", "QTP", "GEG", "REE", "NT2", "POW", "BWE", "PPC", "TDM"],
    "THỰC PHẨM": ["DBC", "PAN", "HNG", "QNS", "HAG", "BAF", "SAB", "MSN", "VNM", "KDC", "SBT", "SLS"],
    "XUẤT KHẨU": ["ASM", "TCM", "VGT", "GIL", "TNG", "VHC", "ANV", "IDI", "STK"],
    "DẦU KHÍ": ["OIL", "PVC", "PLX", "BSR", "GAS", "PVD", "PVB", "PVS", "PVT"],
    "CẢNG BIỂN": ["VSC", "SGP", "HAH", "GMD", "DVP", "PHP", "PVP"],
    "HÓA CHẤT - PHÂN BÓN": ["DPM", "DGC", "DDV", "CSV", "DCM", "LAS", "BFC"],
    "THÉP": ["NKG", "HSG", "HPG", "TLH", "SMC"],
    "CNTT": ["FPT", "FOX", "FOC", "CMG", "VGI", "ELC", "CTR", "MFS"]
}
ALL_TICKERS = [t for tickers in SECTOR_MAP.values() for t in tickers]

SESSION_LABELS = {
    "ATO": "Phiên ATO", "LO": "Phiên liên tục", "BREAK": "Nghỉ trưa",
    "ATC": "Phiên ATC", "PT": "Thỏa thuận", "ENDED": "Đã đóng cửa",
}


# 4. Kho dữ liệu realtime dùng chung + Background Thread cập nhật liên tục
#    (Thread ngầm KHÔNG được dùng st.session_state - chỉ ghi vào kho này, có khóa để an toàn luồng)
class LiveQuoteStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.ready = threading.Event()  # được bật sau lần lấy dữ liệu đầu tiên
        self.tickers = list(ALL_TICKERS)  # danh sách mã cần lấy, cập nhật khi sửa SECTOR_MAP
        self.quotes = {}          # ticker -> dict giá
        self.last_update = None   # thời điểm lấy dữ liệu thành công gần nhất
        self.session = None       # trạng thái phiên giao dịch
        self.error = None         # lỗi gần nhất (None nếu đang kết nối tốt)

    def snapshot(self):
        with self.lock:
            return dict(self.quotes), self.last_update, self.session, self.error

    def refresh_now(self):
        self.wake.set()


def classify(price, ref, ceiling, floor):
    """Phân loại màu theo giá trần/sàn/tham chiếu thực tế của sàn"""
    if price >= ceiling:
        return "ceil"
    if price <= floor:
        return "floor"
    if price > ref:
        return "up"
    if price < ref:
        return "down"
    return "ref"


def fetch_price_board(tickers):
    resp = requests.post(PRICE_BOARD_URL, json={"symbols": tickers}, headers=PRICE_BOARD_HEADERS, timeout=10)
    resp.raise_for_status()
    quotes, session = {}, None
    for item in resp.json():
        info, match = item.get("listingInfo") or {}, item.get("matchPrice") or {}
        ref = info.get("refPrice") or 0
        if not ref:
            continue
        # Chưa có lệnh khớp trong ngày -> hiển thị giá tham chiếu
        price = match.get("matchPrice") or ref
        session = session or match.get("session")
        quotes[info["symbol"]] = {
            "price": price / 1000,                                     # nghìn đồng
            "pct": round((price - ref) / ref * 100, 2),
            "vol": (match.get("accumulatedVolume") or 0) / 1_000_000,  # triệu cổ phiếu
            "cls": classify(price, ref, info.get("ceiling") or 0, info.get("floor") or 0),
        }
    return quotes, session


def poll_forever(store):
    while True:
        started = time.monotonic()
        try:
            quotes, session = fetch_price_board(store.tickers)
            with store.lock:
                store.quotes = quotes
                store.session = session
                store.last_update = datetime.now()
                store.error = None
        except Exception as e:
            with store.lock:
                store.error = str(e)
        store.ready.set()
        # Trừ thời gian gọi API để giữ chu kỳ đều POLL_SECONDS giây
        store.wake.wait(max(0.0, POLL_SECONDS - (time.monotonic() - started)))
        store.wake.clear()


# Chỉ khởi chạy 1 thread duy nhất, dùng chung cho mọi người dùng/tab đang mở
@st.cache_resource
def start_live_feed():
    store = LiveQuoteStore()
    threading.Thread(target=poll_forever, args=(store,), daemon=True).start()
    store.ready.wait(timeout=15)  # Chờ lần lấy dữ liệu đầu tiên để không hiện dữ liệu giả lập lúc mở app
    return store


# 5. Dữ liệu giả lập - chỉ dùng khi chưa kết nối được nguồn realtime
@st.cache_data(ttl=10)
def get_simulated_data():
    quotes = {}
    for ticker in ALL_TICKERS:
        pct_change = round(np.random.normal(0.8, 2.2), 2)
        if pct_change >= 6.8:
            css_cls = "ceil"
        elif pct_change > 0:
            css_cls = "up"
        elif pct_change == 0:
            css_cls = "ref"
        elif pct_change <= -6.8:
            css_cls = "floor"
        else:
            css_cls = "down"
        quotes[ticker] = {
            "price": round(np.random.uniform(10.0, 75.0), 2),
            "pct": pct_change,
            "vol": round(np.random.uniform(0.15, 3.8), 2),
            "cls": css_cls,
        }
    return quotes


store = start_live_feed()
# Thread ngầm chạy liên tục nên không tự thấy mã mới thêm vào SECTOR_MAP - cập nhật cho nó ở mỗi lần chạy script
if store.tickers != ALL_TICKERS:
    store.tickers = list(ALL_TICKERS)
    store.refresh_now()

# 6. Header Bar
col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.title("📈 Bảng Giá Phân Ngành Chứng Khoán")
with col_h2:
    if st.button("🔄 Làm Mới Dữ Liệu", width="stretch"):
        store.refresh_now()
        get_simulated_data.clear()


# 7. Render Grid Layout - Fragment tự chạy lại mỗi POLL_SECONDS giây, không tải lại toàn trang
@st.fragment(run_every=POLL_SECONDS)
def render_board():
    quotes, last_update, session, error = store.snapshot()

    if quotes:
        source = f"🟢 Realtime (Vietcap) · {SESSION_LABELS.get(session, session or 'N/A')}"
        if error:
            source = f"🟡 Mất kết nối, đang thử lại - hiển thị dữ liệu lúc {last_update:%H:%M:%S}"
        updated = last_update
    else:
        quotes = get_simulated_data()
        source = "🔴 Chưa kết nối được nguồn realtime - đang dùng dữ liệu giả lập"
        if error:
            source += f" ({error[:80]})"
        updated = datetime.now()

    st.caption(f"Cập nhật lúc: {updated:%H:%M:%S} | Nguồn: {source} | Tự làm mới mỗi {POLL_SECONDS}s")

    cols = st.columns(4)
    for index, (sector_name, tickers) in enumerate(SECTOR_MAP.items()):
        with cols[index % 4]:
            # HTML phải viết liền, không thụt lề/dòng trống, nếu không Markdown sẽ hiểu là code block
            card_html = (
                '<div class="sector-card">'
                '<div class="sector-header">'
                f'<span>{sector_name}</span>'
                '<span style="font-size: 10px; color: #8b949e;">MÃ | GIÁ | % | KL</span>'
                '</div>'
            )
            # Sắp xếp trong từng ngành theo % thay đổi, từ cao xuống thấp
            rows = sorted(((t, quotes[t]) for t in tickers if t in quotes), key=lambda r: r[1]["pct"], reverse=True)
            for ticker, s in rows:
                sign = "+" if s['pct'] > 0 else ""
                card_html += (
                    f'<div class="stock-row {s["cls"]}">'
                    f'<span style="width: 25%;">{ticker}</span>'
                    f'<span style="width: 25%;">{s["price"]:.2f}</span>'
                    f'<span style="width: 30%;">{sign}{s["pct"]:.2f}%</span>'
                    f'<span style="width: 20%; text-align: right; color: #8b949e;">{s["vol"]:.2f}</span>'
                    '</div>'
                )
            card_html += "</div>"
            st.markdown(card_html, unsafe_allow_html=True)


render_board()
