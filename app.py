import json
import random
import time
import urllib.parse
import urllib.request
import re

from datetime import datetime, timedelta

import streamlit as st
from streamlit_local_storage import LocalStorage


# ============================================================
# 1. CẤU HÌNH APP
# ============================================================

st.set_page_config(
    page_title="MochiVocab",
    page_icon="🍌",
    layout="centered"
)

local_storage = LocalStorage()


# ============================================================
# 2. CẤU HÌNH THỜI ĐIỂM VÀNG
# ============================================================
#
# Mỗi cấp có 4 MỐC.
#
# Cấp 0:
#   1h -> 4h -> 12h -> 24h
#
# Cấp 1:
#   25h -> 28h -> 36h -> 48h
#
# Cấp 2:
#   49h -> 52h -> 60h -> 72h
#
# Cấp 3:
#   73h -> 76h -> 84h -> 96h
#
# Cấp 4:
#   97h -> 100h -> 108h -> 120h
#
# Cấp 5:
#   121h -> 124h -> 132h -> 144h
#
# Nếu đúng:
#   móc 0 -> móc 1
#   móc 1 -> móc 2
#   móc 2 -> móc 3
#   móc 3 -> lên cấp tiếp theo, móc 0
#
# Nếu sai:
#   lùi 1 móc.
#
# Ví dụ:
#   Cấp 2, móc 3 -> sai -> Cấp 2, móc 2
#   Cấp 2, móc 0 -> sai -> giữ Cấp 2, móc 0
#
# Từ mới bắt đầu:
#   Cấp 0, móc 0 = 1 giờ
# ============================================================

GOLDEN_LEVELS = {
    0: [1, 4, 12, 24],
    1: [25, 28, 36, 48],
    2: [49, 52, 60, 72],
    3: [73, 76, 84, 96],
    4: [97, 100, 108, 120],
    5: [121, 124, 132, 144],
}

MAX_LEVEL = 5
MOC_PER_LEVEL = 4


# ============================================================
# 3. SESSION STATE
# ============================================================

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

if "temp_word" not in st.session_state:
    st.session_state.temp_word = None

if "review_started" not in st.session_state:
    st.session_state.review_started = False


# ============================================================
# 4. FORMAT THỜI GIAN
# ============================================================

def format_interval(hours):
    hours = float(hours)

    if hours < 1:
        minutes = round(hours * 60)
        return f"{minutes} phút"

    if hours.is_integer():
        hours_int = int(hours)

        if hours_int < 24:
            return f"{hours_int} giờ"

        days = hours_int / 24

        if days.is_integer():
            return f"{int(days)} ngày"

        return f"{hours_int} giờ"

    return f"{hours:.1f} giờ"


def format_remaining(seconds):
    seconds = int(max(0, seconds))

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0:
        return f"{days} ngày {hours:02d}:{minutes:02d}:{seconds:02d}"

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


# ============================================================
# 5. XỬ LÝ MỐC GOLDEN TIME
# ============================================================

def get_golden_hours(level, moc):
    """
    Trả về số giờ của mốc hiện tại.
    """

    level = max(0, min(int(level), MAX_LEVEL))
    moc = max(0, min(int(moc), MOC_PER_LEVEL - 1))

    return GOLDEN_LEVELS[level][moc]


def get_level_name(level):
    names = {
        0: "🆕 Cấp 0 - Mới học",
        1: "🥉 Cấp 1 - Đang hình thành",
        2: "🥈 Cấp 2 - Đã nhớ",
        3: "🥇 Cấp 3 - Nhớ khá tốt",
        4: "💎 Cấp 4 - Nhớ lâu",
        5: "🏆 Cấp 5 - Ghi nhớ rất tốt",
    }

    return names.get(level, "🆕 Cấp 0 - Mới học")


def get_moc_name(moc):
    names = {
        0: "Mốc 1/4",
        1: "Mốc 2/4",
        2: "Mốc 3/4",
        3: "Mốc 4/4",
    }

    return names.get(moc, "Mốc 1/4")


def get_golden_status(item):
    level = int(item.get("level", 0))
    moc = int(item.get("moc", 0))

    level = max(0, min(level, MAX_LEVEL))
    moc = max(0, min(moc, 3))

    hours = get_golden_hours(level, moc)

    return {
        "level": level,
        "moc": moc,
        "hours": hours,
        "interval_text": format_interval(hours),
        "level_name": get_level_name(level),
        "moc_name": get_moc_name(moc),
    }


# ============================================================
# 6. CẬP NHẬT MỐC SAU KHI TRẢ LỜI
# ============================================================

def calculate_next_golden(item, is_correct):
    """
    Đúng:
        Mốc 1 -> Mốc 2
        Mốc 2 -> Mốc 3
        Mốc 3 -> Mốc 4
        Mốc 4 -> Cấp tiếp theo, Mốc 1

    Sai:
        Mốc 4 -> Mốc 3
        Mốc 3 -> Mốc 2
        Mốc 2 -> Mốc 1
        Mốc 1 -> giữ Mốc 1

    Cấp không bị tụt khi sai.
    """

    old_level = int(item.get("level", 0))
    old_moc = int(item.get("moc", 0))

    old_level = max(0, min(old_level, MAX_LEVEL))
    old_moc = max(0, min(old_moc, 3))

    new_level = old_level
    new_moc = old_moc

    if is_correct:

        if old_moc < 3:
            new_moc = old_moc + 1

        else:
            # Đã đủ 4 móc -> lên cấp
            if old_level < MAX_LEVEL:
                new_level = old_level + 1
                new_moc = 0
            else:
                # Cấp 5 là cấp cao nhất.
                # Đúng tiếp tục quay lại mốc 4.
                new_level = MAX_LEVEL
                new_moc = 3

    else:

        if old_moc > 0:
            new_moc = old_moc - 1
        else:
            new_moc = 0

    new_hours = get_golden_hours(new_level, new_moc)

    return new_level, new_moc, new_hours


