import streamlit as st
import html
import json
import math
import numpy as np
import os
import re
import requests
import sys
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
STOCK_DETAIL_URL = "https://24hmoney.vn/stock/{ticker}"  # Trang mở khi bấm vào 1 mã

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
    .stApp [data-testid="stCaptionContainer"] {
        color: #8b949e;
    }
    /* Bố cục gọn để toàn bộ các ngành vừa 1 màn hình 1920x1080 */
    header[data-testid="stHeader"] {
        display: none;
    }
    .block-container {
        padding: 0.5rem 1rem 0.5rem 1rem;
        max-width: 100%;
    }
    .block-container [data-testid="stVerticalBlock"] {
        gap: 0.25rem;
    }
    .app-title {
        font-size: 22px;
        font-weight: 700;
        color: #f0f6fc;
        line-height: 1.2;
    }
    .board {
        column-count: 6;      /* 6-8 cột (đặt trong render_board), trình duyệt tự cân bằng chiều cao các cột */
        column-gap: 8px;
    }
    .sector-card {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 4px 5px;
        margin-bottom: 6px;
        break-inside: avoid;   /* không cắt 1 ngành ra 2 cột */
    }
    .sector-header {
        font-weight: 700;
        color: #f0f6fc;
        font-size: 13px;
        letter-spacing: 0.5px;
        border-bottom: 1px solid #30363d;
        padding: 1px 2px 3px 2px;
        margin-bottom: 3px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .stock-row {
        font-family: 'Roboto Mono', monospace, monospace;
        font-size: 13px;
        font-weight: 600;
        line-height: 19px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1px 6px;
        border-radius: 3px;
        margin-bottom: 1px;
        text-decoration: none !important;  /* mỗi dòng là 1 link sang 24hmoney - bỏ gạch chân */
    }
    .stock-row:hover {
        filter: brightness(1.5);
        outline: 1px solid rgba(240, 246, 252, 0.4);
    }
    /* !important để màu theo giá không bị màu link mặc định của Streamlit ghi đè */
    .ceil { background-color: rgba(156, 39, 176, 0.25); color: #e040fb !important; border-left: 3px solid #e040fb; }
    .up { background-color: rgba(46, 125, 50, 0.25); color: #4caf50 !important; border-left: 3px solid #4caf50; }
    .ref { background-color: rgba(245, 124, 0, 0.2); color: #ffb74d !important; border-left: 3px solid #ffb74d; }
    .down { background-color: rgba(198, 40, 40, 0.25); color: #ef5350 !important; border-left: 3px solid #ef5350; }
    .floor { background-color: rgba(2, 136, 209, 0.25); color: #29b6f6 !important; border-left: 3px solid #29b6f6; }
    </style>
""", unsafe_allow_html=True)

# 3. Danh sách các nhóm ngành và mã cổ phiếu tương ứng
#    Danh sách mặc định - dùng khi chưa có file sectors.json (người dùng sửa qua nút "Quản lý ngành")
DEFAULT_SECTORS = {
    "NGÂN HÀNG": ["EIB", "STB", "TPB", "MSB", "VIB", "BID", "CTG", "MBB", "TCB", "VCB", "ACB", "VPB", "HDB", "NVB",  # NVB = mã CK của NCB
                  "ABB", "BVB", "LPB"],
    "CHỨNG KHOÁN": ["ORS", "VIX", "MBS", "VDS", "SHS", "VCI", "BSI", "SSI", "VND", "CTS", "FTS", "HCM",
                    "TCX", "VCK", "VPX", "AAS", "APS"],
    "BẤT ĐỘNG SẢN": ["HDC", "CEO", "NLG", "DIG", "VHM", "HDG", "VIC", "DXG", "PDR", "NVL", "KDH", "TCH", "HHS"],
    "VLXD - ĐẦU TƯ CÔNG": ["C4G", "G36", "HBC", "LCG", "CII", "HHV", "FCN", "HUT", "CTD", "KSB", "VCG", "HT1"],
    "BĐS KCN - CAO SU": ["SZC", "DRC", "TDC", "DPR", "KBC", "PHR", "LHG", "VGC", "TIP", "GVR", "IDC", "BCM"],
    "ĐIỆN NƯỚC": ["GEE", "GEX", "GEL", "PC1", "QTP", "GEG", "REE", "NT2", "POW", "BWE", "PPC", "TDM"],
    "THỰC PHẨM": ["DBC", "PAN", "HNG", "QNS", "HAG", "BAF", "SAB", "MSN", "VNM", "KDC", "SBT", "SLS", "NAF"],
    "XUẤT KHẨU": ["ASM", "TCM", "VGT", "GIL", "TNG", "VHC", "ANV", "IDI", "STK", "FMC"],
    "DẦU KHÍ": ["OIL", "PVC", "PLX", "BSR", "GAS", "PVD", "PVB", "PVS", "PVT"],
    "CẢNG BIỂN": ["VSC", "SGP", "HAH", "GMD", "DVP", "PHP", "PVP", "VOS", "VIP", "DXP"],
    "HÓA CHẤT - PHÂN BÓN": ["DPM", "DGC", "DDV", "CSV", "DCM", "LAS", "BFC"],
    "THÉP": ["NKG", "HSG", "HPG", "TLH", "SMC", "TVN"],
    "CNTT": ["FPT", "FOX", "FOC", "CMG", "VGI", "ELC", "CTR", "MFS", "ICT"],
    "KHOÁNG SẢN": ["MSR", "BKC", "KSV"],
    "BÁN LẺ": ["FRT", "PET", "MWG", "DMX", "PNJ", "DGW"]
}

# File lưu danh sách ngành do người dùng chỉnh sửa: cạnh StockBoard.exe khi chạy bản .exe, cạnh app.py khi chạy code
DATA_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
SECTORS_FILE = os.path.join(DATA_DIR, "sectors.json")


def load_sectors():
    try:
        with open(SECTORS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and all(isinstance(v, list) for v in data.values()):
            return {str(k): [str(t) for t in v] for k, v in data.items()}
    except (OSError, ValueError):
        pass  # Chưa có file hoặc file hỏng -> dùng danh sách mặc định
    return {k: list(v) for k, v in DEFAULT_SECTORS.items()}


def save_sectors(sectors):
    # Ghi ra file tạm rồi đổi tên, tránh hỏng file nếu bị ngắt giữa chừng
    tmp_path = SECTORS_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(sectors, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, SECTORS_FILE)


SECTOR_MAP = load_sectors()
ALL_TICKERS = list(dict.fromkeys(t for tickers in SECTOR_MAP.values() for t in tickers))

SESSION_LABELS = {
    "ATO": "Phiên ATO", "LO": "Phiên liên tục", "LO_MORNING": "Phiên sáng", "LO_AFTERNOON": "Phiên chiều",
    "BREAK": "Nghỉ trưa", "INTERMISSION": "Nghỉ trưa",
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

# 6. Quản lý ngành: thêm/xóa/đổi tên ngành, thêm/xóa mã trong ngành (lưu vào sectors.json)
def clean_tickers(items):
    """Chuẩn hóa mã: viết hoa, bỏ trùng; cho phép dán nhiều mã 1 lần (vd: 'dxs, nha')"""
    result = []
    for item in items:
        for part in re.split(r"[\s,;]+", str(item)):
            ticker = part.strip().upper()
            if ticker and ticker not in result:
                result.append(ticker)
    return result


def find_unknown_tickers(tickers):
    """Trả về các mã không có trên bảng giá (gõ sai, đã hủy niêm yết...)"""
    quotes, _ = fetch_price_board(tickers)
    return [t for t in tickers if t not in quotes]


def validate_and_save(sectors, new_tickers, success_msg):
    """Kiểm tra mã mới với bảng giá rồi lưu. Trả về thông báo lỗi, hoặc None nếu đã lưu thành công."""
    if new_tickers:
        try:
            unknown = find_unknown_tickers(new_tickers)
        except requests.RequestException as e:
            return f"Không kiểm tra được mã cổ phiếu (lỗi kết nối): {e}"
        if unknown:
            return f"Không tìm thấy mã trên bảng giá: {', '.join(unknown)}. Kiểm tra lại mã (vd: NCB phải nhập là NVB)."
    try:
        save_sectors(sectors)
    except OSError as e:
        return f"Không lưu được file {SECTORS_FILE}: {e}"
    st.session_state["mg_flash"] = success_msg
    st.rerun()


@st.dialog("⚙️ Quản lý ngành", width="medium")
def manage_sectors():
    sectors = load_sectors()
    tab_edit, tab_add = st.tabs(["Sửa / xóa ngành", "Thêm ngành mới"])

    with tab_edit:
        if not sectors:
            st.info("Chưa có ngành nào. Thêm ngành ở thẻ \"Thêm ngành mới\".")
        else:
            sel = st.selectbox("Ngành", list(sectors), key="mg_sector")
            new_name = st.text_input("Tên ngành", value=sel, key=f"mg_name_{sel}")
            tickers = st.multiselect(
                "Mã cổ phiếu", options=sectors[sel], default=sectors[sel],
                accept_new_options=True, key=f"mg_tickers_{sel}",
                placeholder="Gõ mã mới rồi nhấn Enter",
            )
            st.caption("Bấm **×** trên mã để xóa · Gõ mã mới (vd: DXS) rồi nhấn **Enter** để thêm · Bấm **Lưu** để áp dụng")

            col_save, col_delete = st.columns(2)
            if col_save.button("💾 Lưu thay đổi", type="primary", width="stretch", key="mg_save"):
                name = new_name.strip().upper()
                cleaned = clean_tickers(tickers)
                if not name:
                    st.error("Tên ngành không được để trống.")
                elif name != sel and name in sectors:
                    st.error(f"Đã có ngành \"{name}\".")
                elif not cleaned:
                    st.error("Ngành cần ít nhất 1 mã. Muốn bỏ cả ngành thì bấm \"Xóa ngành\".")
                else:
                    # Giữ nguyên vị trí ngành trên bảng khi đổi tên
                    updated = {(name if k == sel else k): (cleaned if k == sel else v) for k, v in sectors.items()}
                    added = [t for t in cleaned if t not in sectors[sel]]
                    error = validate_and_save(updated, added, f"Đã lưu ngành {name} ({len(cleaned)} mã)")
                    st.error(error)
            with col_delete.popover("🗑️ Xóa ngành", width="stretch"):
                st.write(f"Xóa ngành **{sel}** ({len(sectors[sel])} mã) khỏi bảng giá?")
                if st.button("Xác nhận xóa", type="primary", key="mg_delete"):
                    remaining = {k: v for k, v in sectors.items() if k != sel}
                    st.error(validate_and_save(remaining, [], f"Đã xóa ngành {sel}"))

    with tab_add:
        name = st.text_input("Tên ngành mới", key="mg_new_name", placeholder="VD: HÀNG KHÔNG")
        raw = st.text_input("Mã cổ phiếu (cách nhau bởi dấu phẩy)", key="mg_new_tickers", placeholder="VD: HVN, VJC, ACV")
        if st.button("➕ Thêm ngành", type="primary", key="mg_add"):
            name = name.strip().upper()
            cleaned = clean_tickers([raw])
            if not name:
                st.error("Nhập tên ngành.")
            elif name in sectors:
                st.error(f"Đã có ngành \"{name}\" - sửa ở thẻ \"Sửa / xóa ngành\".")
            elif not cleaned:
                st.error("Nhập ít nhất 1 mã cổ phiếu.")
            else:
                st.error(validate_and_save({**sectors, name: cleaned}, cleaned,
                                           f"Đã thêm ngành {name} ({len(cleaned)} mã)"))

    st.divider()
    with st.popover("↩️ Khôi phục danh sách mặc định"):
        st.write("Bỏ mọi thay đổi và dùng lại danh sách ngành ban đầu?")
        if st.button("Xác nhận khôi phục", key="mg_reset"):
            st.error(validate_and_save({k: list(v) for k, v in DEFAULT_SECTORS.items()}, [],
                                       "Đã khôi phục danh sách ngành mặc định"))


# 7. Header Bar
col_h1, col_h2, col_h3 = st.columns([5, 1, 1], vertical_alignment="center")
with col_h1:
    st.markdown('<div class="app-title">📈 Bảng Giá Phân Ngành Chứng Khoán</div>', unsafe_allow_html=True)
with col_h2:
    if st.button("⚙️ Quản lý ngành", width="stretch"):
        manage_sectors()
with col_h3:
    if st.button("🔄 Làm Mới Dữ Liệu", width="stretch"):
        store.refresh_now()
        get_simulated_data.clear()

if "mg_flash" in st.session_state:
    st.toast(st.session_state.pop("mg_flash"), icon="✅")


# 8. Render Grid Layout - Fragment tự chạy lại mỗi POLL_SECONDS giây, không tải lại toàn trang
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

    if not SECTOR_MAP:
        st.info("Chưa có ngành nào. Bấm \"⚙️ Quản lý ngành\" để thêm.")
        return

    # Thêm cột khi danh sách dài ra (mỗi thẻ ngành ~ số mã + 2 dòng tiêu đề; ~32 dòng/cột vừa màn hình 1080p)
    row_units = sum(len(tickers) + 2 for tickers in SECTOR_MAP.values())
    column_count = min(8, max(6, math.ceil(row_units / 32)))

    # Toàn bộ các ngành trong 1 khối HTML, chia cột bằng CSS (.board) để vừa 1 màn hình
    # HTML phải viết liền, không thụt lề/dòng trống, nếu không Markdown sẽ hiểu là code block
    board_html = f'<div class="board" style="column-count: {column_count};">'
    for sector_name, tickers in SECTOR_MAP.items():
        board_html += (
            '<div class="sector-card">'
            '<div class="sector-header">'
            f'<span>{html.escape(sector_name)}</span>'
            '<span style="font-size: 10px; color: #8b949e;">MÃ | GIÁ | % | KL</span>'
            '</div>'
        )
        # Sắp xếp trong từng ngành theo % thay đổi, từ cao xuống thấp
        rows = sorted(((t, quotes[t]) for t in tickers if t in quotes), key=lambda r: r[1]["pct"], reverse=True)
        for ticker, s in rows:
            sign = "+" if s['pct'] > 0 else ""
            # Bấm vào mã -> mở trang chi tiết trên 24hmoney ở tab mới
            board_html += (
                f'<a class="stock-row {s["cls"]}" href="{STOCK_DETAIL_URL.format(ticker=ticker)}" '
                f'target="_blank" rel="noopener noreferrer" title="Xem {ticker} trên 24hmoney">'
                f'<span style="width: 25%;">{ticker}</span>'
                f'<span style="width: 25%;">{s["price"]:.2f}</span>'
                f'<span style="width: 30%;">{sign}{s["pct"]:.2f}%</span>'
                f'<span style="width: 20%; text-align: right; color: #8b949e;">{s["vol"]:.2f}</span>'
                '</a>'
            )
        board_html += "</div>"
    board_html += "</div>"
    st.markdown(board_html, unsafe_allow_html=True)


render_board()
