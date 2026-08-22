import json
import random
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
import streamlit as st

# ==========================================
# 1. CẤU HÌNH TRANG & BẢNG MÀU MOCHI
# ==========================================
st.set_page_config(page_title="MochiVocab", page_icon="🍌", layout="centered")

GOLDEN_INTERVALS = {
    1: 5,        # Cấp 1: 5 phút
    2: 1440,     # Cấp 2: 1 ngày
    3: 4320,     # Cấp 3: 3 ngày
    4: 10080,    # Cấp 4: 7 ngày
    5: 20160     # Cấp 5: 14 ngày
}

# ==========================================
# 2. BỘ LƯU TRỮ VĨNH VIỄN (LOCAL STORAGE)
# ==========================================
def save_deck_to_local():
    """Lưu danh sách từ vựng vào LocalStorage của máy"""
    serializable_deck = []
    for item in st.session_state.deck:
        c_item = item.copy()
        if isinstance(c_item['next_review'], datetime):
            c_item['next_review'] = c_item['next_review'].isoformat()
        serializable_deck.append(c_item)
    
    json_str = json.dumps(serializable_deck, ensure_ascii=False)
    js_code = f"""
        <script>
            localStorage.setItem('mochi_deck_data', '{json_str}');
        </script>
    """
    st.components.v1.html(js_code, height=0)

# Khởi tạo bộ nhớ tạm
if "deck" not in st.session_state:
    st.session_state.deck = []
if "review_item" not in st.session_state:
    st.session_state.review_item = None
if "review_start_time" not in st.session_state:
    st.session_state.review_start_time = 0

# ==========================================
# 3. HÀM PHÁT ÂM & TRA CỨU TỪ ĐIỂN
# ==========================================
def play_audio_script(word):
    """Phát âm chuẩn bằng trình duyệt"""
    js_code = f"""
        <script>
            var msg = new SpeechSynthesisUtterance('{word}');
            msg.lang = 'en-US';
            window.speechSynthesis.speak(msg);
        </script>
    """
    st.components.v1.html(js_code, height=0)

def translate_single_text(text):
    if not text or not text.strip(): 
        return text
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=vi&dt=t&q={urllib.parse.quote(text.strip())}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3.0) as response:
            data = json.loads(response.read().decode('utf-8'))
            translated = "".join([item[0] for item in data[0] if item[0]])
            return translated.strip()
    except Exception:
        return text

def fetch_word_full_data_FAST(word):
    """Tra từ qua API và phát hiện lỗi chính tả"""
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    meanings_raw = []
    examples = []
    phonetic = f"/{word}/"

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3.0) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            if isinstance(data, list) and len(data) > 0:
                phonetic = data[0].get('phonetic', phonetic)
                for m in data[0].get('meanings', []):
                    pos = m.get('partOfSpeech', 'từ')
                    for d in m.get('definitions', []):
                        if d.get('definition'):
                            meanings_raw.append({"type": pos, "en": d['definition']})
                        if d.get('example'):
                            examples.append(d['example'])
                        if len(meanings_raw) >= 3: break
                    if len(meanings_raw) >= 3: break
    except Exception:
        pass

    if not meanings_raw: 
        return {"success": False}

    short_vn = translate_single_text(word)
    final_meanings = []
    for item in meanings_raw:
        vn_meaning = translate_single_text(item['en'])
        final_meanings.append({
            "type": item['type'], 
            "en": item['en'], 
            "vn": vn_meaning
        })

    return {
        "success": True, 
        "phonetic": phonetic, 
        "meanings": final_meanings, 
        "short_vn": short_vn, 
        "examples": examples
    }

# ==========================================
# 4. GIAO DIỆN UNG DUNG (WEB / MOBILE)
# ==========================================
st.title("🍌 MochiVocab - Thời Điểm Vàng")

due_count = len([x for x in st.session_state.deck if x['next_review'] <= datetime.now()])
tab1, tab2, tab3 = st.tabs([
    "🔍 Tra Từ Mới", 
    f"⏰ Ôn Tập ({due_count})", 
    f"📋 Sổ Tay ({len(st.session_state.deck)})"
])

