import json
import random
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
import streamlit as st
from streamlit_local_storage import LocalStorage

# ==========================================
# 1. CẤU HÌNH THỜI ĐIỂM VÀNG CHUẨN MOCHIMOCHI
# ==========================================
st.set_page_config(page_title="MochiVocab", page_icon="🍌", layout="centered")

local_storage = LocalStorage()

# Thuật toán MochiMochi 5 Cấp độ (Thời gian tính theo phút)
GOLDEN_INTERVALS = {
    1: 120,      # Cấp 1: 2 tiếng
    2: 1440,     # Cấp 2: 1 ngày (24 tiếng)
    3: 4320,     # Cấp 3: 3 ngày (72 tiếng)
    4: 10080,    # Cấp 4: 7 ngày (168 tiếng)
    5: 20160     # Cấp 5: 14 ngày (336 tiếng)
}

FAKE_MEANINGS_POOL = [
    "Sự kiên trì", "Khả năng thích ứng", "Tác động tích cực", 
    "Sự phát triển", "Sự hoài nghi", "Tạo ra sản phẩm mới", 
    "Sự trì hoãn", "Sự cân bằng", "Lợi ích lâu dài"
]

# Khởi tạo state
if "deck" not in st.session_state:
    st.session_state.deck = []
if "data_loaded" not in st.session_state:
    st.session_state.data_loaded = False
if "review_item" not in st.session_state:
    st.session_state.review_item = None
if "q_type" not in st.session_state:
    st.session_state.q_type = None
if "q_data" not in st.session_state:
    st.session_state.q_data = {}
if "review_start_time" not in st.session_state:
    st.session_state.review_start_time = 0

if "active_tab" not in st.session_state:
    st.session_state.active_tab = "⏰ Ôn Tập"

# ==========================================
# 2. BỘ LƯU TRỮ LOCAL STORAGE
# ==========================================
if not st.session_state.data_loaded:
    saved_data = local_storage.getItem("mochi_deck_data")
    if saved_data:
        try:
            items = json.loads(saved_data)
            for it in items:
                if isinstance(it['next_review'], str):
                    it['next_review'] = datetime.fromisoformat(it['next_review'])
            st.session_state.deck = items
        except Exception:
            pass
    st.session_state.data_loaded = True

def save_deck():
    serializable_deck = []
    for item in st.session_state.deck:
        c_item = item.copy()
        if isinstance(c_item['next_review'], datetime):
            c_item['next_review'] = c_item['next_review'].isoformat()
        serializable_deck.append(c_item)
    
    json_str = json.dumps(serializable_deck, ensure_ascii=False)
    local_storage.setItem("mochi_deck_data", json_str)