# ============================================================
# 7. LOAD & SAVE LOCAL STORAGE
# ============================================================

if not st.session_state.data_loaded:

    saved_data = local_storage.getItem("mochi_deck_data")

    if saved_data:

        try:
            items = json.loads(saved_data)

            cleaned_items = []

            for item in items:

                # --------------------------------------------
                # Dữ liệu cũ
                # --------------------------------------------

                if "level" not in item:
                    item["level"] = 0

                item["level"] = max(
                    0,
                    min(int(item.get("level", 0)), MAX_LEVEL)
                )

                # Dữ liệu cũ chưa có mốc
                if "moc" not in item:

                    old_review_count = int(
                        item.get("review_count", 0)
                    )

                    # Cố gắng chuyển review_count cũ
                    # sang mốc mới.
                    item["moc"] = min(old_review_count, 3)

                item["moc"] = max(
                    0,
                    min(int(item.get("moc", 0)), 3)
                )

                # --------------------------------------------
                # Các trường thống kê
                # --------------------------------------------

                item["review_count"] = int(
                    item.get("review_count", 0)
                )

                item["correct_count"] = int(
                    item.get("correct_count", 0)
                )

                item["wrong_count"] = int(
                    item.get("wrong_count", 0)
                )

                item["last_response_time"] = item.get(
                    "last_response_time",
                    None
                )

                item["last_result"] = item.get(
                    "last_result",
                    None
                )

                # --------------------------------------------
                # next_review
                # --------------------------------------------

                next_review = item.get("next_review")

                if isinstance(next_review, str):

                    try:
                        next_review = datetime.fromisoformat(
                            next_review
                        )
                    except Exception:
                        next_review = datetime.now()

                elif not isinstance(next_review, datetime):

                    next_review = datetime.now()

                item["next_review"] = next_review

                # --------------------------------------------
                # Interval mới
                # --------------------------------------------

                item["interval_hours"] = get_golden_hours(
                    item["level"],
                    item["moc"]
                )

                cleaned_items.append(item)

            st.session_state.deck = cleaned_items

        except Exception:
            st.session_state.deck = []

    st.session_state.data_loaded = True


def save_deck():

    serializable_deck = []

    for item in st.session_state.deck:

        copy_item = item.copy()

        if isinstance(
            copy_item.get("next_review"),
            datetime
        ):
            copy_item["next_review"] = (
                copy_item["next_review"].isoformat()
            )

        serializable_deck.append(copy_item)

    local_storage.setItem(
        "mochi_deck_data",
        json.dumps(
            serializable_deck,
            ensure_ascii=False
        )
    )


# ============================================================
# 8. PHÁT ÂM
# ============================================================

def play_audio_script(word):

    safe_word = (
        word
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", " ")
        .replace("\r", " ")
    )

    js_code = f"""
    <script>
    window.speechSynthesis.cancel();

    var msg = new SpeechSynthesisUtterance('{safe_word}');
    msg.lang = 'en-US';
    msg.rate = 0.9;

    window.speechSynthesis.speak(msg);
    </script>
    """

    st.components.v1.html(
        js_code,
        height=0
    )


# ============================================================
# 9. DỊCH ANH -> VIỆT
# ============================================================

