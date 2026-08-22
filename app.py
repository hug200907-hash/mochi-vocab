import streamlit as st
import random
import time
from datetime import datetime, timedelta

# Cấu hình trang Streamlit chuẩn giao diện Mobile
st.set_page_config(page_title="MochiVocab", page_icon="🍌", layout="centered")

# ==========================================
# 1. KHỞI TẠO DỮ LIỆU & BẢNG MÀU MOCHI
# ==========================================
GOLDEN_INTERVALS = {1: 5, 2: 1440, 3: 4320, 4: 10080, 5: 20160}

if "deck" not in st.session_state:
    st.session_state.deck = []
if "review_item" not in st.session_state:
    st.session_state.review_item = None
if "review_start_time" not in st.session_state:
    st.session_state.review_start_time = 0

# Hàm phát âm chuẩn iOS Browser bằng JavaScript
def play_audio_script(word):
    js_code = f"""
        <script>
            var msg = new SpeechSynthesisUtterance('{word}');
            msg.lang = 'en-US';
            window.speechSynthesis.speak(msg);
        </script>
    """
    st.components.v1.html(js_code, height=0)

# ==========================================
# 2. GIAO DIỆN CHÍNH & THANH DIEU HƯỚNG
# ==========================================
st.title("🍌 MochiVocab - Thời Điểm Vàng")

tab1, tab2, tab3 = st.tabs(["🔍 Tra Từ Mới", f"⏰ Ôn Tập ({len([x for x in st.session_state.deck if x['next_review'] <= datetime.now()])})", f"📋 Sổ Tay ({len(st.session_state.deck)})"])

# ------------------------------------------
# TAB 1: TRA TỪ MỚI
# ------------------------------------------
with tab1:
    st.subheader("Tra cứu & Thêm từ mới")
    word_input = st.text_input("Nhập từ tiếng Anh:", placeholder="Ví dụ: resilience, innovate...").strip().lower()
    
    if st.button("Tra Từ", type="primary"):
        if word_input:
            # Mô phỏng dữ liệu tra từ nhanh
            st.session_state.temp_word = {
                "word": word_input,
                "phonetic": f"/{word_input}/",
                "meaning": f"Nghĩa tiếng Việt của {word_input}",
                "example": f"This is an example sentence using {word_input}."
            }
            play_audio_script(word_input)

    if "temp_word" in st.session_state and st.session_state.temp_word["word"] == word_input:
        data = st.session_state.temp_word
        
        st.info(f"**{data['word'].upper()}** `{data['phonetic']}`")
        st.write(f"👉 **Nghĩa:** {data['meaning']}")
        st.caption(f"💡 **Ví dụ:** {data['example']}")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔊 Nghe Phát Âm"):
                play_audio_script(data['word'])
        with col2:
            if st.button("➕ Thêm vào Sổ Tay"):
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
        st.warning("Sổ tay đang trống. Hãy qua tab Tra Từ Mới để thêm từ vựng!")
    elif not due_items:
        next_item = min(st.session_state.deck, key=lambda x: x["next_review"])
        wait_sec = int((next_item["next_review"] - now).total_seconds())
        mins, secs = divmod(wait_sec, 60)
        st.success(f"🎉 Bạn đã hoàn thành hết các từ! Lượt tiếp theo sau: **{mins} phút {secs} giây**.")
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
            
            # Kiểm tra cơ bản
            if user_ans.strip():
                new_level = min(item["level"] + 1, 5)
                st.balloons()
                st.success(f"✨ Chính xác! (Thời gian: {response_time:.1f}s) ➔ Thăng Cấp {new_level}")
            else:
                new_level = max(item["level"] - 1, 1)
                st.error(f"❌ Chưa đúng! Nghĩa đúng: {item['meaning']} ➔ Giảm xuống Cấp {new_level}")

            item["level"] = new_level
            item["next_review"] = datetime.now() + timedelta(minutes=GOLDEN_INTERVALS[new_level])
            st.session_state.review_item = None
            time.sleep(1.5)
            st.rerun()

# ------------------------------------------
# TAB 3: SỔ TAY TỪ VỰNG
# ------------------------------------------
with tab3:
    st.subheader("Danh sách từ vựng")
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
    else:
        st.write("Chưa có dữ liệu.")