# ==========================================
# 3. HÀM PHÁT ÂM & TRA TỪ
# ==========================================
def play_audio_script(word):
    js_code = f"""
        <script>
            window.speechSynthesis.cancel();
            var msg = new SpeechSynthesisUtterance('{word}');
            msg.lang = 'en-US';
            msg.rate = 0.9;
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
    return {
        "success": True, 
        "phonetic": phonetic, 
        "short_vn": short_vn, 
        "examples": examples
    }

def get_distractors(correct_meaning, count=3):
    other_meanings = [x['meaning'] for x in st.session_state.deck if x['meaning'] != correct_meaning]
    pool = list(set(other_meanings + FAKE_MEANINGS_POOL))
    if correct_meaning in pool:
        pool.remove(correct_meaning)
    return random.sample(pool, min(count, len(pool)))

def process_answer(is_correct, correct_ans_text):
    item = st.session_state.review_item
    response_time = time.time() - st.session_state.review_start_time
    
    if is_correct:
        new_level = min(item["level"] + 1, 5)
        st.balloons()
        st.success(f"✨ Chính xác! ({response_time:.1f}s) ➔ Thăng lên Cấp {new_level}")
        item["level"] = new_level
        item["next_review"] = datetime.now() + timedelta(minutes=GOLDEN_INTERVALS[new_level])
    else:
        new_level = max(item["level"] - 1, 1)
        st.error(f"❌ Chưa đúng! Đáp án đúng: **{correct_ans_text}** ➔ Giữ/Giảm xuống Cấp {new_level}")
        item["level"] = new_level
        # Nếu ở Cấp 1 mà làm sai, bắt ôn lại sau 5 phút
        if new_level == 1:
            item["next_review"] = datetime.now() + timedelta(minutes=5)
        else:
            item["next_review"] = datetime.now() + timedelta(minutes=GOLDEN_INTERVALS[new_level])

    save_deck()
    st.session_state.review_item = None
    time.sleep(1.5)
    st.rerun()

# ==========================================
# 4. GIAO DIỆN CHÍNH
# ==========================================
st.title("🍌 MochiVocab - Thời Điểm Vàng")

due_count = len([x for x in st.session_state.deck if x['next_review'] <= datetime.now()])

tab_options = ["⏰ Ôn Tập", "🔍 Tra Từ Mới", "📋 Sổ Tay"]
tab_labels = {
    "⏰ Ôn Tập": f"⏰ Ôn Tập ({due_count})",
    "🔍 Tra Từ Mới": "🔍 Tra Từ Mới",
    "📋 Sổ Tay": f"📋 Sổ Tay ({len(st.session_state.deck)})"
}

selected_tab = st.radio(
    "Menu Navigation",
    options=tab_options,
    format_func=lambda x: tab_labels[x],
    key="active_tab",
    horizontal=True,
    label_visibility="collapsed"
)

st.markdown("---")

# ------------------------------------------
# TAB: ÔN TẬP BÀI TẬP
# ------------------------------------------
if selected_tab == "⏰ Ôn Tập":
    st.subheader("Ôn tập đúng Thời Điểm Vàng")
    now = datetime.now()
    due_items = [x for x in st.session_state.deck if x["next_review"] <= now]

    if not st.session_state.deck:
        st.warning("Sổ tay đang trống. Hãy chọn tab 'Tra Từ Mới' để thêm từ!")
    elif not due_items:
        next_item = min(st.session_state.deck, key=lambda x: x["next_review"])
        target_timestamp = int(next_item["next_review"].timestamp() * 1000)

        st.success("🎉 Bạn đã hoàn thành tất cả các từ trong lượt này!")
        st.markdown(f"**Từ tiếp theo:** `{next_item['word'].upper()}` (Cấp {next_item['level']})")
        
        countdown_html = f"""
        <div style="text-align: center; background-color: #262730; color: #00FF66; padding: 20px; border-radius: 12px; margin: 15px 0;">
            <div style="font-size: 14px; color: #A0A0A0; margin-bottom: 5px;">THỜI GIAN CÒN LẠI ĐẾN LƯỢT ÔN TIẾP THEO</div>
            <div id="countdown" style="font-size: 32px; font-weight: bold; font-family: monospace;">00:00:00</div>
        </div>
        <script>
            var targetTime = {target_timestamp};
            function updateCountdown() {{
                var now = new Date().getTime();
                var diff = targetTime - now;
                if (diff <= 0) {{
                    document.getElementById("countdown").innerHTML = "🎉 ĐÃ ĐẾN GIỜ VÀNG!";
                    window.parent.location.reload();
                    return;
                }}
                var hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
                var minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
                var seconds = Math.floor((diff % (1000 * 60)) / 1000);
                
                hours = hours < 10 ? "0" + hours : hours;
                minutes = minutes < 10 ? "0" + minutes : minutes;
                seconds = seconds < 10 ? "0" + seconds : seconds;
                
                document.getElementById("countdown").innerHTML = hours + ":" + minutes + ":" + seconds;
            }}
            updateCountdown();
            setInterval(updateCountdown, 1000);
        </script>
        """
        st.components.v1.html(countdown_html, height=120)

    else:
        if st.session_state.review_item is None or st.session_state.review_item not in due_items:
            item = random.choice(due_items)
            q_types = ["CHOICE_MEANING", "FILL_BLANK", "SPELLING", "CONTEXT_MATCH", "FLASHCARD_TRUE_FALSE"]
            
            chosen_q = random.choice(q_types)
            st.session_state.review_item = item
            st.session_state.q_type = chosen_q
            st.session_state.review_start_time = time.time()
            st.session_state.q_data = {}

            if chosen_q in ["CHOICE_MEANING", "CONTEXT_MATCH"]:
                opts = [item['meaning']] + get_distractors(item['meaning'])
                random.shuffle(opts)
                st.session_state.q_data['options'] = opts
            elif chosen_q == "FLASHCARD_TRUE_FALSE":
                is_true = random.choice([True, False])
                fake_ans = get_distractors(item['meaning'], count=1)[0]
                st.session_state.q_data['is_true'] = is_true
                st.session_state.q_data['disp_meaning'] = item['meaning'] if is_true else fake_ans

        item = st.session_state.review_item
        q_type = st.session_state.q_type
        q_data = st.session_state.q_data

        if q_type == "CHOICE_MEANING":
            st.markdown("### 🎲 TRẮC NGHIỆM CHỌN NGHĨA")
            st.info(f"Từ: **{item['word'].upper()}** `{item['phonetic']}`")
            if st.button("🔊 Bấm để nghe"):
                play_audio_script(item['word'])
            
            st.write("Chọn nghĩa tiếng Việt tương ứng:")
            for opt in q_data['options']:
                if st.button(opt, key=f"btn_{opt}"):
                    process_answer(opt == item['meaning'], item['meaning'])

        elif q_type == "FILL_BLANK":
            st.markdown("### 🎲 ĐỤC LỖ CÂU VÍ DỤ")
            blanked = item['example'].lower().replace(item['word'].lower(), "________")
            st.info(f"\"{blanked}\"")
            st.write("Điền từ tiếng Anh còn thiếu vào chỗ trống (________):")
            
            user_ans = st.text_input("Nhập từ còn thiếu:", key="ans_fill")
            if st.button("Xác Nhận Đáp Án", type="primary"):
                process_answer(user_ans.strip().lower() == item['word'].lower(), item['word'].upper())

        elif q_type == "SPELLING":
            st.markdown("### 🎲 LUYỆN CHÍNH TẢ")
            st.info(f"Nghĩa: **{item['meaning'].upper()}**")
            st.write("Gõ chính xác từ tiếng Anh:")
            
            user_ans = st.text_input("Gõ từ tiếng Anh:", key="ans_spelling")
            if st.button("Xác Nhận Đáp Án", type="primary"):
                process_answer(user_ans.strip().lower() == item['word'].lower(), item['word'].upper())

        elif q_type == "CONTEXT_MATCH":
            st.markdown("### 🎲 NGHĨA THEO NGỮ CẢNH")
            st.info(f"Câu: \"{item['example']}\"")
            st.write(f"Từ **'{item['word'].upper()}'** trong câu trên có nghĩa là gì?")
            
            for opt in q_data['options']:
                if st.button(opt, key=f"btn_ctx_{opt}"):
                    process_answer(opt == item['meaning'], item['meaning'])

        elif q_type == "FLASHCARD_TRUE_FALSE":
            st.markdown("### 🎲 FLASHCARD PHẢN XẠ")
            st.info(f"Từ: **{item['word'].upper()}**\n\nNghĩa là: \"**{q_data['disp_meaning'].upper()}**\"")
            st.write("Đánh giá thông tin trên Đúng hay Sai?")
            
            col_t, col_f = st.columns(2)
            with col_t:
                if st.button("✅ ĐÚNG", type="primary"):
                    process_answer(q_data['is_true'] == True, "ĐÚNG" if q_data['is_true'] else "SAI")
            with col_f:
                if st.button("❌ SAI"):
                    process_answer(q_data['is_true'] == False, "SAI" if not q_data['is_true'] else "ĐÚNG")

# ------------------------------------------
# TAB: TRA TỪ MỚI
# ------------------------------------------
elif selected_tab == "🔍 Tra Từ Mới":
    st.subheader("Tra cứu & Thêm từ mới")
    word_input = st.text_input("Nhập từ tiếng Anh:", placeholder="Ví dụ: resilience, innovate...").strip().lower()
    
    if st.button("Tra Từ", type="primary"):
        if word_input:
            with st.spinner("Đang kết nối từ điển..."):
                data = fetch_word_full_data_FAST(word_input)
                if not data["success"]:
                    st.error(f"❌ Từ **'{word_input}'** không tồn tại hoặc gõ sai chính tả.")
                    if "temp_word" in st.session_state:
                        del st.session_state["temp_word"]
                else:
                    st.session_state.temp_word = {
                        "word": word_input,
                        "phonetic": data["phonetic"],
                        "meaning": data["short_vn"],
                        "example": data["examples"][0] if data["examples"] else f"It is important to understand {word_input}."
                    }

    if "temp_word" in st.session_state and st.session_state.temp_word["word"] == word_input:
        data = st.session_state.temp_word
        st.info(f"**{data['word'].upper()}** `{data['phonetic']}`")
        st.write(f"👉 **Nghĩa:** {data['meaning'].upper()}")
        st.caption(f"💡 **Ví dụ:** {data['example']}")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔊 Nghe Phát Âm"):
                play_audio_script(data['word'])
        with col2:
            if st.button("➕ Thêm vào Sổ Tay"):
                if any(x['word'] == data['word'] for x in st.session_state.deck):
                    st.warning("Từ này đã có trong sổ tay!")
                else:
                    # Mới thêm vào sẽ ở Cấp 1 và CÓ THỂ ÔN NGAY LẬP TỨC (next_review = datetime.now())
                    new_item = {
                        "id": len(st.session_state.deck) + 1,
                        "word": data['word'],
                        "phonetic": data['phonetic'],
                        "meaning": data['meaning'],
                        "example": data['example'],
                        "level": 1,
                        "next_review": datetime.now()  # Ôn ngay lập tức
                    }
                    st.session_state.deck.append(new_item)
                    save_deck()
                    st.success(f"Đã thêm [{data['word'].upper()}] vào Cấp 1! Từ đã sẵn sàng trong danh sách Ôn Tập.")
                    time.sleep(1.5)
                    st.rerun()

# ------------------------------------------
# TAB: SỔ TAY TỪ VỰNG
# ------------------------------------------
elif selected_tab == "📋 Sổ Tay":
    st.subheader("Sổ tay từ vựng của bạn")
    if st.session_state.deck:
        deck_data = []
        for x in st.session_state.deck:
            wait_sec = int((x["next_review"] - datetime.now()).total_seconds())
            if wait_sec <= 0:
                status = "🔥 Đến giờ vàng!"
            else:
                hours, rem = divmod(wait_sec, 3600)
                mins, _ = divmod(rem, 60)
                status = f"Sau {hours}h {mins}m"
                
            deck_data.append({
                "Từ vựng": x["word"].upper(),
                "Nghĩa": x["meaning"],
                "Cấp độ": f"Cấp {x['level']}",
                "Trạng thái": status
            })
        st.table(deck_data)
        
        if st.button("🗑️ Xóa toàn bộ từ vựng"):
            st.session_state.deck = []
            save_deck()
            st.rerun()
    else:
        st.write("Chưa có từ vựng nào trong sổ tay.")