def translate_single_text(text):

    """
    Dịch từ tiếng Anh sang tiếng Việt.

    QUAN TRỌNG:
    Không trả về definition tiếng Anh nếu API dịch lỗi.
    """

    if not text:
        return ""

    text = text.strip()

    if not text:
        return ""

    # --------------------------------------------------------
    # API 1: Google Translate
    # --------------------------------------------------------

    try:

        url = (
            "https://translate.googleapis.com/"
            "translate_a/single"
            "?client=gtx"
            "&sl=en"
            "&tl=vi"
            "&dt=t"
            f"&q={urllib.parse.quote(text)}"
        )

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urllib.request.urlopen(
            req,
            timeout=5
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

            if (
                isinstance(data, list)
                and len(data) > 0
                and isinstance(data[0], list)
            ):

                translated_parts = []

                for item in data[0]:

                    if (
                        isinstance(item, list)
                        and len(item) > 0
                        and item[0]
                    ):
                        translated_parts.append(
                            str(item[0])
                        )

                result = "".join(
                    translated_parts
                ).strip()

                if result:

                    # Kiểm tra đơn giản xem có thực sự
                    # khác câu tiếng Anh không.
                    if result.lower() != text.lower():
                        return result

                    # Với từ đơn, Google đôi khi có thể
                    # trả nguyên tiếng Anh.
                    if " " not in text:
                        return result

    except Exception:
        pass

    # --------------------------------------------------------
    # API 2: MyMemory
    # --------------------------------------------------------

    try:

        url = (
            "https://api.mymemory.translated.net/get"
            f"?q={urllib.parse.quote(text)}"
            "&langpair=en|vi"
        )

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urllib.request.urlopen(
            req,
            timeout=5
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

            translated = (
                data
                .get("responseData", {})
                .get("translatedText", "")
                .strip()
            )

            if translated:
                return translated

    except Exception:
        pass

    # --------------------------------------------------------
    # Không dịch được
    # --------------------------------------------------------

    return ""


# ============================================================
# 10. TRA TỪ ĐIỂN
# ============================================================

def fetch_word_dictionary(word):

    url = (
        "https://api.dictionaryapi.dev/"
        "api/v2/entries/en/"
        f"{urllib.parse.quote(word)}"
    )

    try:

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urllib.request.urlopen(
            req,
            timeout=5
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

            if isinstance(data, list) and data:

                return data[0]

    except Exception:
        pass

    return None


# ============================================================
# 11. LẤY PHIÊN ÂM
# ============================================================

def extract_phonetic(data, word):

    if not data:
        return f"/{word}/"

    phonetic = data.get("phonetic")

    if phonetic:
        return phonetic

    for p in data.get("phonetics", []):

        text = p.get("text")

        if text:
            return text

    return f"/{word}/"


# ============================================================
# 12. LẤY CÂU VÍ DỤ
# ============================================================

def extract_example(data, word):

    if data:

        for meaning in data.get(
            "meanings",
            []
        ):

            for definition in meaning.get(
                "definitions",
                []
            ):

                example = definition.get(
                    "example"
                )

                if example:
                    return example

    return (
        f"It is important to understand "
        f"{word}."
    )


# ============================================================
# 13. LẤY THÔNG TIN TỪ MỚI
# ============================================================

def fetch_word_full_data(word):

    dictionary_data = fetch_word_dictionary(word)

    if not dictionary_data:
        return {
            "success": False
        }

    phonetic = extract_phonetic(
        dictionary_data,
        word
    )

    example = extract_example(
        dictionary_data,
        word
    )

    # --------------------------------------------------------
    # DỊCH CHÍNH TỪ ĐÓ SANG TIẾNG VIỆT
    # --------------------------------------------------------

    vietnamese_meaning = translate_single_text(word)

    # --------------------------------------------------------
    # Nếu không dịch được thì thử thêm lần nữa
    # bằng lowercase.
    # --------------------------------------------------------

    if not vietnamese_meaning:

        vietnamese_meaning = translate_single_text(
            word.lower()
        )

    # --------------------------------------------------------
    # Tuyệt đối không dùng English definition
    # làm nghĩa tiếng Việt.
    # --------------------------------------------------------

    if not vietnamese_meaning:

        vietnamese_meaning = "Chưa lấy được nghĩa tiếng Việt"

    return {
        "success": True,
        "word": word,
        "phonetic": phonetic,
        "meaning": vietnamese_meaning,
        "example": example
    }


# ============================================================
# 14. ID
# ============================================================

def get_next_id():

    if not st.session_state.deck:
        return 1

    return (
        max(
            int(x.get("id", 0))
            for x in st.session_state.deck
        )
        + 1
    )


# ============================================================
# 15. LẤY TỪ GÂY NHIỄU
# ============================================================

def get_other_words(current_word):

    return [
        x.get("word", "").strip()
        for x in st.session_state.deck
        if (
            x.get("word", "").strip()
            and x.get("word", "").strip().lower()
            != current_word.lower()
        )
    ]


def get_other_meanings(current_meaning):

    return [
        x.get("meaning", "").strip()
        for x in st.session_state.deck
        if (
            x.get("meaning", "").strip()
            and x.get("meaning", "").strip()
            != current_meaning
        )
    ]


# ============================================================
# 16. TẠO CÂU HỎI
# ============================================================
#
# ĐÃ BỎ:
#   AUDIO_CHOICE
#
# Còn 6 dạng:
#   1. CHOICE_MEANING
#   2. FILL_BLANK
#   3. SPELLING
#   4. CONTEXT_MATCH
#   5. FLASHCARD_TRUE_FALSE
#   6. MEANING_CHOICE
# ============================================================

def prepare_review_question(item):

    q_types = [
        "CHOICE_MEANING",
        "FILL_BLANK",
        "SPELLING",
        "CONTEXT_MATCH",
        "FLASHCARD_TRUE_FALSE",
        "MEANING_CHOICE"
    ]

    chosen_q = random.choice(q_types)

    st.session_state.review_item = item
    st.session_state.q_type = chosen_q
    st.session_state.review_start_time = time.time()
    st.session_state.q_data = {}

    word = item.get(
        "word",
        ""
    ).strip()

    meaning = item.get(
        "meaning",
        ""
    ).strip()

    example = item.get(
        "example",
        ""
    ).strip()

    if not example:

        example = (
            f"It is important to "
            f"understand {word}."
        )

    other_words = get_other_words(
        word
    )

    other_meanings = get_other_meanings(
        meaning
    )

    # ========================================================
    # 1. TỪ -> CHỌN NGHĨA
    # ========================================================

    if chosen_q == "CHOICE_MEANING":

        options = [meaning]

        if other_meanings:

            distractors = random.sample(
                other_meanings,
                min(
                    len(other_meanings),
                    3
                )
            )

            for d in distractors:

                if d not in options:
                    options.append(d)

        fallback_meanings = [
            "Sự phát triển",
            "Khả năng thích nghi",
            "Thành tựu",
            "Môi trường",
            "Kinh nghiệm",
            "Sự thay đổi"
        ]

        for m in fallback_meanings:

            if len(options) >= 4:
                break

            if m not in options:
                options.append(m)

        random.shuffle(options)

        st.session_state.q_data = {
            "question": word,
            "options": options,
            "answer": meaning
        }

    # ========================================================
    # 2. ĐIỀN TỪ VÀO CHỖ TRỐNG
    # ========================================================

    elif chosen_q == "FILL_BLANK":

        # ----------------------------------------------------
        # Ưu tiên câu ví dụ từ Oxford/Dictionary API
        # đã lưu trong item.
        #
        # Tìm đúng từ và thay bằng _____.
        # ----------------------------------------------------

        pattern = re.compile(
            r"\b" + re.escape(word) + r"\b",
            re.IGNORECASE
        )

        blank_sentence = pattern.sub(
            "_____",
            example
        )

        # ----------------------------------------------------
        # Nếu câu ví dụ không chứa từ,
        # tạo câu hỏi dạng ngữ cảnh.
        # ----------------------------------------------------

        if blank_sentence == example:

            blank_sentence = (
                f"{example} "
                f"Which word fits the sentence?"
            )

        st.session_state.q_data = {
            "sentence": blank_sentence,
            "answer": word
        }

    # ========================================================
    # 3. NGHĨA -> GÕ TỪ
    # ========================================================

    elif chosen_q == "SPELLING":

        st.session_state.q_data = {
            "question": meaning,
            "answer": word
        }

    # ========================================================
    # 4. NGỮ CẢNH -> CHỌN NGHĨA
    # ========================================================

    elif chosen_q == "CONTEXT_MATCH":

        options = [meaning]

        if other_meanings:

            distractors = random.sample(
                other_meanings,
                min(
                    len(other_meanings),
                    3
                )
            )

            for d in distractors:

                if d not in options:
                    options.append(d)

        fallback_meanings = [
            "Sự phát triển",
            "Khả năng thích nghi",
            "Thành tựu",
            "Môi trường",
            "Kinh nghiệm",
            "Sự thay đổi"
        ]

        for m in fallback_meanings:

            if len(options) >= 4:
                break

            if m not in options:
                options.append(m)

        random.shuffle(options)

        st.session_state.q_data = {
            "context": example,
            "word": word,
            "options": options,
            "answer": meaning
        }

    # ========================================================
    # 5. FLASHCARD ĐÚNG / SAI
    # ========================================================

    elif chosen_q == "FLASHCARD_TRUE_FALSE":

        is_true = random.choice(
            [True, False]
        )

        if is_true or not other_meanings:

            display_meaning = meaning
            answer = True

        else:

            display_meaning = random.choice(
                other_meanings
            )

            answer = False

        st.session_state.q_data = {
            "word": word,
            "disp_meaning": display_meaning,
            "is_true": answer,
            "answer": answer
        }

    # ========================================================
    # 6. NGHĨA -> CHỌN TỪ
    # ========================================================

    elif chosen_q == "MEANING_CHOICE":

        options = [word]

        if other_words:

            sampled_words = random.sample(
                other_words,
                min(
                    len(other_words),
                    3
                )
            )

            for w in sampled_words:

                if w.lower() not in [
                    x.lower()
                    for x in options
                ]:
                    options.append(w)

        fallback_words = [
            "resilience",
            "innovate",
            "experience",
            "development",
            "adaptation",
            "environment"
        ]

        for fb in fallback_words:

            if len(options) >= 4:
                break

            if fb.lower() not in [
                x.lower()
                for x in options
            ]:
                options.append(fb)

        random.shuffle(options)

        st.session_state.q_data = {
            "word": word,
            "question": meaning,
            "options": options,
            "answer": word
        }


# ============================================================
# 17. XỬ LÝ CÂU TRẢ LỜI
# ============================================================

def process_answer(
    is_correct,
    correct_ans_text
):

    item = st.session_state.review_item

    if item is None:
        return

    # --------------------------------------------------------
    # Tính thời gian phản hồi
    # --------------------------------------------------------

    response_time = max(
        0.1,
        time.time()
        - st.session_state.review_start_time
    )

    old_level = int(
        item.get("level", 0)
    )

    old_moc = int(
        item.get("moc", 0)
    )

    old_hours = get_golden_hours(
        old_level,
        old_moc
    )

    # --------------------------------------------------------
    # Tính cấp + móc mới
    # --------------------------------------------------------

    new_level, new_moc, new_hours = (
        calculate_next_golden(
            item,
            is_correct
        )
    )

    item["level"] = new_level
    item["moc"] = new_moc
    item["interval_hours"] = new_hours

    # --------------------------------------------------------
    # Thống kê
    # --------------------------------------------------------

    item["review_count"] = int(
        item.get("review_count", 0)
    ) + 1

    if is_correct:

        item["correct_count"] = int(
            item.get("correct_count", 0)
        ) + 1

    else:

        item["wrong_count"] = int(
            item.get("wrong_count", 0)
        ) + 1

    item["last_response_time"] = round(
        response_time,
        2
    )

    item["last_result"] = (
        "correct"
        if is_correct
        else "wrong"
    )

    # --------------------------------------------------------
    # Thời điểm ôn tiếp theo
    # --------------------------------------------------------

    item["next_review"] = (
        datetime.now()
        + timedelta(hours=new_hours)
    )

    # ========================================================
    # ĐÚNG
    # ========================================================

    if is_correct:

        st.success(
            "✨ Chính xác!"
        )

        st.write(
            f"⚡ Thời gian phản hồi: "
            f"**{response_time:.1f} giây**"
        )

        if new_level > old_level:

            st.success(
                f"📈 Đủ 4 móc! "
                f"Cấp độ: **{old_level} → {new_level}**"
            )

            st.success(
                "🎉 Từ này đã lên cấp!"
            )

        else:

            st.info(
                f"📊 {get_level_name(new_level)}"
            )

        st.info(
            f"📍 Mốc: "
            f"**{new_moc + 1}/4**"
        )

        st.info(
            f"⏰ Thời Điểm Vàng tiếp theo: "
            f"**{format_interval(new_hours)}**"
        )

        if new_level == 5:

            st.balloons()

            st.success(
                "🏆 Từ này đã đạt Cấp 5!"
            )

    # ========================================================
    # SAI
    # ========================================================

    else:

        st.error(
            "❌ Chưa chính xác."
        )

        st.warning(
            f"Đáp án đúng: "
            f"**{correct_ans_text}**"
        )

        st.warning(
            f"📉 Mốc: "
            f"**{old_moc + 1}/4 → {new_moc + 1}/4**"
        )

        st.info(
            f"🔄 Thời Điểm Vàng mới: "
            f"**{format_interval(new_hours)}**"
        )

        # ----------------------------------------------------
        # Sai 1 lần = rớt 1 móc
        # Câu hỏi tiếp theo sẽ được tạo lại.
        # ----------------------------------------------------

        st.info(
            "🔄 Câu hỏi mới cho từ này sẽ được tạo lại."
        )

    save_deck()

    # --------------------------------------------------------
    # Reset câu hỏi hiện tại
    # --------------------------------------------------------

    st.session_state.review_item = None
    st.session_state.q_type = None
    st.session_state.q_data = {}

    # Không dừng phiên ôn tập.
    # Lần render tiếp theo sẽ tạo câu hỏi mới.

    time.sleep(1.2)

    st.rerun()


# ============================================================
# 18. HEADER
# ============================================================

st.title("🍌 MochiVocab")

st.caption(
    "Dynamic Golden Time • 4 móc / cấp"
)

now = datetime.now()

due_count = sum(
    1
    for x in st.session_state.deck
    if x.get("next_review", now) <= now
)

tab_options = [
    "⏰ Ôn Tập",
    "🔍 Tra Từ Mới",
    "📋 Sổ Tay"
]

tab_labels = {
    "⏰ Ôn Tập": f"⏰ Ôn Tập ({due_count})",
    "🔍 Tra Từ Mới": "🔍 Tra Từ Mới",
    "📋 Sổ Tay": (
        f"📋 Sổ Tay "
        f"({len(st.session_state.deck)})"
    )
}

selected_tab = st.radio(
    "Navigation",
    options=tab_options,
    format_func=lambda x: tab_labels[x],
    key="active_tab",
    horizontal=True,
    label_visibility="collapsed"
)

st.markdown("---")


# ============================================================
# 19. TAB ÔN TẬP
# ============================================================

if selected_tab == "⏰ Ôn Tập":

    st.subheader(
        "⏰ Ôn tập đúng Thời Điểm Vàng"
    )

    now = datetime.now()

    due_items = [
        x
        for x in st.session_state.deck
        if x.get(
            "next_review",
            now
        ) <= now
    ]

    # --------------------------------------------------------
    # Không có từ
    # --------------------------------------------------------

    if not st.session_state.deck:

        st.warning(
            "📚 Sổ tay đang trống."
        )

        st.write(
            "Hãy sang **🔍 Tra Từ Mới** "
            "để thêm từ."
        )

    # --------------------------------------------------------
    # Chưa đến giờ
    # --------------------------------------------------------

    elif not due_items:

        st.session_state.review_started = False
        st.session_state.review_item = None
        st.session_state.q_type = None
        st.session_state.q_data = {}

        next_item = min(
            st.session_state.deck,
            key=lambda x: x.get(
                "next_review",
                datetime.now()
            )
        )

        remaining = (
            next_item["next_review"]
            - datetime.now()
        ).total_seconds()

        status = get_golden_status(
            next_item
        )

        st.success(
            "🎉 Hiện tại không có từ nào "
            "đến Thời Điểm Vàng."
        )

        col1, col2 = st.columns(2)

        with col1:

            st.metric(
                "Từ tiếp theo",
                next_item["word"].upper()
            )

        with col2:

            st.metric(
                "Cấp độ",
                next_item["level"]
            )

        st.info(
            f"📍 {status['moc_name']} • "
            f"{format_interval(status['hours'])}"
        )

        st.info(
            f"⏰ Còn khoảng "
            f"**{format_remaining(remaining)}**"
        )

        target_timestamp = int(
            next_item["next_review"].timestamp()
            * 1000
        )

        countdown_html = f"""
        <div style="
            text-align:center;
            background:#262730;
            color:#00FF66;
            padding:20px;
            border-radius:15px;
            margin-top:15px;
        ">
            <div style="
                font-size:13px;
                color:#AAAAAA;
                margin-bottom:8px;
            ">
                THỜI ĐIỂM VÀNG TIẾP THEO
            </div>

            <div id="countdown" style="
                font-size:30px;
                font-weight:bold;
                font-family:monospace;
            ">
                00:00:00
            </div>
        </div>

        <script>
        var targetTime = {target_timestamp};

        function updateCountdown() {{

            var now = new Date().getTime();
            var diff = targetTime - now;

            var element =
                document.getElementById("countdown");

            if (diff <= 0) {{

                element.innerHTML =
                    "🎉 ĐÃ ĐẾN GIỜ VÀNG!";

                return;
            }}

            var totalSeconds =
                Math.floor(diff / 1000);

            var days =
                Math.floor(
                    totalSeconds / 86400
                );

            totalSeconds %= 86400;

            var hours =
                Math.floor(
                    totalSeconds / 3600
                );

            totalSeconds %= 3600;

            var minutes =
                Math.floor(
                    totalSeconds / 60
                );

            var seconds =
                totalSeconds % 60;

            hours =
                hours < 10
                ? "0" + hours
                : hours;

            minutes =
                minutes < 10
                ? "0" + minutes
                : minutes;

            seconds =
                seconds < 10
                ? "0" + seconds
                : seconds;

            if (days > 0) {{

                element.innerHTML =
                    days
                    + " ngày "
                    + hours
                    + ":"
                    + minutes
                    + ":"
                    + seconds;

            }} else {{

                element.innerHTML =
                    hours
                    + ":"
                    + minutes
                    + ":"
                    + seconds;
            }}
        }}

        updateCountdown();

        setInterval(
            updateCountdown,
            1000
        );
        </script>
        """

        st.components.v1.html(
            countdown_html,
            height=120
        )

    # --------------------------------------------------------
    # Có từ cần ôn
    # --------------------------------------------------------

    else:

        if not st.session_state.review_started:

            st.success(
                f"🔥 Có **{len(due_items)} từ** "
                "đang đến Thời Điểm Vàng."
            )

            st.markdown("---")

            st.markdown(
                """
                ### 🧠 Sẵn sàng ôn tập?

                MochiVocab sẽ ưu tiên từ có cấp thấp
                và bắt đầu tính thời gian phản hồi
                ngay khi bạn bắt đầu.
                """
            )

            if st.button(
                "▶️ BẮT ĐẦU ÔN TẬP",
                type="primary",
                use_container_width=True,
                key="start_review"
            ):

                min_level = min(
                    x["level"]
                    for x in due_items
                )

                candidates = [
                    x
                    for x in due_items
                    if x["level"] == min_level
                ]

                item = random.choice(
                    candidates
                )

                st.session_state.review_started = True

                prepare_review_question(
                    item
                )

                st.rerun()

        else:

            # ------------------------------------------------
            # Không còn câu hỏi hiện tại
            # -> tạo câu hỏi mới
            # ------------------------------------------------

            current_item = (
                st.session_state.review_item
            )

            if current_item is None:

                now = datetime.now()

                due_items = [
                    x
                    for x in st.session_state.deck
                    if x.get(
                        "next_review",
                        now
                    ) <= now
                ]

                if not due_items:

                    st.session_state.review_started = False
                    st.rerun()

                min_level = min(
                    x["level"]
                    for x in due_items
                )

                candidates = [
                    x
                    for x in due_items
                    if x["level"] == min_level
                ]

                item = random.choice(
                    candidates
                )

                prepare_review_question(
                    item
                )

                st.rerun()

            # ------------------------------------------------
            # Nút dừng
            # ------------------------------------------------

            if st.button(
                "⏹️ Dừng ôn tập",
                key="stop_review"
            ):

                st.session_state.review_started = False
                st.session_state.review_item = None
                st.session_state.q_type = None
                st.session_state.q_data = {}
                st.session_state.review_start_time = 0

                st.rerun()

            item = (
                st.session_state.review_item
            )

            q_type = (
                st.session_state.q_type
            )

            q_data = (
                st.session_state.q_data
            )

            # ------------------------------------------------
            # Level / mốc
            # ------------------------------------------------

            level = int(
                item.get("level", 0)
            )

            moc = int(
                item.get("moc", 0)
            )

            current_hours = (
                get_golden_hours(
                    level,
                    moc
                )
            )

            # Progress 4 mốc trong cấp
            st.progress(
                (moc + 1) / 4
            )

            col1, col2 = st.columns(2)

            with col1:

                st.caption(
                    get_level_name(level)
                )

            with col2:

                st.caption(
                    f"📍 Mốc {moc + 1}/4"
                )

            st.caption(
                f"⏰ Mốc hiện tại: "
                f"**{format_interval(current_hours)}**"
            )

            st.caption(
                f"🔄 Đã ôn: "
                f"**{item.get('review_count', 0)} lần**"
            )

            st.markdown("---")

            # =================================================
            # DẠNG 1: CHỌN NGHĨA
            # =================================================

            if q_type == "CHOICE_MEANING":

                st.markdown(
                    "### 🎲 TRẮC NGHIỆM CHỌN NGHĨA"
                )

                st.info(
                    f"Từ: **{item['word'].upper()}** "
                    f"`{item.get('phonetic', '')}`"
                )

                if st.button(
                    "🔊 Nghe",
                    key="choice_audio"
                ):

                    play_audio_script(
                        item["word"]
                    )

                st.write(
                    "Chọn nghĩa tiếng Việt:"
                )

                for index, option in enumerate(
                    q_data.get(
                        "options",
                        []
                    )
                ):

                    if st.button(
                        option,
                        key=(
                            f"choice_"
                            f"{item['id']}_"
                            f"{index}"
                        )
                    ):

                        process_answer(
                            option == item["meaning"],
                            item["meaning"]
                        )

            # =================================================
            # DẠNG 2: ĐIỀN VÀO CHỖ TRỐNG
            # =================================================

            elif q_type == "FILL_BLANK":

                st.markdown(
                    "### ✏️ ĐIỀN TỪ VÀO CHỖ TRỐNG"
                )

                st.info(
                    f'"{q_data.get("sentence", "")}"'
                )

                st.caption(
                    "💡 Điền từ tiếng Anh còn thiếu."
                )

                user_ans = st.text_input(
                    "Từ còn thiếu:",
                    key=f"fill_{item['id']}"
                )

                if st.button(
                    "Xác Nhận",
                    type="primary",
                    key=f"fill_submit_{item['id']}"
                ):

                    process_answer(
                        user_ans.strip().lower()
                        == item["word"].strip().lower(),
                        item["word"].upper()
                    )

            # =================================================
            # DẠNG 3: CHÍNH TẢ
            # =================================================

            elif q_type == "SPELLING":

                st.markdown(
                    "### ✍️ LUYỆN CHÍNH TẢ"
                )

                st.info(
                    f"Nghĩa: "
                    f"**{item['meaning'].upper()}**"
                )

                user_ans = st.text_input(
                    "Gõ từ tiếng Anh:",
                    key=f"spell_{item['id']}"
                )

                if st.button(
                    "Xác Nhận",
                    type="primary",
                    key=f"spell_submit_{item['id']}"
                ):

                    process_answer(
                        user_ans.strip().lower()
                        == item["word"].strip().lower(),
                        item["word"].upper()
                    )

            # =================================================
            # DẠNG 4: NGỮ CẢNH
            # =================================================

            elif q_type == "CONTEXT_MATCH":

                st.markdown(
                    "### 🧠 NGHĨA THEO NGỮ CẢNH"
                )

                st.info(
                    f'"{q_data.get("context", "")}"'
                )

                st.write(
                    f'Từ **{item["word"].upper()}** '
                    "có nghĩa là gì?"
                )

                for index, option in enumerate(
                    q_data.get(
                        "options",
                        []
                    )
                ):

                    if st.button(
                        option,
                        key=(
                            f"context_"
                            f"{item['id']}_"
                            f"{index}"
                        )
                    ):

                        process_answer(
                            option == item["meaning"],
                            item["meaning"]
                        )

            # =================================================
            # DẠNG 5: FLASHCARD ĐÚNG / SAI
            # =================================================

            elif q_type == "FLASHCARD_TRUE_FALSE":

                st.markdown(
                    "### ⚡ FLASHCARD PHẢN XẠ"
                )

                st.info(
                    f"Từ: **{item['word'].upper()}**"
                    f"\n\n"
                    f"Nghĩa: "
                    f"**{q_data.get('disp_meaning', '').upper()}**"
                )

                st.write(
                    "Thông tin trên đúng hay sai?"
                )

                col1, col2 = st.columns(2)

                with col1:

                    if st.button(
                        "✅ ĐÚNG",
                        type="primary",
                        key=f"true_{item['id']}"
                    ):

                        process_answer(
                            q_data["is_true"],
                            "ĐÚNG"
                            if q_data["is_true"]
                            else "SAI"
                        )

                with col2:

                    if st.button(
                        "❌ SAI",
                        key=f"false_{item['id']}"
                    ):

                        process_answer(
                            not q_data["is_true"],
                            "SAI"
                            if not q_data["is_true"]
                            else "ĐÚNG"
                        )

            # =================================================
            # DẠNG 6: NGHĨA -> CHỌN TỪ
            # =================================================

            elif q_type == "MEANING_CHOICE":

                st.markdown(
                    "### 🔤 NGHĨA → CHỌN TỪ TIẾNG ANH"
                )

                st.info(
                    f"Nghĩa: "
                    f"**{q_data.get('question', '').upper()}**"
                )

                st.write(
                    "Chọn từ tiếng Anh "
                    "có nghĩa tương ứng:"
                )

                for index, option in enumerate(
                    q_data.get(
                        "options",
                        []
                    )
                ):

                    if st.button(
                        option.upper(),
                        key=(
                            f"mchoice_opt_"
                            f"{item['id']}_"
                            f"{index}"
                        )
                    ):

                        process_answer(
                            option.lower()
                            == item["word"].lower(),
                            item["word"].upper()
                        )


# ============================================================
# 20. TAB TRA TỪ MỚI
# ============================================================

elif selected_tab == "🔍 Tra Từ Mới":

    st.subheader(
        "🔍 Tra cứu & Thêm từ mới"
    )

    word_input = st.text_input(
        "Nhập từ tiếng Anh:",
        placeholder=(
            "Ví dụ: resilience, innovate..."
        )
    ).strip().lower()

    if st.button(
        "🔎 Tra Từ",
        type="primary"
    ):

        if word_input:

            with st.spinner(
                "Đang tra từ..."
            ):

                data = fetch_word_full_data(
                    word_input
                )

            if not data["success"]:

                st.error(
                    f"❌ Không tìm thấy "
                    f"**{word_input}**."
                )

                st.session_state.temp_word = None

            else:

                st.session_state.temp_word = {
                    "word": data["word"],
                    "phonetic": data["phonetic"],
                    "meaning": data["meaning"],
                    "example": data["example"]
                }

    data = st.session_state.temp_word

    if (
        data is not None
        and data["word"] == word_input
    ):

        st.markdown("---")

        st.info(
            f"**{data['word'].upper()}** "
            f"`{data['phonetic']}`"
        )

        # ----------------------------------------------------
        # NGHĨA TIẾNG VIỆT
        # ----------------------------------------------------

        st.write(
            f"🇻🇳 **Nghĩa tiếng Việt:** "
            f"{data['meaning']}"
        )

        st.caption(
            f"💡 Ví dụ: {data['example']}"
        )

        col1, col2 = st.columns(2)

        with col1:

            if st.button(
                "🔊 Nghe",
                key="new_word_audio"
            ):

                play_audio_script(
                    data["word"]
                )

        with col2:

            if st.button(
                "➕ Thêm vào Sổ Tay",
                key="add_new_word"
            ):

                exists = any(
                    x["word"].lower()
                    == data["word"].lower()
                    for x in st.session_state.deck
                )

                if exists:

                    st.warning(
                        "Từ này đã có."
                    )

                else:

                    # ----------------------------------------
                    # TỪ MỚI:
                    # Cấp 0
                    # Mốc 1/4
                    # Thời Điểm Vàng = 1 giờ
                    # ----------------------------------------

                    new_item = {
                        "id": get_next_id(),

                        "word": data["word"],

                        "phonetic": data["phonetic"],

                        "meaning": data["meaning"],

                        "example": data["example"],

                        "level": 0,

                        "moc": 0,

                        "interval_hours": 1,

                        "review_count": 0,

                        "correct_count": 0,

                        "wrong_count": 0,

                        "last_response_time": None,

                        "last_result": None,

                        "next_review": (
                            datetime.now()
                            + timedelta(hours=1)
                        )
                    }

                    st.session_state.deck.append(
                        new_item
                    )

                    save_deck()

                    st.success(
                        f"✅ Đã thêm "
                        f"**{data['word'].upper()}**"
                    )

                    st.info(
                        "⏰ Mốc đầu tiên: "
                        "**1 giờ**"
                    )

                    time.sleep(1)

                    st.rerun()


# ============================================================
# 21. TAB SỔ TAY
# ============================================================

elif selected_tab == "📋 Sổ Tay":

    st.subheader(
        "📋 Sổ tay từ vựng"
    )

    if st.session_state.deck:

        total = len(
            st.session_state.deck
        )

        due = sum(
            1
            for x in st.session_state.deck
            if x.get(
                "next_review",
                datetime.now()
            ) <= datetime.now()
        )

        mastered = sum(
            1
            for x in st.session_state.deck
            if int(x.get("level", 0))
            == MAX_LEVEL
            and int(x.get("moc", 0))
            == 3
        )

        col1, col2, col3 = st.columns(3)

        with col1:

            st.metric(
                "Tổng từ",
                total
            )

        with col2:

            st.metric(
                "Cần ôn",
                due
            )

        with col3:

            st.metric(
                "Cấp 5",
                mastered
            )

        st.markdown("---")

        table_data = []

        for item in st.session_state.deck:

            remaining = (
                item["next_review"]
                - datetime.now()
            ).total_seconds()

            if remaining <= 0:

                status = "🔥 Sẵn sàng ôn!"

            else:

                status = (
                    f"⏳ "
                    f"{format_remaining(remaining)}"
                )

            accuracy_total = (
                item.get("correct_count", 0)
                + item.get("wrong_count", 0)
            )

            if accuracy_total > 0:

                accuracy_text = (
                    f"{item.get('correct_count', 0)}"
                    / accuracy_total * 100:.f}%"
                )

            else:

                accuracy_text = "—"

            level = int(
                item.get("level", 0)
            )

            moc = int(
                item.get("moc", 0)
            )

            golden_hours = (
                get_golden_hours(
                    level,
                    moc
                )
            )

            table_data.append({

                "Từ":
                    item["word"].upper(),

                "Nghĩa tiếng Việt":
                    item["meaning"],

                "Cấp":
                    level,

                "Mốc":
                    f"{moc + 1}/4",

                "Trạng thái":
                    get_level_name(level),

                "Thời Điểm Vàng":
                    format_interval(
                        golden_hours
                    ),

                "Độ chính xác":
                    accuracy_text,

                "Số lần ôn":
                    item.get(
                        "review_count",
                        0
                    ),

                "Tiếp theo":
                    status
            })

        st.dataframe(
            table_data,
            use_container_width=True,
            hide_index=True
        )

        st.markdown("---")

        # ----------------------------------------------------
        # HIỂN THỊ CÁC MỐC
        # ----------------------------------------------------

        st.markdown(
            "### 🧠 Hệ thống Thời Điểm Vàng"
        )

        st.write(
            "Mỗi cấp có 4 móc. Trả lời đúng "
            "để tiến lên móc tiếp theo; trả lời "
            "sai sẽ lùi 1 móc."
        )

        for level in range(
            MAX_LEVEL + 1
        ):

            hours = GOLDEN_LEVELS[
                level
            ]

            st.write(
                f"**Cấp {level}:** "
                + " → ".join(
                    format_interval(h)
                    for h in hours
                )
            )

        st.markdown("---")

        # ----------------------------------------------------
        # XÓA TOÀN BỘ
        # ----------------------------------------------------

        if st.button(
            "🗑️ Xóa toàn bộ từ vựng",
            key="delete_all_words"
        ):

            st.session_state.deck = []

            st.session_state.review_item = None

            st.session_state.review_started = False

            st.session_state.q_type = None

            st.session_state.q_data = {}

            st.session_state.temp_word = None

            save_deck()

            st.success(
                "Đã xóa toàn bộ dữ liệu."
            )

            time.sleep(0.5)

            st.rerun()

    else:

        st.info(
            "📚 Sổ tay đang trống."
        )


# ============================================================
# 22. FOOTER
# ============================================================

st.markdown("---")

st.caption(
    "🍌 MochiVocab • "
    "Golden Time 4 Mốc / Cấp"
)