# ------------------------------------------
# TAB 1: TRA TỪ MỚI & KIỂM TRA CHÍNH TẢ
# ------------------------------------------
with tab1:
    st.subheader("Tra cứu & Thêm từ mới")
    word_input = st.text_input("Nhập từ tiếng Anh:", placeholder="Ví dụ: resilience, innovate...").strip().lower()
    
    if st.button("Tra Từ", type="primary"):
        if word_input:
            with st.spinner("Đang kết nối từ điển..."):
                data = fetch_word_full_data_FAST(word_input)
                
                if not data["success"]:
                    st.error(f"❌ Từ **'{word_input}'** không tồn tại hoặc đã bị gõ sai chính tả. Vui lòng kiểm tra lại!")
                    if "temp_word" in st.session_state:
                        del st.session_state["temp_word"]
                else:
                    st.session_state.temp_word = {
                        "word": word_input,
                        "phonetic": data["phonetic"],
                        "meaning": data["short_vn"],
                        "detail": data["meanings"],
                        "example": data["examples"][0] if data["examples"] else f"It is important to understand {word_input}."
                    }
                    play_audio_script(word_input)

    if "temp_word" in st.session_state and st.session_state.temp_word["word"] == word_input:
        data = st.session_state.temp_word
        
        st.info(f"**{data['word'].upper()}** `{data['phonetic']}`")
        st.write(f"👉 **Nghĩa nhanh:** {data['meaning'].upper()}")
        st.caption(f"💡 **Ví dụ:** {data['example']}")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔊 Nghe Phát Âm"):
                play_audio_script(data['word'])
        with col2:
            if st.button("➕ Thêm vào Sổ Tay"):
                if any(x['word'] == data['word'] for x in st.session_state.deck):
                    st.warning("Từ này đã có trong sổ tay của bạn rồi!")
                else:
                    new_item = {
                        "id": len(st.session_state.deck) + 1,
                        "word": data['word'],
                        "phonetic": data['phonetic'],
                        "meaning": data['meaning'],
                        "example": data['example'],
                        "level": 1,
                        "next_review": datetime.now()
                    }
                    st.session_state.deck.append(new_item)
                    save_deck_to_local()  # LƯU VĨNH VIỄN VÀO MÁY
                    st.success(f"Đã thêm [{data['word'].upper()}] vào Thời Điểm Vàng!")
                    time.sleep(1)
                    st.rerun()

# ------------------------------------------
# TAB 2: ÔN TẬP THỜI ĐIỂM VÀNG
# ------------------------------------------
with tab2:
    st.subheader("Ôn tập đúng Thời Điểm Vàng")
    now = datetime.now()
    due_items = [x for x in st.session_state.deck if x["next_review"] <= now]

    if not st.session_state.deck:
        st.warning("Sổ tay đang trống. Hãy qua tab 'Tra Từ Mới' để thêm từ vựng!")
    elif not due_items:
        next_item = min(st.session_state.deck, key=lambda x: x["next_review"])
        wait_sec = int((next_item["next_review"] - now).total_seconds())
        mins, secs = divmod(wait_sec, 60)
        st.success(f"🎉 Bạn đã hoàn thành hết bài tập! Lượt ôn tập tiếp theo sau: **{mins} phút {secs} giây**.")
    else:
        if st.session_state.review_item is None or st.session_state.review_item not in due_items:
            st.session_state.review_item = random.choice(due_items)
            st.session_state.review_start_time = time.time()
            play_audio_script(st.session_state.review_item['word'])

        item = st.session_state.review_item

        st.markdown(f"### Từ cần nhớ: **{item['word'].upper()}** `{item['phonetic']}`")
        if st.button("🔊 Nghe lại"):
            play_audio_script(item['word'])

        user_ans = st.text_input("Nhập nghĩa tiếng Việt của từ này:", key="ans_input")

        if st.button("Xác Nhận Đáp Án", type="primary"):
            response_time = time.time() - st.session_state.review_start_time
            
            if user_ans.strip().lower() in item['meaning'].lower():
                new_level = min(item["level"] + 1, 5)
                st.balloons()
                st.success(f"✨ Chính xác! ({response_time:.1f}s) ➔ Thăng lên Cấp {new_level}")
            else:
                new_level = max(item["level"] - 1, 1)
                st.error(f"❌ Chưa chính xác! Nghĩa đúng: **{item['meaning']}** ➔ Giảm xuống Cấp {new_level}")

            item["level"] = new_level
            item["next_review"] = datetime.now() + timedelta(minutes=GOLDEN_INTERVALS[new_level])
            save_deck_to_local()  # LƯU VĨNH VIỄN VÀO MÁY
            st.session_state.review_item = None
            time.sleep(1.5)
            st.rerun()

# ------------------------------------------
# TAB 3: SỔ TAY TỪ VỰNG CÁ NHÂN
# ------------------------------------------
with tab3:
    st.subheader("Sổ tay từ vựng của bạn")
    if st.session_state.deck:
        deck_data = []
        for x in st.session_state.deck:
            wait_min = int((x["next_review"] - datetime.now()).total_seconds() / 60)
            status = "🔥 Đến giờ vàng!" if wait_min <= 0 else f"Sau {wait_min} phút"
            deck_data.append({
                "Từ vựng": x["word"].upper(),
                "Nghĩa": x["meaning"],
                "Cấp độ": f"Cấp {x['level']}",
                "Trạng thái": status
            })
        st.table(deck_data)
        
        if st.button("🗑️ Xóa toàn bộ từ vựng"):
            st.session_state.deck = []
            save_deck_to_local()
            st.rerun()
    else:
        st.write("Chưa có từ vựng nào trong sổ tay.")
